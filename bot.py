import os
import re
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from string import Template

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command, CommandObject
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import store
from llm_provider import LLM
from stt import STT

load_dotenv()
bot = Bot(token=os.getenv("TELEGRAM_TOKEN"))
dp = Dispatcher()
llm = LLM()
stt = STT()
scheduler = AsyncIOScheduler()  # naive datetime трактуется как локальное время

SYSTEM_PROMPT_TPL = """Ты помощник по расписанию и задачам.
Твоя задача — преобразовать фразу пользователя в JSON-команду со строгой схемой:

{
  "intent": "add_task" | "list_tasks" | "complete_task" | "add_event" | "agenda" | "help" | "remind",
  "payload": { ... }
}

Правила:
- Даты и время всегда в ISO 8601 (локаль пользователя, сейчас: $now_iso).
- Если говорится «завтра/послезавтра/сегодня в 15:00», рассчитай конкретный ISO.
- Для add_task: payload = {"text": str, "due": str | null}
- Для complete_task: payload = {"id": str}  # можно принимать префикс UUID
- Для add_event: payload = {"title": str, "start": str, "duration_min": int}
- Для agenda: payload = {"day": "today" | "tomorrow" | "YYYY-MM-DD"}
- Для remind: payload = {"text": str, "at": str}
- Для list_tasks, help: payload = {}

Примеры:
"Добавь задачу купить молоко завтра в 18:00" ->
{"intent":"add_task","payload":{"text":"купить молоко","due":"$tomorrow_1800"}}

"Создай событие 'Звонок с Петром' послезавтра в 09:30 на 30 минут" ->
{"intent":"add_event","payload":{"title":"Звонок с Петром","start":"$after_tomorrow_0930","duration_min":30}}

"Напомни позвонить маме завтра в 09:00" ->
{"intent":"remind","payload":{"text":"позвонить маме","at":"$tomorrow_0900"}}

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
    delta = dt - now
    mins = int(delta.total_seconds() // 60)
    if 0 <= mins < 24*60:
        day = "сегодня" if dt.date() == now.date() else "завтра" if dt.date() == (now.date() + timedelta(days=1)) else dt.date().isoformat()
        return f"{day} {dt.strftime('%H:%M')}"
    return dt.strftime("%Y-%m-%d %H:%M")

def task_keyboard(id8: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Готово ✅", callback_data=f"t:done:{id8}"),
        InlineKeyboardButton(text="Отложить 10 мин", callback_data=f"t:snooze10:{id8}"),
    ], [
        InlineKeyboardButton(text="Отложить 1 час", callback_data=f"t:snooze60:{id8}"),
    ]])

def event_keyboard(id8: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Сдвинуть +10 мин", callback_data=f"e:snooze10:{id8}"),
        InlineKeyboardButton(text="Сдвинуть +60 мин", callback_data=f"e:snooze60:{id8}"),
    ], [
        InlineKeyboardButton(text="Удалить ❌", callback_data=f"e:del:{id8}"),
    ]])

def reminder_keyboard(id8: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отложить 10 мин", callback_data=f"r:snooze10:{id8}"),
        InlineKeyboardButton(text="Отложить 1 час", callback_data=f"r:snooze60:{id8}"),
    ], [
        InlineKeyboardButton(text="Удалить ❌", callback_data=f"r:del:{id8}"),
    ]])

async def send_task_reminder(chat_id: int, text: str, short_id: str):
    await bot.send_message(
        chat_id,
        f"⏰ Напоминание: {text} (id {short_id})",
        reply_markup=task_keyboard(short_id)
    )

async def send_event_reminder(chat_id: int, title: str, start_iso: str, short_id: str):
    await bot.send_message(
        chat_id,
        f"📅 Начинается событие: {title} @ { _human(start_iso) } (id {short_id})",
        reply_markup=event_keyboard(short_id)
    )

async def send_reminder(chat_id: int, text: str, short_id: str):
    await bot.send_message(
        chat_id,
        f"🔔 Напоминание: {text} (id {short_id})",
        reply_markup=reminder_keyboard(short_id)
    )

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
        id=f"task:{task['id']}", replace_existing=True,
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
        id=f"event:{ev['id']}", replace_existing=True,
        args=[owner, ev["title"], ev["start"], ev["id"][:8]]
    )

def schedule_reminder_if_due(rem: dict):
    at = rem.get("at")
    owner = rem.get("owner")
    if not at or not owner:
        return
    try:
        dt = datetime.fromisoformat(at)
    except Exception:
        return
    if dt <= datetime.now():
        return
    scheduler.add_job(
        send_reminder, "date", run_date=dt,
        id=f"rem:{rem['id']}", replace_existing=True,
        args=[owner, rem["text"], rem["id"][:8]]
    )

def rehydrate_all_jobs():
    for t in store.list_tasks():
        schedule_task_if_due(t)
    for e in store.list_events():
        schedule_event_if_due(e)
    for r in store.list_reminders():
        schedule_reminder_if_due(r)

# ---------- compact list render ----------

def compact_tasks_text(tasks: list) -> str:
    if not tasks:
        return "Задач нет."
    lines = []
    for t in tasks:
        if t["done"]:
            status = "✅"
        else:
            status = "•"
        due = f" — {_human(t['due'])}" if t.get("due") else ""
        text = t["text"]
        if len(text) > 60:
            text = text[:57] + "…"
        lines.append(f"{status} [{t['id'][:8]}] {text}{due}")
    return "\n".join(lines)

async def send_task_list(chat_id: int, mode: str = "open"):
    """
    mode: 'open' (только незавершённые) | 'all' (все)
    """
    tasks = store.list_tasks(owner=chat_id)
    if mode == "open":
        tasks = [t for t in tasks if not t["done"]]
    text = compact_tasks_text(tasks)
    suffix = "\n\nПодсказка: напиши «покажи все задачи», чтобы увидеть завершённые тоже."
    if mode == "open":
        text += suffix
    await bot.send_message(chat_id, text)

# ---------- greet/help ----------

WELCOME_TEXT = (
    "Привет! Я Jarvis. Просто пиши по-человечески, без команд:\n"
    "• «Добавь задачу полить цветы завтра в 9:00»\n"
    "• «Создай событие \"Звонок с Петром\" завтра в 15:30 на 30 минут»\n"
    "• «Напомни через 10 минут проверить чайник»\n"
    "• «Покажи все задачи» или «Покажи повестку на сегодня»\n"
    "• «Я уже выполнил задачу с курицей» — помечу как сделанную\n\n"
    "Команды на всякий случай: /task, /event, /list, /agenda, /remind, /help"
)

HELP_TEXT = (
    "Можно писать свободным текстом (предпочтительно). Примеры:\n"
    "— «Добавь задачу купить молоко завтра в 18:00»\n"
    "— «Создай событие \"Совещание\" сегодня в 16:00 на 45 минут»\n"
    "— «Покажи задачи» (по умолчанию только незавершённые)\n"
    "— «Покажи все задачи» (включая завершённые)\n"
    "— «Я уже сделал отчёт по продажам» (fuzzy-метч по тексту)\n"
    "— «Напомни через 2 часа разморозить тесто»\n\n"
    "Команды: /task, /event, /done, /list [all], /agenda, /remind, /reminders, /rem_del"
)

# ---------- commands ----------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)

@dp.message(Command("task"))
async def cmd_task(message: Message, command: CommandObject):
    text = command.args or ""
    m = re.match(r'(.+?)(?:\s+due:([0-9T:\-]+))?$', text)
    if not m:
        await message.answer("Формат: /task ТЕКСТ due:YYYY-MM-DDTHH:MM")
        return
    item = store.add_task(m.group(1).strip(), m.group(2), owner=message.chat.id)
    schedule_task_if_due(item)
    kb = task_keyboard(item['id'][:8])
    await message.answer(
        f"✅ Добавил: [{item['id'][:8]}] {item['text']}{' — ' + _human(item['due']) if item['due'] else ''}",
        reply_markup=kb
    )

@dp.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Формат: /done ID_PREFIX")
        return
    ok = store.complete_task(command.args.strip(), owner=message.chat.id)
    await message.answer("Готово ✅" if ok else "Не найдено ❌")

@dp.message(Command("list"))
async def cmd_list(message: Message, command: CommandObject):
    arg = (command.args or "").strip().lower()
    mode = "all" if arg in {"all", "все", "alltasks", "full"} else "open"
    await send_task_list(message.chat.id, mode=mode)

@dp.message(Command("event"))
async def cmd_event(message: Message, command: CommandObject):
    args = command.args or ""
    m = re.match(r'^"(.+?)"\s+([0-9T:\-]+)\s+(\d+)$', args)
    if not m:
        await message.answer('Формат: /event "Название" YYYY-MM-DDTHH:MM ДЛИТ_МИН')
        return
    ev = store.add_event(m.group(1), m.group(2), int(m.group(3)), owner=message.chat.id)
    schedule_event_if_due(ev)
    await message.answer(
        f"📌 Событие: [{ev['id'][:8]}] {ev['title']} — { _human(ev['start']) } ({ev['duration_min']} мин)",
        reply_markup=event_keyboard(ev['id'][:8])
    )

@dp.message(Command("agenda"))
async def cmd_agenda(message: Message, command: CommandObject):
    arg = (command.args or "").strip().lower() or "today"
    if arg == "today":
        date_str = datetime.now().date().isoformat()
    elif arg == "tomorrow":
        date_str = (datetime.now() + timedelta(days=1)).date().isoformat()
    else:
        date_str = arg
    events = [e for e in store.list_events(owner=message.chat.id) if e["start"].startswith(date_str)]
    if not events:
        await message.answer(f"Событий на {date_str} нет.")
        return
    for e in events:
        await message.answer(
            f"📅 [{e['id'][:8]}] {e['title']} — { _human(e['start']) } ({e['duration_min']} мин)",
            reply_markup=event_keyboard(e['id'][:8])
        )

# reminders
@dp.message(Command("remind"))
async def cmd_remind(message: Message, command: CommandObject):
    args = command.args or ""
    m = re.match(r'^"(.+?)"\s+([0-9T:\-]+)$', args)
    if not m:
        await message.answer('Формат: /remind "Текст" YYYY-MM-DDTHH:MM')
        return
    r = store.add_reminder(m.group(1), m.group(2), owner=message.chat.id)
    schedule_reminder_if_due(r)
    await message.answer(
        f"🔔 Напоминание: [{r['id'][:8]}] {r['text']} — { _human(r['at']) }",
        reply_markup=reminder_keyboard(r['id'][:8])
    )

@dp.message(Command("reminders"))
async def cmd_reminders(message: Message):
    rems = store.list_reminders(owner=message.chat.id)
    if not rems:
        await message.answer("Напоминаний нет.")
        return
    for r in rems:
        await message.answer(
            f"🔔 [{r['id'][:8]}] {r['text']} — { _human(r['at']) }",
            reply_markup=reminder_keyboard(r['id'][:8])
        )

@dp.message(Command("rem_del"))
async def cmd_rem_del(message: Message, command: CommandObject):
    id8 = (command.args or "").strip()
    if not id8:
        await message.answer("Формат: /rem_del ID_PREFIX")
        return
    r = store.delete_reminder(id8, owner=message.chat.id)
    if not r:
        await message.answer("Напоминание не найдено ❌")
        return
    try:
        scheduler.remove_job(f"rem:{r['id']}")
    except Exception:
        pass
    await message.answer(f"🗑 Удалено: [{r['id'][:8]}] {r['text']}")

# ---------- fuzzy complete by text ----------

def _best_task_match(chat_id: int, text: str):
    """
    Возвращает (task, score) по лучшему совпадению среди НЕЗАВЕРШЁННЫХ задач.
    """
    from rapidfuzz import fuzz
    q = text.lower()
    tasks = [t for t in store.list_tasks(owner=chat_id) if not t["done"]]
    best = (None, 0.0)
    for t in tasks:
        s = t["text"].lower()
        score = max(
            fuzz.partial_ratio(q, s),
            fuzz.token_set_ratio(q, s)
        )
        if score > best[1]:
            best = (t, score)
    return best

async def try_complete_by_text(message: Message, original_text: str) -> bool:
    task, score = _best_task_match(message.chat.id, original_text)
    if task and score >= 80:
        ok = store.complete_task(task["id"][:8], owner=message.chat.id)
        if ok:
            await message.answer(f"✅ Пометил как выполненную: [{task['id'][:8]}] {task['text']}")
            return True
    return False

# ---------- free text + audio ----------

async def process_free_text(message: Message, user_text: str):
    # быстрые эвристики: список задач «все/всё»
    lowered = user_text.lower()
    if "все задачи" in lowered or "всё задачи" in lowered or "покажи все задачи" in lowered or "all tasks" in lowered:
        await send_task_list(message.chat.id, mode="all")
        return
    if lowered.strip() in {"список задач", "покажи задачи", "список дел", "покажи дела"}:
        await send_task_list(message.chat.id, mode="open")
        return

    now_iso = datetime.now().replace(microsecond=0).isoformat()
    tpl = Template(SYSTEM_PROMPT_TPL)
    sys_prompt = tpl.substitute(
        now_iso=now_iso,
        tomorrow_1800=(datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
                       + timedelta(days=1)).isoformat(),
        after_tomorrow_0930=(datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
                             + timedelta(days=2)).isoformat(),
        tomorrow_0900=(datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
                       + timedelta(days=1)).isoformat()
    )

    # сначала пробуем LLM-парсинг
    try:
        cmd = llm.ask_json(sys_prompt, user_text)
    except Exception:
        # если не получилось распарсить — попробуем закрыть задачу по тексту
        if await try_complete_by_text(message, user_text):
            return
        await message.answer("Не понял запрос. Примеры: «Добавь задачу…», «Покажи задачи», «Я уже сделал …»")
        return

    intent = cmd.get("intent")
    payload = cmd.get("payload", {})

    try:
        if intent == "add_task":
            item = store.add_task(payload["text"], payload.get("due"), owner=message.chat.id)
            schedule_task_if_due(item)
            kb = task_keyboard(item['id'][:8])
            await message.answer(
                f"✅ Добавил: [{item['id'][:8]}] {item['text']}{' — ' + _human(item['due']) if item['due'] else ''}",
                reply_markup=kb
            )
        elif intent == "list_tasks":
            # По умолчанию — только незавершённые; если в исходной фразе явно просили «все», покажем все
            mode = "all" if any(w in lowered for w in ["все", "всё", "all"]) else "open"
            await send_task_list(message.chat.id, mode=mode)
        elif intent == "complete_task":
            task_id = payload.get("id")
            if task_id:
                ok = store.complete_task(task_id, owner=message.chat.id)
                await message.answer("Готово ✅" if ok else "Не найдено ❌")
            else:
                # нет id — попробуем сматчить по тексту исходного запроса
                if not await try_complete_by_text(message, user_text):
                    await message.answer("Не смог найти задачу по описанию 😕")
        elif intent == "add_event":
            ev = store.add_event(payload["title"], payload["start"], int(payload.get("duration_min", 60)), owner=message.chat.id)
            schedule_event_if_due(ev)
            await message.answer(
                f"📌 Событие: [{ev['id'][:8]}] {ev['title']} — { _human(ev['start']) } ({ev['duration_min']} мин)",
                reply_markup=event_keyboard(ev['id'][:8])
            )
        elif intent == "agenda":
            day = payload.get("day", "today")
            await cmd_agenda(message, CommandObject(args=day))
        elif intent == "remind":
            r = store.add_reminder(payload["text"], payload["at"], owner=message.chat.id)
            schedule_reminder_if_due(r)
            await message.answer(
                f"🔔 Напоминание: [{r['id'][:8]}] {r['text']} — { _human(r['at']) }",
                reply_markup=reminder_keyboard(r['id'][:8])
            )
        else:
            # неуверены в интенте — попробуем закрыть задачу по тексту
            if await try_complete_by_text(message, user_text):
                return
            await message.answer(HELP_TEXT)
    except Exception as e:
        await message.answer(f"Ошибка выполнения: {e}")

@dp.message(F.text)
async def handle_free_text(message: Message):
    await process_free_text(message, message.text)

# ---------- audio & voice ----------

async def _download_file_to(message: Message, file_id: str, to_path: Path):
    to_path.parent.mkdir(parents=True, exist_ok=True)
    # aiogram v3: бот умеет скачивать сразу по file_id
    await bot.download(file_id, destination=to_path)

@dp.message(F.voice)
async def handle_voice(message: Message):
    try:
        ogg_path = Path("data/voices") / f"{message.chat.id}_{message.message_id}.ogg"
        await _download_file_to(message, message.voice.file_id, ogg_path)
        # Конвертнём в WAV 16k mono (stt сам тоже перестрахуется)
        wav_path = Path(str(ogg_path.with_suffix(".wav")))
        cmd = ["ffmpeg", "-y", "-i", str(ogg_path), "-ac", "1", "-ar", "16000", "-f", "wav", str(wav_path)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        text = stt.transcribe(str(wav_path), lang="ru")
        if not text:
            await message.answer("Не разобрал голосовое 😕 Попробуй ещё раз.")
            return
        await process_free_text(message, text)
    except Exception as e:
        await message.answer(f"Проблема с аудио: {e}\nУбедись, что установлен ffmpeg и настроен STT (VOSK_MODEL_DIR или OPENAI_API_KEY).")

@dp.message(F.audio)
async def handle_audio(message: Message):
    try:
        # Для обычных аудио (mp3/m4a/ogg) — аналогично
        src_path = Path("data/audios") / f"{message.chat.id}_{message.message_id}"
        ext = (message.audio.file_name.split(".")[-1] if message.audio.file_name else "mp3").lower()
        src_path = src_path.with_suffix("." + ext)
        await _download_file_to(message, message.audio.file_id, src_path)
        wav_path = Path(str(src_path.with_suffix(".wav")))
        cmd = ["ffmpeg", "-y", "-i", str(src_path), "-ac", "1", "-ar", "16000", "-f", "wav", str(wav_path)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        text = stt.transcribe(str(wav_path), lang="ru")
        if not text:
            await message.answer("Не смог распознать аудио 😕")
            return
        await process_free_text(message, text)
    except Exception as e:
        await message.answer(f"Проблема с аудио: {e}")

# ---------- callbacks: tasks/events/reminders ----------

@dp.callback_query(F.data.startswith("t:"))
async def on_task_action(q: CallbackQuery):
    try:
        _, action, id8 = q.data.split(":")
    except Exception:
        await q.answer("Некорректные данные", show_alert=True)
        return

    chat_id = q.message.chat.id

    if action == "done":
        ok = store.complete_task(id8, owner=chat_id)
        if ok:
            new_text = (q.message.text or "") + "\nСтатус: ✅ Готово"
            await q.message.edit_text(new_text)
            await q.answer("Отмечено как готово")
        else:
            await q.answer("Задача не найдена", show_alert=True)
        return

    if action.startswith("snooze"):
        minutes = 10 if action == "snooze10" else 60
        t = store.snooze_task(id8, minutes, owner=chat_id)
        if not t:
            await q.answer("Задача не найдена", show_alert=True)
            return
        schedule_task_if_due(t)
        base_text = q.message.text.split("\n")[0] if q.message.text else ""
        await q.message.edit_text(
            f"{base_text}\nНовый срок: { _human(t['due']) }",
            reply_markup=task_keyboard(t["id"][:8])
        )
        await q.answer(f"Отложено на {minutes} мин")
        return

    await q.answer("Неизвестное действие", show_alert=True)

@dp.callback_query(F.data.startswith("e:"))
async def on_event_action(q: CallbackQuery):
    try:
        _, action, id8 = q.data.split(":")
    except Exception:
        await q.answer("Некорректные данные", show_alert=True)
        return

    chat_id = q.message.chat.id

    if action.startswith("snooze"):
        minutes = 10 if action == "snooze10" else 60
        e = store.snooze_event(id8, minutes, owner=chat_id)
        if not e:
            await q.answer("Событие не найдено", show_alert=True)
            return
        try:
            scheduler.remove_job(f"event:{e['id']}")
        except Exception:
            pass
        schedule_event_if_due(e)
        base_text = q.message.text.split("\n")[0] if q.message.text else ""
        await q.message.edit_text(
            f"{base_text}\nНовое время: { _human(e['start']) }",
            reply_markup=event_keyboard(e["id"][:8])
        )
        await q.answer(f"Сдвинуто на {minutes} мин")
        return

    if action == "del":
        e = store.delete_event(id8, owner=chat_id)
        if not e:
            await q.answer("Событие не найдено", show_alert=True)
            return
        try:
            scheduler.remove_job(f"event:{e['id']}")
        except Exception:
            pass
        await q.message.edit_text((q.message.text or "") + "\n🗑 Удалено")
        await q.answer("Удалено")
        return

    await q.answer("Неизвестное действие", show_alert=True)

@dp.callback_query(F.data.startswith("r:"))
async def on_reminder_action(q: CallbackQuery):
    try:
        _, action, id8 = q.data.split(":")
    except Exception:
        await q.answer("Некорректные данные", show_alert=True)
        return

    chat_id = q.message.chat.id

    if action.startswith("snooze"):
        minutes = 10 if action == "snooze10" else 60
        r = store.snooze_reminder(id8, minutes, owner=chat_id)
        if not r:
            await q.answer("Напоминание не найдено", show_alert=True)
            return
        try:
            scheduler.remove_job(f"rem:{r['id']}")
        except Exception:
            pass
        schedule_reminder_if_due(r)
        base_text = q.message.text.split("\n")[0] if q.message.text else ""
        await q.message.edit_text(
            f"{base_text}\nНовый момент: { _human(r['at']) }",
            reply_markup=reminder_keyboard(r["id"][:8])
        )
        await q.answer(f"Отложено на {minutes} мин")
        return

    if action == "del":
        r = store.delete_reminder(id8, owner=chat_id)
        if not r:
            await q.answer("Напоминание не найдено", show_alert=True)
            return
        try:
            scheduler.remove_job(f"rem:{r['id']}")
        except Exception:
            pass
        await q.message.edit_text((q.message.text or "") + "\n🗑 Удалено")
        await q.answer("Удалено")
        return

    await q.answer("Неизвестное действие", show_alert=True)

# ---------- boot ----------

async def main():
    scheduler.start()
    try:
        rehydrate_all_jobs()
    except Exception as e:
        print(f"[rehydrate] warning: {e}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
