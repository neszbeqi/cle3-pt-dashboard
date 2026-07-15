"""
Auto-updater for CLE3 PT Dashboard.
Checks GitHub on startup for a newer version.json, downloads changed files,
and notifies the user to restart.

Runs silently in a background thread — never blocks the UI.
"""
import os, sys, json, threading, urllib.request, shutil, tempfile

REPO_RAW   = 'https://raw.githubusercontent.com/neszbeqi/cle3-pt-dashboard/main'
VERSION_URL = f'{REPO_RAW}/version.json'

UPDATABLE_FILES = [
    'app.py', 'fclm.py', 'processor.py', 'history.py',
    'generate_report.py', 'build_trends.py', 'backfill_shifts.py',
]

def _install_dir():
    """Where the running app's source files live."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _local_version():
    vpath = os.path.join(_install_dir(), 'version.json')
    try:
        with open(vpath) as f:
            return json.load(f).get('version', '0.0.0')
    except Exception:
        return '0.0.0'

def _remote_version():
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=5) as r:
            return json.loads(r.read()).get('version', '0.0.0')
    except Exception:
        return None

def _download_file(fname):
    url = f'{REPO_RAW}/{fname}'
    dest = os.path.join(_install_dir(), fname)
    tmp  = dest + '.tmp'
    try:
        urllib.request.urlretrieve(url, tmp)
        shutil.move(tmp, dest)
        return True
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False

def _update_version_file(remote):
    vpath = os.path.join(_install_dir(), 'version.json')
    try:
        with open(vpath, 'w') as f:
            import datetime
            json.dump({'version': remote,
                       'updated': datetime.date.today().strftime('%Y-%m-%d')}, f)
    except Exception:
        pass

def check(on_update_available=None):
    """
    Call this on app startup. Runs in a background thread.
    on_update_available(new_version) is called on the main thread
    if a newer version is found and installed.
    """
    def _worker():
        local  = _local_version()
        remote = _remote_version()
        if not remote or remote == local:
            return   # up to date or no internet

        # Download all updatable files
        updated = []
        for fname in UPDATABLE_FILES:
            if _download_file(fname):
                updated.append(fname)

        if updated:
            _update_version_file(remote)
            if on_update_available:
                on_update_available(remote)

    threading.Thread(target=_worker, daemon=True).start()
