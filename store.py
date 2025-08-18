import json
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from uuid import uuid4

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
TASKS_PATH = DATA_DIR / "tasks.json"
EVENTS_PATH = DATA_DIR / "events.json"
REMINDERS_PATH = DATA_DIR / "reminders.json"

def _safe_load_json(path: Path) -> List[Dict]:
    # Пустой файл — это ок
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        # Бэкапим битый файл и начинаем с чистого листа
        backup = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}.bak")
        try:
            path.replace(backup)
        except Exception:
            pass
        with path.open("w", encoding="utf-8") as f:
            f.write("[]")
        return []

def _atomic_save_json(path: Path, data: List[Dict]):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)  # атомарная замена на NTFS

def _load(path: Path) -> List[Dict]:
    return _safe_load_json(path)

def _save(path: Path, data: List[Dict]):
    _atomic_save_json(path, data)

# ---------- Tasks ----------
def add_task(text: str, due_iso: Optional[str] = None, owner: Optional[int] = None) -> Dict:
    tasks = _load(TASKS_PATH)
    item = {
        "id": str(uuid4()),
        "text": text,
        "due": due_iso,  # ISO 8601 или None
        "done": False,
        "owner": owner,  # chat_id телеграма или None для CLI
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    tasks.append(item)
    _save(TASKS_PATH, tasks)
    return item

def list_tasks(owner: Optional[int] = None) -> List[Dict]:
    tasks = _load(TASKS_PATH)
    if owner is None:
        return tasks
    return [t for t in tasks if t.get("owner") == owner]

def complete_task(task_id_prefix: str, owner: Optional[int] = None) -> bool:
    tasks = _load(TASKS_PATH)
    ok = False
    for t in tasks:
        if t["id"].startswith(task_id_prefix) and (owner is None or t.get("owner") == owner):
            t["done"] = True
            ok = True
            break
    if ok:
        _save(TASKS_PATH, tasks)
    return ok

def get_task_by_prefix(task_id_prefix: str, owner: Optional[int] = None) -> Optional[Dict]:
    tasks = _load(TASKS_PATH)
    for t in tasks:
        if t["id"].startswith(task_id_prefix) and (owner is None or t.get("owner") == owner):
            return t
    return None

def snooze_task(task_id_prefix: str, minutes: int, owner: Optional[int] = None) -> Optional[Dict]:
    tasks = _load(TASKS_PATH)
    for t in tasks:
        if t["id"].startswith(task_id_prefix) and (owner is None or t.get("owner") == owner):
            base = datetime.fromisoformat(t["due"]) if t.get("due") else datetime.now()
            new_due = (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
            t["due"] = new_due
            _save(TASKS_PATH, tasks)
            return t
    return None

# ---------- Events ----------
def add_event(title: str, start_iso: str, duration_min: int = 60, owner: Optional[int] = None) -> Dict:
    events = _load(EVENTS_PATH)
    item = {
        "id": str(uuid4()),
        "title": title,
        "start": start_iso,     # ISO 8601
        "duration_min": duration_min,
        "owner": owner,         # chat_id
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    events.append(item)
    _save(EVENTS_PATH, events)
    return item

def list_events(owner: Optional[int] = None) -> List[Dict]:
    events = _load(EVENTS_PATH)
    if owner is None:
        return events
    return [e for e in events if e.get("owner") == owner]

def get_event_by_prefix(event_id_prefix: str, owner: Optional[int] = None) -> Optional[Dict]:
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (owner is None or e.get("owner") == owner):
            return e
    return None

def update_event_title(event_id_prefix: str, new_title: str, owner: Optional[int] = None) -> Optional[Dict]:
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (owner is None or e.get("owner") == owner):
            e["title"] = new_title
            _save(EVENTS_PATH, events)
            return e
    return None

def update_event_time(event_id_prefix: str, new_start_iso: str, owner: Optional[int] = None) -> Optional[Dict]:
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (owner is None or e.get("owner") == owner):
            e["start"] = new_start_iso
            _save(EVENTS_PATH, events)
            return e
    return None

def update_event_duration(event_id_prefix: str, new_duration_min: int, owner: Optional[int] = None) -> Optional[Dict]:
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (owner is None or e.get("owner") == owner):
            e["duration_min"] = int(new_duration_min)
            _save(EVENTS_PATH, events)
            return e
    return None

def snooze_event(event_id_prefix: str, minutes: int, owner: Optional[int] = None) -> Optional[Dict]:
    events = _load(EVENTS_PATH)
    for e in events:
        if e["id"].startswith(event_id_prefix) and (owner is None or e.get("owner") == owner):
            base = datetime.fromisoformat(e["start"])
            new_start = (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
            e["start"] = new_start
            _save(EVENTS_PATH, events)
            return e
    return None

def delete_event(event_id_prefix: str, owner: Optional[int] = None) -> Optional[Dict]:
    events = _load(EVENTS_PATH)
    deleted = None
    left = []
    for e in events:
        if not deleted and e["id"].startswith(event_id_prefix) and (owner is None or e.get("owner") == owner):
            deleted = e
            continue
        left.append(e)
    if deleted is not None:
        _save(EVENTS_PATH, left)
    return deleted

# ---------- Reminders ----------
def add_reminder(text: str, at_iso: str, owner: Optional[int] = None) -> Dict:
    reminders = _load(REMINDERS_PATH)
    item = {
        "id": str(uuid4()),
        "text": text,
        "at": at_iso,   # ISO 8601
        "owner": owner,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    reminders.append(item)
    _save(REMINDERS_PATH, reminders)
    return item

def list_reminders(owner: Optional[int] = None) -> List[Dict]:
    reminders = _load(REMINDERS_PATH)
    if owner is None:
        return reminders
    return [r for r in reminders if r.get("owner") == owner]

def get_reminder_by_prefix(rem_id_prefix: str, owner: Optional[int] = None) -> Optional[Dict]:
    reminders = _load(REMINDERS_PATH)
    for r in reminders:
        if r["id"].startswith(rem_id_prefix) and (owner is None or r.get("owner") == owner):
            return r
    return None

def snooze_reminder(rem_id_prefix: str, minutes: int, owner: Optional[int] = None) -> Optional[Dict]:
    reminders = _load(REMINDERS_PATH)
    for r in reminders:
        if r["id"].startswith(rem_id_prefix) and (owner is None or r.get("owner") == owner):
            base = datetime.fromisoformat(r["at"])
            new_at = (base + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
            r["at"] = new_at
            _save(REMINDERS_PATH, reminders)
            return r
    return None

def delete_reminder(rem_id_prefix: str, owner: Optional[int] = None) -> Optional[Dict]:
    reminders = _load(REMINDERS_PATH)
    deleted = None
    left = []
    for r in reminders:
        if not deleted and r["id"].startswith(rem_id_prefix) and (owner is None or r.get("owner") == owner):
            deleted = r
            continue
        left.append(r)
    if deleted is not None:
        _save(REMINDERS_PATH, left)
    return deleted
