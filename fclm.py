"""
FCLM data fetcher — reads the live DOM directly from the process inspector page.
Mirrors the intent of the Tampermonkey PPA Productive Time v6 script.

Data source: employee-level tbody rows from PRIME and UNKNOWN BIN_TYPE tables only.
Cross-check: bottom-up sum of individual employee hours matches FCLM's own tfoot
totals on those same tables, confirming accuracy.

Always uses a visible browser; FCLM's JS won't render tables in headless mode.
"""
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = 'https://fclm-portal.amazon.com/ppa/inspect/process'

# Use a local data folder for the browser session.
# Prefer LOCALAPPDATA (always local on Windows), then USERPROFILE, then TEMP.
def _local_data_dir():
    for env in ('LOCALAPPDATA', 'USERPROFILE', 'TEMP', 'TMP'):
        base = os.environ.get(env)
        if base and os.path.isdir(base):
            return os.path.join(base, '.pt_dashboard', 'session')
    return os.path.join(os.path.expanduser('~'), '.pt_dashboard', 'session')

PROFILE_DIR = _local_data_dir()
try:
    os.makedirs(PROFILE_DIR, exist_ok=True)
except Exception:
    import tempfile
    PROFILE_DIR = os.path.join(tempfile.gettempdir(), '.pt_dashboard', 'session')
    os.makedirs(PROFILE_DIR, exist_ok=True)

def _load_config():
    """Load config.json — checks next to the .exe first (user-editable), then the bundle."""
    import json, sys
    defaults = {'warehouse_id': 'CLE3', 'process_id': '100360', 'pt_target': 84}
    # When frozen by PyInstaller, prefer config.json sitting next to the .exe so
    # users can edit it without touching the bundle. Fall back to the bundled copy.
    if getattr(sys, 'frozen', False):
        search = [
            os.path.join(os.path.dirname(sys.executable), 'config.json'),
            os.path.join(sys._MEIPASS, 'config.json'),
        ]
    else:
        search = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')]
    for cfg_path in search:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, encoding='utf-8') as f:
                    loaded = json.load(f)
                defaults.update({k: v for k, v in loaded.items() if not k.startswith('_')})
                break
            except Exception:
                pass
    return defaults

_CONFIG     = _load_config()
PROCESS_ID  = str(_CONFIG['process_id'])


SHIFTS = {
    'All Day':             {'spanType': 'Day',      'startHour': 0,  'endHour': 0},
    'Day Shift  (6a-6p)':  {'spanType': 'Intraday', 'startHour': 6,  'endHour': 18},
    'Night Shift (6p-6a)': {'spanType': 'Intraday', 'startHour': 18, 'endHour': 6},
}

# ── JavaScript extraction ───────────────────────────────────────────────────────
# Cell layout (17 cells per employee row, confirmed from live DOM):
#   [0]  Employee ID   [1] Name   [2] Manager
#   [3-12] Unit/rate metrics
#   [13] Inferred (indirect) hours
#   [14] Total hours
#
# Strategy: work table-by-table, only include tables whose nearest preceding
# BIN_TYPE heading contains "prime" or "unknown".  The same employee can appear
# in both sections; accumulate across them (same as Tampermonkey's intent).
# This approach is verified: our bottom-up sum matches FCLM's own tfoot totals.
_EXTRACT_JS = """
() => {
    var TARGET_BINS = ['prime', 'unknown'];
    var employees = {};

    function getBinType(table) {
        // Walk backwards through preceding siblings to find the BIN_TYPE heading
        var el = table.previousElementSibling;
        for (var i = 0; i < 15 && el; i++, el = el.previousElementSibling) {
            var txt = (el.textContent || '').toLowerCase();
            for (var b = 0; b < TARGET_BINS.length; b++) {
                if (txt.indexOf(TARGET_BINS[b]) >= 0) return TARGET_BINS[b];
            }
        }
        // Also check parent's preceding siblings
        if (table.parentElement) {
            var p = table.parentElement.previousElementSibling;
            for (var i = 0; i < 8 && p; i++, p = p.previousElementSibling) {
                var txt2 = (p.textContent || '').toLowerCase();
                for (var b = 0; b < TARGET_BINS.length; b++) {
                    if (txt2.indexOf(TARGET_BINS[b]) >= 0) return TARGET_BINS[b];
                }
            }
        }
        return null;
    }

    var tables = document.querySelectorAll('table');
    for (var t = 0; t < tables.length; t++) {
        var table = tables[t];

        // Only process tables that have employee rows
        if (!table.querySelector('td.employeeInspect')) continue;

        // Only include PRIME and UNKNOWN BIN_TYPE sections
        if (!getBinType(table)) continue;

        var rows = table.querySelectorAll('tbody tr');
        for (var r = 0; r < rows.length; r++) {
            var cells = rows[r].querySelectorAll('td');
            if (cells.length < 15) continue;
            if (!cells[0].classList.contains('employeeInspect')) continue;

            var empId   = (cells[0].textContent || '').trim();
            var name    = (cells[1].textContent || '').trim();
            var manager = (cells[2].textContent || '').trim();
            if (!name || !manager) continue;

            var inferred = parseFloat((cells[13].textContent || '0').replace(/,/g,'')) || 0;
            var total    = parseFloat((cells[14].textContent || '0').replace(/,/g,'')) || 0;

            var key = empId || name;
            if (!employees[key]) {
                employees[key] = {
                    'Employee Id':      empId,
                    'Employee Name':    name,
                    'Manager Name':     manager,
                    'Hours (Inferred)': 0,
                    'Hours (Total)':    0,
                    'BIN_TYPE':         'PRIME'
                };
            }
            employees[key]['Hours (Inferred)'] += inferred;
            employees[key]['Hours (Total)']    += total;
        }
    }

    return Object.values(employees).filter(function(e){ return e['Hours (Total)'] > 0; });
}
"""
# ───────────────────────────────────────────────────────────────────────────────


