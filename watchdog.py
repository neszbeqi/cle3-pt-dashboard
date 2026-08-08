"""
CLE3 PT Dashboard - Watchdog launcher.
Runs server.py forever, restarting immediately if it ever exits.
Task Scheduler runs this instead of server.py directly.
"""
import subprocess, sys, os, time, datetime, signal

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON  = sys.executable
LOG     = os.path.join(APP_DIR, "watchdog.log")

def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except: pass

def kill_stale_servers():
    """Kill any leftover server.py processes from previous runs to prevent port conflicts."""
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                if any('server.py' in c for c in cmdline) and proc.pid != current_pid:
                    log(f"Killing stale server.py PID {proc.pid}")
                    proc.kill()
            except Exception:
                pass
    except ImportError:
        # psutil not available -- fall back to taskkill
        try:
            subprocess.run(
                ["taskkill", "/F", "/FI", "WINDOWTITLE eq server.py", "/T"],
                capture_output=True
            )
        except Exception:
            pass

log("Watchdog started")
kill_stale_servers()
time.sleep(2)   # Let killed processes release port 5050

restart_count = 0

while True:
    log(f"Starting server.py (restart #{restart_count})")
    try:
        proc = subprocess.run([PYTHON, "server.py"], cwd=APP_DIR)
        log(f"server.py exited with code {proc.returncode}")
    except Exception as e:
        log(f"server.py failed to start: {e}")
    restart_count += 1
    log("Restarting in 3 seconds...")
    time.sleep(3)
