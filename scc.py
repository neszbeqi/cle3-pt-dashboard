"""
CLE3 Staffing Command Center scraper.
Pulls AA -> station assignments for all 4 floors.
Uses Firefox cookie bridge (same auth as FCLM) - no persistent context needed.
"""
import os, re, json
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

WAREHOUSE = "CLE3"
FLOORS = {
    1: "https://staffingcommandcenter-na.aka.amazon.com/CLE3/approved/AR_RSP/paKivaA01/IB",
    2: "https://staffingcommandcenter-na.aka.amazon.com/CLE3/approved/AR_RSP/paKivaA02/IB",
    3: "https://staffingcommandcenter-na.aka.amazon.com/CLE3/approved/AR_RSP/paKivaA03/IB",
    4: "https://staffingcommandcenter-na.aka.amazon.com/CLE3/approved/AR_RSP/paKivaA04/IB",
}
LOG_DIR = os.path.join(os.path.dirname(__file__), "scc_debug")

_EXTRACT_JS = r"""
() => {
    var assignments = [];  // [{login, station, source}]
    var name_map    = [];  // [{login, full_name}]

    var loginPat   = /^[a-z]{1,3}[0-9]{3,8}$|^[a-z]{3,8}$/;
    var stationSuf = /^([1-4][0-9]{3})\s*[UA]?$/;  // matches "1106 U" or "1106"
    var hasSpace   = /\S+\s+\S+/;                   // at least two words (a full name)

    document.querySelectorAll("table tr").forEach(function(row) {
        var tds   = row.querySelectorAll("td");
        var cells = Array.from(tds).map(function(c) { return c.textContent.trim(); });

        if (cells.length === 0) return;

        // -- Floor plan row: cell[0] = station like "2207 U", cell[-1] = login --
        var c0m = stationSuf.exec(cells[0]);
        if (c0m) {
            var station = c0m[1];
            // last non-empty cell that looks like a login
            for (var i = cells.length - 1; i >= 1; i--) {
                if (loginPat.test(cells[i]) && cells[i].length >= 3 && cells[i].length <= 12) {
                    assignments.push({ login: cells[i].toLowerCase(), station: station, source: "floor_plan" });
                    break;
                }
            }
            return;
        }

        // -- Sidebar / Global row: cell[0] = login, cell[1] = full name (has space) --
        var c0 = cells[0];
        if (loginPat.test(c0) && c0.length >= 3 && c0.length <= 12 &&
            cells.length >= 2 && hasSpace.test(cells[1])) {
            name_map.push({ login: c0.toLowerCase(), full_name: cells[1] });
            return;
        }
    });

    var allText = document.body.innerText || "";

    return {
        assignments:    assignments,
        name_map:       name_map,
        stations_found: [...new Set((allText.match(/[1-4][0-9]{3}/g) || []))],
        pageText:       allText.substring(0, 8000),
        url:            window.location.href,
        title:          document.title,
    };
}
"""


def _import_firefox_cookies(ctx):
    """Copy FCLM/AEA cookies from Firefox into a Playwright context."""
    import sqlite3, shutil, time, glob
    base = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")
    db = None
    for p in glob.glob(os.path.join(base, "*.default*", "cookies.sqlite")):
        if os.path.exists(p):
            db = p
            break
    if not db:
        return False
    tmp = db + ".scccopy"
    try:
        shutil.copy2(db, tmp)
        conn = sqlite3.connect(tmp)
        rows = conn.execute(
            "SELECT host, name, value, path, expiry, isSecure, isHttpOnly "
            "FROM moz_cookies "
            "WHERE (host LIKE '%aka.amazon%' OR host LIKE '%fclm-portal%' "
            "       OR host = 'midway-auth.amazon.com') "
            "AND expiry > ?", (int(time.time()),)
        ).fetchall()
        conn.close()
        if not rows:
            return False
        cookies = []
        for host, name, value, path, expiry, secure, httponly in rows:
            cookies.append({
                "name": name, "value": value, "domain": host,
                "path": path or "/", "expires": expiry,
                "secure": bool(secure), "httpOnly": bool(httponly), "sameSite": "None",
            })
        ctx.add_cookies(cookies)
        return True
    except Exception:
        return False
    finally:
        try: os.remove(tmp)
        except: pass


def _parse_assignments(raw, floor):
    """
    Parse raw JS extraction into:
      - assignments: [{login, station, floor}]  -- people with a kiva station
      - name_map:    {login: full_name}          -- from Global sidebar (for name-based join)
    Returns (assignments, name_map).
    """
    assignments = []
    seen = set()
    login_re   = re.compile(r"^[a-z]{1,3}[0-9]{3,8}$|^[a-z]{3,8}$")
    station_re = re.compile(r"^[1-4][0-9]{3}$")

    for item in raw.get("assignments", []):
        login   = (item.get("login") or "").strip().lower()
        station = (item.get("station") or "").strip()
        if not login or not login_re.match(login) or login in seen:
            continue
        if not station_re.match(station):
            continue  # JS already stripped suffix; skip unassigned
        fl = int(station[0])
        seen.add(login)
        assignments.append({"login": login, "station": station, "floor": fl})

    # Name map from the Global sidebar: login -> full_name
    name_map = {}
    for item in raw.get("name_map", []):
        login     = (item.get("login") or "").strip().lower()
        full_name = (item.get("full_name") or "").strip()
        if login and full_name and login not in name_map:
            name_map[login] = full_name

    return assignments, name_map


