"""
CLE3 PT Dashboard - Login Helper
Run once at shift start. Stops the background server scraper, opens a
visible browser so you can log in, then restarts the server.
"""
import os, subprocess, time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SESSION_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),
    '.pt_dashboard', 'session'
)
os.makedirs(SESSION_DIR, exist_ok=True)

SITES = [
    ('FCLM', 'https://fclm-portal.amazon.com',                 'fclm-portal.amazon.com'),
    ('SCC',  'https://staffingcommandcenter-na.aka.amazon.com', 'staffingcommandcenter-na.aka.amazon.com'),
]

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10, **kw)

def stop_server():
    run(['schtasks', '/End', '/TN', 'CLE3_PT_Server'])

def start_server():
    run(['schtasks', '/Run', '/TN', 'CLE3_PT_Server'])

def kill_chrome():
    """Kill any chrome.exe processes holding the pt_dashboard session."""
    try:
        r = run(['wmic', 'process', 'where',
                 'name="chrome.exe" and commandline like "%pt_dashboard%"',
                 'get', 'processid', '/value'])
        pids = [l.split('=')[1].strip() for l in r.stdout.splitlines()
                if l.startswith('ProcessId=') and l.split('=')[1].strip()]
        for pid in pids:
            run(['taskkill', '/F', '/PID', pid])
            print(f'  Killed stale Chrome (PID {pid})')
        if pids:
            time.sleep(2)
    except Exception:
        pass

def is_auth(page, host):
    try:
        return (host in page.url
                and 'midway' not in page.url
                and 'login' not in page.url.lower())
    except:
        return False

def main():
    print('\n' + '='*58)
    print('  CLE3 PT Dashboard — Login Helper')
    print('='*58)

    print('\nPausing background scraper...')
    stop_server()
    time.sleep(2)

    print('Clearing stale Chrome processes...')
    kill_chrome()

    print('Opening browser...\n')

    all_ok = True
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=SESSION_DIR,
                headless=False,
                ignore_https_errors=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--start-maximized'],
                viewport={'width': 1280, 'height': 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            for name, base_url, host in SITES:
                print(f'[{name}] Checking {base_url} ...')
                try:
                    page.goto(base_url, timeout=30000, wait_until='domcontentloaded')
                except Exception as e:
                    print(f'[{name}] Navigation failed: {e}')
                    all_ok = False
                    continue

                if is_auth(page, host):
                    print(f'[{name}] Already logged in!')
                    continue

                print(f'[{name}] >> Log in via the browser window <<')
                try:
                    page.wait_for_url(f'https://{host}/**', timeout=300000)
                    print(f'[{name}] Login successful!')
                except PWTimeout:
                    print(f'[{name}] Timed out. Run this again if needed.')
                    all_ok = False

            ctx.close()

    except Exception as e:
        print(f'\nERROR: {e}')
        all_ok = False

    finally:
        print('\nRestarting background scraper...')
        start_server()

    print()
    if all_ok:
        print('='*58)
        print('  Done! Dashboard will load data within 3 minutes.')
        print('  Open http://localhost:5050 in Firefox.')
        print('  No need to run this again until tomorrow.')
        print('='*58)
    else:
        print('  Some logins may have failed — run this again if data')
        print('  does not appear within 5 minutes.')
    print()
    input('Press Enter to close...')

if __name__ == '__main__':
    main()
