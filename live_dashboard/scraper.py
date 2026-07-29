"""
Data scrapers: FCLM (associates + ETI/TPH) and Vantage (andons).
Reuses the existing .pt_dashboard/session Playwright profile so no re-login needed.
"""
import os, json, re
from datetime import datetime, timedelta
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ── Session dir — same as PT_Dashboard so auth carries over ──────────────────
def _session_dir():
    for env in ('LOCALAPPDATA','USERPROFILE','TEMP'):
        base = os.environ.get(env)
        if base and os.path.isdir(base):
            return os.path.join(base, '.pt_dashboard', 'session')
    return os.path.join(os.path.expanduser('~'), '.pt_dashboard', 'session')

SESSION_DIR = _session_dir()
CACHE_DIR   = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), '.live_dashboard')

FCLM_BASE  = 'https://fclm-portal.amazon.com/ppa/inspect/process'
PROCESS_ID = '100360'
WH         = 'CLE3'

# ── URL builders ──────────────────────────────────────────────────────────────
def _shift_params(shift):
    """Return (start_dt, end_dt, span_type) for the given shift."""
    now   = datetime.now()
    today = now.date()
    if shift == 'night':
        # 6 PM yesterday → 6 AM today
        end   = datetime.combine(today, datetime.min.time()).replace(hour=6)
        start = end - timedelta(hours=12)
    else:
        # 6 AM → 6 PM today
        start = datetime.combine(today, datetime.min.time()).replace(hour=6)
        end   = datetime.combine(today, datetime.min.time()).replace(hour=18)
    return start, end

def _fmt(dt): return f"{dt.year}/{str(dt.month).zfill(2)}/{str(dt.day).zfill(2)}"

def build_fclm_url(shift):
    s, e = _shift_params(shift)
    p = {
        'primaryAttribute':'BIN_TYPE','secondaryAttribute':'CONTAINER_TYPE',
        'nodeType':'FC','warehouseId':WH,'processId':PROCESS_ID,
        'spanType':'Intraday','maxIntradayDays':'1',
        'startDateDay':_fmt(s),'startDateWeek':_fmt(s),'startDateMonth':_fmt(s),
        'startDateIntraday':_fmt(s),
        'startHourIntraday':str(s.hour),'startMinuteIntraday':'0',
        'endDateIntraday':_fmt(e),
        'endHourIntraday':str(e.hour),'endMinuteIntraday':'0',
        'startHourIntraday1':'0','startMinuteIntraday1':'0',
        'startHourIntraday2':'0','startMinuteIntraday2':'0',
        'startHourIntraday3':'0','startMinuteIntraday3':'0',
        'startHourIntraday4':'0','startMinuteIntraday4':'0',
    }
    return f"{FCLM_BASE}?{urlencode(p)}"

def build_timecard_url(badge, shift):
    s, e = _shift_params(shift)
    p = {
        'primaryAttribute':'BIN_TYPE','secondaryAttribute':'CONTAINER_TYPE',
        'nodeType':'FC','warehouseId':WH,'processId':PROCESS_ID,
        'spanType':'Intraday','maxIntradayDays':'1',
        'startDateDay':_fmt(s),'startDateWeek':_fmt(s),'startDateMonth':_fmt(s),
        'startDateIntraday':_fmt(s),
        'startHourIntraday':str(s.hour),'startMinuteIntraday':'0',
        'endDateIntraday':_fmt(e),
        'endHourIntraday':str(e.hour),'endMinuteIntraday':'0',
        'startHourIntraday1':'0','startMinuteIntraday1':'0',
        'startHourIntraday2':'0','startMinuteIntraday2':'0',
        'startHourIntraday3':'0','startMinuteIntraday3':'0',
        'startHourIntraday4':'0','startMinuteIntraday4':'0',
        'employeeId': badge,
    }
    base = FCLM_BASE.replace('/process', '/employee')
    return f"{base}?{urlencode(p)}"

