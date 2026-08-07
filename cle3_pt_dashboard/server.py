"""
CLE3 PT Dashboard - Flask server.
Auto-refreshes from FCLM every 3 minutes.
"""
import threading, queue, json, socket, os
from datetime import datetime, date, timedelta
from flask import Flask, jsonify, request, Response, render_template, stream_with_context, redirect
from db     import init_db, get_db
from engine import enrich, save_snapshot, floor_summary, PT_TARGET
from fclm   import build_timecard_url

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# -- Cache ---------------------------------------------------------------------
_cache = {}
_cache_lock = threading.Lock()

def cache_set(key, val):
    with _cache_lock:
        _cache[key] = {'data': val, 'ts': datetime.now()}

def cache_get(key):
    with _cache_lock:
        e = _cache.get(key)
        if e:
            return e['data'], e['ts']
    return None, None

# -- SSE -----------------------------------------------------------------------
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

# -- Scrape state --------------------------------------------------------------
_scrape_lock   = threading.Lock()
_scrape_status = {'msg': 'Not yet fetched', 'last_ok': None, 'error': ''}
_current_shift = 'night'

def _current_date():
    """Return the correct date string for the active shift."""
    now = datetime.now()
    if _current_shift == 'night' and now.hour < 6:
        return (now - timedelta(days=1)).strftime('%Y-%m-%d')
    return now.strftime('%Y-%m-%d')

