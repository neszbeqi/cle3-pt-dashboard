"""
CLE3 PT Dashboard - FCLM scraper.
Pulls associate PT data from the process inspector page.
Also fetches individual timecards for whole-shift PT calculation.
"""
import os, re, asyncio
from datetime import datetime, timedelta
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL   = 'https://fclm-portal.amazon.com/ppa/inspect/process'
PROCESS_ID = '100360'
WAREHOUSE  = 'CLE3'

def _session_dir():
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('USERPROFILE') or os.path.expanduser('~')
    path = os.path.join(base, '.pt_dashboard', 'session')
    os.makedirs(path, exist_ok=True)
    return path

SESSION_DIR    = _session_dir()
API_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.fclm_api_cache.json')

# -- Firefox cookie bridge --------------------------------------------------------
def _find_firefox_db():
    """Locate Firefox cookies.sqlite across any profile."""
    import glob
    base = os.path.join(os.environ.get('APPDATA', ''), 'Mozilla', 'Firefox', 'Profiles')
    for db in glob.glob(os.path.join(base, '*.default*', 'cookies.sqlite')):
        if os.path.exists(db):
            return db
    return None

def _load_firefox_cookies():
    """
    Read FCLM/AEA cookies from Firefox's SQLite DB and return as a list of
    Playwright cookie dicts.  Pure I/O -- no Playwright interaction.
    """
    import sqlite3, shutil, time
    db = _find_firefox_db()
    if not db:
        return []
    tmp = db + '.ptcopy'
    try:
        shutil.copy2(db, tmp)
        conn = sqlite3.connect(tmp)
        now  = int(time.time())
        rows = conn.execute(
            "SELECT host, name, value, path, expiry, isSecure, isHttpOnly "
            "FROM moz_cookies "
            "WHERE (host LIKE '%fclm-portal%' OR host LIKE '%aea.aka%' "
            "       OR host = 'midway-auth.amazon.com') "
            "AND expiry > ?", (now,)
        ).fetchall()
        conn.close()
        cookies = []
        for host, name, value, path, expiry, secure, httponly in rows:
            cookies.append({
                'name': name, 'value': value,
                'domain': host, 'path': path or '/',
                'expires': expiry, 'secure': bool(secure),
                'httpOnly': bool(httponly), 'sameSite': 'None',
            })
        return cookies
    except Exception:
        return []
    finally:
        try: os.remove(tmp)
        except: pass

def _import_firefox_cookies(ctx):
    """Copy Firefox FCLM cookies into a sync Playwright context."""
    cookies = _load_firefox_cookies()
    if not cookies:
        return False
    ctx.add_cookies(cookies)
    return True


SHIFTS = {
    'night': {'spanType':'Intraday','startHour':18,'endHour':6,  'next_day':True},
    'day':   {'spanType':'Intraday','startHour':6, 'endHour':18, 'next_day':False},
}


# -- Direct API acceleration ------------------------------------------------------
def _save_api_cache(endpoint_url, cookies):
    import json as _json
    data = {'url': endpoint_url, 'cookies': cookies}
    with open(API_CACHE_FILE, 'w', encoding='utf-8') as f:
        _json.dump(data, f)

def _try_direct_api(date_str, shift):
    return None

def _extract_cookies_from_context(ctx):
    try:
        cookies = ctx.cookies()
        return {c['name']: c['value'] for c in cookies
                if 'fclm-portal' in c.get('domain','') or 'amazon.com' in c.get('domain','')}
    except:
        return {}

