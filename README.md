# Jarvis Assistant

Jarvis is a personal assistant designed to help you manage your tasks, events and reminders using natural language.  It runs locally on your machine, keeping your data private, and can interact through both a command‑line interface and a Telegram bot.  Jarvis understands plain Russian (and English) input, supports speech‑to‑text for voice messages, and can use either local or cloud language models.

## Features

* **Natural language commands** – tell Jarvis to add tasks, schedule events or set reminders in plain Russian (e.g. “Добавь задачу купить молоко завтра в 18:00” or “Создай событие ‘Звонок с Петром’ послезавтра в 09:30 на 30 минут”).
* **Slash commands** – fall back to deterministic commands like `/task`, `/event`, `/list`, `/agenda`, `/remind` for precise control.
* **Smart listing** – by default Jarvis shows only open (unfinished) tasks; use “покажи все задачи” to include completed ones.  Lists are compact with short IDs and due times formatted relative to today.
* **Fuzzy completion** – mark tasks as done by mentioning them in free text (“я уже выполнил задачу с курицей”) without remembering the ID.  Jarvis uses fuzzy matching to find the right task.
* **Events** – schedule events with a start time and duration, reschedule or rename them, and delete them when finished.  Receive a reminder when the event is about to start.
* **Reminders** – one‑off alerts at a specific time; snooze or delete them via inline buttons.
* **Inline keyboards** – in Telegram you can mark tasks as done, snooze tasks/events/reminders (+10 min, +1 hour) or delete them with a tap.
* **Speech to text** – send voice or audio messages and Jarvis will transcribe them using offline Vosk or online Whisper and process as normal commands.
* **Local‑first** – tasks, events and reminders are stored in JSON files in the `data/` folder.  No data is sent anywhere unless you configure a cloud model for LLM/STT.
* **Flexible language models** – use a local model via [Ollama](https://ollama.com) by default or switch to OpenAI by changing environment variables.  The system prompt is defined in `jarvis/bot.py`/`jarvis/cli.py`.

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
   pip install .
   # or install the published package
   # pip install jarvis
   ```

3. **Install ffmpeg** (required for voice transcription).  On Windows you can use [Scoop](https://scoop.sh) or [Winget](https://learn.microsoft.com/windows/package-manager/winget/) to install `ffmpeg`.  Alternatively download a static build and add it to your `PATH`.  Set `FFMPEG_BIN` in your `.env` if it is not in the `PATH`.

4. **Configure environment**:

   * Copy `.env.example` to `.env` and fill in the values appropriate for your setup.  At a minimum you need to set `TELEGRAM_TOKEN` to run the bot.  If you plan to use OpenAI models, provide your `OPENAI_API_KEY`.  For offline speech recognition, download a Russian Vosk model and set `VOSK_MODEL_DIR`.  See comments in `.env.example` for details.
   * Install Ollama and fetch a model if using local LLMs.  For example:

     ```sh
     # install Ollama from https://ollama.com/download and then
     ollama pull llama3.1:8b
     ```

5. **Run the command‑line interface** (optional):

   ```sh
   jarvis-cli
   ```

   Jarvis will greet you and you can start typing commands or natural language.  Type `/exit` to quit.

6. **Run the Telegram bot**:

   ```sh
   jarvis-bot
   ```

   Start chatting with your bot in Telegram.  The bot automatically schedules reminders for tasks, events and reminders and resumes them on restart.

## Usage examples

* “Добавь задачу купить молоко завтра в 18:00” – создаёт задачу с дедлайном завтра в 18:00.
* “Создай событие ‘Звонок с Петром’ завтра в 15:00 на 30 минут” – планирует событие.
* “Напомни через 2 часа разморозить тесто” – ставит одноразовое напоминание.
* “Покажи задачи” – выводит незавершённые задачи.
* “Покажи все задачи” – включает завершённые задачи.
* “Я уже выполнил задачу с курицей” – завершает подходящую задачу без указания ID.
* В Telegram можно нажимать кнопки под задачами, событиями и напоминаниями, чтобы отметить выполненными, отложить или удалить.

## Project structure

* `jarvis/cli.py` – интерактивный интерфейс для терминала с поддержкой LLM, команд и запланированных уведомлений.
* `jarvis/bot.py` – реализация Telegram‑бота на aiogram.  Содержит хендлеры команд, обработку естественного языка, inline‑кнопки и планировщик.
* `jarvis/store.py` – модуль для хранения задач, событий и напоминаний.  Использует JSON‑файлы и поддерживает многопользовательский режим (поле `owner`).
* `jarvis/llm_provider.py` – абстракция над языковыми моделями.  Выбирает Ollama или OpenAI в зависимости от переменных окружения и предоставляет методы `ask` и `ask_json`.
* `jarvis/stt.py` – модуль для распознавания речи.  Работает через офлайн Vosk или онлайн OpenAI Whisper.  Требуется ffmpeg для конвертации аудио.
* `data/` – папка для сохранения JSON‑файлов с вашими данными.  Создаётся автоматически.

## Contributing

Пожалуйста, открывайте issues и pull‑requests для предложений улучшений.  Ветки должны проходить тесты (CLI запускается без ошибок) и обновлять документацию при добавлении новых возможностей.

## License

This project is licensed under the MIT License.
