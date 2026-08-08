"""
Auto-updater for CLE3 PT Dashboard.
Checks GitHub for updates and applies them before the server starts.
Files in the 'cle3_pt_dashboard' subfolder of the repo are downloaded.
"""
import urllib.request, json, zipfile, io, os, sys

REPO      = 'neszbeqi/cle3-pt-dashboard'
SUBFOLDER = 'cle3_pt_dashboard'
API_URL   = f'https://api.github.com/repos/{REPO}/commits?path={SUBFOLDER}&per_page=1'
ZIP_URL   = f'https://github.com/{REPO}/archive/refs/heads/main.zip'
APP_DIR   = os.path.dirname(os.path.abspath(__file__))
VER_FILE  = os.path.join(APP_DIR, 'version.txt')

# Files/folders that should never be overwritten by an update
PROTECTED = {'version.txt', 'venv', '__pycache__', '.git'}


def get_local_sha():
    try:
        return open(VER_FILE, encoding='utf-8').read().strip()
    except FileNotFoundError:
        return ''


def get_remote_sha():
    try:
        req = urllib.request.Request(API_URL, headers={'User-Agent': 'cle3-pt-updater/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data:
                return data[0]['sha'][:7]
    except Exception as e:
        print(f'[updater] Could not reach GitHub: {e}')
    return ''


def apply_update():
    print('[updater] Downloading update...')
    req = urllib.request.Request(ZIP_URL, headers={'User-Agent': 'cle3-pt-updater/1.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        zdata = resp.read()

    prefix = f'cle3-pt-dashboard-main/{SUBFOLDER}/'
    count  = 0
    with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
        for info in zf.infolist():
            if not info.filename.startswith(prefix):
                continue
            rel = info.filename[len(prefix):]
            if not rel:
                continue
            top = rel.split('/')[0]
            if top in PROTECTED:
                continue
            dest = os.path.join(APP_DIR, rel)
            if info.is_dir():
                os.makedirs(dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest) or APP_DIR, exist_ok=True)
                with zf.open(info) as src:
                    open(dest, 'wb').write(src.read())
                count += 1
    print(f'[updater] Applied {count} files.')


def main():
    local  = get_local_sha()
    remote = get_remote_sha()

    if not remote:
        print('[updater] Skipping update check (no network or repo not pushed yet).')
        return

    if local == remote:
        print(f'[updater] Up to date ({local}).')
        return

    print(f'[updater] Update available: {local or "first install"} -> {remote}')
    try:
        apply_update()
        open(VER_FILE, 'w', encoding='utf-8').write(remote)
        print('[updater] Update complete. Restart will use new files.')
    except Exception as e:
        print(f'[updater] Update failed (continuing with current version): {e}')


if __name__ == '__main__':
    main()