def fetch_all(status_cb=None, out_file=None):
    """
    Scrape all 4 floor SCC pages using Firefox cookie auth.
    Returns list of {login, station, floor}.
    Saves diagnostic JSON to scc_debug/ for parser tuning.
    """
    def log(m):
        if status_cb: status_cb(m)

    os.makedirs(LOG_DIR, exist_ok=True)
    all_assignments = []
    all_names       = {}   # login -> full_name from Global sidebar
    _out_file       = out_file

    with sync_playwright() as pw:
        args = [
            "--no-sandbox", "--disable-dev-shm-usage",
            "--window-position=-32000,-32000", "--window-size=1280,900",
        ]
        browser = pw.chromium.launch(headless=False, args=args)
        ctx = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 900},
        )
        try:
            log("Importing Firefox cookies for SCC...")
            _import_firefox_cookies(ctx)
            page = ctx.new_page()

            log("Checking SCC auth...")
            page.goto("https://staffingcommandcenter-na.aka.amazon.com",
                      timeout=20000, wait_until="domcontentloaded")
            if "midway" in page.url or "login" in page.url.lower():
                log("SCC: session expired -- open SCC in Firefox to refresh.")
            else:
                for floor, url in FLOORS.items():
                    log(f"Loading Floor {floor}...")
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    except PWTimeout:
                        pass

                    # Click "Global" tab in the sidebar to get full name data for name-based join
                    try:
                        page.click("text=Global", timeout=3000)
                        page.wait_for_timeout(800)
                    except: pass

                    # Wait for React floor plan grid to render.
                    # Sidebar loads first (~5000 chars of unassigned logins) -- we need to wait
                    # until actual station IDs like "1106 U" or "3212 A" appear in the page text.
                    # These ONLY appear in the floor plan grid, never in the sidebar.
                    try:
                        page.wait_for_function(
                            r"() => /[1-4]\d{3}\s+[UA]/.test(document.body.innerText)",
                            timeout=20000
                        )
                    except: pass
                    # Brief extra settle for all rows to finish rendering
                    try:
                        page.wait_for_timeout(1500)
                    except: pass

                    raw = page.evaluate(_EXTRACT_JS) or {}

                    log_path = os.path.join(LOG_DIR, f"floor{floor}.json")
                    with open(log_path, "w", encoding="utf-8") as f:
                        json.dump(raw, f, indent=2, ensure_ascii=False)
                    log(f"Floor {floor}: saved to {log_path}")

                    parsed, nm = _parse_assignments(raw, floor)
                    n_st = len(raw.get("stations_found", []))
                    log(f"Floor {floor}: {len(parsed)} assigned, {len(nm)} names in Global sidebar, {n_st} stations in page")
                    all_assignments.extend(parsed)
                    all_names.update(nm)

            # Write result INSIDE try, so it always executes unless we crash before the for loop.
            # Moving it here (not after finally) prevents Windows Playwright teardown from skipping it.
            _result = {"assignments": all_assignments, "name_map": all_names}
            if _out_file:
                try:
                    with open(_out_file, "w", encoding="utf-8") as _f:
                        json.dump(_result, _f, ensure_ascii=False)
                    log(f"SCC result written: {len(all_assignments)} assignments, {len(all_names)} names")
                except Exception as e:
                    log(f"SCC result write failed: {e}")

        except Exception as e:
            log(f"SCC fetch_all error: {e}")
        finally:
            try: ctx.close()
            except: pass
            try: browser.close()
            except: pass

    return _result


def fetch_floor(floor_num, status_cb=None):
    """Fetch a single floor (used for quick refresh)."""
    def log(m):
        if status_cb: status_cb(m)
    url = FLOORS.get(floor_num)
    if not url:
        return []

    with sync_playwright() as pw:
        args = ["--no-sandbox","--disable-dev-shm-usage",
                "--window-position=-32000,-32000","--window-size=1280,900"]
        browser = pw.chromium.launch(headless=False, args=args)
        ctx = browser.new_context(ignore_https_errors=True, viewport={"width":1280,"height":900})
        try:
            _import_firefox_cookies(ctx)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            raw = page.evaluate(_EXTRACT_JS) or {}
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(os.path.join(LOG_DIR, f"floor{floor_num}.json"), "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)
            parsed, nm = _parse_assignments(raw, floor_num)
            return parsed
        finally:
            try: ctx.close()
            except: pass
            try: browser.close()
            except: pass

