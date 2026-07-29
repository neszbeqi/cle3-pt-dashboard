"""
Database layer — SQLite, stored in LOCALAPPDATA/.live_dashboard/data.db
All tables created on first run via init_db().
"""
import sqlite3, os

DB_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    '.live_dashboard', 'data.db'
)

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            login       TEXT    NOT NULL,
            name        TEXT    DEFAULT '',
            type        TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            has_pending INTEGER DEFAULT 0,
            notes       TEXT    DEFAULT '',
            am_name     TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS barriers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            login       TEXT NOT NULL,
            name        TEXT DEFAULT '',
            date        TEXT NOT NULL,
            shift       TEXT DEFAULT 'night',
            barrier     TEXT NOT NULL,
            flag_type   TEXT DEFAULT '',
            am_name     TEXT DEFAULT '',
            resolved    INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS handoff_notes (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            login    TEXT DEFAULT '',
            name     TEXT DEFAULT '',
            date     TEXT NOT NULL,
            shift    TEXT DEFAULT 'night',
            note     TEXT NOT NULL,
            am_name  TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS shift_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            login         TEXT NOT NULL,
            name          TEXT DEFAULT '',
            date          TEXT NOT NULL,
            shift         TEXT DEFAULT 'night',
            pt_pct        REAL,
            idle_hrs      REAL DEFAULT 0,
            total_hrs     REAL DEFAULT 0,
            had_black_bar INTEGER DEFAULT 0,
            manager       TEXT DEFAULT '',
            created_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(login, date, shift)
        );

        CREATE TABLE IF NOT EXISTS new_hires (
            login      TEXT PRIMARY KEY,
            name       TEXT DEFAULT '',
            start_date TEXT NOT NULL,
            notes      TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS am_actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            am_name     TEXT NOT NULL,
            action_type TEXT NOT NULL,
            associate   TEXT DEFAULT '',
            login       TEXT DEFAULT '',
            date        TEXT NOT NULL,
            shift       TEXT DEFAULT 'night',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS pt_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            login       TEXT NOT NULL,
            name        TEXT DEFAULT '',
            date        TEXT NOT NULL,
            shift       TEXT NOT NULL,
            ts          TEXT NOT NULL,
            pt_pct      REAL,
            inferred    REAL,
            total       REAL,
            manager     TEXT DEFAULT ''
        );
    ''')
    conn.commit()
    conn.close()
