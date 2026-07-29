"""
CLE3 Live Dashboard — Flask backend.
Run via run.bat; accessible at http://[your-IP]:5000 on Amazon WiFi.
"""
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
import threading, queue, json, socket, os
from datetime import datetime, date
from db     import get_db, init_db
from engine import (get_next_action, compute_flags, project_pt, detect_patterns,
                    would_be_pt, get_expiring_soon, get_stu_template,
                    save_shift_snapshot, get_pt_trend, LABELS, EXPIRY)

app = Flask(__name__)

# ── SSE notification hub ──────────────────────────────────────────────────────
_sse_clients: list[queue.Queue] = []
_sse_lock    = threading.Lock()

def push_event(event_type, payload):
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:    q.put_nowait({'type': event_type, 'payload': payload, 'ts': datetime.now().isoformat()})
            except: dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

# ── In-memory data cache ──────────────────────────────────────────────────────
_cache     = {}
_cache_lck = threading.Lock()
CACHE_TTL  = 180  # seconds

def cached(key):
    with _cache_lck:
        e = _cache.get(key)
        if e and (datetime.now() - e['ts']).seconds < CACHE_TTL:
            return e['data']
    return None

def cache_set(key, data):
    with _cache_lck:
        _cache[key] = {'data': data, 'ts': datetime.now()}

# ── Background scrape thread ──────────────────────────────────────────────────
_scrape_lock   = threading.Lock()
_scrape_status = {'message': 'Not yet fetched', 'last_ok': None}
_current_shift = 'night'

def _enrich(rows, shift):
    """Attach feedback, flags, projection, and pattern data to each associate row."""
    associates = []
    for r in rows:
        login = r.get('id', r.get('login', ''))
        pt    = round(100 - (r['inferred'] / r['total'] * 100), 1) if r.get('total', 0) > 0 else None
        aa    = {**r, 'pt': pt, 'login': login}

        # New hire info
        conn = get_db()
        nh   = conn.execute("SELECT * FROM new_hires WHERE login=?", (login,)).fetchone()
        if nh:
            start    = datetime.strptime(nh['start_date'], '%Y-%m-%d')
            day_num  = (datetime.now() - start).days + 1
            aa['new_hire'] = {'start_date': nh['start_date'], 'day': day_num, 'notes': nh['notes']}
        else:
            aa['new_hire'] = None

        # Handoff note for today
        today = date.today().isoformat()
        note  = conn.execute(
            "SELECT note, am_name FROM handoff_notes WHERE login=? AND date=? ORDER BY created_at DESC LIMIT 1",
            (login, today)
        ).fetchone()
        aa['handoff_note'] = dict(note) if note else None
        conn.close()

        aa['flags']       = compute_flags(aa)
        aa['next_action'] = get_next_action(login)
        aa['projection']  = project_pt(aa)
        aa['pattern']     = detect_patterns(login)
        associates.append(aa)

    return associates

def _do_scrape(shift):
    from scraper import fetch_associates
    global _scrape_status
    if not _scrape_lock.acquire(blocking=False):
        return  # already scraping
    try:
        _scrape_status['message'] = f'Scraping {shift} shift…'
        result = fetch_associates(shift, status_cb=lambda m: _scrape_status.update({'message': m}))
        if result.get('ok'):
            rows       = result['associates']
            enriched   = _enrich(rows, shift)
            cache_set(f'associates_{shift}', enriched)
            today      = date.today().isoformat()
            save_shift_snapshot(enriched, shift, today)
            _scrape_status = {'message': f'Updated {datetime.now().strftime("%H:%M")} — {len(enriched)} AAs', 'last_ok': datetime.now().isoformat()}

            # Push notifications for new flags
            for aa in enriched:
                for flag in aa.get('flags', []):
                    if flag['severity'] in ('high', 'critical'):
                        push_event('flag', {'name': aa.get('name'), 'login': aa.get('login'), 'flag': flag['label']})
        else:
            _scrape_status['message'] = f'Scrape error: {result.get("error","")}'
    finally:
        _scrape_lock.release()

