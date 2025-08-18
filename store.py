"""
store.py
~~~~~~~~

Persistence layer backed by SQLite.

This module mirrors the public API of the previous JSON-based store but
uses a SQLite database located in ``data/jarvis.db``.  It exposes helper
functions for tasks, events and reminders as well as a simple full-text
search facility.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
from uuid import uuid4

from db import get_conn


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _task_from_row(row) -> Dict[str, object]:
    d = dict(row)
    d["done"] = bool(d["done"])
    return d
# -----------------------------------------------------------------------------
# Tasks
# -----------------------------------------------------------------------------


def add_task(
    text: str,
    due_iso: Optional[str] = None,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    task_id = str(uuid4())
    try:
        created_at_dt = datetime.now(tz=ZoneInfo("local"))
    except Exception:
        created_at_dt = datetime.now().astimezone()
    created_at = created_at_dt.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (id, text, due, done, owner, created_at) VALUES (?,?,?,?,?,?)",
            (
                task_id,
                text,
                datetime.fromisoformat(due_iso).astimezone(ZoneInfo("UTC")).isoformat()
                if due_iso
                else None,
                0,
                owner,
                created_at,
            ),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (task_id, "task", text, owner),
        )
    return {
        "id": task_id,
        "text": text,
        "due": datetime.fromisoformat(due_iso).astimezone(ZoneInfo("UTC")).isoformat()
        if due_iso
        else None,
        "done": False,
        "owner": owner,
        "created_at": created_at,
    }


def list_tasks(owner: Optional[int] = None) -> List[Dict[str, object]]:
    sql = "SELECT * FROM tasks"
    params: List[object] = []
    if owner is not None:
        sql += " WHERE owner = ?"
        params.append(owner)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_task_from_row(r) for r in rows]


def get_task_by_prefix(
    task_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    sql = "SELECT * FROM tasks WHERE id LIKE ? || '%'"
    params: List[object] = [task_id_prefix]
    if owner is not None:
        sql += " AND owner = ?"
        params.append(owner)
    with get_conn() as conn:
        row = conn.execute(sql + " LIMIT 1", params).fetchone()
        return _task_from_row(row) if row else None


def complete_task(task_id_prefix: str, owner: Optional[int] = None) -> bool:
    task = get_task_by_prefix(task_id_prefix, owner)
    if not task:
        return False
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task["id"],))
    return True


def snooze_task(
    task_id_prefix: str, minutes: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    task = get_task_by_prefix(task_id_prefix, owner)
    if not task:
        return None
    base = (
        datetime.fromisoformat(task["due"]) if task.get("due") else datetime.now(tz=ZoneInfo("UTC"))
    )
    new_due = (
        base + timedelta(minutes=minutes)
    ).replace(microsecond=0).astimezone(ZoneInfo("UTC")).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET due = ? WHERE id = ?", (new_due, task["id"]))
    task["due"] = new_due
    return task


# -----------------------------------------------------------------------------
# Events
# -----------------------------------------------------------------------------


def add_event(
    title: str,
    start_iso: str,
    duration_min: int = 60,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    event_id = str(uuid4())
    try:
        created_at_dt = datetime.now(tz=ZoneInfo("local"))
    except Exception:
        created_at_dt = datetime.now().astimezone()
    created_at = created_at_dt.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO events (id, title, start, duration_min, owner, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                event_id,
                title,
                datetime.fromisoformat(start_iso).astimezone(ZoneInfo("UTC")).isoformat(),
                int(duration_min),
                owner,
                created_at,
            ),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (event_id, "event", title, owner),
        )
    return {
        "id": event_id,
        "title": title,
        "start": datetime.fromisoformat(start_iso).astimezone(ZoneInfo("UTC")).isoformat(),
        "duration_min": int(duration_min),
        "owner": owner,
        "created_at": created_at,
    }


def list_events(owner: Optional[int] = None) -> List[Dict[str, object]]:
    sql = "SELECT * FROM events"
    params: List[object] = []
    if owner is not None:
        sql += " WHERE owner = ?"
        params.append(owner)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_event_by_prefix(
    event_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    sql = "SELECT * FROM events WHERE id LIKE ? || '%'"
    params: List[object] = [event_id_prefix]
    if owner is not None:
        sql += " AND owner = ?"
        params.append(owner)
    with get_conn() as conn:
        row = conn.execute(sql + " LIMIT 1", params).fetchone()
        return dict(row) if row else None


def update_event_title(
    event_id_prefix: str, new_title: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    event = get_event_by_prefix(event_id_prefix, owner)
    if not event:
        return None
    with get_conn() as conn:
        conn.execute("UPDATE events SET title = ? WHERE id = ?", (new_title, event["id"]))
        conn.execute(
            "UPDATE search_index SET content = ? WHERE id = ? AND type = 'event'",
            (new_title, event["id"]),
        )
    event["title"] = new_title
    return event


def update_event_time(
    event_id_prefix: str, new_start_iso: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    event = get_event_by_prefix(event_id_prefix, owner)
    if not event:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE events SET start = ? WHERE id = ?",
            (
                datetime.fromisoformat(new_start_iso)
                .astimezone(ZoneInfo("UTC"))
                .isoformat(),
                event["id"],
            ),
        )
    event["start"] = (
        datetime.fromisoformat(new_start_iso)
        .astimezone(ZoneInfo("UTC"))
        .isoformat()
    )
    return event


def update_event_duration(
    event_id_prefix: str, new_duration_min: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    event = get_event_by_prefix(event_id_prefix, owner)
    if not event:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE events SET duration_min = ? WHERE id = ?",
            (int(new_duration_min), event["id"]),
        )
    event["duration_min"] = int(new_duration_min)
    return event


def snooze_event(
    event_id_prefix: str, minutes: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    event = get_event_by_prefix(event_id_prefix, owner)
    if not event:
        return None
    base = datetime.fromisoformat(event["start"])
    new_start = (
        base + timedelta(minutes=minutes)
    ).replace(microsecond=0).astimezone(ZoneInfo("UTC")).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE events SET start = ? WHERE id = ?", (new_start, event["id"]))
    event["start"] = new_start
    return event


def delete_event(
    event_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    event = get_event_by_prefix(event_id_prefix, owner)
    if not event:
        return None
    with get_conn() as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event["id"],))
        conn.execute(
            "DELETE FROM search_index WHERE id = ? AND type = 'event'",
            (event["id"],),
        )
    return event


# -----------------------------------------------------------------------------
# Reminders
# -----------------------------------------------------------------------------


def add_reminder(
    text: str,
    at_iso: str,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    rem_id = str(uuid4())
    try:
        created_at_dt = datetime.now(tz=ZoneInfo("local"))
    except Exception:
        created_at_dt = datetime.now().astimezone()
    created_at = created_at_dt.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (id, text, at, owner, created_at) VALUES (?,?,?,?,?)",
            (
                rem_id,
                text,
                datetime.fromisoformat(at_iso).astimezone(ZoneInfo("UTC")).isoformat(),
                owner,
                created_at,
            ),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (rem_id, "reminder", text, owner),
        )
    return {
        "id": rem_id,
        "text": text,
        "at": datetime.fromisoformat(at_iso).astimezone(ZoneInfo("UTC")).isoformat(),
        "owner": owner,
        "created_at": created_at,
    }


def list_reminders(owner: Optional[int] = None) -> List[Dict[str, object]]:
    sql = "SELECT * FROM reminders"
    params: List[object] = []
    if owner is not None:
        sql += " WHERE owner = ?"
        params.append(owner)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_reminder_by_prefix(
    rem_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    sql = "SELECT * FROM reminders WHERE id LIKE ? || '%'"
    params: List[object] = [rem_id_prefix]
    if owner is not None:
        sql += " AND owner = ?"
        params.append(owner)
    with get_conn() as conn:
        row = conn.execute(sql + " LIMIT 1", params).fetchone()
        return dict(row) if row else None


def snooze_reminder(
    rem_id_prefix: str, minutes: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    rem = get_reminder_by_prefix(rem_id_prefix, owner)
    if not rem:
        return None
    base = datetime.fromisoformat(rem["at"])
    new_at = (
        base + timedelta(minutes=minutes)
    ).replace(microsecond=0).astimezone(ZoneInfo("UTC")).isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE reminders SET at = ? WHERE id = ?", (new_at, rem["id"]))
    rem["at"] = new_at
    return rem


def delete_reminder(
    rem_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    rem = get_reminder_by_prefix(rem_id_prefix, owner)
    if not rem:
        return None
    with get_conn() as conn:
        conn.execute("DELETE FROM reminders WHERE id = ?", (rem["id"],))
        conn.execute(
            "DELETE FROM search_index WHERE id = ? AND type = 'reminder'",
            (rem["id"],),
        )
    return rem


# -----------------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------------


def search_entries(query: str, owner: Optional[int] = None) -> List[Dict[str, object]]:
    """Search tasks, events and reminders using FTS5."""
    sql = "SELECT id, type, content, owner FROM search_index WHERE search_index MATCH ?"
    params: List[object] = [query]
    if owner is not None:
        sql += " AND owner = ?"
        params.append(owner)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

