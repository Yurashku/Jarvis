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
from typing import Dict, List, Optional
from uuid import uuid4

from dateutil.rrule import rrulestr
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
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (id, text, due, done, owner, created_at) VALUES (?,?,?,?,?,?)",
            (task_id, text, due_iso, 0, owner, created_at),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (task_id, "task", text, owner),
        )
    return {
        "id": task_id,
        "text": text,
        "due": due_iso,
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
        datetime.fromisoformat(task["due"]) if task.get("due") else datetime.now()
    )
    new_due = (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
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
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO events (id, title, start, duration_min, owner, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (event_id, title, start_iso, int(duration_min), owner, created_at),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (event_id, "event", title, owner),
        )
    return {
        "id": event_id,
        "title": title,
        "start": start_iso,
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
        conn.execute("UPDATE events SET start = ? WHERE id = ?", (new_start_iso, event["id"]))
    event["start"] = new_start_iso
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
    new_start = (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
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
# Recurring events
# -----------------------------------------------------------------------------


def _recurring_event_from_row(row) -> Dict[str, object]:
    return dict(row)


def add_recurring_event(
    title: str,
    rrule_str: str,
    duration_min: int = 60,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    rec_id = str(uuid4())
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO recurring_events (id, title, rrule, duration_min, owner, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (rec_id, title, rrule_str, int(duration_min), owner, created_at),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (rec_id, "event", title, owner),
        )
    return {
        "id": rec_id,
        "title": title,
        "rrule": rrule_str,
        "duration_min": int(duration_min),
        "owner": owner,
        "created_at": created_at,
    }


def list_recurring_events(owner: Optional[int] = None) -> List[Dict[str, object]]:
    sql = "SELECT * FROM recurring_events"
    params: List[object] = []
    if owner is not None:
        sql += " WHERE owner = ?"
        params.append(owner)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_recurring_event_from_row(r) for r in rows]


def get_recurring_event_by_prefix(
    rec_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    sql = "SELECT * FROM recurring_events WHERE id LIKE ? || '%'"
    params: List[object] = [rec_id_prefix]
    if owner is not None:
        sql += " AND owner = ?"
        params.append(owner)
    with get_conn() as conn:
        row = conn.execute(sql + " LIMIT 1", params).fetchone()
        return _recurring_event_from_row(row) if row else None


def update_recurring_event_title(
    rec_id_prefix: str, new_title: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    rec = get_recurring_event_by_prefix(rec_id_prefix, owner)
    if not rec:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE recurring_events SET title = ? WHERE id = ?",
            (new_title, rec["id"]),
        )
        conn.execute(
            "UPDATE search_index SET content = ? WHERE id = ? AND type = 'event'",
            (new_title, rec["id"]),
        )
    rec["title"] = new_title
    return rec


def update_recurring_event_rule(
    rec_id_prefix: str, new_rrule: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    rec = get_recurring_event_by_prefix(rec_id_prefix, owner)
    if not rec:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE recurring_events SET rrule = ? WHERE id = ?",
            (new_rrule, rec["id"]),
        )
    rec["rrule"] = new_rrule
    return rec


def delete_recurring_event(
    rec_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    rec = get_recurring_event_by_prefix(rec_id_prefix, owner)
    if not rec:
        return None
    with get_conn() as conn:
        conn.execute("DELETE FROM recurring_events WHERE id = ?", (rec["id"],))
        conn.execute(
            "DELETE FROM search_index WHERE id = ? AND type = 'event'",
            (rec["id"],),
        )
    return rec


def list_events_on(
    day: str, owner: Optional[int] = None
) -> List[Dict[str, object]]:
    start = datetime.fromisoformat(day + "T00:00:00")
    end = start + timedelta(days=1)
    events = [
        e
        for e in list_events(owner)
        if e.get("start", "").startswith(day)
    ]
    for rec in list_recurring_events(owner):
        rule = rrulestr(rec["rrule"])
        for dt in rule.between(start, end, inc=False):
            events.append(
                {
                    "id": rec["id"],
                    "title": rec["title"],
                    "start": dt.isoformat(),
                    "duration_min": rec["duration_min"],
                    "owner": rec["owner"],
                    "created_at": rec["created_at"],
                    "recurring": True,
                }
            )
    events.sort(key=lambda e: e["start"])
    return events


# -----------------------------------------------------------------------------
# Reminders
# -----------------------------------------------------------------------------


def add_reminder(
    text: str,
    at_iso: str,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    rem_id = str(uuid4())
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (id, text, at, owner, created_at) VALUES (?,?,?,?,?)",
            (rem_id, text, at_iso, owner, created_at),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (rem_id, "reminder", text, owner),
        )
    return {
        "id": rem_id,
        "text": text,
        "at": at_iso,
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
    new_at = (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
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


# -----------------------------------------------------------------------------
# Reminders
# -----------------------------------------------------------------------------


def add_reminder(
    text: str,
    at_iso: str,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    rem_id = str(uuid4())
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (id, text, at, owner, created_at) VALUES (?,?,?,?,?)",
            (rem_id, text, at_iso, owner, created_at),
        )
        conn.execute(
            "INSERT INTO search_index (id, type, content, owner) VALUES (?,?,?,?)",
            (rem_id, "reminder", text, owner),
        )
    return {
        "id": rem_id,
        "text": text,
        "at": at_iso,
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
    new_at = (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
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

