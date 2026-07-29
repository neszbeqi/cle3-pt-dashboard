"""
Business logic: feedback progression, flags, PT projection, pattern detection.
"""
from datetime import datetime, timedelta
from db import get_db

# ── Feedback constants ─────────────────────────────────────────────────────────
EXPIRY = {
    'document_coaching': 60,
    'first_warning':     60,
    'second_warning':    60,
    'final_warning':     90,
}
LABELS = {
    'document_coaching': 'Document Coaching',
    'first_warning':     'First Warning',
    'second_warning':    'Second Warning',
    'final_warning':     'Final Warning',
    'separation':        'Separation',
    'stu':               'STU Only',
}
PROGRESSION = ['document_coaching','first_warning','second_warning','final_warning','separation']
COLORS = {
    'document_coaching': '#f59e0b',
    'first_warning':     '#f97316',
    'second_warning':    '#ef4444',
    'final_warning':     '#dc2626',
    'separation':        '#7f1d1d',
    'stu':               '#a78bfa',
}

def get_next_action(login):
    """Return next suggested feedback action for this associate."""
    conn = get_db()
    pending = conn.execute(
        "SELECT * FROM feedback WHERE login=? AND has_pending=1 ORDER BY date DESC LIMIT 1",
        (login,)).fetchone()
    last = conn.execute(
        "SELECT * FROM feedback WHERE login=? AND has_pending=0 ORDER BY date DESC LIMIT 1",
        (login,)).fetchone()
    conn.close()

    if pending:
        return {'action':'stu','label':'STU Only',
                'reason':'Pending feedback on file — cannot deliver new feedback',
                'color':COLORS['stu'],'days_remaining':None,'last_label':None,'delivered':None}

    if last is None:
        return {'action':'document_coaching','label':'Document Coaching',
                'reason':'No feedback on file','color':COLORS['document_coaching'],
                'days_remaining':None,'last_label':None,'delivered':None}

    last_type = last['type']
    try:    last_date = datetime.strptime(last['date'], '%Y-%m-%d')
    except: last_date = datetime.now()

    expiry     = EXPIRY.get(last_type, 60)
    days_since = (datetime.now() - last_date).days

    if days_since >= expiry:
        return {'action':'document_coaching','label':'Document Coaching',
                'reason':f'{LABELS.get(last_type,"?")} expired ({days_since}d ago)',
                'color':COLORS['document_coaching'],'days_remaining':None,
                'last_label':LABELS.get(last_type),'delivered':last['date']}

    days_rem = expiry - days_since
    idx = PROGRESSION.index(last_type) if last_type in PROGRESSION else 0
    nxt = PROGRESSION[min(idx + 1, len(PROGRESSION) - 1)]
    return {
        'action':       nxt,
        'label':        LABELS.get(nxt, nxt),
        'reason':       f'Active {LABELS.get(last_type)} — {days_rem}d remaining',
        'color':        COLORS.get(nxt, '#f59e0b'),
        'days_remaining': days_rem,
        'last_type':    last_type,
        'last_label':   LABELS.get(last_type),
        'delivered':    last['date'],
    }

def get_expiring_soon(days=7):
    """Return list of feedback records expiring within `days` days."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM feedback WHERE has_pending=0 ORDER BY date DESC"
    ).fetchall()
    conn.close()
    results = []
    seen = set()
    for row in rows:
        if row['login'] in seen: continue
        seen.add(row['login'])
        try:    d = datetime.strptime(row['date'], '%Y-%m-%d')
        except: continue
        exp   = EXPIRY.get(row['type'], 60)
        rem   = exp - (datetime.now() - d).days
        if 0 < rem <= days:
            results.append({
                'login': row['login'], 'name': row['name'],
                'type': row['type'], 'label': LABELS.get(row['type']),
                'days_remaining': rem, 'delivered': row['date'],
            })
    return results

def compute_flags(aa):
    """Compute list of flags for an associate dict."""
    flags = []
    pt       = aa.get('pt') or 0
    idle_hrs = aa.get('inferred', 0)
    idle_min = idle_hrs * 60

    if pt < 88 and pt > 0:
        flags.append({'type':'low_pt','label':f'PT {pt:.1f}% < 88%','severity':'high'})

    if aa.get('had_black_bar'):
        flags.append({'type':'black_bar','label':'Off task / black bar','severity':'critical'})

    # Idle segment analysis (when individual timecard data available)
    segments = aa.get('idle_segments', [])
    if segments:
        long10  = [s for s in segments if s.get('duration_min',0) >= 10]
        long15  = [s for s in segments if s.get('duration_min',0) >= 15]
        if len(long10) >= 4:
            flags.append({'type':'idle_count','label':f'{len(long10)} idle gaps >10 min','severity':'medium'})
        if len(long15) >= 2:
            flags.append({'type':'idle_long','label':f'{len(long15)} idle gaps ≥15 min','severity':'high'})
    else:
        # Heuristic from total idle time
        if idle_min >= 40:
            flags.append({'type':'idle_count','label':f'{idle_min:.0f} min idle (≥4×10m)','severity':'medium'})
        if idle_min >= 30:
            long_est = int(idle_min // 15)
            if long_est >= 2:
                flags.append({'type':'idle_long','label':f'Est. {long_est} idle blocks ≥15m','severity':'high'})

    return flags

def project_pt(aa, shift_hours=12):
    """
    Project end-of-shift PT% based on current trajectory.
    Returns dict with: trending (same pace), best_case (perfect rest),
    needs_hours (hours of perfect work needed to hit 88%).
    """
    pt       = aa.get('pt') or 0
    total    = aa.get('total', 0)      # hours elapsed so far
    inferred = aa.get('inferred', 0)   # idle hours so far

    if total <= 0:
        return None

    productive_so_far = total - inferred
    remaining         = max(0, shift_hours - total)

    # If same pace continues
    trending_productive = productive_so_far + remaining * (pt / 100)
    trending_pt         = round((trending_productive / shift_hours) * 100, 1)

    # Best case: perfect from here
    best_productive = productive_so_far + remaining
    best_pt         = round((best_productive / shift_hours) * 100, 1)

    # Hours of perfect work to hit 88%
    target_prod   = shift_hours * 0.88
    still_needed  = max(0, target_prod - productive_so_far)
    can_hit       = still_needed <= remaining

    return {
        'trending':      min(trending_pt, 100),
        'best_case':     min(best_pt, 100),
        'still_needed':  round(still_needed, 1),
        'remaining_hrs': round(remaining, 1),
        'can_hit_88':    can_hit,
        'elapsed_hrs':   round(total, 1),
    }

def detect_patterns(login, lookback=5):
    """
    Check last N shifts for consecutive low PT or idle issues.
    Returns dict with pattern info.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM shift_history WHERE login=? ORDER BY date DESC, shift DESC LIMIT ?",
        (login, lookback)
    ).fetchall()
    conn.close()

    if not rows:
        return {'consecutive_low': 0, 'shifts_checked': 0, 'history': []}

    history = [{'date':r['date'],'shift':r['shift'],'pt':r['pt_pct']} for r in rows]
    consecutive = 0
    for r in rows:
        if r['pt_pct'] is not None and r['pt_pct'] < 88:
            consecutive += 1
        else:
            break

    return {
        'consecutive_low': consecutive,
        'shifts_checked':  len(rows),
        'history':         history,
        'streak_label':    f'{consecutive} consecutive shifts below 88%' if consecutive >= 2 else '',
    }

