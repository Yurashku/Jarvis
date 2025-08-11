import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from uuid import uuid4

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
TASKS_PATH = DATA_DIR / "tasks.json"
EVENTS_PATH = DATA_DIR / "events.json"

def _load(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _save(path: Path, data: List[Dict]):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- Tasks ----------
def add_task(text: str, due_iso: str | None = None) -> Dict:
    tasks = _load(TASKS_PATH)
    item = {
        "id": str(uuid4()),
        "text": text,
        "due": due_iso,
        "done": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    tasks.append(item)
    _save(TASKS_PATH, tasks)
    return item

def list_tasks() -> List[Dict]:
    return _load(TASKS_PATH)

def complete_task(task_id: str) -> bool:
    tasks = _load(TASKS_PATH)
    ok = False
    for t in tasks:
        if t["id"].startswith(task_id):
            t["done"] = True
            ok = True
            break
    if ok:
        _save(TASKS_PATH, tasks)
    return ok

# ---------- Events ----------
def add_event(title: str, start_iso: str, duration_min: int = 60) -> Dict:
    events = _load(EVENTS_PATH)
    item = {
        "id": str(uuid4()),
        "title": title,
        "start": start_iso,     # ISO 8601, напр. 2025-08-12T15:00
        "duration_min": duration_min,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    events.append(item)
    _save(EVENTS_PATH, events)
    return item

def list_events() -> List[Dict]:
    return _load(EVENTS_PATH)
