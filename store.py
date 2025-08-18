"""
store.py
~~~~~~~~

This module provides a simple persistence layer backed by JSON files.  It
supports tasks, events and one-off reminders, along with helper
functions for completing, snoozing and editing entries.  Each record
includes an optional ``owner`` field to support multi-user scenarios (the
owner being the Telegram chat ID).  Files are written atomically and
loaded defensively to avoid data corruption.

The functions in this module are intentionally minimal and
synchronous; concurrency concerns are handled at a higher level.

Data model summary:

* Task: {id, text, due, done, owner, created_at}
* Event: {id, title, start, duration_min, owner, created_at}
* Reminder: {id, text, at, owner, created_at}

If ``owner`` is ``None``, the record is considered global (used by CLI).

"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

TASKS_PATH = DATA_DIR / "tasks.json"
EVENTS_PATH = DATA_DIR / "events.json"
REMINDERS_PATH = DATA_DIR / "reminders.json"


def _safe_load_json(path: Path) -> List[Dict[str, object]]:
    """Load JSON from a file, returning an empty list on missing/empty files."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # Backup corrupt file and start fresh
        backup = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}.bak")
        try:
            path.replace(backup)
        except Exception:
            # If we can't rename, ignore
            pass
        with path.open("w", encoding="utf-8") as f:
            f.write("[]")
        return []


def _atomic_save_json(path: Path, data: List[Dict[str, object]]) -> None:
    """Write JSON to a file atomically to avoid partial writes."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _load(path: Path) -> List[Dict[str, object]]:
    return _safe_load_json(path)


def _save(path: Path, data: List[Dict[str, object]]) -> None:
    _atomic_save_json(path, data)


# -----------------------------------------------------------------------------
# Tasks
# -----------------------------------------------------------------------------

def add_task(
    text: str,
    due_iso: Optional[str] = None,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    """Create a new task.

    :param text: description of the task
    :param due_iso: ISO datetime string when the task should be completed
    :param owner: optional user identifier; used by Telegram bot
    """
    tasks = _load(TASKS_PATH)
    item = {
        "id": str(uuid4()),
        "text": text,
        "due": due_iso,
        "done": False,
        "owner": owner,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    tasks.append(item)
    _save(TASKS_PATH, tasks)
    return item


def list_tasks(owner: Optional[int] = None) -> List[Dict[str, object]]:
    """Return all tasks for the specified owner (or all if owner is None)."""
    tasks = _load(TASKS_PATH)
    if owner is None:
        return tasks
    return [t for t in tasks if t.get("owner") == owner]


def complete_task(task_id_prefix: str, owner: Optional[int] = None) -> bool:
    """Mark a task as done using a prefix of its UUID.

    Returns True if a task was found and updated; False otherwise.
    """
    tasks = _load(TASKS_PATH)
    updated = False
    for t in tasks:
        if t["id"].startswith(task_id_prefix) and (
            owner is None or t.get("owner") == owner
        ):
            t["done"] = True
            updated = True
            break
    if updated:
        _save(TASKS_PATH, tasks)
    return updated


def get_task_by_prefix(task_id_prefix: str, owner: Optional[int] = None) -> Optional[Dict[str, object]]:
    """Find a task by ID prefix."""
    tasks = _load(TASKS_PATH)
    for t in tasks:
        if t["id"].startswith(task_id_prefix) and (
            owner is None or t.get("owner") == owner
        ):
            return t
    return None


def snooze_task(
    task_id_prefix: str, minutes: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Delay a task's deadline by a number of minutes."""
    tasks = _load(TASKS_PATH)
    for t in tasks:
        if t["id"].startswith(task_id_prefix) and (
            owner is None or t.get("owner") == owner
        ):
            base = (
                datetime.fromisoformat(t["due"])
                if t.get("due")
                else datetime.now()
            )
            new_due = (
                base + timedelta(minutes=minutes)
            ).replace(microsecond=0).isoformat()
            t["due"] = new_due
            _save(TASKS_PATH, tasks)
            return t
    return None


# -----------------------------------------------------------------------------
# Events
# -----------------------------------------------------------------------------

