"""
Timecard batch fetch worker -- called as subprocess by _bg_timecards().

Reads JSON from stdin:  {"badges": ["badge1", ...], "shift": "night",
                         "out_file": "path/to/result.json"}
Writes JSON to out_file (not stdout) to avoid the Windows stdout-pipe hang
that occurs when Chromium grandchildren outlive this process.

Result format: {badge: {pt_pct, total_min, activity_min,
                         idle_min, adj_idle_min, credit_min}}
"""
import sys, json, os
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else '.')

from fclm   import fetch_timecards_batch
from engine import parse_timecard_pt

data     = json.load(sys.stdin)
badges   = data.get('badges', [])
shift    = data.get('shift',  'night')
out_file = data.get('out_file', None)

# Fetch raw rows for all badges concurrently
tc_raw = fetch_timecards_batch(badges, shift=shift)

out = {}
for badge, tc in tc_raw.items():
    if not tc:
        continue
    if tc.get('pt_direct') is not None:
        out[badge] = {'pt_pct': tc['pt_direct'], 'source': 'direct'}
        continue
    rows = tc.get('rows', [])
    if not rows:
        continue
    parsed = parse_timecard_pt(rows, shift=shift)
    if parsed and parsed.get('pt_pct') is not None:
        out[badge] = parsed

# Write to file (not stdout) so pipe-hang can't block the caller
if out_file:
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(out, f)
else:
    print(json.dumps(out, default=str))