def build_rollup_url(shift):
    s, e = _shift_params(shift)
    p = {
        'reportFormat':'HTML','warehouseId':WH,
        'startDateDay':_fmt(s),'maxIntradayDays':'1','spanType':'Intraday',
        'startDateIntraday':_fmt(s),
        'startHourIntraday':str(s.hour),'startMinuteIntraday':'0',
        'endDateIntraday':_fmt(e),
        'endHourIntraday':str(e.hour),'endMinuteIntraday':'0',
        '_adjustPlanHours':'on','_hideEmptyLineItems':'on',
        'employmentType':'AllEmployees',
        'startHourIntraday1':'0','startMinuteIntraday1':'0',
        'startHourIntraday2':'0','startMinuteIntraday2':'0',
        'startHourIntraday3':'0','startMinuteIntraday3':'0',
        'startHourIntraday4':'0','startMinuteIntraday4':'0',
    }
    return f"https://fclm-portal.amazon.com/reports/processPathRollup?{urlencode(p)}"

# ── JS extractors ──────────────────────────────────────────────────────────────
_ASSOC_JS = """
() => {
    var TARGET = ['prime','unknown'];
    var employees = {};
    function binType(table) {
        var el = table.previousElementSibling;
        for (var i=0;i<15&&el;i++,el=el.previousElementSibling){
            var t=(el.textContent||'').toLowerCase();
            for(var b=0;b<TARGET.length;b++) if(t.indexOf(TARGET[b])>=0) return TARGET[b];
        }
        if(table.parentElement){
            var p=table.parentElement.previousElementSibling;
            for(var i=0;i<8&&p;i++,p=p.previousElementSibling){
                var t2=(p.textContent||'').toLowerCase();
                for(var b=0;b<TARGET.length;b++) if(t2.indexOf(TARGET[b])>=0) return TARGET[b];
            }
        }
        return null;
    }
    var tables=document.querySelectorAll('table');
    for(var t=0;t<tables.length;t++){
        var tbl=tables[t];
        if(!tbl.querySelector('td.employeeInspect')) continue;
        if(!binType(tbl)) continue;
        var rows=tbl.querySelectorAll('tbody tr');
        for(var r=0;r<rows.length;r++){
            var cells=rows[r].querySelectorAll('td');
            if(cells.length<15) continue;
            if(!cells[0].classList.contains('employeeInspect')) continue;
            var empId=(cells[0].textContent||'').trim();
            var name=(cells[1].textContent||'').trim();
            var mgr=(cells[2].textContent||'').trim();
            if(!name||!mgr) continue;
            var inf=parseFloat((cells[13].textContent||'0').replace(/,/g,''))||0;
            var tot=parseFloat((cells[14].textContent||'0').replace(/,/g,''))||0;
            var key=empId||name;
            if(!employees[key]) employees[key]={'id':empId,'name':name,'manager':mgr,'inferred':0,'total':0};
            employees[key]['inferred']+=inf;
            employees[key]['total']+=tot;
        }
    }
    return Object.values(employees).filter(function(e){return e['total']>0;});
}
"""

