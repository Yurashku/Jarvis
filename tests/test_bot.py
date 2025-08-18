import types
from pathlib import Path
import importlib
import pytest
import store


class DummyMessage:
    def __init__(self, text="", chat_id=1):
        self.text = text
        self.chat = types.SimpleNamespace(id=chat_id)
        self.message_id = 1
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.fixture
def bot_module(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:ABC")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("STT_PROVIDER", "openai")
    import bot
    importlib.reload(bot)
    return bot


@pytest.mark.anyio
async def test_process_free_text_add_task(bot_module, monkeypatch):
    msg = DummyMessage("add task")
    fake_item = {"id": "12345678", "text": "milk", "due": None}
    monkeypatch.setattr(bot_module.llm, "ask_json", lambda sys, txt: {"intent": "add_task", "payload": {"text": "milk", "due": None}})
    monkeypatch.setattr(store, "add_task", lambda text, due, owner: fake_item)
    monkeypatch.setattr(bot_module, "schedule_task_if_due", lambda t: None)
    monkeypatch.setattr(bot_module, "task_keyboard", lambda _: None)
    monkeypatch.setattr(bot_module, "_human", lambda x: x)
    await bot_module.process_free_text(msg, msg.text)
    assert msg.answers[0][0].startswith("✅ Добавил")


@pytest.mark.anyio
async def test_handle_voice_uses_stt(bot_module, monkeypatch, tmp_path):
    msg = DummyMessage(chat_id=2)
    msg.voice = types.SimpleNamespace(file_id="f")
    async def fake_download(file_id, destination):
        Path(destination).write_bytes(b"data")
    monkeypatch.setattr(bot_module.bot, "download", fake_download)
    monkeypatch.setattr(bot_module.stt, "provider_in_use", lambda: "openai")
    monkeypatch.setattr(bot_module.stt, "transcribe", lambda path, lang="ru": "text from voice")
    called = []
    async def fake_process(message, text):
        called.append(text)
    monkeypatch.setattr(bot_module, "process_free_text", fake_process)
    monkeypatch.setattr(bot_module, "Path", lambda p: Path(tmp_path / p))
    await bot_module.handle_voice(msg)
    assert called == ["text from voice"]
