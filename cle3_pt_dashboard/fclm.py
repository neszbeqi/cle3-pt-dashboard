"""
CLE3 PT Dashboard - FCLM scraper.
Pulls associate PT data from the process inspector page.
Captures all cell values so station/workstation can be auto-detected.
"""
import os, re
from datetime import datetime, timedelta
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL   = 'https://fclm-portal.amazon.com/ppa/inspect/process'
PROCESS_ID = '100360'
WAREHOUSE  = 'CLE3'

def _session_dir():
    # Reuse the existing .pt_dashboard session — it already has AEA auth cookies.
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('USERPROFILE') or os.path.expanduser('~')
    path = os.path.join(base, '.pt_dashboard', 'session')
    os.makedirs(path, exist_ok=True)
    return path

SESSION_DIR = _session_dir()

SHIFTS = {
    'night': {'spanType':'Intraday','startHour':18,'endHour':6,  'next_day':True},
    'day':   {'spanType':'Intraday','startHour':6, 'endHour':18, 'next_day':False},
}

# -- JS extractor - returns ALL cell values so Python can detect station --------
_EXTRACT_JS = """
() => {
    var TARGET_BINS = ['prime','unknown'];
    var employees = {};

    function getBinType(table) {
        var el = table.previousElementSibling;
        for (var i=0; i<15 && el; i++, el=el.previousElementSibling) {
            var txt = (el.textContent||'').toLowerCase();
            if (txt.indexOf('prime')>=0)   return 'prime';
            if (txt.indexOf('unknown')>=0) return 'unknown';
        }
        if (table.parentElement) {
            var p = table.parentElement.previousElementSibling;
            for (var i=0; i<8 && p; i++, p=p.previousElementSibling) {
                var txt2 = (p.textContent||'').toLowerCase();
                if (txt2.indexOf('prime')>=0)   return 'prime';
                if (txt2.indexOf('unknown')>=0) return 'unknown';
            }
        }
        return null;
    }

    function getHeaders(table) {
        var headers = [];
        var hrow = table.querySelector('thead tr');
        if (hrow) {
            var ths = hrow.querySelectorAll('th,td');
            for (var i=0; i<ths.length; i++)
                headers.push((ths[i].textContent||'').trim().toLowerCase());
        }
        return headers;
    }

    var tables = document.querySelectorAll('table');
    for (var t=0; t<tables.length; t++) {
        var table = tables[t];
        if (!table.querySelector('td.employeeInspect')) continue;
        if (!getBinType(table)) continue;

        var headers = getHeaders(table);
        var rows = table.querySelectorAll('tbody tr');
        for (var r=0; r<rows.length; r++) {
            var cells = rows[r].querySelectorAll('td');
            if (cells.length < 15) continue;
            if (!cells[0].classList.contains('employeeInspect')) continue;

            var empId   = (cells[0].textContent||'').trim();
            var name    = (cells[1].textContent||'').trim();
            var manager = (cells[2].textContent||'').trim();
            if (!name || !manager) continue;

            var inferred = parseFloat((cells[13].textContent||'0').replace(/,/g,''))||0;
            var total    = parseFloat((cells[14].textContent||'0').replace(/,/g,''))||0;

            // Capture all cell values for station detection
            var allCells = [];
            for (var c=0; c<cells.length; c++)
                allCells.push((cells[c].textContent||'').trim());

            var key = empId || name;
            if (!employees[key]) {
                employees[key] = {
                    badge: empId, name: name, manager: manager,
                    inferred: 0, total: 0,
                    cells: allCells, headers: headers
                };
            }
            employees[key].inferred += inferred;
            employees[key].total    += total;
            // Keep cells from first row (station most likely unchanged)
        }
    }
    return Object.values(employees).filter(function(e){ return e.total > 0; });
}
"""

def _detect_station(cells, headers):
    """
    CLE3 station format: 4-digit number, first digit = floor (1-4).
    Example: 3212 = Floor 3.
    """
    for kw in ('station', 'workstation'):
        for i, h in enumerate(headers):
            if kw in h.lower() and i < len(cells):
                val = cells[i].strip()
                if val and val not in ('', '-', 'N/A', '--'):
                    return val
    # Look for 4-digit value starting with 1-4
    digit4 = re.compile(r'^[1-4][0-9]{3}$')
    digit3 = re.compile(r'^[1-4][0-9]{2,}')
    for i in range(3, min(len(cells), 16)):
        val = cells[i].strip()
        if digit4.match(val):
            return val
    for i in range(3, min(len(cells), 16)):
        val = cells[i].strip()
        if digit3.match(val):
            return val
    return ''

def _get_floor(station):
    """Extract floor number (1-4) from station string. 0 = unknown."""
    if not station:
        return 0
    m = re.match(r'^([1-4])', station.strip())
    return int(m.group(1)) if m else 0

