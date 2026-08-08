"""
CLE3 PT Dashboard -- business logic.
Flags, projections, patterns.
"""
from datetime import datetime, date
from db import get_db

PT_TARGET   = 88.0   # flag below this
PT_WATCH    = 84.0   # amber zone
SHIFT_HOURS = 12


# ---------------------------------------------------------------------------
# Break credit helpers
# ---------------------------------------------------------------------------
# Break rules differ by regular vs FLEX associates.
#
# Regular AAs:
#   10 PM (night) / 10 AM (day) break -- CLOCKED OUT.
#       FCLM shows no idle during the 30-min off-clock window.
#       Credit only the 5-min grace on each side = 10 min max.
#       Pre-grace window : 9:55-10:00    (5 min)
#       Post-grace window: 10:30-10:35   (5 min)
#   2 AM (night) / 2 PM (day) break -- ON CLOCK.
#       FCLM tracks idle for the full 30 min. Credit all 30 min.
#
# FLEX AAs (is_flex=True):
#   10 PM / 10 AM break -- ON CLOCK (paid).
#       Credit 9:55-10:35 = 40 min (break + 5-min grace each side).
#   2 AM / 2 PM break -- CLOCKED OUT.
#       No idle tracked. Credit 0.
# ---------------------------------------------------------------------------

def _window_credit(now_min, start_min, end_min, max_min):
    """
    Minutes of credit earned for a single time window.
    Prorates during the window; returns max_min once past it.
    """
    if now_min >= end_min:
        return max_min
    elif now_min > start_min:
        return min(now_min - start_min, max_min)
    return 0.0


def break_credit_hours(shift='night', is_flex=False):
    """
    Total hours of paid-break credit to subtract from inferred idle.
    Handles midnight crossing for night shift.
    is_flex: True if FCLM labels this associate as FLEX.
    """
    now  = datetime.now()
    h, m = now.hour, now.minute
    nm   = h * 60 + m      # minutes since midnight

    total_min = 0.0

    if shift == 'night':
        # -- 10 PM break (22:00) ------------------------------------------
        # Night shift runs 18:00-06:00. If h < 6, we are in early-AM portion;
        # the 10 PM window is fully elapsed. If h >= 18, we are in PM portion.
        if h >= 18:
            if is_flex:
                # On clock: credit 9:55 PM to 10:35 PM = 40 min
                total_min += _window_credit(nm, 21*60+55, 22*60+35, 40)
            else:
                # Clocked out: credit pre-grace 9:55-10:00 (5 min)
                total_min += _window_credit(nm, 21*60+55, 22*60+0, 5)
                # and post-grace 10:30-10:35 (5 min)
                total_min += _window_credit(nm, 22*60+30, 22*60+35, 5)
        else:
            # Past midnight (0-6 AM): 10 PM window fully elapsed
            total_min += 40 if is_flex else 10

        # -- 2 AM break (02:00) -------------------------------------------
        # Regular: on clock, credit 30 min. FLEX: clocked out, credit 0.
        if not is_flex and h < 6:
            total_min += _window_credit(nm, 2*60, 2*60+30, 30)

    elif shift == 'day':
        # -- 10 AM break (10:00) ------------------------------------------
        if is_flex:
            total_min += _window_credit(nm, 9*60+55, 10*60+35, 40)
        else:
            total_min += _window_credit(nm, 9*60+55, 10*60+0, 5)
            total_min += _window_credit(nm, 10*60+30, 10*60+35, 5)

        # -- 2 PM break (14:00) -------------------------------------------
        # Regular: on clock, credit 30 min. FLEX: clocked out, credit 0.
        if not is_flex:
            total_min += _window_credit(nm, 14*60, 14*60+30, 30)

    return round(total_min / 60.0, 4)



