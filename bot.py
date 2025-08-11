import os
import re
import asyncio
from datetime import datetime, timedelta
from string import Template

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command, CommandObject
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import store
from llm_provider import LLM

load_dotenv()
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()
llm = LLM()
scheduler = AsyncIOScheduler()  # naive datetime трактуется как локальное время

SYSTEM_PROMPT_TPL = """Ты помощник по расписанию и задачам.
Твоя задача — преобразовать фразу пользователя в JSON-команду со строгой схемой:

{
  "intent": "add_task" | "list_tasks" | "complete_task" | "add_event" | "agenda" | "help",
  "payload": { ... }
}

Правила:
- Даты и время всегда в ISO 8601 (локаль пользователя, сейчас: $now_iso).
- Если говорится «завтра/послезавтра/сегодня в 15:00», рассчитай конкретный ISO.
- Для add_task: payload = {"text": str, "due": str | null}
- Для complete_task: payload = {"id": str}  # можно принимать префикс UUID
- Для add_event: payload = {"title": str, "start": str, "duration_min": int}
- Для agenda: payload = {"day": "today" | "tomorrow" | "YYYY-MM-DD"}
- Для list_tasks, help: payload = {}

Примеры:
"Добавь задачу купить молоко завтра в 18:00" ->
{"intent":"add_task","payload":{"text":"купить молоко","due":"$tomorrow_1800"}}

"Создай событие 'Звонок с Петром' послезавтра в 09:30 на 30 минут" ->
{"intent":"add_event","payload":{"title":"Звонок с Петром","start":"$after_tomorrow_0930","duration_min":30}}

"Покажи мои задачи" -> {"intent":"list_tasks","payload":{}}
"Покажи повестку на сегодня" -> {"intent":"agenda","payload":{"day":"today"}}
"""

# ---------- helpers ----------

def _human(dt_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_iso)
    except Exception:
        return dt_iso
    now = datetime.now()
    delta = (dt - now).total_seconds()
    if delta > 0:
        mins = int(delta // 60)
        return f"{dt_iso} (через {mins} мин)"
    return dt_iso

async def send_task_reminder(chat_id: int, text: str, short_id: str):
    await bot.send_message(chat_id, f"⏰ Напоминание: {text} (id {short_id})")

async def send_event_reminder(chat_id: int, title: str, start_iso: str, short_id: str):
    when = datetime.fromisoformat(start_iso).strftime("%Y-%m-%d %H:%M")
    await bot.send_message(chat_id, f"📅 Начинается событие: {title} @ {when} (id {short_id})")

def schedule_task_if_due(task: dict):
    due = task.get("due")
    owner = task.get("owner")
    if not due or not owner or task.get("done"):
        return
    try:
        dt = datetime.fromisoformat(due)
    except Exception:
        return
    if dt <= datetime.now():
        return
    scheduler.add_job(
        send_task_reminder, "date", run_date=dt,
        args=[owner, task["text"], task["id"][:8]]
    )

def schedule_event_if_due(ev: dict):
    start = ev.get("start")
    owner = ev.get("owner")
    if not start or not owner:
        return
    try:
        dt = datetime.fromisoformat(start)
    except Exception:
        return
    if dt <= datetime.now():
        return
    scheduler.add_job(
        send_event_reminder, "date", run_date=dt,
        args=[owner, ev["title"], ev["start"], ev["id"][:8]]
    )

def rehydrate_all_jobs():
    # На старте восстанавливаем напоминания
    for t in store.list_tasks():
        schedule_task_if_due(t)
    for e in store.list_events():
        schedule_event_if_due(e)

# ---------- command handlers ----------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я Jarvis в Telegram. Пиши:\n"
        "— /task ТЕКСТ due:YYYY-MM-DDTHH:MM\n"
        "— /event \"Название\" YYYY-MM-DDTHH:MM ДЛИТ_МИН\n"
        "— /done ID_PREFIX\n"
        "— /list\n"
        "— /agenda today|tomorrow|YYYY-MM-DD\n"
        "Или просто по-русски: «Добавь задачу …», «Создай событие …»."
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Команды:\n"
        "/task ТЕКСТ due:YYYY-MM-DDTHH:MM\n"
        "/event \"Название\" YYYY-MM-DDTHH:MM ДЛИТ_МИН\n"
        "/done ID_PREFIX\n"
        "/list\n"
        "/agenda today|tomorrow|YYYY-MM-DD"
    )

