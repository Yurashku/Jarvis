import db
import store
from datetime import datetime, timedelta
from dateutil.rrule import rrule, WEEKLY, MO


def setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_tasks_flow(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    t = store.add_task("test", None, owner=1)
    tasks = store.list_tasks(owner=1)
    assert tasks == [t]
    assert store.complete_task(t["id"][:8], owner=1)
    assert store.list_tasks(owner=1)[0]["done"] is True


def test_events_and_reminders(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
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


def test_recurring_events(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    now = datetime.now().replace(second=0, microsecond=0)
    # Next Monday 10:00
    days_ahead = (0 - now.weekday()) % 7
    dt = now + timedelta(days=days_ahead)
    dt = dt.replace(hour=10, minute=0)
    rule = rrule(WEEKLY, dtstart=dt, byweekday=MO)
    rec = store.add_recurring_event("standup", str(rule), 15, owner=1)
    day = dt.date().isoformat()
    events = store.list_events_on(day, owner=1)
    assert any(e.get("recurring") and e["title"] == "standup" for e in events)
    deleted = store.delete_recurring_event(rec["id"][:8], owner=1)
    assert deleted and deleted["id"] == rec["id"]
    events = store.list_events_on(day, owner=1)
    assert all(e["id"] != rec["id"] for e in events)