def do_scrape():
    """Run FCLM fetch in a separate subprocess so Playwright crashes cannot kill Flask."""
    global _scrape_status
    if not _scrape_lock.acquire(blocking=False):
        return
    try:
        import subprocess, json as _json, sys as _sys
        shift    = _current_shift
        date_str = _current_date()
        _scrape_status['msg'] = f'Scraping {shift} shift...'

        # Run fclm.fetch in a child process - isolates Playwright from Flask
        script = (
            f"import sys, json; sys.path.insert(0, r'{os.path.dirname(__file__)}');"
            f"from fclm import fetch; r = fetch('{date_str}', '{shift}'); print(json.dumps(r))"
        )
        proc = subprocess.run(
            [_sys.executable, '-c', script],
            capture_output=True, text=True, timeout=180
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            err = (proc.stderr or 'Subprocess exited with no output').strip()[-200:]
            _scrape_status['msg']   = f'Error: {err}'
            _scrape_status['error'] = err
            return

        result = _json.loads(proc.stdout.strip().splitlines()[-1])
        if result['ok']:
            associates = enrich(result['associates'], shift, date_str)
            cache_set(f'data_{shift}', associates)
            save_snapshot(associates, shift, date_str)
            flagged = [a for a in associates if a['flagged']]
            _scrape_status = {
                'msg': f'Updated {datetime.now():%H:%M} - {len(associates)} AAs',
                'last_ok': datetime.now().isoformat(),
                'error': '',
            }
            if flagged:
                push('flags', {'count': len(flagged), 'below': [a['name'] for a in flagged if a['status']=='below']})
        else:
            _scrape_status['msg']   = f'Error: {result["error"]}'
            _scrape_status['error'] = result['error']
    except subprocess.TimeoutExpired:
        _scrape_status['msg']   = 'Error: FCLM scrape timed out (180s)'
        _scrape_status['error'] = 'Timed out'
    except Exception as e:
        _scrape_status['msg']   = f'Error: {e}'
        _scrape_status['error'] = str(e)
    finally:
        _scrape_lock.release()

def _bg_loop():
    import time
    while True:
        do_scrape()
        time.sleep(180)

# -- Routes --------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    data, ts = cache_get(f'data_{_current_shift}')
    return jsonify({
        **_scrape_status,
        'shift': _current_shift,
        'date':  _current_date(),
        'count': len(data) if data else 0,
        'updated': ts.isoformat() if ts else None,
    })

@app.route('/api/data')
def get_data():
    shift   = request.args.get('shift', _current_shift)
    floor   = request.args.get('floor', 'all')
    data, ts = cache_get(f'data_{shift}')
    if data is None:
        threading.Thread(target=do_scrape, daemon=True).start()
        err = _scrape_status.get('error', '')
        msg = f'Error: {err}' if err else _scrape_status.get('msg', 'Fetching data - check back in ~30s.')
        return jsonify({'ok': False, 'associates': [], 'msg': msg, 'error': err})

    # Filter by floor
    result = data
    if floor != 'all':
        try:
            fl_num = int(floor)
            result = [a for a in data if a.get('floor') == fl_num]
        except ValueError:
            pass

    summary = floor_summary(data)
    return jsonify({
        'ok':         True,
        'associates': result,
        'summary':    summary,
        'floors':     sorted(set(a.get('floor',0) for a in data if a.get('floor',0) > 0)),
        'updated':    ts.isoformat() if ts else None,
        'shift':      shift,
        'date':       _current_date(),
    })

@app.route('/api/refresh', methods=['POST'])
def manual_refresh():
    global _current_shift
    body = request.get_json(silent=True) or {}
    if 'shift' in body:
        _current_shift = body['shift']
    threading.Thread(target=do_scrape, daemon=True).start()
    return jsonify({'ok': True, 'msg': 'Refresh started.'})

@app.route('/api/set-shift', methods=['POST'])
def set_shift():
    global _current_shift
    body = request.get_json(silent=True) or {}
    shift = body.get('shift', 'night')
    if shift in ('night', 'day'):
        _current_shift = shift
    return jsonify({'ok': True, 'shift': _current_shift})

@app.route('/timecard/<badge>')
def timecard_redirect(badge):
    """Open FCLM timecard for this associate in the browser."""
    shift    = request.args.get('shift', _current_shift)
    date_str = request.args.get('date',  _current_date())
    url      = build_timecard_url(badge)
    return redirect(url)

@app.route('/api/actions')
def get_actions():
    shift    = request.args.get('shift', _current_shift)
    date_str = request.args.get('date',  _current_date())
    db  = get_db()
    rows = db.execute(
        "SELECT * FROM actions WHERE date=? AND shift=? ORDER BY ts DESC",
        (date_str, shift)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/action', methods=['POST'])
def log_action():
    d  = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "INSERT INTO actions (badge,name,manager,action_type,note,am_name,date,shift,ts) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (d.get('badge',''), d.get('name',''), d.get('manager',''),
         d.get('action_type',''), d.get('note',''), d.get('am_name',''),
         d.get('date', date.today().isoformat()),
         d.get('shift', _current_shift),
         datetime.now().isoformat())
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/barrier', methods=['POST'])
def log_barrier():
    d  = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "INSERT INTO barriers (badge,name,barrier,note,am_name,date,shift,ts) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (d.get('badge',''), d.get('name',''), d.get('barrier',''),
         d.get('note',''), d.get('am_name',''),
         d.get('date', date.today().isoformat()),
         d.get('shift', _current_shift),
         datetime.now().isoformat())
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/barriers')
def get_barriers():
    badge    = request.args.get('badge', '')
    date_str = request.args.get('date', _current_date())
    db       = get_db()
    if badge:
        rows = db.execute(
            "SELECT * FROM barriers WHERE badge=? ORDER BY ts DESC LIMIT 20", (badge,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT barrier, COUNT(*) as cnt, GROUP_CONCAT(name) as names "
            "FROM barriers WHERE date>=date('now','-7 days') "
            "GROUP BY LOWER(barrier) ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/history/<badge>')
def get_history(badge):
    db   = get_db()
    rows = db.execute(
        "SELECT date, shift, pt_pct, total, inferred FROM snapshots "
        "WHERE badge=? ORDER BY ts DESC LIMIT 10",
        (badge,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/events')
def sse_stream():
    def stream():
        q = queue.Queue(maxsize=50)
        with _sse_lock:
            _sse_clients.append(q)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f'data: {msg}\n\n'
                except queue.Empty:
                    yield ': keepalive\n\n'
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                try: _sse_clients.remove(q)
                except: pass
    return Response(stream_with_context(stream()), mimetype='text/event-stream',
                    headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

import traceback, sys

def _excepthook(exc_type, exc_value, exc_tb):
    log_path = os.path.join(os.path.dirname(__file__), 'crash.log')
    with open(log_path, 'a', encoding='utf-8') as f:
        import datetime
        f.write(f'\n--- CRASH {datetime.datetime.now()} ---\n')
        traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    traceback.print_exception(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook

if __name__ == '__main__':
    init_db()
    h = datetime.now().hour
    _current_shift = 'night' if (h >= 18 or h < 6) else 'day'

    try:    ip = socket.gethostbyname(socket.gethostname())
    except: ip = '127.0.0.1'

    print(f"\n  {'='*52}")
    print(f"   CLE3 PT Dashboard")
    print(f"   Local:   http://localhost:5050")
    print(f"   Network: http://{ip}:5050")
    print(f"   Shift:   {_current_shift}")
    print(f"  {'='*52}\n")

    threading.Thread(target=_bg_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)