def add_event(
    title: str,
    start_iso: str,
    duration_min: int = 60,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    """Create a new event."""
    events = _load(EVENTS_PATH)
    item = {
        "id": str(uuid4()),
        "title": title,
        "start": start_iso,
        "duration_min": int(duration_min),
        "owner": owner,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    events.append(item)
    _save(EVENTS_PATH, events)
    return item


def list_events(owner: Optional[int] = None) -> List[Dict[str, object]]:
    """Return all events for a given owner."""
    events = _load(EVENTS_PATH)
    if owner is None:
        return events
    return [e for e in events if e.get("owner") == owner]


def get_event_by_prefix(
    event_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Find an event by ID prefix."""
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (
            owner is None or e.get("owner") == owner
        ):
            return e
    return None


def update_event_title(
    event_id_prefix: str, new_title: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Rename an event."""
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (
            owner is None or e.get("owner") == owner
        ):
            e["title"] = new_title
            _save(EVENTS_PATH, events)
            return e
    return None


def update_event_time(
    event_id_prefix: str, new_start_iso: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Move an event to a new start time."""
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (
            owner is None or e.get("owner") == owner
        ):
            e["start"] = new_start_iso
            _save(EVENTS_PATH, events)
            return e
    return None


def update_event_duration(
    event_id_prefix: str, new_duration_min: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Change the duration of an event."""
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (
            owner is None or e.get("owner") == owner
        ):
            e["duration_min"] = int(new_duration_min)
            _save(EVENTS_PATH, events)
            return e
    return None


def snooze_event(
    event_id_prefix: str, minutes: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Delay an event's start time by a number of minutes."""
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (
            owner is None or e.get("owner") == owner
        ):
            base = datetime.fromisoformat(e["start"])
            new_start = (
                base + timedelta(minutes=minutes)
            ).replace(microsecond=0).isoformat()
            e["start"] = new_start
            _save(EVENTS_PATH, events)
            return e
    return None


def delete_event(
    event_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Remove an event from the store and return it."""
    events = _load(EVENTS_PATH)
    removed: Optional[Dict[str, object]] = None
    remaining: List[Dict[str, object]] = []
    for e in events:
        if removed is None and e["id"].startswith(event_id_prefix) and (
            owner is None or e.get("owner") == owner
        ):
            removed = e
            continue
        remaining.append(e)
    if removed is not None:
        _save(EVENTS_PATH, remaining)
    return removed


# -----------------------------------------------------------------------------
# Reminders
# -----------------------------------------------------------------------------

def add_reminder(
    text: str,
    at_iso: str,
    owner: Optional[int] = None,
) -> Dict[str, object]:
    """Create a one-off reminder."""
    reminders = _load(REMINDERS_PATH)
    item = {
        "id": str(uuid4()),
        "text": text,
        "at": at_iso,
        "owner": owner,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    reminders.append(item)
    _save(REMINDERS_PATH, reminders)
    return item


def list_reminders(owner: Optional[int] = None) -> List[Dict[str, object]]:
    """Return all reminders for a given owner."""
    reminders = _load(REMINDERS_PATH)
    if owner is None:
        return reminders
    return [r for r in reminders if r.get("owner") == owner]


def get_reminder_by_prefix(
    rem_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Find a reminder by ID prefix."""
    reminders = _load(REMINDERS_PATH)
    for r in reminders:
        if r["id"].startswith(rem_id_prefix) and (
            owner is None or r.get("owner") == owner
        ):
            return r
    return None


def snooze_reminder(
    rem_id_prefix: str, minutes: int, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Delay a reminder by a number of minutes."""
    reminders = _load(REMINDERS_PATH)
    for r in reminders:
        if r["id"].startswith(rem_id_prefix) and (
            owner is None or r.get("owner") == owner
        ):
            base = datetime.fromisoformat(r["at"])
            new_at = (
                base + timedelta(minutes=minutes)
            ).replace(microsecond=0).isoformat()
            r["at"] = new_at
            _save(REMINDERS_PATH, reminders)
            return r
    return None


def delete_reminder(
    rem_id_prefix: str, owner: Optional[int] = None
) -> Optional[Dict[str, object]]:
    """Remove a reminder from the store and return it."""
    reminders = _load(REMINDERS_PATH)
    removed: Optional[Dict[str, object]] = None
    remaining: List[Dict[str, object]] = []
    for r in reminders:
        if removed is None and r["id"].startswith(rem_id_prefix) and (
            owner is None or r.get("owner") == owner
        ):
            removed = r
            continue
        remaining.append(r)
    if removed is not None:
        _save(REMINDERS_PATH, remaining)
    return removed