def _background_loop():
    import time
    while True:
        _do_scrape(_current_shift)
        time.sleep(180)

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify(_scrape_status)

@app.route('/api/refresh', methods=['POST'])
def refresh():
    shift = request.json.get('shift', 'night') if request.json else 'night'
    global _current_shift
    _current_shift = shift
    threading.Thread(target=_do_scrape, args=(shift,), daemon=True).start()
    return jsonify({'ok': True, 'message': 'Scrape started'})

@app.route('/api/associates')
def get_associates():
    shift  = request.args.get('shift', 'night')
    global _current_shift
    _current_shift = shift
    data   = cached(f'associates_{shift}')
    ts     = _cache.get(f'associates_{shift}', {}).get('ts')
    if data is None:
        threading.Thread(target=_do_scrape, args=(shift,), daemon=True).start()
        return jsonify({'ok': False, 'data': [], 'message': 'Fetching data — refresh in 30 seconds.'})
    return jsonify({'ok': True, 'data': data, 'updated': ts.isoformat() if ts else None,
                    'would_be': would_be_pt(data), 'expiring': get_expiring_soon()})

@app.route('/api/eti')
def get_eti():
    shift = request.args.get('shift', 'night')
    data  = cached(f'eti_{shift}')
    if data:
        return jsonify({'ok': True, **data})
    def _fetch():
        from scraper import fetch_eti_tph
        r = fetch_eti_tph(shift)
        if r.get('ok'):
            cache_set(f'eti_{shift}', r)
    threading.Thread(target=_fetch, daemon=True).start()
    return jsonify({'ok': False, 'message': 'ETI/TPH fetch started — refresh in 30s.'})

@app.route('/api/andons')
def get_andons():
    login = request.args.get('login', '')
    def _fetch():
        from scraper import fetch_andons
        r = fetch_andons(login_filter=login or None)
        if r.get('ok'):
            cache_set(f'andons_{login}', r)
    data = cached(f'andons_{login}')
    if data:
        return jsonify(data)
    threading.Thread(target=_fetch, daemon=True).start()
    return jsonify({'ok': False, 'andons': [], 'message': 'Fetching andons…'})

@app.route('/api/trend/<login>')
def get_trend(login):
    shift  = request.args.get('shift', 'night')
    today  = date.today().isoformat()
    points = get_pt_trend(login, today, shift)
    return jsonify({'ok': True, 'points': points})

@app.route('/api/patterns/<login>')
def get_patterns(login):
    return jsonify(detect_patterns(login))

# ── Feedback CRUD ─────────────────────────────────────────────────────────────
@app.route('/api/feedback/<login>')
def get_feedback(login):
    conn = get_db()
    rows = conn.execute("SELECT * FROM feedback WHERE login=? ORDER BY date DESC", (login,)).fetchall()
    conn.close()
    return jsonify({'records': [dict(r) for r in rows], 'next_action': get_next_action(login)})

@app.route('/api/feedback', methods=['POST'])
def save_feedback():
    d = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO feedback (login,name,type,date,has_pending,notes,am_name) VALUES (?,?,?,?,?,?,?)",
        (d['login'], d.get('name',''), d['type'], d['date'],
         int(d.get('has_pending', False)), d.get('notes',''), d.get('am_name',''))
    )
    conn.commit()
    # Log AM action
    conn.execute(
        "INSERT INTO am_actions (am_name,action_type,associate,login,date,shift) VALUES (?,?,?,?,?,?)",
        (d.get('am_name',''), d['type'], d.get('name',''), d['login'],
         date.today().isoformat(), _current_shift)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'next_action': get_next_action(d['login'])})

