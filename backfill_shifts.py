"""
One-time backfill — fetches any missing shift data for July 1 through yesterday,
then rebuilds CLE3_PT_Trends.xlsx.

For each date in the range, fetches whichever of the 3 shifts are not yet in history:
  - Night Shift (6p-6a)
  - Day Shift  (6a-6p)
  - All Day

Safe to re-run: skips dates/shifts already present.

Run once:
    python backfill_shifts.py
"""
import os, sys, importlib.util
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fclm, processor, history
import openpyxl

HISTORY_PATH = os.path.join(os.path.expanduser("~"), "Documents", "CLE3_Reports", "CLE3_PT_History.xlsx")
WAREHOUSE    = "CLE3"

# Backfill this full date range
BACKFILL_START = date(2026, 7, 1)
BACKFILL_END   = date.today() - timedelta(days=1)   # up through yesterday

# All 3 shifts: (FCLM name, display label used in history)
SHIFTS = [
    ("Night Shift (6p-6a)", "Night Shift (6p \u2013 6a)"),
    ("Day Shift  (6a-6p)",  "Day Shift (6a \u2013 6p)"),
    ("All Day",             "All Day"),
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def get_existing():
    """Return set of 'YYYY-MM-DD|Label' strings already in history."""
    if not os.path.exists(HISTORY_PATH):
        return set()
    wb = openpyxl.load_workbook(HISTORY_PATH)
    ws = wb["Daily Summary"]
    existing = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        date_val, shift_val = row[0], row[1]
        if date_val and shift_val:
            d = str(date_val)[:10]
            existing.add(f"{d}|{str(shift_val)}")
    return existing

def backfill():
    existing = get_existing()

    # Build list of (date_str, fclm_name, label) to fetch
    todo = []
    d = BACKFILL_START
    while d <= BACKFILL_END:
        date_str = d.strftime("%Y-%m-%d")
        for fclm_name, label in SHIFTS:
            if f"{date_str}|{label}" not in existing:
                todo.append((date_str, fclm_name, label))
        d += timedelta(days=1)

    if not todo:
        log("All data already present — nothing to fetch.")
    else:
        log(f"Need to fetch {len(todo)} shift(s) across "
            f"{BACKFILL_START} → {BACKFILL_END}")

        for date_str, fclm_name, label in todo:
            log(f"  Fetching {label}  {date_str} ...")
            result = fclm.fetch(date_str, fclm_name, WAREHOUSE, status_cb=log)
            if not result["ok"]:
                log(f"  FAILED: {result['error']}")
                continue
            data = processor.process(result["rows"])
            log(f"  OK  {data['aa_count']} associates, PT={data['overall_pt']}%")
            history.update(date_str, label, data)

    # Rebuild trends workbook
    log("Rebuilding CLE3_PT_Trends.xlsx ...")
    _candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_trends.py"),
        r"C:\Users\neszbeqi\.aki\aki_workspace\build_trends.py",
    ]
    bt_path = next((p for p in _candidates if os.path.exists(p)), None)
    if bt_path:
        spec = importlib.util.spec_from_file_location("build_trends", bt_path)
        bt   = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bt)
        bt.main()
        log(f"Trends saved: {bt.OUT_PATH}")
    else:
        log("build_trends.py not found — trends not rebuilt")

    log("Backfill complete!")

if __name__ == "__main__":
    backfill()