_TIMECARD_JS = """
() => {
    var segments = [];
    // Try to find timeline rows — FCLM employee page often has a table
    // with columns: start time, end time, activity, duration
    var tables = document.querySelectorAll('table');
    for (var t = 0; t < tables.length; t++) {
        var rows = tables[t].querySelectorAll('tr');
        var headerRow = null;
        var timeIdx=-1, endIdx=-1, actIdx=-1, durIdx=-1;
        for (var r = 0; r < rows.length; r++) {
            var cells = rows[r].querySelectorAll('th,td');
            if (r === 0 || rows[r].querySelectorAll('th').length > 0) {
                // Try to find header
                for (var c = 0; c < cells.length; c++) {
                    var h = (cells[c].textContent||'').toLowerCase();
                    if (h.includes('start') || h.includes('begin')) timeIdx = c;
                    if (h.includes('end')) endIdx = c;
                    if (h.includes('activ') || h.includes('type') || h.includes('state')) actIdx = c;
                    if (h.includes('dur') || h.includes('min') || h.includes('hrs')) durIdx = c;
                }
                continue;
            }
            if (timeIdx < 0) continue;
            var cellArr = Array.from(cells);
            var seg = {
                start: cellArr[timeIdx] ? (cellArr[timeIdx].textContent||'').trim() : '',
                end:   endIdx>=0 && cellArr[endIdx] ? (cellArr[endIdx].textContent||'').trim() : '',
                type:  actIdx>=0 && cellArr[actIdx] ? (cellArr[actIdx].textContent||'').trim() : '',
                dur:   durIdx>=0 && cellArr[durIdx] ? (cellArr[durIdx].textContent||'').trim() : '',
            };
            if (seg.start) segments.push(seg);
        }
    }
    // Also try to extract from color-coded bar elements
    document.querySelectorAll('[class*="idle"],[class*="inactive"],[class*="gap"]').forEach(function(el){
        var title = el.getAttribute('title') || el.getAttribute('data-tooltip') || '';
        if (title) segments.push({start:'', end:'', type:'idle', dur:title, from_element:true});
    });
    return segments;
}
"""

_ETI_JS = """
() => {
    var result = {eti: null, tph: null, rows: []};
    var tables = document.querySelectorAll('table');
    for (var t = 0; t < tables.length; t++) {
        var rows = Array.from(tables[t].querySelectorAll('tr'));
        rows.forEach(function(row) {
            var cells = Array.from(row.querySelectorAll('td,th')).map(function(c){
                return (c.textContent||'').trim();
            });
            var rowText = cells.join(' ').toLowerCase();
            if (rowText.includes('each transfer in') || rowText.includes('eti')) {
                // Find the numeric value
                cells.forEach(function(c){
                    var n = parseFloat(c.replace(/,/g,''));
                    if (!isNaN(n) && n > 0 && result.eti === null) result.eti = n;
                });
            }
            if (rowText.includes('ib total') || rowText.includes('inbound total') ||
                rowText.includes('tph') || rowText.includes('throughput')) {
                cells.forEach(function(c){
                    var n = parseFloat(c.replace(/,/g,''));
                    if (!isNaN(n) && n > 0 && result.tph === null) result.tph = n;
                });
            }
            // Collect all rows with numeric data
            var nums = cells.filter(function(c){ return !isNaN(parseFloat(c.replace(/,/g,''))); });
            if (cells.length >= 2 && nums.length >= 1) {
                result.rows.push(cells);
            }
        });
    }
    return result;
}
"""

_ANDON_JS = """
() => {
    var andons = [];
    // Try tables first
    var tables = document.querySelectorAll('table');
    for (var t = 0; t < tables.length; t++) {
        var rows = Array.from(tables[t].querySelectorAll('tr'));
        var headers = [];
        rows.forEach(function(row, idx) {
            var cells = Array.from(row.querySelectorAll('th,td')).map(function(c){
                return (c.textContent||'').trim();
            });
            if (idx === 0 || row.querySelectorAll('th').length > 0) {
                headers = cells.map(function(c){ return c.toLowerCase(); });
                return;
            }
            if (cells.length < 2) return;
            var obj = {};
            headers.forEach(function(h, i){ obj[h] = cells[i] || ''; });
            // Look for andon-relevant fields
            var entry = {
                associate: obj['associate'] || obj['employee'] || obj['login'] || obj['aa'] || cells[0],
                type:      obj['type'] || obj['reason'] || obj['category'] || cells[1] || '',
                created:   obj['created'] || obj['time'] || obj['start'] || '',
                resolved:  obj['resolved'] || obj['end'] || '',
                dwell:     obj['dwell'] || obj['duration'] || obj['time to resolve'] || '',
                station:   obj['station'] || obj['location'] || '',
            };
            if (entry.associate && entry.associate.length > 1) andons.push(entry);
        });
    }
    // Try card-based or list-based layouts
    if (andons.length === 0) {
        document.querySelectorAll('[class*="andon"],[class*="alert"],[data-type="andon"]').forEach(function(el){
            andons.push({
                associate: (el.querySelector('[class*="name"],[class*="employee"]') || {textContent:''}).textContent.trim(),
                type:      (el.querySelector('[class*="type"],[class*="reason"]') || {textContent:''}).textContent.trim(),
                dwell:     (el.querySelector('[class*="dwell"],[class*="time"],[class*="dur"]') || {textContent:''}).textContent.trim(),
                station:   (el.querySelector('[class*="station"],[class*="loc"]') || {textContent:''}).textContent.trim(),
                created:   '',resolved:'',
            });
        });
    }
    return andons;
}
"""

