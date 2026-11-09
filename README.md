# Jarvis Assistant

Jarvis is a personal assistant prototype for tasks, calendar events and reminders. It combines a Python command-line interface, a Telegram bot, SQLite storage, scheduled notifications, and adapters for local or cloud language and speech models. Russian natural-language commands are the main examples; explicit slash commands provide another entry point.

Task data are stored locally in `data/jarvis.db`. Telegram messages still pass through Telegram, and cloud LLM/STT providers receive the inputs sent to them. A local database does not make every interface or configuration offline.

## Status and a quick way to inspect the project

This is a personal integration project, not a hosted service. The useful engineering pieces are the shared persistence layer, owner-scoped records, reminder scheduling, provider adapters, and recurring Telegram events. [The development history](https://github.com/Yurashku/Jarvis/commits/main/) records the work; [recurring-event support](https://github.com/Yurashku/Jarvis/commit/5a936832c582a01af977b6dc86e46cc9c38c0298) is one concrete change associated with Yurashku.

For a check that needs no Telegram account, language model, microphone or API key, run the storage tests from the repository root:

```bash
python -m pip install pytest python-dateutil
python -m pytest tests/test_store.py -q
```

These tests exercise creating/completing tasks, moving/deleting events and reminders, and expanding/deleting recurring events in temporary SQLite databases. They passed in the documentation check on Python 3.14.0. This does not verify live Telegram, LLM, speech recognition or notification delivery. The repository's CI is configured for Python 3.11.

## Features

* **Natural language commands** – tell Jarvis to add tasks, schedule events or set reminders in plain Russian (e.g. “Добавь задачу купить молоко завтра в 18:00” or “Создай событие ‘Звонок с Петром’ послезавтра в 09:30 на 30 минут”).
* **Slash commands** – fall back to deterministic commands like `/task`, `/event`, `/list`, `/agenda`, `/remind` for precise control.
* **Smart listing** – by default Jarvis shows only open (unfinished) tasks; use “покажи все задачи” to include completed ones.  Lists are compact with short IDs and due times formatted relative to today.
* **Fuzzy completion** – mark tasks as done by mentioning them in free text (“я уже выполнил задачу с курицей”) without remembering the ID.  Jarvis uses fuzzy matching to find the right task.
* **Events** – schedule events with a start time and duration, reschedule or rename them, and delete them when finished.  Receive a reminder when the event is about to start.
* **Reminders** – one‑off alerts at a specific time; snooze or delete them via inline buttons.
* **Inline keyboards** – in Telegram you can mark tasks as done, snooze tasks/events/reminders (+10 min, +1 hour) or delete them with a tap.
* **Speech to text** – send voice or audio messages and Jarvis will transcribe them using offline Vosk or online Whisper and process as normal commands.
* **Local storage** – tasks, events and reminders are stored in SQLite (`data/jarvis.db`); Telegram and any configured cloud providers have their own data flows.
* **Flexible language models** – use a local model via [Ollama](https://ollama.com) by default or switch to OpenAI by changing environment variables.  The system prompt is defined in `bot.py`/`cli.py`.

## Installation

1. **Clone the repository**:

   ```sh
   git clone https://github.com/Yurashku/Jarvis.git
   cd Jarvis
   ```

2. **Create a virtual environment** and install dependencies:

   ```sh
   python -m venv venv
   source venv/bin/activate  # or `venv\Scripts\activate` on Windows
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Install ffmpeg** (required for voice transcription).  On Windows you can use [Scoop](https://scoop.sh) or [Winget](https://learn.microsoft.com/windows/package-manager/winget/) to install `ffmpeg`.  Alternatively download a static build and add it to your `PATH`.  Set `FFMPEG_BIN` in your `.env` if it is not in the `PATH`.

4. **Configure environment**:

   * Copy `.env.example` to `.env` and fill in the values appropriate for your setup.  The bot needs `TELEGRAM_TOKEN`, a configured LLM, and a speech provider: its startup checks require STT configuration even before you send a voice message. The CLI needs an LLM but no Telegram token.  If you plan to use OpenAI models, provide your `OPENAI_API_KEY`.  For offline speech recognition, download a Russian Vosk model and set `VOSK_MODEL_DIR`; otherwise `STT_PROVIDER=auto` will fall back to OpenAI Whisper.  See comments in `.env.example` for details.
   * Install Ollama and fetch a model if using local LLMs.  For example:

     ```sh
     # install Ollama from https://ollama.com/download and then
     ollama pull llama3.1:8b
     ```

5. **Migrate existing JSON data** (optional):

   ```sh
   python migrate_to_sqlite.py
   ```

6. **Run the command‑line interface** (optional):

   ```sh
   python cli.py
   ```

   Jarvis will greet you and you can start typing commands or natural language.  Type `/exit` to quit.

7. **Run the Telegram bot**:

   ```sh
   python bot.py
   ```

   Start chatting with your bot in Telegram.  The bot automatically schedules reminders for tasks, events and reminders and resumes them on restart.

## Recurring events in Telegram

Use `/event_repeat "Standup" каждый ПОНЕДЕЛЬНИК в 10:00 15` to schedule a weekly 15-minute event. `/agenda` includes the expanded occurrences; `/event_repeat_delete ID_PREFIX` removes the rule. Recurrence is implemented in the Telegram interface and storage layer; the CLI does not expose these recurrence commands.

## Usage examples

* “Добавь задачу купить молоко завтра в 18:00” – создаёт задачу с дедлайном завтра в 18:00.
* “Создай событие ‘Звонок с Петром’ завтра в 15:00 на 30 минут” – планирует событие.
* “Напомни через 2 часа разморозить тесто” – ставит одноразовое напоминание.
* “Покажи задачи” – выводит незавершённые задачи.
* “Покажи все задачи” – включает завершённые задачи.
* “Я уже выполнил задачу с курицей” – завершает подходящую задачу без указания ID.
* В Telegram можно нажимать кнопки под задачами, событиями и напоминаниями, чтобы отметить выполненными, отложить или удалить.

## Troubleshooting

On startup Jarvis validates that required models and API keys are available. If something is misconfigured it will exit with a helpful message.

* **`VOSK_MODEL_DIR missing`** – download a Vosk model (for example from https://alphacephei.com/vosk/models) and set `VOSK_MODEL_DIR` to its path, or switch STT to OpenAI by providing `OPENAI_API_KEY`.
* **`OPENAI_API_KEY not set or unsupported region`** – obtain an API key from OpenAI and export it as `OPENAI_API_KEY`. If the service is not available in your region, switch to a supported provider or a local model.
* **`Ollama model '<name>' missing`** – install Ollama and run `ollama pull <name>` to fetch the required model.

## Project structure

* `cli.py` – интерактивный интерфейс для терминала с поддержкой LLM, команд и запланированных уведомлений.
* `bot.py` – реализация Telegram‑бота на aiogram.  Содержит хендлеры команд, обработку естественного языка, inline‑кнопки и планировщик.
* `store.py` – модуль для хранения задач, событий и напоминаний.  Использует SQLite с полнотекстовым поиском и поддерживает многопользовательский режим (поле `owner`).
* `llm_provider.py` – абстракция над языковыми моделями.  Выбирает Ollama или OpenAI в зависимости от переменных окружения и предоставляет методы `ask` и `ask_json`.
* `stt.py` – модуль для распознавания речи.  Работает через офлайн Vosk или онлайн OpenAI Whisper.  Требуется ffmpeg для конвертации аудио.
* `data/` – папка для сохранения базы данных (`jarvis.db`) с вашими данными.  Создаётся автоматически.

## Contributing

Пожалуйста, открывайте issues и pull‑requests для предложений улучшений.  Ветки должны проходить тесты (CLI запускается без ошибок) и обновлять документацию при добавлении новых возможностей.

## License

The current repository does not contain a `LICENSE` file. Contact the maintainer to clarify reuse terms.
