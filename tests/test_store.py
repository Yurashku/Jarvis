import store
from datetime import datetime, timedelta


def setup_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "TASKS_PATH", tmp_path / "tasks.json")
    monkeypatch.setattr(store, "EVENTS_PATH", tmp_path / "events.json")
    monkeypatch.setattr(store, "REMINDERS_PATH", tmp_path / "reminders.json")


def test_tasks_flow(tmp_path, monkeypatch):
    setup_store(tmp_path, monkeypatch)
    t = store.add_task("test", None, owner=1)
    assert store.list_tasks(owner=1) == [t]
    assert store.complete_task(t["id"][:8], owner=1)
    assert store.list_tasks(owner=1)[0]["done"] is True


def test_events_and_reminders(tmp_path, monkeypatch):
    setup_store(tmp_path, monkeypatch)
    start = datetime.now().replace(microsecond=0).isoformat()
    ev = store.add_event("meet", start, 30, owner=1)
    assert store.snooze_event(ev["id"][:8], 10, owner=1)["start"]
    deleted = store.delete_event(ev["id"][:8], owner=1)
    assert deleted and deleted["id"] == ev["id"]
    at = (datetime.now() + timedelta(minutes=5)).replace(microsecond=0).isoformat()
    rem = store.add_reminder("call", at, owner=1)
    assert store.list_reminders(owner=1) == [rem]
    assert store.snooze_reminder(rem["id"][:8], 5, owner=1)["at"]
    deleted_rem = store.delete_reminder(rem["id"][:8], owner=1)
    assert deleted_rem and deleted_rem["id"] == rem["id"]
