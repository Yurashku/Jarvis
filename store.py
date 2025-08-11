import json
import os
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from uuid import uuid4

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
TASKS_PATH = DATA_DIR / "tasks.json"
EVENTS_PATH = DATA_DIR / "events.json"

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
            # Если не удалось переименовать — лишь логически продолжим
            pass
        # Создаём новый пустой
        with path.open("w", encoding="utf-8") as f:
            f.write("[]")
        return []

def _atomic_save_json(path: Path, data: List[Dict]):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    # Замена атомарна на большинстве ФС Windows/NTFS
    tmp.replace(path)

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