def would_be_pt(associates, threshold=88.0):
    """
    Calculate what the floor PT would be if every flagged AA hit threshold.
    Returns {'current': X, 'would_be': Y, 'delta': Z}
    """
    valid = [a for a in associates if a.get('pt') is not None and a.get('total', 0) > 0]
    if not valid:
        return None

    current_inf  = sum(a['inferred'] for a in valid)
    current_tot  = sum(a['total']    for a in valid)
    current_pt   = round(100 - (current_inf / current_tot * 100), 1) if current_tot else 0

    # Simulate: flagged AAs hit threshold
    adj_inf = current_inf
    for a in valid:
        if a['pt'] < threshold:
            target_inf = a['total'] * (1 - threshold / 100)
            adj_inf   -= (a['inferred'] - target_inf)

    would_be = round(100 - (adj_inf / current_tot * 100), 1) if current_tot else 0
    return {
        'current':  current_pt,
        'would_be': min(would_be, 100.0),
        'delta':    round(would_be - current_pt, 1),
    }

def get_stu_template(flags):
    """Return a suggested STU conversation template based on flag types."""
    types = {f['type'] for f in flags}

    if 'black_bar' in types:
        return ("I noticed there was a period during your shift where you weren't "
                "active in the system. Can you help me understand what was going on "
                "during that time and if there's anything I can do to support you?")
    if 'idle_long' in types:
        return ("I can see you had a couple of extended gaps between stows today — "
                "15 minutes or more. Walk me through your shift. Were there any "
                "barriers or issues that were slowing you down?")
    if 'idle_count' in types:
        return ("Looking at your timecard, there were several periods where stowing "
                "stopped for 10 minutes or more. That kind of pattern usually means "
                "something got in the way. What happened today?")
    if 'low_pt' in types:
        return ("Your productive time came in below our 88% target today. "
                "Before we talk about next steps, I want to make sure I understand "
                "your side — were there any barriers, equipment issues, or anything "
                "else that affected your shift?")
    return ("I wanted to check in about your shift today. I noticed some things on "
            "your timecard I'd like to better understand. Walk me through how your "
            "shift went.")

def save_shift_snapshot(associates, shift, date_str):
    """Store shift history for pattern detection (called after each scrape)."""
    conn = get_db()
    from datetime import datetime as dt
    ts = dt.now().isoformat()
    for aa in associates:
        login = aa.get('id','')
        if not login: continue
        pt    = aa.get('pt')
        try:
            conn.execute('''
                INSERT OR REPLACE INTO shift_history
                (login, name, date, shift, pt_pct, idle_hrs, total_hrs, manager)
                VALUES (?,?,?,?,?,?,?,?)
            ''', (login, aa.get('name',''), date_str, shift, pt,
                  aa.get('inferred',0), aa.get('total',0), aa.get('manager','')))
        except Exception:
            pass

        # Snapshot for trend chart
        try:
            conn.execute('''
                INSERT INTO pt_snapshots (login, name, date, shift, ts, pt_pct, inferred, total, manager)
                VALUES (?,?,?,?,?,?,?,?,?)
            ''', (login, aa.get('name',''), date_str, shift, ts, pt,
                  aa.get('inferred',0), aa.get('total',0), aa.get('manager','')))
        except Exception:
            pass
    conn.commit()
    conn.close()

def get_pt_trend(login, date_str, shift):
    """Return time-series PT snapshots for momentum chart."""
    conn = get_db()
    rows = conn.execute(
        "SELECT ts, pt_pct, inferred, total FROM pt_snapshots "
        "WHERE login=? AND date=? AND shift=? ORDER BY ts",
        (login, date_str, shift)
    ).fetchall()
    conn.close()
    return [{'ts': r['ts'], 'pt': r['pt_pct'],
             'inferred': r['inferred'], 'total': r['total']} for r in rows]
