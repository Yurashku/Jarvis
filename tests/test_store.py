import store
import db
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def setup_store(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jarvis.db")
    db.init_db()


def test_tasks_flow(tmp_path, monkeypatch):
    setup_store(tmp_path, monkeypatch)
    t = store.add_task("test", None, owner=1)
    assert store.list_tasks(owner=1) == [t]
    assert store.complete_task(t["id"][:8], owner=1)
    assert store.list_tasks(owner=1)[0]["done"] is True


def test_events_and_reminders(tmp_path, monkeypatch):
    setup_store(tmp_path, monkeypatch)
    start = datetime.now(tz=ZoneInfo("UTC")).replace(microsecond=0).isoformat()
    ev = store.add_event("meet", start, 30, owner=1)
    assert store.snooze_event(ev["id"][:8], 10, owner=1)["start"]
    deleted = store.delete_event(ev["id"][:8], owner=1)
    assert deleted and deleted["id"] == ev["id"]
    at = (
        datetime.now(tz=ZoneInfo("UTC")) + timedelta(minutes=5)
    ).replace(microsecond=0).isoformat()
    rem = store.add_reminder("call", at, owner=1)
    assert store.list_reminders(owner=1) == [rem]
    assert store.snooze_reminder(rem["id"][:8], 5, owner=1)["at"]
    deleted_rem = store.delete_reminder(rem["id"][:8], owner=1)
    assert deleted_rem and deleted_rem["id"] == rem["id"]
