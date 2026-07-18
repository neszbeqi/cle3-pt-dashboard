"""
vantage.py — Vantage Station Map scraper for CLE3 PT Dashboard
Fetches per-associate stow metrics: rate, cycle time, units per face
"""

import os, json, re
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SESSION_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    '.pt_dashboard', 'session'
)
CACHE_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    '.pt_dashboard'
)
BASE_URL = 'https://vantage.amazon.com/app/fulfillment-dashboards/station-map'

# Performance targets
TARGETS = {
    'rate':       {'min': 150, 'higher_better': True},
    'cycle_time': {'max': 12,  'higher_better': False},
    'upf':        {'min': 6,   'higher_better': True},
}

def _url(warehouse, zones, time_str, region='us-east-1'):
    params = f'customer=AMZN&warehouse={warehouse}&region={region}'
    if zones:
        params += f'&zones={",".join(zones)}'
    if time_str:
        params += f'&startTime={time_str}'
    return f'{BASE_URL}?{params}'

def _ctx(playwright):
    os.makedirs(SESSION_DIR, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        SESSION_DIR, headless=False,
        args=['--start-maximized'], no_viewport=True
    )

def _dismiss_picker(page, warehouse, cb):
    """
    If Vantage shows a building/warehouse picker, auto-click the right warehouse.
    Returns True if picker was found and handled.
    """
    try:
        # Give picker a moment to appear
        page.wait_for_timeout(2000)
        current_url = page.url
        cb(f'Current URL: {current_url}')

        # Check if we're on a picker/selector page (URL changed away from station-map)
        if 'station-map' not in current_url:
            cb('Picker detected — looking for warehouse option...')
            # Try to find and click warehouse by text
            found = page.evaluate(f"""() => {{
                const wh = '{warehouse}';
                // Try buttons, links, list items, cards containing the warehouse code
                const candidates = [
                    ...document.querySelectorAll('button, a, li, [role="option"], [role="button"], td, .card, [class*="item"]')
                ];
                for (const el of candidates) {{
                    if (el.textContent?.includes(wh)) {{
                        el.click();
                        return true;
                    }}
                }}
                // Try input/select
                const sel = document.querySelector('select');
                if (sel) {{
                    for (const opt of sel.options) {{
                        if (opt.text.includes(wh) || opt.value.includes(wh)) {{
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            return true;
                        }}
                    }}
                }}
                return false;
            }}""")
            if found:
                cb(f'Clicked {warehouse} in picker — waiting for page...')
                page.wait_for_load_state('networkidle', timeout=30000)
                page.wait_for_timeout(3000)
                return True
            else:
                cb(f'WARNING: Could not auto-click {warehouse} in picker. Please click it manually.')
                # Wait up to 30s for user to click manually
                try:
                    page.wait_for_url(f'**/station-map**', timeout=30000)
                    cb('User selected building — continuing...')
                    page.wait_for_timeout(2000)
                    return True
                except Exception:
                    cb('Timed out waiting for building selection')
                    return False
        return False  # No picker, already on correct page
    except Exception as e:
        cb(f'Picker check error: {e}')
        return False


