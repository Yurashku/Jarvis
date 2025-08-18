"""
cli.py
~~~~~~

Command-line interface for the Jarvis personal assistant.  This CLI
mimics the behaviour of the Telegram bot while operating in a
terminal.  It supports natural language input parsed through a
language model as well as explicit slash commands.  Tasks, events and
reminders are persisted via the ``store`` module.  A background
scheduler delivers notifications for upcoming deadlines directly to
the console.

Run this script with ``python cli.py``.  It will load environment
variables from a ``.env`` file if present.

"""

from __future__ import annotations

import os
import re
import sys
import threading
from datetime import datetime, timedelta
from string import Template
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Prompt

import store
from llm_provider import LLM


# Load environment variables from .env for local development
load_dotenv()

console = Console()
llm = LLM()

# Background scheduler to deliver notifications to the console
scheduler = BackgroundScheduler()

# System prompt for LLM instructions, extended with examples
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


def _human(dt_iso: str) -> str:
    """Return a friendly representation of a datetime (relative today/tomorrow)."""
    try:
        dt = datetime.fromisoformat(dt_iso)
    except Exception:
        return dt_iso
    now = datetime.now()
    if dt.date() == now.date():
        prefix = "сегодня"
    elif dt.date() == (now.date() + timedelta(days=1)):
        prefix = "завтра"
    else:
        prefix = dt.date().isoformat()
    return f"{prefix} {dt.strftime('%H:%M')}"


def schedule_console_notification(message: str, run_at_iso: str) -> None:
    """Schedule a console notification for the given time."""
    try:
        dt = datetime.fromisoformat(run_at_iso)
    except Exception:
        return
    if dt <= datetime.now():
        return
    def notify() -> None:
        console.print(f"[bold yellow]Напоминание:[/bold yellow] {message}")
    scheduler.add_job(notify, "date", run_date=dt)


def rehydrate_jobs(owner: Optional[int] = None) -> None:
    """Restore scheduled notifications from persisted data."""
    # For CLI, owner is None
    for t in store.list_tasks(owner=owner):
        if t.get("due") and not t.get("done"):
            schedule_console_notification(f"Задача: {t['text']}", t["due"])
    for e in store.list_events(owner=owner):
        schedule_console_notification(
            f"Событие: {e['title']}", e["start"]
        )
    for r in store.list_reminders(owner=owner):
        schedule_console_notification(
            f"Напоминание: {r['text']}", r["at"]
        )


def compact_tasks(tasks: list) -> str:
    """Format a list of tasks for display."""
    if not tasks:
        return "[italic]Задач нет.[/italic]"
    lines = []
    for t in tasks:
        status = "✅" if t.get("done") else "🔹"
        due = f" — {_human(t['due'])}" if t.get("due") else ""
        text = t["text"]
        if len(text) > 60:
            text = text[:57] + "…"
        lines.append(f"{status} [{t['id'][:8]}] {text}{due}")
    return "\n".join(lines)


def list_tasks_console(mode: str = "open", owner: Optional[int] = None) -> None:
    """List tasks to the console."""
    tasks = store.list_tasks(owner=owner)
    if mode == "open":
        tasks = [t for t in tasks if not t.get("done")]
    console.print(compact_tasks(tasks))
    if mode == "open" and tasks:
        console.print(
            "\n[dim]Напиши 'покажи все задачи', чтобы увидеть завершённые тоже.[/dim]"
        )


def try_fuzzy_complete(text: str) -> bool:
    """Attempt to complete a task by fuzzy-matching its description."""
    from rapidfuzz import fuzz

    q = text.lower()
    tasks = [t for t in store.list_tasks(owner=None) if not t.get("done")]
    best_score = 0.0
    best_task = None
    for t in tasks:
        s = t["text"].lower()
        score = max(fuzz.partial_ratio(q, s), fuzz.token_set_ratio(q, s))
        if score > best_score:
            best_score = score
            best_task = t
    if best_task and best_score >= 80:
        store.complete_task(best_task["id"][:8], owner=None)
        console.print(
            f"[green]Пометил как выполненную:[/green] [{best_task['id'][:8]}] {best_task['text']}"
        )
        return True
    return False


