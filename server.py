"""
CLE3 PT Dashboard - Flask server.
Pipeline: SCC (station assignments, once/shift) -> FCLM timecards (PT%, every 3 min) -> serve.
"""
import threading, queue, json, socket, os, subprocess, sys
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, Response, render_template, stream_with_context, redirect
from db     import init_db, get_db
from engine import enrich, save_snapshot, floor_summary, shift_trend, PT_TARGET
from fclm   import build_timecard_url
import github_sync

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON  = sys.executable

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# ── Cache ─────────────────────────────────────────────────────────────────────
_cache      = {}
_cache_lock = threading.Lock()

# Timecard PT overlay -- updated by background thread, independent of scrape loop
_tc_cache      = {}   # {badge: {pt_pct, total_min, idle_min, credit_min}}
_tc_cache_lock = threading.Lock()
_tc_bg_running = threading.Event()   # prevents two timecard batches overlapping

def cache_set(key, val):
    with _cache_lock:
        _cache[key] = {'data': val, 'ts': datetime.now()}

def cache_get(key):
    with _cache_lock:
        e = _cache.get(key)
        if e:
            return e['data'], e['ts']
    return None, None

# ── SSE ───────────────────────────────────────────────────────────────────────
_sse_clients = []
_sse_lock    = threading.Lock()

def push(event_type, payload):
    msg = json.dumps({'type': event_type, 'payload': payload})
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:    q.put_nowait(msg)
            except: dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

# ── Scrape state ──────────────────────────────────────────────────────────────
_scrape_lock   = threading.Lock()
_scrape_status = {'msg': 'Not yet fetched', 'last_ok': None, 'error': '', 'step': '', 'need_login': False}
_current_shift = 'night'

def _current_date():
    now = datetime.now()
    if _current_shift == 'night' and now.hour < 6:
        return (now - timedelta(days=1)).strftime('%Y-%m-%d')
    return now.strftime('%Y-%m-%d')

