"""Migrate existing JSON data files into the SQLite database.

This script reads ``tasks.json``, ``events.json`` and ``reminders.json``
from the ``data`` directory (if present) and imports their contents into
the new SQLite database using the same identifiers.  Existing rows are
left untouched which allows the script to be run multiple times safely.
"""

from __future__ import annotations

import json
from pathlib import Path

from db import get_conn, init_db


def _load(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def migrate() -> None:
    data_dir = Path("data")
    init_db()
    tasks = _load(data_dir / "tasks.json")
    events = _load(data_dir / "events.json")
    reminders = _load(data_dir / "reminders.json")

    with get_conn() as conn:
        cur = conn.cursor()
        for t in tasks:
            cur.execute(
                """
                INSERT OR IGNORE INTO tasks(id, text, due, done, owner, created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    t.get("id"),
                    t.get("text"),
                    t.get("due"),
                    1 if t.get("done") else 0,
                    t.get("owner"),
                    t.get("created_at"),
                ),
            )
            cur.execute(
                "INSERT OR IGNORE INTO search_index(id,type,content,owner) VALUES(?,?,?,?)",
                (t.get("id"), "task", t.get("text"), t.get("owner")),
            )
        for e in events:
            cur.execute(
                """
                INSERT OR IGNORE INTO events(id, title, start, duration_min, owner, created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    e.get("id"),
                    e.get("title"),
                    e.get("start"),
                    e.get("duration_min"),
                    e.get("owner"),
                    e.get("created_at"),
                ),
            )
            cur.execute(
                "INSERT OR IGNORE INTO search_index(id,type,content,owner) VALUES(?,?,?,?)",
                (e.get("id"), "event", e.get("title"), e.get("owner")),
            )
        for r in reminders:
            cur.execute(
                """
                INSERT OR IGNORE INTO reminders(id, text, at, owner, created_at)
                VALUES(?,?,?,?,?)
                """,
                (
                    r.get("id"),
                    r.get("text"),
                    r.get("at"),
                    r.get("owner"),
                    r.get("created_at"),
                ),
            )
            cur.execute(
                "INSERT OR IGNORE INTO search_index(id,type,content,owner) VALUES(?,?,?,?)",
                (r.get("id"), "reminder", r.get("text"), r.get("owner")),
            )
        conn.commit()


if __name__ == "__main__":
    migrate()

