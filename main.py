import os
import re
from datetime import datetime, timedelta
from rich.console import Console
from rich.prompt import Prompt
from string import Template
from dotenv import load_dotenv

from llm_provider import LLM
import store

load_dotenv()
console = Console()
llm = LLM()

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


def slash_command(text: str) -> bool:
    """
    Обработка надежных /команд без LLM.
    Примеры:
      /task купить молоко due:2025-08-12T18:00
      /event "Колл с Петром" 2025-08-12T15:00 60
      /done <id_prefix>
      /list
      /agenda today|tomorrow|YYYY-MM-DD
      /help
    """
    text = text.strip()
    if text.startswith("/task"):
        m = re.match(r'^/task\s+(.+?)(?:\s+due:([0-9T:\-]+))?$', text)
        if not m:
            console.print("[red]Формат:[/red] /task ТЕКСТ due:YYYY-MM-DDTHH:MM")
            return True
        task = store.add_task(m.group(1), m.group(2))
        console.print(f"[green]Добавил задачу:[/green] {task['text']} (id {task['id'][:8]})")
        return True

    if text.startswith("/event"):
        m = re.match(r'^/event\s+"(.+?)"\s+([0-9T:\-]+)\s+(\d+)$', text)
        if not m:
            console.print("[red]Формат:[/red] /event \"Название\" 2025-08-12T15:00 60")
            return True
        ev = store.add_event(m.group(1), m.group(2), int(m.group(3)))
        console.print(f"[green]Создал событие:[/green] {ev['title']} @ {ev['start']} ({ev['duration_min']} мин) id {ev['id'][:8]}")
        return True

    if text.startswith("/done"):
        m = re.match(r'^/done\s+([a-f0-9\-]+)$', text.strip(), re.I)
        if not m:
            console.print("[red]Формат:[/red] /done ID_PREFIX")
            return True
        ok = store.complete_task(m.group(1))
        console.print("[green]Готово[/green]" if ok else "[red]Не найдено[/red]")
        return True

    if text.startswith("/list"):
        tasks = store.list_tasks()
        if not tasks:
            console.print("[yellow]Задач нет[/yellow]")
        else:
            for t in tasks:
                done = "✅" if t["done"] else "🔹"
                due = f" (срок: {t['due']})" if t["due"] else ""
                console.print(f"{done} [{t['id'][:8]}] {t['text']}{due}")
        return True

    if text.startswith("/agenda"):
        arg = text.replace("/agenda", "").strip() or "today"
        day = arg.lower()
        if day == "today":
            date_str = datetime.now().date().isoformat()
        elif day == "tomorrow":
            date_str = (datetime.now() + timedelta(days=1)).date().isoformat()
        else:
            date_str = day  # предполагаем YYYY-MM-DD
        events = [e for e in store.list_events() if e["start"].startswith(date_str)]
        if not events:
            console.print(f"[yellow]Событий на {date_str} нет[/yellow]")
        else:
            for e in events:
                console.print(f"📅 [{e['id'][:8]}] {e['title']} @ {e['start']} ({e['duration_min']} мин)")
        return True

    if text.startswith("/help"):
        console.print("""Команды:
  /task ТЕКСТ due:YYYY-MM-DDTHH:MM
  /event "Название" YYYY-MM-DDTHH:MM ДЛИТ_МИН
  /done ID_PREFIX
  /list
  /agenda today|tomorrow|YYYY-MM-DD
  (либо пиши по-русски, я распарсю через LLM)
""")
        return True

    return False

def main():
    console.print("[bold cyan]Jarvis[/bold cyan] запущен. По умолчанию провайдер: "
                  f"[bold]{os.getenv('LLM_PROVIDER','ollama')}[/bold]. Напиши /help для справки.")
    while True:
        text = Prompt.ask("[white]Ты[/white]")
        if text.strip().lower() in {"exit", "quit"}:
            console.print("Пока 👋")
            break

        # Сначала пробуем надежные /команды
        if slash_command(text):
            continue

        # Иначе — пробуем «умный» парсинг через LLM
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
            cmd = llm.ask_json(sys_prompt, text)
        except Exception as e:
            console.print(f"[red]Не смог распарсить через LLM:[/red] {e}")
            continue

        intent = cmd.get("intent")
        payload = cmd.get("payload", {})

        try:
            if intent == "add_task":
                item = store.add_task(payload["text"], payload.get("due"))
                console.print(f"[green]Добавил задачу:[/green] {item['text']} (id {item['id'][:8]})")
            elif intent == "list_tasks":
                slash_command("/list")
            elif intent == "complete_task":
                ok = store.complete_task(payload["id"])
                console.print("[green]Готово[/green]" if ok else "[red]Не найдено[/red]")
            elif intent == "add_event":
                ev = store.add_event(payload["title"], payload["start"], int(payload.get("duration_min", 60)))
                console.print(f"[green]Создал событие:[/green] {ev['title']} @ {ev['start']} ({ev['duration_min']} мин)")
            elif intent == "agenda":
                day = payload.get("day", "today")
                slash_command(f"/agenda {day}")
            else:
                slash_command("/help")
        except Exception as e:
            console.print(f"[red]Ошибка выполнения:[/red] {e}")

if __name__ == "__main__":
    main()
