"""
CLE3 PT Dashboard — SQLite database.
Stores snapshots, actions, and patterns.
"""
import os, sqlite3
from datetime import datetime

def _db_path():
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('USERPROFILE') or os.path.expanduser('~')
    folder = os.path.join(base, '.cle3_pt')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, 'data.db')

DB_PATH = _db_path()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            badge       TEXT NOT NULL,
            name        TEXT,
            manager     TEXT,
            station     TEXT,
            floor       INTEGER,
            date        TEXT NOT NULL,
            shift       TEXT NOT NULL,
            ts          TEXT NOT NULL,
            pt_pct      REAL,
            inferred    REAL,
            total       REAL
        );
        CREATE INDEX IF NOT EXISTS idx_snap_badge ON snapshots(badge, date, shift);

        CREATE TABLE IF NOT EXISTS actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            badge       TEXT NOT NULL,
            name        TEXT,
            manager     TEXT,
            action_type TEXT NOT NULL,
            note        TEXT,
            am_name     TEXT,
            date        TEXT NOT NULL,
            shift       TEXT NOT NULL,
            ts          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_act_badge ON actions(badge, date);

        CREATE TABLE IF NOT EXISTS barriers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            badge       TEXT NOT NULL,
            name        TEXT,
            barrier     TEXT NOT NULL,
            note        TEXT,
            am_name     TEXT,
            date        TEXT NOT NULL,
            shift       TEXT NOT NULL,
            ts          TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
