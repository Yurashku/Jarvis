"""Database utilities for Jarvis.

This module provides a tiny wrapper around :mod:`sqlite3` used by the
store layer.  It is responsible for initialising the database file and
creating all tables, indexes and the FTS5 search table.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DB_PATH = Path("data") / "jarvis.db"


def get_conn() -> sqlite3.Connection:
    """Return a connection to the SQLite database with row access by name."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create database tables, indexes and the FTS5 search table."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                due TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                owner INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner);
            CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due);

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                start TEXT NOT NULL,
                duration_min INTEGER NOT NULL,
                owner INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_owner ON events(owner);
            CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);

            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                at TEXT NOT NULL,
                owner INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_owner ON reminders(owner);
            CREATE INDEX IF NOT EXISTS idx_reminders_at ON reminders(at);

            CREATE VIRTUAL TABLE IF NOT EXISTS search_index
            USING fts5(id UNINDEXED, type UNINDEXED, content, owner UNINDEXED);
            """
        )
        conn.commit()
        migrate_times_to_utc(conn)


def _to_utc(s: str) -> str:
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC")).isoformat()


def migrate_times_to_utc(conn: sqlite3.Connection) -> None:
    """Ensure all stored timestamps are normalised to UTC."""
    tables = {
        "tasks": ["due", "created_at"],
        "events": ["start", "created_at"],
        "reminders": ["at", "created_at"],
    }
    for table, cols in tables.items():
        rows = conn.execute(f"SELECT id, {', '.join(cols)} FROM {table}").fetchall()
        for row in rows:
            for col in cols:
                val = row[col]
                if not val:
                    continue
                utc_val = _to_utc(val)
                if utc_val != val:
                    conn.execute(
                        f"UPDATE {table} SET {col} = ? WHERE id = ?",
                        (utc_val, row["id"]),
                    )
    conn.commit()


# Ensure tables exist when the module is imported
init_db()