def _run_sub(script, timeout=300):
    try:
        proc = subprocess.run([PYTHON, '-c', script],
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0 or not proc.stdout.strip():
            return False, (proc.stderr or 'No output').strip()[-300:]
        return True, json.loads(proc.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return False, 'Subprocess timed out'
    except Exception as e:
        return False, str(e)

def _run_script(script_path, stdin_json=None, timeout=300):
    """Run a Python script file as subprocess. Passes stdin_json via stdin."""
    try:
        proc = subprocess.run(
            [PYTHON, script_path, APP_DIR],
            input=json.dumps(stdin_json or {}),
            capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return False, (proc.stderr or 'No output').strip()[-400:]
        return True, json.loads(proc.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return False, 'Timecard fetch timed out'
    except Exception as e:
        return False, str(e)

def _bg_scc():
    """
    Run SCC in background without blocking the main scrape.
    Uses fetch_scc.py (file-based IPC) to avoid Chromium stdout-pipe issues on Windows.
    fetch_scc.py writes result to .scc_result_tmp.json in APP_DIR.
    """
    import traceback as _tb
    _dbg_log = os.path.join(APP_DIR, 'scc_debug', '_bg_scc.log')
    def _dbg(msg):
        try:
            with open(_dbg_log, 'a', encoding='utf-8') as _lf:
                _lf.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        except Exception: pass

    out_file   = os.path.join(APP_DIR, '.scc_result_tmp.json')
    scc_script = os.path.join(APP_DIR, 'fetch_scc.py')
    _dbg(f"starting -- out_file={out_file}")
    # Remove stale result file if it exists
    try:
        if os.path.exists(out_file): os.remove(out_file)
    except Exception:
        pass
    try:
        proc = subprocess.run(
            [PYTHON, scc_script, APP_DIR],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
        )
        _dbg(f"subprocess exit={proc.returncode}")
        if proc.stdout: _dbg(f"stdout: {proc.stdout.decode('utf-8','replace')[-500:]}")
        if proc.stderr: _dbg(f"stderr: {proc.stderr.decode('utf-8','replace')[-800:]}")
    except subprocess.TimeoutExpired:
        _dbg("subprocess TIMED OUT")
        return
    except Exception as e:
        _dbg(f"subprocess error: {e}")
        return

    _dbg(f"result file exists: {os.path.exists(out_file)}")
    if not os.path.exists(out_file):
        return
    try:
        with open(out_file, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        _dbg(f"file size={len(raw_text)} chars, first 200: {raw_text[:200]}")
        result = json.loads(raw_text)
        os.remove(out_file)
    except Exception as e:
        _dbg(f"json parse error: {e}")
        return

    if isinstance(result, dict):
        assignments = result.get('assignments', [])
        name_map    = result.get('name_map', {})
    elif isinstance(result, list):
        assignments = result
        name_map    = {}
    else:
        _dbg(f"unexpected result type: {type(result)}")
        return
    _dbg(f"assignments={len(assignments)}, name_map={len(name_map)}")
    if assignments or name_map:
        cache_set('scc', {'assignments': assignments, 'name_map': name_map})
        _dbg(f"cache_set done")
    else:
        _dbg("WARNING: assignments and name_map both empty -- cache NOT set")


def _bg_timecards(badges, shift, date_str):
    """
    Background thread: fetch whole-shift timecards for all associates.
    Writes results to _tc_cache so enrich() can overlay them.
    Runs as a daemon thread -- never blocks the main scrape loop.
    Uses a temp file for IPC to avoid the Windows stdout-pipe hang when
    Chromium grandchildren outlive the fetch_tc.py subprocess.
    """
    if _tc_bg_running.is_set():
        return   # another batch is still running
    _tc_bg_running.set()
    try:
        import tempfile, time as _time
        tc_script   = os.path.join(APP_DIR, 'fetch_tc.py')
        out_file    = os.path.join(APP_DIR, '.tc_result_tmp.json')
        stdin_data  = json.dumps({'badges': badges, 'shift': shift, 'out_file': out_file})

        # Run subprocess with stdout discarded -- fetch_tc.py writes to out_file instead.
        # This prevents the Chromium grandchild pipe-hang on Windows.
        try:
            proc = subprocess.run(
                [PYTHON, tc_script, APP_DIR],
                input=stdin_data,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=600,   # 10 min hard cap
            )
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        # Read results from file
        if os.path.exists(out_file):
            try:
                with open(out_file, 'r', encoding='utf-8') as f:
                    tc_result = json.load(f)
                os.remove(out_file)
                if isinstance(tc_result, dict):
                    with _tc_cache_lock:
                        _tc_cache.update(tc_result)
                    # Trigger a fresh enrich pass so the dashboard shows updated PT
                    threading.Thread(target=_apply_tc_overlay, args=(shift, date_str), daemon=True).start()
            except Exception:
                pass
    finally:
        _tc_bg_running.clear()


def _apply_tc_overlay(shift, date_str):
    """Re-enrich cached associates with fresh timecard data and push update."""
    import time as _time
    _time.sleep(1)   # let _tc_cache settle
    data, ts = cache_get(f'data_{shift}')
    if not data:
        return
    # Re-overlay tc data on the raw associates (stored in cache with tc_ fields already)
    with _tc_cache_lock:
        for a in data:
            tc = _tc_cache.get(a.get('badge', ''))
            if isinstance(tc, dict) and tc.get('pt_pct') is not None:
                a['tc_pt_pct']    = tc['pt_pct']
                a['tc_total_min'] = tc.get('total_min',    a.get('total', 0) * 60)
                a['tc_idle_min']  = tc.get('adj_idle_min', a.get('inferred', 0) * 60)

    from engine import enrich, save_snapshot
    enriched = enrich(data, shift, date_str)
    cache_set(f'data_{shift}', enriched)
    save_snapshot(enriched, shift, date_str)
    flagged  = [a for a in enriched if a.get('flagged')]
    critical = [a for a in enriched if a.get('status') == 'below']
    if flagged:
        push('flags', {'count': len(flagged), 'critical': len(critical),
                       'below': [a['name'] for a in critical]})


def do_scrape():
    global _scrape_status, _current_shift
    if not _scrape_lock.acquire(blocking=False):
        return
    try:
        # Auto-detect shift from current time so the server doesn't need a restart
        # when crossing the 18:00 (day→night) or 06:00 (night→day) boundary.
        h = datetime.now().hour
        auto_shift = 'night' if (h >= 18 or h < 6) else 'day'
        if auto_shift != _current_shift:
            _current_shift = auto_shift

        shift    = _current_shift
        date_str = _current_date()

        # SCC runs in background only — does not block PT data display
        scc_data, scc_ts = cache_get('scc')
        scc_age = (datetime.now() - scc_ts).total_seconds() if scc_ts else 9999
        if scc_data is None or scc_age > 900:
            threading.Thread(target=_bg_scc, daemon=True).start()

        # PT data from FCLM process inspector (only blocking step)
        _scrape_status['msg']  = 'Loading PT data from FCLM...'
        _scrape_status['step'] = 'fclm_pi'
        pi_script = (
            f"import sys, json; sys.path.insert(0, r'{APP_DIR}');"
            f"from fclm import fetch;"
            f"r = fetch('{date_str}', '{shift}'); print(json.dumps(r))"
        )
        ok, result = _run_sub(pi_script, timeout=300)
        if ok and result.get('ok'):
            associates = result['associates']
            _scrape_status['need_login'] = False
        else:
            err = result.get('error', result) if isinstance(result, dict) else result
            need_login = isinstance(result, dict) and result.get('need_login', False)
            _scrape_status['msg']        = 'Login required — click Login FCLM' if need_login else f'FCLM error: {err}'
            _scrape_status['error']      = str(err)
            _scrape_status['need_login'] = need_login
            return

        # Step 2b: Apply SCC station/floor assignments.
        # Primary join: SCC login == FCLM login (if extracted).
        # Fallback join: normalize FCLM name ("Wiley, Maree") to "maree wiley" and
        #                match against SCC Global sidebar name ("Maree Wiley") -> login -> station.
        scc_cache, _ = cache_get('scc')
        if scc_cache:
            scc_assignments = scc_cache.get('assignments', []) if isinstance(scc_cache, dict) else scc_cache
            scc_name_map    = scc_cache.get('name_map', {})   if isinstance(scc_cache, dict) else {}
            # login -> {station, floor}
            scc_login_map   = {a['login'].lower(): a for a in scc_assignments if a.get('login')}
            # normalized full_name -> login
            def _norm(n):
                return ' '.join(n.lower().split())
            # SCC: "Maree Wiley" -> "maree wiley" -> login "wilsmare"
            scc_norm_to_login = {_norm(fn): lg for lg, fn in scc_name_map.items()}
            # FCLM: "Wiley, Maree" -> "maree wiley" (swap Last, First)
            def _norm_fclm(n):
                n = n.strip()
                if ',' in n:
                    parts = [p.strip() for p in n.split(',', 1)]
                    n = parts[1] + ' ' + parts[0]
                return _norm(n)

            for a in associates:
                existing_login = (a.get('login') or '').lower().strip()
                login_key = existing_login

                # Try name-based lookup if no login
                if not login_key:
                    norm_name = _norm_fclm(a.get('name', ''))
                    login_key = scc_norm_to_login.get(norm_name, '')

                if login_key and login_key in scc_login_map:
                    rec = scc_login_map[login_key]
                    a['station'] = rec.get('station', a.get('station', ''))
                    a['floor']   = rec.get('floor',   a.get('floor',   0))
                    if not existing_login:
                        a['login'] = login_key  # store for next refresh

        # Step 3: Overlay any timecard PT already in cache from background thread
        with _tc_cache_lock:
            for a in associates:
                tc = _tc_cache.get(a.get('badge', ''))
                if isinstance(tc, dict) and tc.get('pt_pct') is not None:
                    a['tc_pt_pct']    = tc['pt_pct']
                    a['tc_total_min'] = tc.get('total_min',    a.get('total', 0) * 60)
                    a['tc_idle_min']  = tc.get('adj_idle_min', a.get('inferred', 0) * 60)

        # Launch timecard batch in background if not already running
        if not _tc_bg_running.is_set():
            badges = [a['badge'] for a in associates if a.get('badge')]
            threading.Thread(
                target=_bg_timecards,
                args=(badges, shift, date_str),
                daemon=True
            ).start()

        # Step 4: Enrich and cache
        enriched = enrich(associates, shift, date_str)
        cache_set(f'data_{shift}', enriched)
        save_snapshot(enriched, shift, date_str)
        github_sync.push_live_data(enriched, shift, date_str)

        flagged  = [a for a in enriched if a.get('flagged')]
        critical = [a for a in enriched if a.get('status') == 'below']

        _scrape_status = {
            'msg':     f"Updated {datetime.now():%H:%M} - {len(enriched)} AAs, {len(flagged)} flagged",
            'last_ok': datetime.now().isoformat(),
            'error':   '',
            'step':    'done',
        }
        if flagged:
            push('flags', {'count': len(flagged), 'critical': len(critical),
                           'below': [a['name'] for a in critical]})

    except Exception as e:
        import traceback
        _scrape_status['msg']   = f'Error: {e}'
        _scrape_status['error'] = traceback.format_exc()[-400:]
    finally:
        _scrape_lock.release()

def _bg_loop():
    import time
    _heartbeat_count = 0
    while True:
        do_scrape()
        _heartbeat_count += 1
        if github_sync.ready() and _heartbeat_count % 2 == 0:
            # Push server URL every ~6 min so portal knows we're alive
            try:
                _ip = socket.gethostbyname(socket.gethostname())
                github_sync.push_server_url(f'http://{_ip}:5050')
            except Exception:
                pass
        time.sleep(180)

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    data, ts     = cache_get(f'data_{_current_shift}')
    scc_data, scc_ts = cache_get('scc')
    return jsonify({
        **_scrape_status,
        'shift':       _current_shift,
        'date':        _current_date(),
        'count':       len(data) if data else 0,
        'updated':     ts.isoformat() if ts else None,
        'scc_count':   len(scc_data.get('assignments', scc_data) if isinstance(scc_data, dict) else (scc_data or [])),
        'scc_names':   len(scc_data.get('name_map', {})) if isinstance(scc_data, dict) else 0,
        'scc_updated': scc_ts.isoformat() if scc_ts else None,
        'need_login':  _scrape_status.get('need_login', False),
    })

@app.route('/api/data')
def get_data():
    shift    = request.args.get('shift', _current_shift)
    floor    = request.args.get('floor', 'all')
    data, ts = cache_get(f'data_{shift}')
    if data is None:
        threading.Thread(target=do_scrape, daemon=True).start()
        return jsonify({'ok': False, 'associates': [], 'summary': {},
                        'msg': _scrape_status.get('msg', 'Fetching data...'),
                        'error': _scrape_status.get('error', ''),
                        'need_login': _scrape_status.get('need_login', False)})
    result = data
    if floor != 'all':
        try:
            result = [a for a in data if a.get('floor') == int(floor)]
        except ValueError:
            pass
    return jsonify({'ok': True, 'associates': result, 'summary': floor_summary(data),
                    'floors': sorted(set(a.get('floor', 0) for a in data if a.get('floor', 0) > 0)),
                    'updated': ts.isoformat() if ts else None,
                    'shift': shift, 'date': _current_date(), 'count': len(data)})

@app.route('/api/report')
def senior_report():
    shift    = request.args.get('shift', _current_shift)
    date_str = request.args.get('date', _current_date())
    data, ts = cache_get(f'data_{shift}')
    if not data:
        return jsonify({'ok': False, 'msg': 'No data yet'})
    summary = floor_summary(data)
    trend   = shift_trend(shift, date_str, limit=30)
    db = get_db()
    intervention_count = db.execute(
        "SELECT COUNT(*) FROM actions WHERE date=? AND shift=?", (date_str, shift)
    ).fetchone()[0]
    db.close()
    groups = {}
    for aa in data:
        stn = aa.get('station', '')
        try:
            stn_int = int(stn)
        except (ValueError, TypeError):
            continue
        base  = (stn_int // 10) * 10          # e.g. 2319 -> 2310
        label = f'{base}–{base + 9}'     # e.g. '2310-2319'
        if label not in groups:
            groups[label] = {'total': 0, 'flagged': 0, 'floor': aa.get('floor', 0), 'pts': [], 'base': base}
        groups[label]['total'] += 1
        if aa.get('flagged'): groups[label]['flagged'] += 1
        if aa.get('pt_pct') is not None: groups[label]['pts'].append(aa['pt_pct'])
    zone_issues = []
    for label, v in groups.items():
        if v['total'] >= 3 and v['flagged'] >= 2:
            avg = sum(v['pts']) / len(v['pts']) if v['pts'] else None
            zone_issues.append({'zone': label, 'total': v['total'], 'flagged': v['flagged'],
                                'floor': v['floor'], 'avg_pt': round(avg, 1) if avg else None})
    total_inf = sum(a.get('inferred', 0) for a in data)
    total_hrs = sum(a.get('total', 0) for a in data)
    overall_pt = round((1 - total_inf / total_hrs) * 100, 1) if total_hrs > 0 else None
    return jsonify({'ok': True, 'overall_pt': overall_pt, 'aa_count': len(data),
                    'flagged_count': sum(1 for a in data if a.get('flagged')),
                    'below_count': sum(1 for a in data if a.get('status') == 'below'),
                    'intervention_count': intervention_count, 'floor_summary': summary,
                    'trend': trend, 'zone_issues': sorted(zone_issues, key=lambda x: -x['flagged']),
                    'shift': shift, 'date': date_str, 'updated': ts.isoformat() if ts else None})

@app.route('/api/trend')
def get_trend():
    shift    = request.args.get('shift', _current_shift)
    date_str = request.args.get('date', _current_date())
    return jsonify({'ok': True, 'trend': shift_trend(shift, date_str)})

@app.route('/api/refresh-scc', methods=['POST'])
def refresh_scc():
    with _cache_lock:
        if 'scc' in _cache: del _cache['scc']
    threading.Thread(target=do_scrape, daemon=True).start()
    return jsonify({'ok': True, 'msg': 'Station reload started.'})

@app.route('/api/refresh', methods=['POST'])
def manual_refresh():
    global _current_shift
    body = request.get_json(silent=True) or {}
    if 'shift' in body: _current_shift = body['shift']
    threading.Thread(target=do_scrape, daemon=True).start()
    return jsonify({'ok': True, 'msg': 'Refresh started.'})

@app.route('/api/set-shift', methods=['POST'])
def set_shift():
    global _current_shift
    body = request.get_json(silent=True) or {}
    shift = body.get('shift', 'night')
    if shift in ('night', 'day'): _current_shift = shift
    return jsonify({'ok': True, 'shift': _current_shift})

@app.route('/timecard/<badge>')
def timecard_redirect(badge):
    return redirect(build_timecard_url(badge))

@app.route('/api/timecard-debug/<badge>')
def timecard_debug(badge):
    """
    Debug endpoint: fetch one timecard and return raw structure + parsed PT.
    Useful for confirming the HTML layout before the full batch runs.
    GET /api/timecard-debug/201065946
    """
    from fclm   import fetch_timecard
    from engine import parse_timecard_pt

    shift = request.args.get('shift', _current_shift)

    # Run in subprocess to isolate Playwright (os._exit safe)
    tc_script_inline = (
        f"import sys, json; sys.path.insert(0, r'{APP_DIR}');"
        f"from fclm import fetch_timecard;"
        f"r = fetch_timecard('{badge}', shift='{shift}'); print(json.dumps(r, default=str))"
    )
    ok, result = _run_sub(tc_script_inline, timeout=120)
    if not ok:
        return jsonify({'ok': False, 'error': result})

    # Also parse the rows so we can show the calculated PT
    parsed = None
    rows = result.get('rows', [])
    if rows:
        try:
            from engine import parse_timecard_pt
            parsed = parse_timecard_pt(rows, shift=shift)
        except Exception as e:
            parsed = {'error': str(e)}

    return jsonify({
        'ok':          result.get('ok', False),
        'badge':       badge,
        'url':         result.get('url', ''),
        'title':       result.get('title', ''),
        'pt_direct':   result.get('pt_direct'),
        'table_count': result.get('table_count', 0),
        'row_count':   len(rows),
        'parsed_pt':   parsed,
        'preview':     result.get('preview', '')[:2000],
        'rows':        rows[:80],    # cap for browser display
        'api_data':    result.get('api_data', []),
        'error':       result.get('error', ''),
    })

@app.route('/api/actions')
def get_actions():
    shift    = request.args.get('shift', _current_shift)
    date_str = request.args.get('date', _current_date())
    db  = get_db()
    rows = db.execute("SELECT * FROM actions WHERE date=? AND shift=? ORDER BY ts DESC",
                      (date_str, shift)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/action', methods=['POST'])
def log_action():
    d  = request.get_json(silent=True) or {}
    db = get_db()
    db.execute("INSERT INTO actions (badge,name,manager,action_type,note,am_name,date,shift,ts) "
               "VALUES (?,?,?,?,?,?,?,?,?)",
               (d.get('badge',''), d.get('name',''), d.get('manager',''),
                d.get('action_type',''), d.get('note',''), d.get('am_name',''),
                d.get('date', date.today().isoformat()), d.get('shift', _current_shift),
                datetime.now().isoformat()))
    db.commit(); db.close()
    github_sync.push_action({
        'badge': d.get('badge',''), 'name': d.get('name',''), 'manager': d.get('manager',''),
        'action_type': d.get('action_type',''), 'note': d.get('note',''), 'am_name': d.get('am_name',''),
        'date': d.get('date', date.today().isoformat()), 'shift': d.get('shift', _current_shift),
        'ts': datetime.now().isoformat()
    })
    return jsonify({'ok': True})

@app.route('/api/barrier', methods=['POST'])
def log_barrier():
    d  = request.get_json(silent=True) or {}
    db = get_db()
    db.execute("INSERT INTO barriers (badge,name,barrier,note,am_name,date,shift,ts) "
               "VALUES (?,?,?,?,?,?,?,?)",
               (d.get('badge',''), d.get('name',''), d.get('barrier',''),
                d.get('note',''), d.get('am_name',''),
                d.get('date', date.today().isoformat()), d.get('shift', _current_shift),
                datetime.now().isoformat()))
    db.commit(); db.close()
    return jsonify({'ok': True})

@app.route('/api/history/<badge>')
def get_history(badge):
    db   = get_db()
    rows = db.execute("SELECT date, shift, pt_pct, total, inferred FROM snapshots "
                      "WHERE badge=? ORDER BY ts DESC LIMIT 10", (badge,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/events')
def sse_stream():
    def stream():
        q = queue.Queue(maxsize=50)
        with _sse_lock: _sse_clients.append(q)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:    yield f'data: {q.get(timeout=25)}\n\n'
                except queue.Empty: yield ': keepalive\n\n'
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                try: _sse_clients.remove(q)
                except: pass
    return Response(stream_with_context(stream()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})



import traceback as _tb
def _excepthook(t, v, tb):
    with open(os.path.join(APP_DIR, 'crash.log'), 'a', encoding='utf-8') as f:
        f.write(f'\n--- CRASH {datetime.now()} ---\n')
        _tb.print_exception(t, v, tb, file=f)
    _tb.print_exception(t, v, tb)
sys.excepthook = _excepthook


@app.route('/api/debug/cache')
def debug_cache():
    """Inspect the in-memory cache keys and sizes."""
    with _cache_lock:
        info = {}
        for k, v in _cache.items():
            d = v.get('data')
            if isinstance(d, dict):
                info[k] = {t: len(v2) for t, v2 in d.items() if isinstance(v2, (list,dict))}
                info[k]['_ts'] = v.get('ts', '').isoformat() if hasattr(v.get('ts',''), 'isoformat') else str(v.get('ts',''))
            elif isinstance(d, list):
                info[k] = {'_len': len(d), '_ts': v.get('ts','').isoformat() if hasattr(v.get('ts',''), 'isoformat') else str(v.get('ts',''))}
            else:
                info[k] = {'_type': str(type(d)), '_ts': v.get('ts','').isoformat() if hasattr(v.get('ts',''), 'isoformat') else str(v.get('ts',''))}
    return jsonify(info)

if __name__ == '__main__':
    # Load GitHub sync config if available
    _cfg_path = os.path.join(APP_DIR, 'agent_config.json')
    if os.path.exists(_cfg_path):
        try:
            with open(_cfg_path, 'r', encoding='utf-8') as _f:
                _cfg = json.load(_f)
            github_sync.configure(_cfg.get('github_token',''), _cfg.get('github_repo',''))
            if github_sync.ready():
                print("  GitHub sync enabled -- seeding actions from GitHub...")
                _gh_actions = github_sync.pull_actions()
                if _gh_actions:
                    print(f"  Pulled {len(_gh_actions)} actions from GitHub")
        except Exception as _e:
            print(f"  GitHub sync config error: {_e}")
    init_db()
    h = datetime.now().hour
    _current_shift = 'night' if (h >= 18 or h < 6) else 'day'
    try:    ip = socket.gethostbyname(socket.gethostname())
    except: ip = '127.0.0.1'
    print(f"\n  {'='*52}\n   CLE3 PT Dashboard\n   Local:   http://localhost:5050")
    print(f"   Network: http://{ip}:5050\n   Shift:   {_current_shift}\n  {'='*52}\n")
    threading.Thread(target=_bg_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