def build_fclm_url(date_str, shift_name, warehouse, employee_id=None):
    """Build the FCLM URL matching the Tampermonkey buildUrl() exactly.
    Pass employee_id to open the inspector pre-filtered to one associate."""
    d     = datetime.strptime(date_str, '%Y-%m-%d')
    sd    = f"{d.year}/{str(d.month).zfill(2)}/{str(d.day).zfill(2)}"
    shift = SHIFTS.get(shift_name, SHIFTS['Day Shift  (6a-6p)'])
    end_d = d + timedelta(days=1) if shift_name.startswith('Night') else d
    ed    = f"{end_d.year}/{str(end_d.month).zfill(2)}/{str(end_d.day).zfill(2)}"

    p = {
        'primaryAttribute':    'BIN_TYPE',
        'secondaryAttribute':  'CONTAINER_TYPE',
        'nodeType':            'FC',
        'warehouseId':         warehouse,
        'processId':           PROCESS_ID,
        'spanType':            shift['spanType'],
        'maxIntradayDays':     '1',
        'startDateDay':        sd,
        'startDateWeek':       sd,
        'startDateMonth':      sd,
        'startDateIntraday':   sd,
        'startHourIntraday':   str(shift['startHour']),
        'startMinuteIntraday': '0',
        'endDateIntraday':     ed,
        'endHourIntraday':     str(shift['endHour']),
        'endMinuteIntraday':   '0',
        'startHourIntraday1':  '0', 'startMinuteIntraday1': '0',
        'startHourIntraday2':  '0', 'startMinuteIntraday2': '0',
        'startHourIntraday3':  '0', 'startMinuteIntraday3': '0',
        'startHourIntraday4':  '0', 'startMinuteIntraday4': '0',
    }
    if employee_id:
        p['employeeId'] = employee_id
    return f"{BASE_URL}?{urlencode(p)}"


def build_employee_timecard_url(badge, date_str, shift_name, warehouse):
    """
    Build the FCLM URL for a single associate's productive time (time card) page.
    Uses /employee endpoint with the same shift parameters as the process inspector.
    """
    d     = datetime.strptime(date_str, '%Y-%m-%d')
    sd    = f"{d.year}/{str(d.month).zfill(2)}/{str(d.day).zfill(2)}"
    shift = SHIFTS.get(shift_name, SHIFTS['Day Shift  (6a-6p)'])
    end_d = d + timedelta(days=1) if shift_name.startswith('Night') else d
    ed    = f"{end_d.year}/{str(end_d.month).zfill(2)}/{str(end_d.day).zfill(2)}"

    p = {
        'primaryAttribute':    'BIN_TYPE',
        'secondaryAttribute':  'CONTAINER_TYPE',
        'nodeType':            'FC',
        'warehouseId':         warehouse,
        'processId':           PROCESS_ID,
        'spanType':            shift['spanType'],
        'maxIntradayDays':     '1',
        'startDateDay':        sd,
        'startDateWeek':       sd,
        'startDateMonth':      sd,
        'startDateIntraday':   sd,
        'startHourIntraday':   str(shift['startHour']),
        'startMinuteIntraday': '0',
        'endDateIntraday':     ed,
        'endHourIntraday':     str(shift['endHour']),
        'endMinuteIntraday':   '0',
        'startHourIntraday1':  '0', 'startMinuteIntraday1': '0',
        'startHourIntraday2':  '0', 'startMinuteIntraday2': '0',
        'startHourIntraday3':  '0', 'startMinuteIntraday3': '0',
        'startHourIntraday4':  '0', 'startMinuteIntraday4': '0',
        'employeeId':          badge,
    }
    # /employee endpoint opens the individual associate's productive time card
    employee_url = BASE_URL.replace('/process', '/employee')
    return f"{employee_url}?{urlencode(p)}"