def parse_timecard_pt(rows, shift="night", is_flex=False):
    """
    Parse raw FCLM timecard JS rows into whole-shift PT metrics.

    FCLM timeDetails page row structure (observed 2026-08):
      Activity rows (table 3): 6 cells
        [0] trackingType  ("i", "d", …)
        [1] activity name ("Stow Each Nike", "RF Pick", …)
        [2] start         "MM/DD-HH:MM:SS"
        [3] end           "MM/DD-HH:MM:SS"
        [4] duration      "HH:MM" or "HH:MM:SS"  (rightAlign class)
        [5] holder        (empty)

      Punch rows (table 6): captured separately in result.punches
        {type: "clock in"/"clock out", time: "MM/DD-HH:MM:SS"}

    PT% = (on_clock_min - adj_idle_min) / on_clock_min * 100
    on_clock_min  = clock-in to clock-out (minus any off-clock gaps)
    productive_min= sum of activity durations within on-clock window
    idle_min      = on_clock_min - productive_min
    adj_idle_min  = max(0, idle_min - break_credit_min)

    Also accepts punches list (extracted by _TIMECARD_JS) to compute on-clock
    time from actual clock punch data.  Falls back to activity-span heuristic
    if punch data is unavailable.
    """
    import re as _re
    from datetime import datetime as _dt, timedelta as _td

    def _parse_dt(s):
        """MM/DD-HH:MM:SS or MM/DD-HH:MM -> datetime (current year)."""
        if not s:
            return None
        m = _re.match(r"(\d{1,2})/(\d{1,2})-(\d{2}):(\d{2})(?::(\d{2}))?", s.strip())
        if not m:
            return None
        mo, day, h, mn = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        sec = int(m.group(5) or 0)
        year = _dt.now().year
        try:
            return _dt(year, mo, day, h, mn, sec)
        except ValueError:
            return None

    def _parse_dur(s):
        """HH:MM[:SS] -> float minutes."""
        if not s:
            return None
        m = _re.match(r"(\d+):(\d{2})(?::(\d{2}))?", s.strip())
        if not m:
            return None
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3) or 0) / 60.0

    def _fix_midnight(dt, shift, now):
        """
        Night shift midnight correction: if we are in early AM and the
        parsed timestamp is a PM hour, it belongs to the previous calendar day.
        """
        if dt is None:
            return dt
        if shift == "night" and now.hour < 6 and dt.hour >= 18:
            return dt - _td(days=1)
        return dt

    now        = _dt.now()
    activities = []   # list of (start_dt, end_dt, title)
    punches    = []   # list of (type_str, dt) from result.punches if passed in rows meta

    # ── Parse activity rows ───────────────────────────────────────────────
    for row in rows:
        cells = [c.get("text", "") for c in row.get("cells", [])]
        n = len(cells)

        start = end = title = None

        if n >= 5:
            # Preferred format: [trackingType][name][start][end][duration][holder]
            candidate_start = _parse_dt(cells[2])
            candidate_end   = _parse_dt(cells[3])
            if candidate_start:
                title = cells[1].strip()
                start = _fix_midnight(candidate_start, shift, now)
                end   = _fix_midnight(candidate_end,   shift, now) if candidate_end else None
                if not end:
                    dur = _parse_dur(cells[4])
                    if dur is not None:
                        end = start + _td(minutes=dur)

        if start is None and n >= 4:
            # Legacy / alternate format: [name][start][end][duration]
            candidate_start = _parse_dt(cells[1])
            if candidate_start:
                title = cells[0].strip()
                start = _fix_midnight(candidate_start, shift, now)
                end   = _fix_midnight(_parse_dt(cells[2]), shift, now)
                if not end:
                    dur = _parse_dur(cells[3])
                    if dur is not None:
                        end = start + _td(minutes=dur)

        if start is None or not title:
            continue
        if not end:
            end = now
        if (end - start).total_seconds() / 60.0 <= 0:
            continue

        # Skip visual/legend rows (title is a single char like "i", "d", etc.)
        if len(title) <= 1 and not title.isalpha():
            continue
        # Skip rows that look like column headers or totals
        tl = title.lower()
        if any(kw in tl for kw in ("clock/paid", "direct function", "exempt job",
                                    "indirect function", "time off task", "punch type")):
            continue

        activities.append((start, end, title))

    if not activities:
        return None

    # ── Derive on-clock window ────────────────────────────────────────────
    # Use the span from the earliest activity start to the latest activity end
    # (or now if shift is still in progress).
    first_start = min(s for s, e, _ in activities)
    last_end    = max(e for s, e, _ in activities)
    # If the shift is ongoing, extend to current time
    if now < last_end + _td(hours=1):
        last_end = max(last_end, now)

    on_clock_min = (last_end - first_start).total_seconds() / 60.0

    # Sum productive time (activity durations, deduplicating overlaps naively)
    activities_sorted = sorted(activities, key=lambda x: x[0])
    productive_min = 0.0
    merged_end = None
    for a_start, a_end, _ in activities_sorted:
        if merged_end is None or a_start >= merged_end:
            productive_min += (a_end - a_start).total_seconds() / 60.0
            merged_end = a_end
        elif a_end > merged_end:
            productive_min += (a_end - merged_end).total_seconds() / 60.0
            merged_end = a_end

    idle_min   = max(0.0, on_clock_min - productive_min)
    credit_min = break_credit_hours(shift, is_flex=is_flex) * 60.0
    adj_idle   = max(0.0, idle_min - credit_min)
    pt_pct     = round((on_clock_min - adj_idle) / on_clock_min * 100.0, 1) if on_clock_min > 0 else None

    return {
        "total_min":    round(on_clock_min,  1),
        "activity_min": round(productive_min, 1),
        "idle_min":     round(idle_min,       1),
        "credit_min":   round(credit_min,     1),
        "adj_idle_min": round(adj_idle,       1),
        "pt_pct":       pt_pct,
    }