# -- Process Inspector JS ---------------------------------------------------------
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
            var linkEl = cells[0].querySelector('a');
            var login = '';
            if (linkEl && linkEl.href) { var lm = linkEl.href.match(/employeeId=([^&]+)/); if (lm) login = decodeURIComponent(lm[1]); }
            var name    = (cells[1].textContent||'').trim();
            var manager = (cells[2].textContent||'').trim();
            if (!name || !manager) continue;

            var inferred = parseFloat((cells[13].textContent||'0').replace(/,/g,''))||0;
            var total    = parseFloat((cells[14].textContent||'0').replace(/,/g,''))||0;

            var allCells = [];
            for (var c=0; c<cells.length; c++)
                allCells.push((cells[c].textContent||'').trim());

            var key = empId || name;
            if (!employees[key]) {
                employees[key] = {
                    badge: empId, name: name, manager: manager, login: login,
                    inferred: 0, total: 0,
                    cells: allCells, headers: headers
                };
            }
            employees[key].inferred += inferred;
            employees[key].total    += total;
        }
    }
    return Object.values(employees).filter(function(e){ return e.name && e.manager; });
}
"""

# -- Timecard extractor JS --------------------------------------------------------
_TIMECARD_JS = r"""
() => {
    var result = {
        rows: [], punches: [], pt_direct: null,
        preview: '', table_count: 0, url: window.location.href, title: document.title
    };

    // Check for a direct PT% summary on the page
    var bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
    var ptIdx = bodyText.indexOf('Productive Time');
    if (ptIdx >= 0) {
        var chunk = bodyText.substring(ptIdx, ptIdx + 40);
        var numMatch = chunk.match(/(\d+\.?\d*)\s*%/);
        if (numMatch) result.pt_direct = parseFloat(numMatch[1]);
    }

    // Extract all table rows
    var tables = document.querySelectorAll('table');
    result.table_count = tables.length;

    for (var t = 0; t < tables.length; t++) {
        var rows = tables[t].querySelectorAll('tr');
        for (var r = 0; r < rows.length; r++) {
            var cells = rows[r].querySelectorAll('td, th');
            if (cells.length === 0) continue;

            var rowObj = { t: t, r: r, cells: [] };
            for (var c = 0; c < cells.length; c++) {
                rowObj.cells.push({
                    text: (cells[c].textContent || '').trim(),
                    cls:  cells[c].className || ''
                });
            }

            // Capture clock punch rows (type = "clock in" / "clock out")
            if (cells.length >= 2) {
                var c0txt = (cells[0].textContent || '').trim().toLowerCase();
                var c1txt = (cells[1].textContent || '').trim();
                if ((c0txt.indexOf('in') >= 0 || c0txt.indexOf('out') >= 0) &&
                     c1txt.match(/\d{2}\/\d{2}-\d{2}:\d{2}/)) {
                    result.punches.push({ type: c0txt, time: c1txt });
                }
            }

            result.rows.push(rowObj);
        }
    }

    result.preview = bodyText.substring(0, 4000);
    return result;
}
"""



# -- Form/navigation element inspector -----------------------------------------------
_FORM_INSPECT_JS = r"""
() => {
    var result = { links: [], inputs: [], selects: [], buttons: [], date_display: '' };

    // All links
    var links = document.querySelectorAll('a');
    for (var i = 0; i < links.length; i++) {
        var el = links[i];
        var txt = (el.textContent || '').trim().substring(0, 80);
        if (txt || el.title || el.href) {
            result.links.push({
                text: txt, href: el.href || '', title: el.title || '',
                cls: el.className || '', id: el.id || ''
            });
        }
    }

    // All inputs
    var inputs = document.querySelectorAll('input');
    for (var i = 0; i < inputs.length; i++) {
        var el = inputs[i];
        result.inputs.push({
            name: el.name || '', type: el.type || '', value: el.value || '',
            id: el.id || '', cls: el.className || ''
        });
    }

    // All selects
    var selects = document.querySelectorAll('select');
    for (var i = 0; i < selects.length; i++) {
        var el = selects[i];
        var opts = [];
        for (var o = 0; o < Math.min(el.options.length, 30); o++)
            opts.push(el.options[o].value);
        result.selects.push({
            name: el.name || '', id: el.id || '', value: el.value || '',
            cls: el.className || '', options: opts
        });
    }

    // All buttons
    var btns = document.querySelectorAll('button, input[type=submit]');
    for (var i = 0; i < btns.length; i++) {
        var el = btns[i];
        result.buttons.push({
            text: (el.textContent || el.value || '').trim().substring(0, 60),
            type: el.type || '', name: el.name || '', id: el.id || '', cls: el.className || ''
        });
    }

    // Date display text (look for the "Day 2026/..." pattern)
    var body = (document.body && document.body.innerText) ? document.body.innerText : '';
    var dm = body.match(/Day\s+\d{4}\/\d{2}\/\d{2}/);
    if (dm) result.date_display = dm[0];

    return result;
}
"""


def _detect_station(cells, headers):
    for kw in ('station', 'workstation'):
        for i, h in enumerate(headers):
            if kw in h.lower() and i < len(cells):
                val = cells[i].strip()
                if val and val not in ('', '-', 'N/A', '--'):
                    return val
    digit4 = re.compile(r'^[1-4][0-9]{3}$')
    digit3 = re.compile(r'^[1-4][0-9]{2,}$')
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
    if not station:
        return 0
    m = re.match(r'^([1-4])', station.strip())
    return int(m.group(1)) if m else 0

def _detect_flex(cells):
    for val in cells:
        if val.strip().upper() == 'FLEX':
            return True
    return False

def _has_session():
    cookies = os.path.join(SESSION_DIR, 'Default', 'Network', 'Cookies')
    return os.path.exists(cookies) and os.path.getsize(cookies) > 0

def _clear_locks():
    import subprocess as _sub, glob as _glob, time as _time
    _sub.run(['taskkill', '/IM', 'chrome.exe',   '/F'], capture_output=True)
    _sub.run(['taskkill', '/IM', 'chromium.exe', '/F'], capture_output=True)
    _time.sleep(1)
    for lock in _glob.glob(os.path.join(SESSION_DIR, '**', 'LOCK'), recursive=True):
        try: os.remove(lock)
        except OSError: pass


def build_url(date_str, shift, employee_id=None):
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

def build_timecard_url(login, shift='night', date_str=None):
    """
    Build FCLM Employee Time Details URL with the correct intraday date range
    for the given shift.  Without proper range parameters the page defaults to
    today's calendar-day view which misses the 18:00–00:00 portion of a night
    shift that started yesterday.
    """
    from datetime import datetime as _dt, timedelta as _td

    if date_str is None:
        now = _dt.now()
        if shift == 'night' and now.hour < 6:
            date_str = (now - _td(days=1)).strftime('%Y-%m-%d')
        else:
            date_str = now.strftime('%Y-%m-%d')

    d = _dt.strptime(date_str, '%Y-%m-%d')
    if shift == 'night':
        start_d, start_h = d,              18
        end_d,   end_h   = d + _td(days=1), 6
    else:  # day
        start_d, start_h = d,  6
        end_d,   end_h   = d, 18

    sd = f"{start_d.year}/{start_d.month:02d}/{start_d.day:02d}"
    ed = f"{end_d.year}/{end_d.month:02d}/{end_d.day:02d}"

    from urllib.parse import urlencode as _ue
    p = {
        'warehouseId':         WAREHOUSE,
        'employeeId':          login,
        'spanType':            'Intraday',
        'startDateIntraday':   sd,
        'startHourIntraday':   str(start_h),
        'startMinuteIntraday': '0',
        'endDateIntraday':     ed,
        'endHourIntraday':     str(end_h),
        'endMinuteIntraday':   '0',
    }
    return f"https://fclm-portal.amazon.com/employee/timeDetails?{_ue(p)}"


# -- Process Inspector fetch ------------------------------------------------------
def fetch(date_str, shift, status_cb=None):
    """
    Scrape FCLM process inspector for current shift data (stow-only).
    Returns {'ok': bool, 'associates': list, 'error': str}
    """
    def log(m):
        if status_cb: status_cb(m)

    url = build_url(date_str, shift)

    with sync_playwright() as pw:
        browser = None
        ctx     = None
        try:
            args = [
                '--no-sandbox', '--disable-dev-shm-usage',
                '--window-position=-32000,-32000',
                '--window-size=1280,900',
                '--disable-session-crashed-bubble',
                '--disable-infobars',
            ]
            browser = pw.chromium.launch(headless=False, args=args)
            ctx  = browser.new_context(
                ignore_https_errors=True,
                viewport={'width': 1280, 'height': 900},
            )
            page = ctx.new_page()

            log('Importing session cookies...')
            _import_firefox_cookies(ctx)

            _captured = []
            def _on_response(resp):
                try:
                    ct = resp.headers.get('content-type', '')
                    if 'fclm-portal.amazon.com' in resp.url and 'json' in ct:
                        body = resp.json()
                        if isinstance(body, list) and len(body) > 5:
                            if any(isinstance(x, dict) and ('employeeId' in x or 'badge' in x or 'login' in x or 'name' in x) for x in body[:3]):
                                _captured.append({'url': resp.url, 'data': body})
                except: pass
            page.on('response', _on_response)

            log('Loading FCLM data...')
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
            except PWTimeout:
                pass

            if 'fclm-portal.amazon.com' not in page.url or 'midway' in page.url or 'login' in page.url.lower():
                ctx.close(); browser.close()
                return {'ok': False, 'need_login': True, 'associates': [],
                        'error': 'FCLM session expired -- open FCLM in Firefox to refresh login.'}
            log('Authenticated -- waiting for rows...')

            try:
                page.wait_for_selector('td.employeeInspect', timeout=90000)
            except PWTimeout:
                body = page.inner_text('body').lower()
                ctx.close(); browser.close()
                if any(x in body for x in ('no data', 'no results', '0 results')):
                    return {'ok': False, 'associates': [], 'error': 'No data for this shift yet.'}
                return {'ok': False, 'associates': [], 'error': 'FCLM rows did not appear (90s timeout).'}

            log('Extracting...')
            raw = page.evaluate(_EXTRACT_JS) or []

            try:
                cookies = _extract_cookies_from_context(ctx)
                _save_api_cache(url, cookies)
            except: pass

            ctx.close()
            browser.close()

            associates = []
            for r in raw:
                station  = _detect_station(r.get('cells', []), r.get('headers', []))
                floor    = _get_floor(station)
                total    = r.get('total', 0)
                inferred = r.get('inferred', 0)
                pt       = round(100 - (inferred / total * 100), 1) if total > 0 else None
                associates.append({
                    'badge':    r['badge'],
                    'name':     r['name'],
                    'manager':  r['manager'],
                    'login':    r.get('login', ''),
                    'station':  station,
                    'floor':    floor,
                    'inferred': inferred,
                    'total':    total,
                    'pt_pct':   pt,
                    'is_flex':  _detect_flex(r.get('cells', [])),
                })

            log(f'Loaded {len(associates)} associates.')
            return {'ok': True, 'associates': associates, 'error': ''}

        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            if browser:
                try: browser.close()
                except: pass
            return {'ok': False, 'associates': [], 'error': str(e)}


# -- Single timecard fetch (debug / one-shot) ------------------------------------
def fetch_timecard(badge, shift='night', date_str=None):
    """
    Fetch raw timecard data for one associate.
    Returns {'ok': bool, 'rows': list, 'pt_direct': float|None,
             'preview': str, 'api_data': list, 'error': str}
    """
    url = build_timecard_url(badge, shift=shift, date_str=date_str)
    with sync_playwright() as pw:
        browser = None
        ctx     = None
        try:
            args = [
                '--no-sandbox', '--disable-dev-shm-usage',
                '--window-position=-32000,-32000',
                '--window-size=1280,900',
            ]
            browser = pw.chromium.launch(headless=False, args=args)
            ctx = browser.new_context(
                ignore_https_errors=True,
                viewport={'width': 1280, 'height': 900},
            )
            page = ctx.new_page()
            _import_firefox_cookies(ctx)

            _api_data = []
            def _on_resp(resp):
                try:
                    ct   = resp.headers.get('content-type', '')
                    rurl = resp.url
                    if 'fclm-portal.amazon.com' in rurl and ('json' in ct or 'employee' in rurl or 'time' in rurl.lower()):
                        try:    body = resp.json()
                        except: body = None
                        _api_data.append({'url': rurl, 'ct': ct, 'data': body})
                except: pass
            page.on('response', _on_resp)

            try:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
            except PWTimeout:
                pass

            if 'midway' in page.url or 'login' in page.url.lower():
                ctx.close(); browser.close()
                return {'ok': False, 'need_login': True, 'rows': [], 'error': 'Session expired'}

            try:
                page.wait_for_selector('table', timeout=30000)
            except PWTimeout:
                pass
            page.wait_for_timeout(2000)

            raw = page.evaluate(_TIMECARD_JS) or {}
            ctx.close()
            browser.close()

            return {
                'ok':          True,
                'rows':        raw.get('rows', []),
                'pt_direct':   raw.get('pt_direct'),
                'preview':     raw.get('preview', ''),
                'table_count': raw.get('table_count', 0),
                'title':       raw.get('title', ''),
                'url':         raw.get('url', url),
                'api_data':    _api_data,
                'error':       '',
            }
        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            if browser:
                try: browser.close()
                except: pass
            return {'ok': False, 'rows': [], 'error': str(e)}


# -- Async batch timecard fetch (production) --------------------------------------
async def _fetch_timecards_async(badges, shift='night', date_str=None, max_concurrent=8):
    """
    Open one browser, fetch timecards for many badges concurrently.
    Returns {badge: {'rows': list, 'pt_direct': float|None}} or {badge: None}.
    """
    from playwright.async_api import async_playwright, TimeoutError as APWTimeout

    cookies = _load_firefox_cookies()
    results = {}

    async with async_playwright() as pw:
        args = [
            '--no-sandbox', '--disable-dev-shm-usage',
            '--window-position=-32000,-32000',
            '--window-size=1280,900',
        ]
        browser = await pw.chromium.launch(headless=False, args=args)
        ctx = await browser.new_context(
            ignore_https_errors=True,
            viewport={'width': 1280, 'height': 900},
        )
        if cookies:
            await ctx.add_cookies(cookies)

        sem = asyncio.Semaphore(max_concurrent)

        async def fetch_one(badge):
            async with sem:
                page = await ctx.new_page()
                try:
                    url = build_timecard_url(badge, shift=shift, date_str=date_str)
                    try:
                        await page.goto(url, wait_until='domcontentloaded', timeout=45000)
                    except APWTimeout:
                        pass

                    # Auth check
                    current = page.url
                    if 'midway' in current or 'login' in current.lower():
                        return badge, None

                    try:
                        await page.wait_for_selector('table', timeout=20000)
                    except APWTimeout:
                        pass
                    await page.wait_for_timeout(1500)

                    raw = await page.evaluate(_TIMECARD_JS) or {}
                    return badge, {
                        'rows':      raw.get('rows', []),
                        'pt_direct': raw.get('pt_direct'),
                        'preview':   raw.get('preview', '')[:500],
                    }
                except Exception as exc:
                    return badge, {'error': str(exc), 'rows': []}
                finally:
                    try: await page.close()
                    except: pass

        # Run all tasks concurrently (semaphore limits to max_concurrent at once)
        tasks = [fetch_one(b) for b in badges]
        for coro in asyncio.as_completed(tasks):
            badge, data = await coro
            results[badge] = data

        try: await ctx.close()
        except: pass
        try: await browser.close()
        except: pass

    return results


def fetch_timecards_batch(badges, shift='night', date_str=None):
    """
    Sync wrapper: fetch timecards for all badges concurrently.
    Returns {badge: {'rows': list, 'pt_direct': float|None}} or {badge: None}.
    """
    if not badges:
        return {}
    return asyncio.run(_fetch_timecards_async(badges, shift=shift, date_str=date_str))


# -- Login helper ----------------------------------------------------------------
def login_and_wait(status_cb=None):
    """Open FCLM in a visible browser and wait for user to log in."""
    def log(m):
        if status_cb: status_cb(m)

    _clear_locks()
    with sync_playwright() as pw:
        ctx = None
        try:
            args = [
                '--no-sandbox', '--disable-dev-shm-usage',
                '--window-position=-32000,-32000',
                '--window-size=1280,900',
            ]
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=SESSION_DIR, headless=False,
                ignore_https_errors=True, args=args,
                viewport={'width': 1280, 'height': 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(
                f'https://fclm-portal.amazon.com/employee/timeDetails?warehouseId={WAREHOUSE}',
                timeout=20000, wait_until='domcontentloaded'
            )

            if 'fclm-portal.amazon.com' in page.url and 'midway' not in page.url and 'login' not in page.url.lower():
                ctx.close()
                return {'ok': True, 'msg': 'Already logged in'}

            log('Waiting for login...')
            try:
                page.wait_for_url('**/fclm-portal.amazon.com/**', timeout=180000)
                page.wait_for_timeout(2000)
                ctx.close()
                return {'ok': True, 'msg': 'Login successful'}
            except PWTimeout:
                ctx.close()
                return {'ok': False, 'error': 'Login timed out (3 min)'}

        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            return {'ok': False, 'error': str(e)}