def _is_authenticated(page):
    try:
        url = page.url
        return ('fclm-portal.amazon.com' in url and
                'midway' not in url and
                'login'  not in url.lower())
    except:
        return False


def _scrape_employees(page, url, log):
    """Navigate to FCLM URL, wait for table, extract employee rows from DOM."""
    log('Loading FCLM data page…')
    try:
        page.goto(url, wait_until='networkidle', timeout=60000)
    except PWTimeout:
        pass   # networkidle can time out on polling pages — table may still render

    log('Waiting for employee rows (up to 90 s)…')
    try:
        page.wait_for_selector('td.employeeInspect', timeout=90000)
    except PWTimeout:
        body      = page.inner_text('body').lower()
        row_count = page.evaluate("document.querySelectorAll('tbody tr').length")
        landed    = page.url
        shot      = os.path.join(os.path.expanduser('~'), '.pt_dashboard', 'debug.png')
        try: page.screenshot(path=shot, full_page=True)
        except: shot = 'n/a'

        if any(p in body for p in ('no data', 'no results', 'no records', '0 results')):
            return []

        raise PWTimeout(
            f'FCLM loaded but no employee rows appeared after 90 s.\n'
            f'  Landed on: {landed}\n'
            f'  tbody rows found: {row_count}\n'
            f'  Screenshot: {shot}'
        )

    log('Extracting employee data (PRIME + UNKNOWN bins)…')
    rows = page.evaluate(_EXTRACT_JS)
    return rows or []




def _has_saved_session():
    """Return True if a Chromium session profile with cookies already exists."""
    import os
    cookies_path = os.path.join(PROFILE_DIR, 'Default', 'Network', 'Cookies')
    return os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0

def fetch(date_str, shift_name, warehouse, status_cb=None):
    """
    Scrape FCLM DOM for PT data.
    Returns {'ok': bool, 'rows': list, 'error': str, 'url': str}
    """
    def log(msg):
        if status_cb: status_cb(msg)

    url = build_fclm_url(date_str, shift_name, warehouse)

    with sync_playwright() as pw:
        ctx = None
        try:
            # Off-screen args: browser runs visibly (headless=False required for FCLM JS)
            # but is positioned off-screen so the user never sees it.
            # On first run (no saved session) we skip off-screen so the login window appears.
            offscreen_args = ['--window-position=-32000,-32000', '--window-size=1,1']
            launch_args = ['--no-sandbox', '--disable-dev-shm-usage']
            if _has_saved_session():
                launch_args += offscreen_args

            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                headless=False,
                ignore_https_errors=True,
                args=launch_args,
                viewport={'width': 1280, 'height': 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            log('Checking FCLM session…')
            page.goto('https://fclm-portal.amazon.com',
                      timeout=20000, wait_until='domcontentloaded')

            if not _is_authenticated(page):
                log('Session expired or first run — please log in to FCLM in the browser window that opened (check your taskbar)…')
                try:
                    page.wait_for_url('https://fclm-portal.amazon.com/**', timeout=300000)
                    log('Login successful. Saving session…')
                except PWTimeout:
                    ctx.close()
                    return {'ok': False, 'rows': [], 'url': url,
                            'error': 'Login timed out (5 min). Please try again.'}

            rows = _scrape_employees(page, url, log)
            ctx.close()

            if rows:
                log(f'Loaded {len(rows)} associates.')
                return {'ok': True, 'rows': rows, 'url': url, 'error': ''}

            return {'ok': False, 'rows': [], 'url': url,
                    'error': f'No employee data for {date_str} — {shift_name}.\n'
                              'The shift may not have data yet.'}

        except (PWTimeout, Exception) as exc:
            if ctx:
                try: ctx.close()
                except: pass
            return {'ok': False, 'rows': [], 'url': url, 'error': str(exc)}