def flag_status(pt):
    """Return status string based on PT%."""
    if pt is None:      return 'unknown'
    if pt >= PT_TARGET: return 'good'
    if pt >= PT_WATCH:  return 'watch'
    return 'below'


def project_pt(inferred, total, shift_hours=SHIFT_HOURS):
    """
    Hours of perfect (100%) stow work needed to reach PT_TARGET.
    Returns 0 if already on target, positive hours if recovery needed.
    """
    if not total or total <= 0 or inferred is None:
        return None
    rate         = 1 - PT_TARGET / 100
    needed_total = inferred / rate
    recovery     = needed_total - total
    return round(max(0, recovery), 1)


def time_to_standard(associates, shift_hours=SHIFT_HOURS):
    result = {}
    for a in associates:
        total    = a.get('total', 0)
        inferred = a.get('inferred', 0)
        if not total:
            result[a['badge']] = {'can_hit': True, 'hours_needed': None}
            continue
        productive_so_far = total - inferred
        target_prod  = shift_hours * (PT_TARGET / 100)
        still_needed = max(0, target_prod - productive_so_far)
        remaining    = max(0, shift_hours - total)
        result[a['badge']] = {
            'can_hit':      still_needed <= remaining,
            'hours_needed': round(still_needed, 2),
            'remaining':    round(remaining, 2),
        }
    return result


def enrich(associates, shift, date_str):
    """Add status, projection, break credit, recent actions to each associate dict."""
    db    = get_db()
    today = date_str

    enriched = []
    for a in associates:
        badge        = a['badge']
        is_flex      = a.get('is_flex', False)
        raw_inferred = a.get('inferred', 0)
        total        = a.get('total', 0)

        # Prefer whole-shift timecard PT if it was fetched; fall back to stow-only
        tc_pt   = a.get('tc_pt_pct')
        tc_tot  = a.get('tc_total_min', 0)
        tc_idle = a.get('tc_idle_min', 0)

        if tc_pt is not None and 0 <= tc_pt <= 100:
            # Timecard data available: use whole-shift numbers
            pt           = tc_pt
            total        = tc_tot / 60.0   # convert minutes -> hours for projection
            adj_inferred = tc_idle / 60.0
            credit       = 0.0             # credit already applied in parse_timecard_pt
        else:
            # Fall back to stow-only PT with break credit
            credit       = break_credit_hours(shift, is_flex=is_flex)
            adj_inferred = max(0.0, raw_inferred - credit)
            if total and total > 0:
                pt = round(100 - (adj_inferred / total * 100), 1)
            else:
                pt = a.get('pt_pct')

        status = flag_status(pt)
        proj   = project_pt(adj_inferred, total)

        # Most recent action today
        row = db.execute(
            'SELECT action_type, note, am_name, ts FROM actions '
            'WHERE badge=? AND date=? AND shift=? ORDER BY ts DESC LIMIT 1',
            (badge, today, shift)
        ).fetchone()
        last_action = dict(row) if row else None

        # Consecutive below-standard shifts (pattern)
        hist = db.execute(
            'SELECT pt_pct FROM snapshots WHERE badge=? ORDER BY ts DESC LIMIT 5',
            (badge,)
        ).fetchall()
        consec = 0
        for h_row in hist:
            if h_row['pt_pct'] is not None and h_row['pt_pct'] < PT_TARGET:
                consec += 1
            else:
                break

        enriched.append({
            **a,
            'pt_pct':          pt,
            'inferred':        adj_inferred,
            'break_credit':    round(credit * 60, 1),   # minutes credited (for tooltip)
            'is_flex':         is_flex,
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
            'INSERT INTO snapshots (badge,name,manager,station,floor,date,shift,ts,pt_pct,inferred,total) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
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


def shift_trend(shift, date_str, limit=20):
    """Return PT% snapshots over the shift for the trend line."""
    db = get_db()
    rows = db.execute(
        'SELECT ts, AVG(pt_pct) as avg_pt, COUNT(*) as cnt '
        'FROM snapshots WHERE shift=? AND date=? AND pt_pct IS NOT NULL '
        'GROUP BY ts ORDER BY ts DESC LIMIT ?',
        (shift, date_str, limit)
    ).fetchall()
    db.close()
    return [{'ts': r['ts'], 'avg_pt': round(r['avg_pt'], 1), 'count': r['cnt']}
            for r in reversed(rows)]