# ── Playwright context ────────────────────────────────────────────────────────
def _ctx(pw):
    os.makedirs(SESSION_DIR, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        SESSION_DIR, headless=False,
        args=['--window-position=-32000,-32000','--window-size=1,1',
              '--no-sandbox','--disable-dev-shm-usage'],
        viewport={'width':1280,'height':900},
        ignore_https_errors=True,
    )

def _auth_check(page):
    try:
        url = page.url
        return ('fclm-portal.amazon.com' in url and
                'midway' not in url and 'login' not in url.lower())
    except: return False

# ── Public scrape functions ───────────────────────────────────────────────────
def fetch_associates(shift, status_cb=None):
    """Scrape FCLM for all associates. Returns list of dicts."""
    cb  = status_cb or (lambda m: None)
    url = build_fclm_url(shift)
    cb(f'Fetching FCLM ({shift} shift)…')

    with sync_playwright() as pw:
        ctx = None
        try:
            ctx  = _ctx(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto('https://fclm-portal.amazon.com', timeout=20000, wait_until='domcontentloaded')

            if not _auth_check(page):
                cb('FCLM login required — please log in to the browser that opened.')
                try:
                    page.wait_for_url('https://fclm-portal.amazon.com/**', timeout=300000)
                    cb('Logged in.')
                except PWTimeout:
                    ctx.close()
                    return {'ok':False,'associates':[],'error':'Login timeout'}

            cb('Loading associate data…')
            try:
                page.goto(url, wait_until='networkidle', timeout=60000)
            except PWTimeout:
                pass
            try:
                page.wait_for_selector('td.employeeInspect', timeout=90000)
            except PWTimeout:
                ctx.close()
                return {'ok':False,'associates':[],'error':'No employee data found — shift may not have data yet.'}

            cb('Extracting rows…')
            rows = page.evaluate(_ASSOC_JS) or []
            ctx.close()
            cb(f'Found {len(rows)} associates.')
            return {'ok':True,'associates':rows,'shift':shift,'url':url}

        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            return {'ok':False,'associates':[],'error':str(e)}

def fetch_timecard_segments(badge, shift, status_cb=None):
    """Scrape individual associate timecard for idle segments."""
    cb  = status_cb or (lambda m: None)
    url = build_timecard_url(badge, shift)

    with sync_playwright() as pw:
        ctx = None
        try:
            ctx  = _ctx(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, wait_until='networkidle', timeout=45000)
            except PWTimeout:
                pass
            page.wait_for_timeout(3000)
            segments_raw = page.evaluate(_TIMECARD_JS) or []
            ctx.close()

            segments = []
            for seg in segments_raw:
                dur_min = _parse_duration(seg.get('dur',''))
                if dur_min is None: continue
                is_idle = any(k in (seg.get('type','') + seg.get('dur','')).lower()
                              for k in ['idle','indirect','inactive','off','gap','inferred'])
                if is_idle and dur_min > 0:
                    segments.append({
                        'start':        seg.get('start',''),
                        'end':          seg.get('end',''),
                        'duration_min': dur_min,
                        'type':         seg.get('type','idle'),
                    })
            return {'ok':True,'segments':segments}

        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            return {'ok':False,'segments':[],'error':str(e)}

def fetch_eti_tph(shift, status_cb=None):
    """Scrape process path rollup for ETI and TPH."""
    cb  = status_cb or (lambda m: None)
    url = build_rollup_url(shift)
    cb(f'Fetching ETI/TPH ({shift} shift)…')

    with sync_playwright() as pw:
        ctx = None
        try:
            ctx  = _ctx(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto('https://fclm-portal.amazon.com', timeout=20000, wait_until='domcontentloaded')

            if not _auth_check(page):
                ctx.close()
                return {'ok':False,'data':None,'error':'Not authenticated'}

            try:
                page.goto(url, wait_until='networkidle', timeout=60000)
            except PWTimeout:
                pass
            page.wait_for_timeout(5000)
            raw = page.evaluate(_ETI_JS)
            ctx.close()

            return {
                'ok':  True,
                'eti': raw.get('eti'),
                'tph': raw.get('tph'),
                'rows': raw.get('rows', []),
                'url': url,
            }
        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            return {'ok':False,'data':None,'error':str(e)}

def fetch_andons(login_filter=None, status_cb=None):
    """Scrape Vantage andon view."""
    cb  = status_cb or (lambda m: None)
    url = 'https://vantage.amazon.com/app/home/404?redirectFrom=%2Fstow-dashboard&view=andons'
    cb('Fetching Vantage andons…')

    with sync_playwright() as pw:
        ctx = None
        try:
            ctx  = _ctx(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            captured = []
            def on_resp(resp):
                try:
                    if 'json' in (resp.headers.get('content-type') or ''):
                        captured.append({'url':resp.url,'data':resp.json()})
                except: pass

            page.on('response', on_resp)
            try:
                page.goto(url, wait_until='networkidle', timeout=45000)
            except PWTimeout:
                pass
            page.wait_for_timeout(8000)

            os.makedirs(CACHE_DIR, exist_ok=True)
            page.screenshot(path=os.path.join(CACHE_DIR, 'vantage_andons.png'), full_page=False)

            andons = page.evaluate(_ANDON_JS) or []

            # Also check intercepted API responses
            for resp in captured:
                data = resp['data']
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and any(
                            k in item for k in ['andonId','dwell','associate','login','employeeId']):
                            andons.append({
                                'associate': item.get('associateName') or item.get('employeeName') or item.get('login',''),
                                'type':      item.get('andonType') or item.get('type',''),
                                'created':   str(item.get('createdAt') or item.get('startTime','')),
                                'resolved':  str(item.get('resolvedAt') or item.get('endTime','')),
                                'dwell':     str(item.get('dwellTime') or item.get('dwell','')),
                                'station':   item.get('station') or item.get('stationId',''),
                            })

            ctx.close()

            if login_filter:
                andons = [a for a in andons
                          if login_filter.lower() in (a.get('associate') or '').lower()]

            return {'ok':True,'andons':andons,'count':len(andons)}

        except Exception as e:
            if ctx:
                try: ctx.close()
                except: pass
            return {'ok':False,'andons':[],'error':str(e)}

# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_duration(text):
    """Parse a duration string into minutes. Returns None if unparseable."""
    if not text: return None
    text = text.strip()
    try:
        # Try plain float (hours)
        return round(float(text) * 60, 1)
    except ValueError:
        pass
    # HH:MM or H:MM
    m = re.match(r'(\d+):(\d{2})', text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    # Xh Ym or Xm
    hrs = re.search(r'(\d+)\s*h', text, re.I)
    mins= re.search(r'(\d+)\s*m', text, re.I)
    if hrs or mins:
        return (int(hrs.group(1)) * 60 if hrs else 0) + (int(mins.group(1)) if mins else 0)
    return None