@app.route('/api/feedback/<int:fid>', methods=['DELETE'])
def delete_feedback(fid):
    conn = get_db(); conn.execute("DELETE FROM feedback WHERE id=?", (fid,)); conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Barriers ──────────────────────────────────────────────────────────────────
@app.route('/api/barriers/<login>')
def get_barriers(login):
    conn = get_db()
    rows = conn.execute("SELECT * FROM barriers WHERE login=? ORDER BY created_at DESC LIMIT 20", (login,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/barriers', methods=['POST'])
def save_barrier():
    d = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO barriers (login,name,date,shift,barrier,flag_type,am_name) VALUES (?,?,?,?,?,?,?)",
        (d['login'], d.get('name',''), date.today().isoformat(), _current_shift,
         d['barrier'], d.get('flag_type',''), d.get('am_name',''))
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/barriers/all')
def all_barriers():
    """Return all barriers to surface systemic patterns."""
    conn = get_db()
    rows = conn.execute(
        "SELECT barrier, flag_type, COUNT(*) as cnt, GROUP_CONCAT(name) as associates "
        "FROM barriers GROUP BY LOWER(barrier) ORDER BY cnt DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ── Handoff notes ─────────────────────────────────────────────────────────────
@app.route('/api/handoff')
def get_handoff():
    shift = request.args.get('shift', 'night')
    today = date.today().isoformat()
    conn  = get_db()
    rows  = conn.execute(
        "SELECT * FROM handoff_notes WHERE date=? AND shift=? ORDER BY created_at DESC",
        (today, shift)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/handoff', methods=['POST'])
def save_handoff():
    d = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO handoff_notes (login,name,date,shift,note,am_name) VALUES (?,?,?,?,?,?)",
        (d.get('login',''), d.get('name',''), date.today().isoformat(),
         _current_shift, d['note'], d.get('am_name',''))
    )
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── New hires ─────────────────────────────────────────────────────────────────
@app.route('/api/new-hire', methods=['POST'])
def save_new_hire():
    d = request.json
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO new_hires (login,name,start_date,notes) VALUES (?,?,?,?)",
        (d['login'], d.get('name',''), d['start_date'], d.get('notes',''))
    )
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/new-hire/<login>', methods=['DELETE'])
def delete_new_hire(login):
    conn = get_db(); conn.execute("DELETE FROM new_hires WHERE login=?", (login,)); conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Coaching prep packet ──────────────────────────────────────────────────────
@app.route('/api/coaching-prep/<login>')
def coaching_prep(login):
    shift   = request.args.get('shift', 'night')
    conn    = get_db()
    fb_rows = conn.execute("SELECT * FROM feedback WHERE login=? ORDER BY date DESC LIMIT 5", (login,)).fetchall()
    bar_rows= conn.execute("SELECT * FROM barriers WHERE login=? ORDER BY created_at DESC LIMIT 5", (login,)).fetchall()
    hist    = conn.execute("SELECT * FROM shift_history WHERE login=? ORDER BY date DESC LIMIT 5", (login,)).fetchall()
    nh      = conn.execute("SELECT * FROM new_hires WHERE login=?", (login,)).fetchone()
    conn.close()

    data_cache = cached(f'associates_{shift}') or []
    aa_data    = next((a for a in data_cache if a.get('login') == login or a.get('id') == login), {})

    pattern = detect_patterns(login)
    flags   = aa_data.get('flags', [])
    stu_tmpl= get_stu_template(flags)

    return jsonify({
        'login':         login,
        'name':          aa_data.get('name', login),
        'badge':         aa_data.get('id', ''),
        'manager':       aa_data.get('manager', ''),
        'current_pt':    aa_data.get('pt'),
        'projection':    aa_data.get('projection'),
        'flags':         flags,
        'next_action':   get_next_action(login),
        'pattern':       pattern,
        'feedback_history': [dict(r) for r in fb_rows],
        'barriers':      [dict(r) for r in bar_rows],
        'shift_history': [{'date':r['date'],'shift':r['shift'],'pt':r['pt_pct']} for r in hist],
        'new_hire':      dict(nh) if nh else None,
        'stu_template':  stu_tmpl,
        'generated_at':  datetime.now().isoformat(),
    })

# ── Rankings ──────────────────────────────────────────────────────────────────
@app.route('/api/rankings')
def get_rankings():
    shift = request.args.get('shift', 'night')
    data  = cached(f'associates_{shift}') or []

    # Group by manager
    mgr_map = {}
    for aa in data:
        m = aa.get('manager','Unknown')
        if m not in mgr_map:
            mgr_map[m] = {'name':m,'associates':[],'flagged':0,'total_inferred':0,'total_hours':0}
        mgr_map[m]['associates'].append(aa)
        if aa.get('flags'): mgr_map[m]['flagged'] += 1
        mgr_map[m]['total_inferred'] += aa.get('inferred',0)
        mgr_map[m]['total_hours']    += aa.get('total',0)

    managers = []
    for m in mgr_map.values():
        tot = m['total_hours']
        inf = m['total_inferred']
        pt  = round(100-(inf/tot*100),1) if tot>0 else None
        # Count actions from am_actions
        conn = get_db()
        actions = conn.execute(
            "SELECT COUNT(*) as cnt FROM am_actions WHERE am_name=? AND date>=date('now','-7 days')",
            (m['name'],)
        ).fetchone()['cnt']
        conn.close()
        managers.append({**m, 'pt': pt, 'aa_count': len(m['associates']), 'actions_7d': actions})

    managers.sort(key=lambda m: m.get('pt') or 0, reverse=True)

    # Top associates (by PT, best performers)
    all_aa  = sorted([a for a in data if a.get('pt') is not None], key=lambda a: a['pt'], reverse=True)
    # Most flagged
    flagged = sorted(data, key=lambda a: len(a.get('flags',[])), reverse=True)[:10]
    # Pattern offenders (most consecutive low shifts)
    patterns = []
    for aa in data[:50]:  # limit API calls
        p = detect_patterns(aa.get('login',''))
        if p.get('consecutive_low', 0) >= 2:
            patterns.append({'name':aa.get('name'),'login':aa.get('login'),
                              'consecutive':p['consecutive_low'],'history':p['history']})
    patterns.sort(key=lambda p: p['consecutive'], reverse=True)

    return jsonify({
        'managers': managers,
        'top_performers': all_aa[:10],
        'most_flagged':   flagged,
        'patterns':       patterns[:10],
        'would_be':       would_be_pt(data),
    })

# ── SSE stream ────────────────────────────────────────────────────────────────
@app.route('/api/events')
def sse():
    def stream():
        q = queue.Queue(maxsize=50)
        with _sse_lock:
            _sse_clients.append(q)
        try:
            # Send initial keepalive
            yield "data: {\"type\":\"connected\"}\n\n"
            while True:
                try:
                    event = q.get(timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                try: _sse_clients.remove(q)
                except: pass

    return Response(stream_with_context(stream()), mimetype='text/event-stream',
                    headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

# ── STU template endpoint ─────────────────────────────────────────────────────
@app.route('/api/stu-template/<login>')
def stu_template(login):
    shift  = request.args.get('shift', 'night')
    data   = cached(f'associates_{shift}') or []
    aa     = next((a for a in data if a.get('login')==login or a.get('id')==login), {})
    flags  = aa.get('flags', [])
    return jsonify({'template': get_stu_template(flags), 'flags': flags})

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    try:    ip = socket.gethostbyname(socket.gethostname())
    except: ip = '127.0.0.1'

    print(f"\n  {'='*50}")
    print(f"   CLE3 Live Dashboard")
    print(f"   Share on Amazon WiFi:  http://{ip}:5000")
    print(f"   Local access:          http://localhost:5000")
    print(f"  {'='*50}\n")

    # Start background scrape loop
    threading.Thread(target=_background_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