def _has_session():
    cookies = os.path.join(SESSION_DIR, 'Default', 'Network', 'Cookies')
    return os.path.exists(cookies) and os.path.getsize(cookies) > 0

def build_url(date_str, shift, employee_id=None):
    """Build FCLM process inspector URL."""
    d  = datetime.strptime(date_str, '%Y-%m-%d')
    sd = f"{d.year}/{d.month:02d}/{d.day:02d}"
    sh = SHIFTS.get(shift, SHIFTS['night'])
    ed_obj = d + timedelta(days=1) if sh['next_day'] else d
    ed = f"{ed_obj.year}/{ed_obj.month:02d}/{ed_obj.day:02d}"
    p  = {
        'primaryAttribute':'BIN_TYPE','secondaryAttribute':'CONTAINER_TYPE',
        'nodeType':'FC','warehouseId':WAREHOUSE,'processId':PROCESS_ID,
        'spanType':sh['spanType'],'maxIntradayDays':'1',
        'startDateDay':sd,'startDateWeek':sd,'startDateMonth':sd,'startDateIntraday':sd,
        'startHourIntraday':str(sh['startHour']),'startMinuteIntraday':'0',
        'endDateIntraday':ed,'endHourIntraday':str(sh['endHour']),'endMinuteIntraday':'0',
        'startHourIntraday1':'0','startMinuteIntraday1':'0',
        'startHourIntraday2':'0','startMinuteIntraday2':'0',
        'startHourIntraday3':'0','startMinuteIntraday3':'0',
        'startHourIntraday4':'0','startMinuteIntraday4':'0',
    }
    if employee_id:
        p['employeeId'] = employee_id
    return f"{BASE_URL}?{urlencode(p)}"

def build_timecard_url(login):
    """
    Build FCLM Employee Time Details URL.
    Confirmed format: /employee/timeDetails?warehouseId=CLE3&employeeId={login}
    """
    return f"https://fclm-portal.amazon.com/employee/timeDetails?warehouseId={WAREHOUSE}&employeeId={login}"

def fetch(date_str, shift, status_cb=None):
    """
    Scrape FCLM for current shift data.
    Returns {'ok': bool, 'associates': list, 'error': str}
    Each associate: {badge, name, manager, station, floor, inferred, total, pt_pct}
    """
    def log(m):
        if status_cb: status_cb(m)

    url = build_url(date_str, shift)

    with sync_playwright() as pw:
        ctx = None
        try:
            args = ['--no-sandbox','--disable-dev-shm-usage']
            if _has_session():
                args += ['--window-position=-32000,-32000','--window-size=1,1']

            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=SESSION_DIR, headless=False,
                ignore_https_errors=True, args=args,
                viewport={'width':1280,'height':900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            log('Checking session...')
            page.goto('https://fclm-portal.amazon.com', timeout=20000, wait_until='domcontentloaded')

            if 'fclm-portal.amazon.com' not in page.url or 'midway' in page.url or 'login' in page.url.lower():
                log('Please log in to FCLM in the browser window (check taskbar)...')
                try:
                    page.wait_for_url('https://fclm-portal.amazon.com/**', timeout=300000)
                    log('Login OK.')
                except PWTimeout:
                    ctx.close()
                    return {'ok':False,'associates':[],'error':'Login timed out.'}

            log('Loading data...')
            try:
                page.goto(url, wait_until='networkidle', timeout=60000)
            except PWTimeout:
                pass

            log('Waiting for employee rows...')
            try:
                page.wait_for_selector('td.employeeInspect', timeout=90000)
            except PWTimeout:
                body = page.inner_text('body').lower()
                if any(x in body for x in ('no data','no results','0 results')):
                    ctx.close()
                    return {'ok':False,'associates':[],'error':'No data for this shift yet.'}
                ctx.close()
                return {'ok':False,'associates':[],'error':'FCLM rows did not appear (90s timeout).'}

            log('Extracting...')
            raw = page.evaluate(_EXTRACT_JS) or []
            ctx.close()

            associates = []
            for r in raw:
                station = _detect_station(r.get('cells',[]), r.get('headers',[]))
                floor   = _get_floor(station)
                total   = r.get('total', 0)
                inferred= r.get('inferred', 0)
                pt      = round(100 - (inferred/total*100), 1) if total > 0 else None
                associates.append({
                    'badge':    r['badge'],
                    'name':     r['name'],
                    'manager':  r['manager'],
                    'station':  station,
                    'floor':    floor,
                    'inferred': inferred,
                    'total':    total,
                    'pt_pct':   pt,
                })

            log(f'Loaded {len(associates)} associates.')
            return {'ok':True,'associates':associates,'error':''}

        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            return {'ok':False,'associates':[],'error':str(e)}