def discover_zones(warehouse='CLE3', status_cb=None):
    """
    Auto-discover available zones for a warehouse from the Vantage page.
    Returns {'ok': True, 'zones': [{'id': ..., 'label': ...}, ...]}
    Caches result to ~/.pt_dashboard/vantage_zones.json
    """
    cb = status_cb or print
    cache_path = os.path.join(CACHE_DIR, 'vantage_zones.json')

    cb('Discovering Vantage zones...')
    captured = []

    def on_response(resp):
        try:
            if 'json' in resp.headers.get('content-type', ''):
                captured.append({'url': resp.url, 'data': resp.json()})
        except Exception:
            pass

    with sync_playwright() as p:
        ctx = _ctx(p)
        page = ctx.new_page()
        page.on('response', on_response)
        try:
            url = f'{BASE_URL}?customer=AMZN&warehouse={warehouse}&region=us-east-1'
            cb(f'Loading {url}')
            page.goto(url, wait_until='networkidle', timeout=90000)
            _dismiss_picker(page, warehouse, cb)
            page.wait_for_timeout(2000)

            # Try to find zone filter chips / checkboxes / select options in the DOM
            zones_raw = page.evaluate('''() => {
                const seen = new Set();
                const results = [];
                const add = (id, label) => {
                    const key = id || label;
                    if (key && !seen.has(key)) { seen.add(key); results.push({id, label}); }
                };
                // Zone chips / buttons
                document.querySelectorAll('[class*="zone"],[data-zone],[data-testid*="zone"]').forEach(el => {
                    add(el.dataset?.zone || el.getAttribute('data-value') || el.id, el.textContent?.trim());
                });
                // Checkboxes with zone-like values
                document.querySelectorAll('input[type="checkbox"]').forEach(el => {
                    const lbl = el.closest('label')?.textContent?.trim() || el.value;
                    if (/[A-Za-z]{2,}[0-9]+/.test(lbl) || /[A-Za-z]{2,}[0-9]+/.test(el.value))
                        add(el.value, lbl);
                });
                // Select options
                document.querySelectorAll('select option').forEach(el => {
                    add(el.value, el.textContent?.trim());
                });
                // Role=option (dropdown)
                document.querySelectorAll('[role="option"],[role="menuitemcheckbox"]').forEach(el => {
                    add(el.getAttribute('data-value') || el.getAttribute('value') || el.id,
                        el.textContent?.trim());
                });
                return results;
            }''')
            cb(f'DOM zone candidates: {len(zones_raw)}')

            # Also try API responses
            api_zones = []
            for r in captured:
                d = r['data']
                if isinstance(d, list):
                    for item in d:
                        if isinstance(item, dict):
                            zid = item.get('zoneId') or item.get('zone') or item.get('id')
                            zlbl = item.get('zoneName') or item.get('label') or item.get('name') or zid
                            if zid:
                                api_zones.append({'id': str(zid), 'label': str(zlbl)})
                elif isinstance(d, dict):
                    for key in ('zones', 'areas', 'floors'):
                        if isinstance(d.get(key), list):
                            for item in d[key]:
                                zid = item.get('id') or item.get('zoneId')
                                zlbl = item.get('name') or item.get('label') or zid
                                if zid:
                                    api_zones.append({'id': str(zid), 'label': str(zlbl)})

            cb(f'API zone candidates: {len(api_zones)}')

            # Save debug snapshot
            debug = {
                'timestamp': datetime.now().isoformat(),
                'dom_zones': zones_raw,
                'api_zones': api_zones,
                'api_urls': [c['url'] for c in captured],
            }
            with open(os.path.join(CACHE_DIR, 'vantage_debug.json'), 'w') as f:
                json.dump(debug, f, indent=2)

            # Prefer API zones if found, fall back to DOM
            zones = api_zones if api_zones else zones_raw
            # If still nothing, build a placeholder
            if not zones:
                cb('No zones found in DOM or API — using paKivaA01 as fallback')
                zones = [{'id': 'paKivaA01', 'label': 'paKivaA01'}]

            # Cache
            with open(cache_path, 'w') as f:
                json.dump({'warehouse': warehouse, 'zones': zones,
                           'fetched': datetime.now().isoformat()}, f, indent=2)
            cb(f'Zones cached: {cache_path}')
            return {'ok': True, 'zones': zones}

        except Exception as e:
            import traceback
            cb(f'Zone discovery error: {e}')
            return {'ok': False, 'error': str(e)}
        finally:
            page.close()
            ctx.close()


def load_cached_zones(warehouse='CLE3'):
    """Return cached zones list, or None if not yet discovered."""
    path = os.path.join(CACHE_DIR, 'vantage_zones.json')
    try:
        with open(path) as f:
            d = json.load(f)
        if d.get('warehouse') == warehouse:
            return d['zones']
    except Exception:
        pass
    return None


def fetch(warehouse, time_str, zones=None, status_cb=None):
    """
    Fetch station map data for a specific time.
    time_str : 'HHMM' e.g. '1750'  (or '' / None for current time)
    zones    : list of zone IDs, or None for all
    Returns  : {'ok': True, 'associates': [...], 'time_str': ..., 'source': 'api'|'dom'}
    Each associate: {'name', 'zone', 'station', 'rate', 'cycle_time', 'upf'}
    """
    cb = status_cb or print
    captured = []

    def on_response(resp):
        try:
            if 'json' in resp.headers.get('content-type', ''):
                captured.append({'url': resp.url, 'data': resp.json()})
        except Exception:
            pass

    url = _url(warehouse, zones or [], time_str or '')
    cb(f'Loading Vantage ({time_str or "now"}): {url}')

    with sync_playwright() as p:
        ctx = _ctx(p)
        page = ctx.new_page()
        page.on('response', on_response)
        try:
            page.goto(url, wait_until='networkidle', timeout=90000)
            _dismiss_picker(page, warehouse, cb)
            page.wait_for_timeout(2000)

            # --- Try API interception first ---
            associates = _parse_api(captured, cb)

            # --- Fallback: DOM table scrape ---
            if not associates:
                cb('No data from API — trying DOM...')
                dom_rows = page.evaluate('''() => {
                    const rows = [];
                    document.querySelectorAll('tr, [role="row"]').forEach(row => {
                        const cells = Array.from(
                            row.querySelectorAll('td, th, [role="cell"], [role="columnheader"]')
                        ).map(c => c.innerText?.trim());
                        if (cells.length >= 3) rows.push(cells);
                    });
                    return rows;
                }''')
                cb(f'DOM rows: {len(dom_rows)}')
                associates = _parse_dom(dom_rows, cb)

            # Save debug
            os.makedirs(CACHE_DIR, exist_ok=True)
            debug_path = os.path.join(CACHE_DIR, f'vantage_debug_{time_str or "now"}.json')
            with open(debug_path, 'w') as f:
                json.dump({
                    'url': url, 'time_str': time_str,
                    'api_urls': [c['url'] for c in captured],
                    'sample_api': [{'url': c['url'], 'sample': str(c['data'])[:300]}
                                   for c in captured[:5]],
                    'associates_found': len(associates),
                    'sample_associates': associates[:3],
                }, f, indent=2, default=str)
            cb(f'Debug: {debug_path}')

            if associates:
                return {'ok': True, 'associates': associates,
                        'time_str': time_str, 'source': 'parsed',
                        'count': len(associates)}
            return {'ok': False,
                    'error': f'No associate data found. Check debug: {debug_path}'}

        except Exception as e:
            cb(f'Vantage fetch error: {e}')
            return {'ok': False, 'error': str(e)}
        finally:
            page.close()
            ctx.close()