def slash_command(text: str) -> bool:
    """Handle slash commands.  Returns True if a command was handled."""
    text = text.strip()
    # /exit or /quit to leave
    if text.lower() in {"/exit", "/quit"}:
        console.print("Пока 👋")
        scheduler.shutdown()
        sys.exit(0)

    # /help
    if text.lower().startswith("/help"):
        console.print(HELP_TEXT)
        return True

    # /task ТЕКСТ due:ISO
    if text.startswith("/task"):
        m = re.match(r"^/task\s+(.+?)(?:\s+due:([0-9T:\-]+))?$", text)
        if not m:
            console.print("[red]Формат:[/red] /task ТЕКСТ due:YYYY-MM-DDTHH:MM")
            return True
        item = store.add_task(m.group(1), m.group(2), owner=None)
        schedule_console_notification(f"Задача: {item['text']}", item["due"])
        console.print(
            f"[green]Добавил:[/green] [{item['id'][:8]}] {item['text']}{' — ' + _human(item['due']) if item['due'] else ''}"
        )
        return True

    # /event "Название" ISO ДЛИТ
    if text.startswith("/event"):
        m = re.match(r'^/event\s+"(.+?)"\s+([0-9T:\-]+)\s+(\d+)$', text)
        if not m:
            console.print("[red]Формат:[/red] /event \"Название\" YYYY-MM-DDTHH:MM ДЛИТ_МИН")
            return True
        ev = store.add_event(m.group(1), m.group(2), int(m.group(3)), owner=None)
        schedule_console_notification(f"Событие: {ev['title']}", ev["start"])
        console.print(
            f"[blue]Событие:[/blue] [{ev['id'][:8]}] {ev['title']} — { _human(ev['start']) } ({ev['duration_min']} мин)"
        )
        return True

    # /done ID_PREFIX
    if text.startswith("/done"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[red]Формат:[/red] /done ID_PREFIX")
            return True
        ok = store.complete_task(parts[1].strip(), owner=None)
        console.print("Готово ✅" if ok else "[red]Не найдено[/red]")
        return True

    # /list [all]
    if text.startswith("/list"):
        parts = text.split(maxsplit=1)
        mode = "all" if len(parts) > 1 and parts[1].strip().lower() in {"all", "все", "alltasks"} else "open"
        list_tasks_console(mode)
        return True

    # /event_rename ID_PREFIX NEW_TITLE
    if text.startswith("/event_rename"):
        # expected: /event_rename id8 New Title
        arg = text.replace("/event_rename", "", 1).strip()
        if not arg or " " not in arg:
            console.print("[red]Формат:[/red] /event_rename ID_PREFIX НОВОЕ_НАЗВАНИЕ")
            return True
        id8, new_title = arg.split(" ", 1)
        ev = store.update_event_title(id8, new_title.strip(), owner=None)
        if not ev:
            console.print("[red]Событие не найдено[/red]")
        else:
            # no need to reschedule: title change does not affect time
            console.print(f"[blue]Переименовано:[/blue] [{ev['id'][:8]}] {ev['title']}")
        return True

    # /event_move ID_PREFIX YYYY-MM-DDTHH:MM
    if text.startswith("/event_move"):
        arg = text.replace("/event_move", "", 1).strip()
        m = re.match(r"^([a-f0-9]{1,8})\s+([0-9T:\-]+)$", arg, re.I)
        if not m:
            console.print("[red]Формат:[/red] /event_move ID_PREFIX YYYY-MM-DDTHH:MM")
            return True
        id8, new_start = m.group(1), m.group(2)
        ev = store.update_event_time(id8, new_start, owner=None)
        if not ev:
            console.print("[red]Событие не найдено[/red]")
        else:
            # schedule new notification
            schedule_console_notification(f"Событие: {ev['title']}", ev['start'])
            console.print(f"[blue]Перенесено:[/blue] [{ev['id'][:8]}] {ev['title']} → { _human(ev['start']) }")
        return True

    # /event_duration ID_PREFIX MINUTES
    if text.startswith("/event_duration"):
        arg = text.replace("/event_duration", "", 1).strip()
        m = re.match(r"^([a-f0-9]{1,8})\s+(\d+)$", arg, re.I)
        if not m:
            console.print("[red]Формат:[/red] /event_duration ID_PREFIX МИНУТЫ")
            return True
        id8, minutes = m.group(1), int(m.group(2))
        ev = store.update_event_duration(id8, minutes, owner=None)
        if not ev:
            console.print("[red]Событие не найдено[/red]")
        else:
            console.print(f"[blue]Длительность обновлена:[/blue] [{ev['id'][:8]}] {ev['duration_min']} мин")
        return True

    # /event_delete ID_PREFIX
    if text.startswith("/event_delete"):
        arg = text.replace("/event_delete", "", 1).strip()
        if not arg:
            console.print("[red]Формат:[/red] /event_delete ID_PREFIX")
            return True
        ev = store.delete_event(arg, owner=None)
        if not ev:
            console.print("[red]Событие не найдено[/red]")
        else:
            console.print(f"[blue]Удалено событие:[/blue] [{ev['id'][:8]}] {ev['title']}")
        return True

    # /agenda day
    if text.startswith("/agenda"):
        arg = text.replace("/agenda", "").strip().lower() or "today"
        day = arg
        if day == "today":
            date_str = datetime.now().date().isoformat()
        elif day == "tomorrow":
            date_str = (datetime.now() + timedelta(days=1)).date().isoformat()
        else:
            date_str = day
        events = [e for e in store.list_events(owner=None) if e["start"].startswith(date_str)]
        if not events:
            console.print(f"[yellow]Событий на {date_str} нет.[/yellow]")
        else:
            for e in events:
                console.print(
                    f"📅 [{e['id'][:8]}] {e['title']} — { _human(e['start']) } ({e['duration_min']} мин)"
                )
        return True

    # /remind "Текст" ISO
    if text.startswith("/remind"):
        m = re.match(r'^/remind\s+"(.+?)"\s+([0-9T:\-]+)$', text)
        if not m:
            console.print("[red]Формат:[/red] /remind \"Текст\" YYYY-MM-DDTHH:MM")
            return True
        r = store.add_reminder(m.group(1), m.group(2), owner=None)
        schedule_console_notification(f"Напоминание: {r['text']}", r["at"])
        console.print(
            f"[cyan]Напоминание:[/cyan] [{r['id'][:8]}] {r['text']} — { _human(r['at']) }"
        )
        return True

    # /reminders
    if text.startswith("/reminders"):
        rems = store.list_reminders(owner=None)
        if not rems:
            console.print("[italic]Напоминаний нет.[/italic]")
        else:
            for r in rems:
                console.print(
                    f"🔔 [{r['id'][:8]}] {r['text']} — { _human(r['at']) }"
                )
        return True

    # /rem_del ID
    if text.startswith("/rem_del"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            console.print("[red]Формат:[/red] /rem_del ID_PREFIX")
            return True
        r = store.delete_reminder(parts[1].strip(), owner=None)
        if r:
            console.print(
                f"Удалено напоминание: [{r['id'][:8]}] {r['text']}"
            )
        else:
            console.print("[red]Напоминание не найдено[/red]")
        return True

    # Unknown slash command fallback
    if text.startswith("/"):
        console.print(
            "[yellow]Неизвестная команда. Используй /help для списка команд.[/yellow]"
        )
        return True
    return False


HELP_TEXT = (
    "Команды:\n"
    "/task ТЕКСТ due:YYYY-MM-DDTHH:MM\n"
    "/event \"Название\" YYYY-MM-DDTHH:MM ДЛИТ_МИН\n"
    "/done ID_PREFIX\n"
    "/list [all]\n"
    "/agenda today|tomorrow|YYYY-MM-DD\n"
    "/remind \"Текст\" YYYY-MM-DDTHH:MM\n"
    "/reminders\n"
    "/rem_del ID_PREFIX\n"
    "/help\n"
    "/exit или /quit — выход"
)


WELCOME_TEXT = (
    "Привет! Я Jarvis в терминале. Пиши обычный текст: например, \"Добавь задачу купить молоко завтра\"\n"
    "Пиши \"Покажи задачи\", \"Покажи все задачи\" или \"Покажи повестку на сегодня\".\n"
    "Команды тоже работают: /task, /event, /list, /agenda, /remind, /help."
)


def process_free_text(user_text: str) -> None:
    """Handle natural language input via the LLM."""
    # Quick checks for listing tasks
    lowered = user_text.lower().strip()
    if any(word in lowered for word in ["все задачи", "всё задачи", "all tasks", "все дела", "all"]):
        list_tasks_console("all")
        return
    if lowered in {"задачи", "дела", "покажи задачи", "список задач", "список дел", "покажи дела"}:
        list_tasks_console("open")
        return

    # Build system prompt with current timestamps for relative examples
    now_iso = datetime.now().replace(microsecond=0).isoformat()
    tpl = Template(SYSTEM_PROMPT_TPL)
    sys_prompt = tpl.substitute(
        now_iso=now_iso,
        tomorrow_1800=(
            datetime.now()
            .replace(hour=18, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        ).isoformat(),
        after_tomorrow_0930=(
            datetime.now()
            .replace(hour=9, minute=30, second=0, microsecond=0)
            + timedelta(days=2)
        ).isoformat(),
        tomorrow_0900=(
            datetime.now()
            .replace(hour=9, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        ).isoformat(),
    )

    try:
        cmd = llm.ask_json(sys_prompt, user_text)
    except Exception:
        # If parsing failed, try to complete a task by fuzzy match
        if try_fuzzy_complete(user_text):
            return
        console.print(
            "[yellow]Не понял. Попробуй написать по-другому или используй /help.[/yellow]"
        )
        return

    intent = cmd.get("intent")
    payload = cmd.get("payload", {})

    try:
        if intent == "add_task":
            item = store.add_task(payload["text"], payload.get("due"), owner=None)
            schedule_console_notification(f"Задача: {item['text']}", item["due"])
            console.print(
                f"[green]Добавил:[/green] [{item['id'][:8]}] {item['text']}"
                + (f" — {_human(item['due'])}" if item.get("due") else "")
            )
        elif intent == "list_tasks":
            mode = "all" if any(w in lowered for w in ["все", "всё", "all"]) else "open"
            list_tasks_console(mode)
        elif intent == "complete_task":
            tid = payload.get("id")
            if tid:
                ok = store.complete_task(tid, owner=None)
                console.print("Готово ✅" if ok else "[red]Не найдено[/red]")
            else:
                # fallback to fuzzy match
                if not try_fuzzy_complete(user_text):
                    console.print("[yellow]Не смог найти задачу по описанию.[/yellow]")
        elif intent == "add_event":
            ev = store.add_event(
                payload["title"],
                payload["start"],
                int(payload.get("duration_min", 60)),
                owner=None,
            )
            schedule_console_notification(f"Событие: {ev['title']}", ev["start"])
            console.print(
                f"[blue]Событие:[/blue] [{ev['id'][:8]}] {ev['title']} — {_human(ev['start'])} ({ev['duration_min']} мин)"
            )
        elif intent == "agenda":
            day = payload.get("day", "today")
            # call slash command to reuse agenda logic
            slash_command(f"/agenda {day}")
        elif intent == "remind":
            r = store.add_reminder(payload["text"], payload["at"], owner=None)
            schedule_console_notification(f"Напоминание: {r['text']}", r["at"])
            console.print(
                f"[cyan]Напоминание:[/cyan] [{r['id'][:8]}] {r['text']} — {_human(r['at'])}"
            )
        else:
            if try_fuzzy_complete(user_text):
                return
            console.print(
                "[yellow]Не понял команду. Используй /help или попробуй переформулировать.[/yellow]"
            )
    except Exception as exc:
        console.print(f"[red]Ошибка выполнения:[/red] {exc}")


def main() -> None:
    """Entry point for the CLI."""
    console.print(WELCOME_TEXT)
    # Start scheduler
    scheduler.start()
    # Rehydrate jobs from store
    rehydrate_jobs(owner=None)
    try:
        while True:
            text = Prompt.ask("[bold white]Ты[/bold white]")
            if not text:
                continue
            # try slash commands first
            if slash_command(text):
                continue
            # else free text
            process_free_text(text)
    except (KeyboardInterrupt, SystemExit):
        console.print("\nПока 👋")
        scheduler.shutdown()


if __name__ == "__main__":
    main()