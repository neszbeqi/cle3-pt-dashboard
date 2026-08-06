"""
CLE3 PT Dashboard — business logic.
Flags, projections, patterns.
"""
from datetime import datetime, date
from db import get_db

PT_TARGET   = 88.0   # flag below this
PT_WATCH    = 84.0   # amber zone
SHIFT_HOURS = 12

def flag_status(pt):
    """Return status string based on PT%."""
    if pt is None:   return 'unknown'
    if pt >= PT_TARGET: return 'good'
    if pt >= PT_WATCH:  return 'watch'
    return 'below'

def project_pt(inferred, total, shift_hours=SHIFT_HOURS):
    """
    Project end-of-shift PT% at current pace.
    Returns projected PT% or None if not enough data.
    """
    if not total or total <= 0:
        return None
    pt = 100 - (inferred / total * 100)
    remaining = max(0, shift_hours - total)
    # At current pace: same PT% for remaining hours
    proj_inferred  = inferred + remaining * (inferred / total)
    proj_pt        = 100 - (proj_inferred / shift_hours * 100)
    return round(max(0, min(100, proj_pt)), 1)

def time_to_standard(associates, shift_hours=SHIFT_HOURS):
    """
    For each associate, compute how many hours of perfect work
    are needed to still hit PT_TARGET.
    Returns dict: badge -> {can_hit: bool, hours_needed: float}
    """
    result = {}
    for a in associates:
        total    = a.get('total', 0)
        inferred = a.get('inferred', 0)
        if not total:
            result[a['badge']] = {'can_hit': True, 'hours_needed': None}
            continue
        productive_so_far = total - inferred
        target_prod = shift_hours * (PT_TARGET / 100)
        still_needed = max(0, target_prod - productive_so_far)
        remaining    = max(0, shift_hours - total)
        result[a['badge']] = {
            'can_hit':      still_needed <= remaining,
            'hours_needed': round(still_needed, 2),
            'remaining':    round(remaining, 2),
        }
    return result

def enrich(associates, shift, date_str):
    """Add status, projection, recent actions to each associate dict."""
    db = get_db()
    today = date_str
    enriched = []
    for a in associates:
        badge  = a['badge']
        pt     = a.get('pt_pct')
        status = flag_status(pt)
        proj   = project_pt(a.get('inferred',0), a.get('total',0))

        # Most recent action today
        row = db.execute(
            "SELECT action_type, note, am_name, ts FROM actions "
            "WHERE badge=? AND date=? AND shift=? ORDER BY ts DESC LIMIT 1",
            (badge, today, shift)
        ).fetchone()
        last_action = dict(row) if row else None

        # Consecutive below-standard shifts (pattern)
        hist = db.execute(
            "SELECT pt_pct FROM snapshots WHERE badge=? ORDER BY ts DESC LIMIT 5",
            (badge,)
        ).fetchall()
        consec = 0
        for h in hist:
            if h['pt_pct'] is not None and h['pt_pct'] < PT_TARGET:
                consec += 1
            else:
                break

        enriched.append({
            **a,
            'status':          status,
            'projection':      proj,
            'last_action':     last_action,
            'consecutive_low': consec,
            'flagged':         status in ('below', 'watch'),
        })

    db.close()
    return enriched

def save_snapshot(associates, shift, date_str):
    """Persist current PT values to snapshots table."""
    db  = get_db()
    ts  = datetime.now().isoformat()
    for a in associates:
        db.execute(
            "INSERT INTO snapshots (badge,name,manager,station,floor,date,shift,ts,pt_pct,inferred,total) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (a['badge'], a.get('name',''), a.get('manager',''), a.get('station',''),
             a.get('floor',0), date_str, shift, ts, a.get('pt_pct'), a.get('inferred',0), a.get('total',0))
        )
    db.commit()
    db.close()

def floor_summary(associates):
    """Return per-floor PT% averages."""
    floors = {}
    for a in associates:
        fl = a.get('floor', 0)
        if fl not in floors:
            floors[fl] = {'total_inferred': 0, 'total_hours': 0, 'count': 0}
        floors[fl]['total_inferred'] += a.get('inferred', 0)
        floors[fl]['total_hours']    += a.get('total', 0)
        floors[fl]['count']          += 1
    result = {}
    for fl, v in floors.items():
        if v['total_hours'] > 0:
            result[fl] = {
                'avg_pt': round(100 - (v['total_inferred'] / v['total_hours'] * 100), 1),
                'count':  v['count'],
            }
    return result
