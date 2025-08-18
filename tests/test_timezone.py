import time
from datetime import datetime
from zoneinfo import ZoneInfo

import importlib

import db
import store


def setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jarvis.db")
    db.init_db()


def test_store_converts_to_utc(tmp_path, monkeypatch):
    setup_db(tmp_path, monkeypatch)
    local_due = datetime(2024, 1, 1, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    task = store.add_task("tz", local_due.isoformat(), owner=1)
    assert task["due"] == local_due.astimezone(ZoneInfo("UTC")).isoformat()
    assert task["created_at"].endswith("+00:00")


def test_human_respects_timezone(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    cli = importlib.reload(importlib.import_module("cli"))
    dt = datetime(2024, 1, 1, 12, tzinfo=ZoneInfo("UTC")).isoformat()
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    assert "12:00" in cli._human(dt)
    monkeypatch.setenv("TZ", "Europe/Moscow")
    time.tzset()
    assert "15:00" in cli._human(dt)