# ── Parsers ────────────────────────────────────────────────────────────────────

def _parse_api(responses, cb):
    """Try to extract associate records from intercepted API responses."""
    for resp in responses:
        url  = resp['url']
        data = resp['data']
        records = _find_associate_list(data)
        if records:
            cb(f'Found {len(records)} records from API: {url}')
            return [_normalize(r) for r in records if _normalize(r)['name']]
    return []


def _find_associate_list(data):
    """Recursively find the list of associate-like dicts in API response."""
    ASSOC_KEYS = {'rate', 'stowRate', 'cycleTime', 'cycle_time', 'unitsPerFace',
                  'upf', 'associateName', 'employeeName', 'employeeId', 'login'}
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if ASSOC_KEYS & set(data[0].keys()):
            return data
    if isinstance(data, dict):
        for val in data.values():
            result = _find_associate_list(val)
            if result:
                return result
    return []


def _normalize(r):
    """Map raw API record keys to standard fields."""
    return {
        'name':       (r.get('associateName') or r.get('employeeName') or
                       r.get('name') or r.get('login') or ''),
        'zone':       (r.get('zone') or r.get('zoneId') or
                       r.get('area') or r.get('floor') or ''),
        'station':    (r.get('station') or r.get('stationId') or
                       r.get('nodeId') or r.get('stationLabel') or ''),
        'rate':       _num(r.get('rate') or r.get('stowRate') or r.get('unitsPerHour')),
        'cycle_time': _num(r.get('cycleTime') or r.get('cycle_time') or r.get('avgCycleTime')),
        'upf':        _num(r.get('unitsPerFace') or r.get('upf') or r.get('units_per_face')),
    }


def _parse_dom(rows, cb):
    """
    Heuristic DOM table parser.
    Looks for a header row, maps columns by name, then parses data rows.
    """
    if not rows:
        return []

    # Find header row
    header_idx = None
    header_map = {}
    for i, row in enumerate(rows):
        lowered = [c.lower() for c in row]
        hits = sum(1 for c in lowered if any(k in c for k in
                   ['rate', 'cycle', 'face', 'name', 'station', 'zone', 'aa', 'associate']))
        if hits >= 2:
            header_idx = i
            for j, h in enumerate(lowered):
                if 'name' in h or 'associate' in h or 'aa' in h: header_map['name'] = j
                elif 'zone' in h or 'floor' in h or 'area' in h: header_map['zone'] = j
                elif 'station' in h or 'node' in h:              header_map['station'] = j
                elif 'rate' in h or 'uph' in h:                  header_map['rate'] = j
                elif 'cycle' in h:                                header_map['cycle_time'] = j
                elif 'face' in h or 'upf' in h:                  header_map['upf'] = j
            cb(f'Header row {i}: {row} → map {header_map}')
            break

    if header_idx is None or not header_map:
        cb('No recognizable header row found in DOM')
        return []

    result = []
    for row in rows[header_idx + 1:]:
        def _get(key):
            idx = header_map.get(key)
            return row[idx] if idx is not None and idx < len(row) else None
        name = _get('name')
        if not name or len(name) < 2:
            continue
        result.append({
            'name':       name,
            'zone':       _get('zone') or '',
            'station':    _get('station') or '',
            'rate':       _num(_get('rate')),
            'cycle_time': _num(_get('cycle_time')),
            'upf':        _num(_get('upf')),
        })
    cb(f'DOM parsed {len(result)} associates')
    return result


def _num(val):
    if val is None: return None
    try:
        return float(str(val).replace(',', '').strip())
    except Exception:
        return None
