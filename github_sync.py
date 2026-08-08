"""
github_sync.py -- sync live data and actions to the GitHub repo.

Each installed server instance pushes:
  data/live.json        -- latest PT data (for offline viewing via GitHub Pages)
  data/current_url.json -- the IP:port of this server (so the portal can redirect)
  data/actions.json     -- all logged actions (shared across all server instances)

Uses only stdlib (urllib) -- no extra dependencies.
"""
import os, json, base64, threading, time
from datetime import datetime

_token = ""
_repo  = ""

def configure(token, repo):
    global _token, _repo
    _token = token.strip()
    _repo  = repo.strip()

def ready():
    return bool(_token and _repo)

# ── Low-level GitHub Contents API ─────────────────────────────────────────────

def _headers():
    return {
        "Authorization": f"token {_token}",
        "Accept":        "application/vnd.github.v3+json",
        "Content-Type":  "application/json",
        "User-Agent":    "CLE3-PT-Dashboard",
    }

def _get_file(path):
    """Return (decoded_bytes, sha) or (None, None)."""
    import urllib.request
    url = f"https://api.github.com/repos/{_repo}/contents/{path}"
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read())
            return base64.b64decode(d["content"].replace("\n", "")), d.get("sha", "")
    except Exception:
        return None, None

def _put_file(path, content_bytes, message, sha=None, retries=2):
    """Create or update a file. Returns True on success."""
    import urllib.request, urllib.error
    url = f"https://api.github.com/repos/{_repo}/contents/{path}"
    for attempt in range(retries + 1):
        if attempt > 0 or sha is None:
            _, sha = _get_file(path)
        payload = {
            "message": message,
            "content": base64.b64encode(content_bytes).decode(),
        }
        if sha:
            payload["sha"] = sha
        try:
            data = json.dumps(payload).encode()
            req  = urllib.request.Request(url, data=data, headers=_headers(), method="PUT")
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status in (200, 201)
        except urllib.error.HTTPError as e:
            if e.code == 409 and attempt < retries:
                time.sleep(1)
                continue
            return False
        except Exception:
            return False
    return False

# ── Public helpers (all fire-and-forget in daemon threads) ────────────────────

def push_live_data(associates, shift, date_str):
    """Commit current enriched associate list so portal can show it offline."""
    if not ready(): return
    def _do():
        try:
            payload = {
                "shift":      shift,
                "date":       date_str,
                "updated":    datetime.now().isoformat(),
                "associates": associates,
            }
            _put_file("data/live.json",
                      json.dumps(payload, ensure_ascii=False, default=str).encode(),
                      f"PT update {datetime.now():%H:%M}")
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

def push_server_url(server_url):
    """Let the GitHub Pages portal know this server is alive and where to find it."""
    if not ready(): return
    def _do():
        try:
            payload = {"url": server_url, "updated": datetime.now().isoformat()}
            _put_file("data/current_url.json",
                      json.dumps(payload).encode(),
                      "Server heartbeat")
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

def push_action(action_dict):
    """Append a new action to data/actions.json (read-modify-write with retry)."""
    if not ready(): return
    def _do():
        try:
            raw, sha = _get_file("data/actions.json")
            actions  = json.loads(raw) if raw else []
            if not isinstance(actions, list): actions = []
            actions.append(action_dict)
            if len(actions) > 2000:
                actions = actions[-2000:]
            _put_file("data/actions.json",
                      json.dumps(actions, ensure_ascii=False, default=str).encode(),
                      "Action logged", sha=sha)
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

def pull_actions():
    """Return list of actions from GitHub (used on server startup to seed local DB)."""
    if not ready(): return []
    try:
        raw, _ = _get_file("data/actions.json")
        if raw:
            actions = json.loads(raw)
            if isinstance(actions, list): return actions
    except Exception:
        pass
    return []
