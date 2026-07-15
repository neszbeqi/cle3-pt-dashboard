"""
BMI (Business Metrics Intelligence) scraper for CLE3.
Fetches facility-level productive time metrics from bmi.amazon.com.
Reuses the same Playwright browser session as fclm.py (shared Midway login).
"""
import os, re
from datetime import date
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BMI_URL = 'https://bmi.amazon.com/level/two/{warehouse}'

def _session_dir():
    for env in ('LOCALAPPDATA', 'USERPROFILE', 'TEMP', 'TMP'):
        base = os.environ.get(env)
        if base and os.path.isdir(base):
            return os.path.join(base, '.pt_dashboard', 'session')
    return os.path.join(os.path.expanduser('~'), '.pt_dashboard', 'session')

SESSION_DIR = _session_dir()

# Metrics we care about, in display order
METRIC_ORDER = [
    'Productive Time',
    'Unknown Idle',
    'Indirect',
    'Labor Move',
    'Fast Start',
    'Break',
    'Strong Finish',
    'Changeover',
]

def _parse_pct(text):
    if not text or text.strip() in ('', '—', '-', 'N/A', 'n/a'):
        return None
    try:
        return round(float(re.sub(r'[^\d.\-]', '', text.strip())), 1)
    except (ValueError, TypeError):
        return None


def fetch(warehouse='CLE3', status_cb=None):
    """
    Returns:
        { 'ok': True,
          'date': 'YYYY-MM-DD',
          'metrics':   { 'Productive Time': 65.4, 'Unknown Idle': 32.3, ... },
          'rolling_7': { 'Productive Time': 64.7, ... },
          'metric_type': { 'Productive Time': '% Availability', ... } }
    or:
        { 'ok': False, 'error': '...' }
    """
    def log(msg):
        if status_cb: status_cb(f'BMI: {msg}')

    url = BMI_URL.format(warehouse=warehouse)

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                SESSION_DIR,
                headless=False,
                args=['--window-position=3000,0'],  # push off-screen
            )
            page = ctx.new_page()
            log('Loading page...')
            page.goto(url, wait_until='networkidle', timeout=30000)

            # Wait for successful data load
            try:
                page.wait_for_selector('text=Loaded data', timeout=15000)
                log('Page loaded.')
            except PWTimeout:
                # Might need Midway login
                log('Waiting for login...')
                page.wait_for_selector('text=Loaded data', timeout=120000)
                log('Logged in. Page loaded.')

            page.wait_for_timeout(1500)

            # Extract raw table as 2-D array via JS
            cells = page.evaluate("""
                () => {
                    const tables = document.querySelectorAll('table');
                    for (const tbl of tables) {
                        const rows = Array.from(tbl.querySelectorAll('tr'));
                        if (rows.length > 3) {
                            return rows.map(r =>
                                Array.from(r.querySelectorAll('th,td'))
                                    .map(c => c.innerText.trim())
                            );
                        }
                    }
                    return null;
                }
            """)

            page.close()
            ctx.close()

            if not cells:
                return {'ok': False, 'error': 'No data table found on BMI page.'}

            return _parse_cells(cells, log)

    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _parse_cells(rows, log):
    if not rows:
        return {'ok': False, 'error': 'Empty table.'}

    # ── Find header row and column indices ─────────────────────
    header = rows[0]
    today  = date.today()

    today_col   = None
    rolling_col = None

    for i, h in enumerate(header):
        h_clean = h.replace('\n', ' ')
        if re.search(r'rolling', h_clean, re.I):
            rolling_col = i
        # Match day number in header like "Mon\n14th" → 14
        m = re.search(r'\b(\d{1,2})(st|nd|rd|th)?\b', h_clean)
        if m and int(m.group(1)) == today.day:
            today_col = i

    # Fallback: use column just before Rolling 7
    if today_col is None and rolling_col is not None:
        today_col = rolling_col - 1

    log(f'Today col={today_col}, Rolling col={rolling_col}')

    metrics     = {}
    rolling_7   = {}
    metric_type = {}

    for row in rows[1:]:
        if not row or len(row) < 3:
            continue
        row_text = ' '.join(row)

        # Identify the metric group from row text
        matched = None
        for name in METRIC_ORDER:
            if name.lower() in row_text.lower():
                matched = name
                break
        if not matched:
            continue

        # Metric type is usually in the third non-empty cell
        mtype = ''
        for cell in row:
            if re.search(r'%\s*(Availability|Hours Lost|Time Spent|Failures)', cell, re.I):
                mtype = cell.strip()
                break
        metric_type[matched] = mtype

        # Today and Rolling 7 values
        today_val   = _parse_pct(row[today_col])   if today_col and today_col < len(row) else None
        rolling_val = _parse_pct(row[rolling_col]) if rolling_col and rolling_col < len(row) else None

        if matched not in metrics:          # first occurrence wins
            metrics[matched]   = today_val
            rolling_7[matched] = rolling_val

    if not metrics:
        return {'ok': False, 'error': 'Could not parse any metrics from BMI table.'}

    log(f'Parsed {len(metrics)} metrics.')
    return {
        'ok':         True,
        'date':       today.strftime('%Y-%m-%d'),
        'metrics':    metrics,
        'rolling_7':  rolling_7,
        'metric_type': metric_type,
    }