@dp.message(Command("task"))
async def cmd_task(message: Message, command: CommandObject):
    # формат: /task ТЕКСТ due:YYYY-MM-DDTHH:MM
    text = command.args or ""
    m = re.match(r'(.+?)(?:\s+due:([0-9T:\-]+))?$', text)
    if not m:
        await message.answer("Формат: /task ТЕКСТ due:YYYY-MM-DDTHH:MM")
        return
    item = store.add_task(m.group(1).strip(), m.group(2), owner=message.chat.id)
    schedule_task_if_due(item)
    await message.answer(f"✅ Добавил задачу: {item['text']} [id {item['id'][:8]}]{' (срок: ' + _human(item['due']) + ')' if item['due'] else ''}")

@dp.message(Command("event"))
async def cmd_event(message: Message, command: CommandObject):
    # формат: /event "Название" YYYY-MM-DDTHH:MM ДЛИТ_МИН
    args = command.args or ""
    m = re.match(r'^"(.+?)"\s+([0-9T:\-]+)\s+(\d+)$', args)
    if not m:
        await message.answer('Формат: /event "Название" YYYY-MM-DDTHH:MM ДЛИТ_МИН')
        return
    ev = store.add_event(m.group(1), m.group(2), int(m.group(3)), owner=message.chat.id)
    schedule_event_if_due(ev)
    await message.answer(f"📌 Создал событие: {ev['title']} @ {ev['start']} ({ev['duration_min']} мин) [id {ev['id'][:8]}]")

@dp.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Формат: /done ID_PREFIX")
        return
    ok = store.complete_task(command.args.strip(), owner=message.chat.id)
    await message.answer("Готово ✅" if ok else "Не найдено ❌")

@dp.message(Command("list"))
async def cmd_list(message: Message):
    tasks = store.list_tasks(owner=message.chat.id)
    if not tasks:
        await message.answer("Задач нет.")
        return
    lines = []
    for t in tasks:
        done = "✅" if t["done"] else "🔹"
        due = f" (срок: { _human(t['due']) })" if t["due"] else ""
        lines.append(f"{done} [{t['id'][:8]}] {t['text']}{due}")
    await message.answer("\n".join(lines))

@dp.message(Command("agenda"))
async def cmd_agenda(message: Message, command: CommandObject):
    arg = (command.args or "").strip().lower() or "today"
    if arg == "today":
        date_str = datetime.now().date().isoformat()
    elif arg == "tomorrow":
        date_str = (datetime.now() + timedelta(days=1)).date().isoformat()
    else:
        date_str = arg  # предполагаем YYYY-MM-DD
    events = [e for e in store.list_events(owner=message.chat.id) if e["start"].startswith(date_str)]
    if not events:
        await message.answer(f"Событий на {date_str} нет.")
        return
    lines = [f"📅 [{e['id'][:8]}] {e['title']} @ {e['start']} ({e['duration_min']} мин)" for e in events]
    await message.answer("\n".join(lines))

# ---------- fallback: свободный текст через LLM ----------

@dp.message(F.text)
async def handle_free_text(message: Message):
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    tpl = Template(SYSTEM_PROMPT_TPL)
    sys_prompt = tpl.substitute(
        now_iso=now_iso,
        tomorrow_1800=(datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
                       + timedelta(days=1)).isoformat(),
        after_tomorrow_0930=(datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
                             + timedelta(days=2)).isoformat()
    )
    try:
        cmd = llm.ask_json(sys_prompt, message.text)
    except Exception as e:
        await message.answer(f"Не смог распарсить запрос: {e}\nПопробуй /help")
        return

    intent = cmd.get("intent")
    payload = cmd.get("payload", {})

    try:
        if intent == "add_task":
            item = store.add_task(payload["text"], payload.get("due"), owner=message.chat.id)
            schedule_task_if_due(item)
            await message.answer(f"✅ Добавил задачу: {item['text']} [id {item['id'][:8]}]{' (срок: ' + _human(item['due']) + ')' if item['due'] else ''}")
        elif intent == "list_tasks":
            await cmd_list(message)
        elif intent == "complete_task":
            ok = store.complete_task(payload["id"], owner=message.chat.id)
            await message.answer("Готово ✅" if ok else "Не найдено ❌")
        elif intent == "add_event":
            ev = store.add_event(payload["title"], payload["start"], int(payload.get("duration_min", 60)), owner=message.chat.id)
            schedule_event_if_due(ev)
            await message.answer(f"📌 Создал событие: {ev['title']} @ {ev['start']} ({ev['duration_min']} мин) [id {ev['id'][:8]}]")
        elif intent == "agenda":
            day = payload.get("day", "today")
            await cmd_agenda(message, CommandObject(args=day))
        else:
            await cmd_help(message)
    except Exception as e:
        await message.answer(f"Ошибка выполнения: {e}")

async def main():
    scheduler.start()
    rehydrate_all_jobs()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
