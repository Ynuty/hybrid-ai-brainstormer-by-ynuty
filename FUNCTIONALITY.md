# AI Brainstorm: функционал проекта

## Назначение

AI Brainstorm — приложение для мозгового штурма с несколькими AI-моделями. Пользователь вводит тему, а система получает ответы от разных экспертных ролей, собирает итоговый Markdown-документ и позволяет отдельно задавать вопросы выбранной модели.

## На чем работает

- Backend: FastAPI в пакете `app/` (точка входа `main.py`).
- Frontend: Streamlit в `ui.py`.
- LLM-вызовы: LiteLLM через OpenRouter.
- Конфигурация моделей и ролей: `agents_config.yaml` (`display_name`, `description`).
- Секреты и инфраструктура: `.env.main`, шаблон `.env.example`.
- Основной API-ключ: `OPENROUTER_API_KEY`.
- Источники контекста: `app/sources/` (файлы, URL, YouTube, аудио).
- Легкий набор зависимостей для Streamlit Cloud / UI-only: `requirements.txt`.
- Полный backend-набор зависимостей: `requirements-backend.txt`.
- Опциональный local Whisper: `requirements-audio.txt`.
- Linux-системные пакеты для полного деплоя: `packages.txt`.

## Структура проекта

| Путь | Назначение |
| --- | --- |
| `main.py` | Точка входа для `uvicorn main:app` |
| `app/main.py` | FastAPI app, routes, health, context endpoints |
| `app/brainstorm.py` | Быстрый brainstorm |
| `app/debate.py` | Спор моделей |
| `app/llm.py` | Общий LiteLLM helper, retry, timeout, semaphore |
| `app/rag.py` | Локальный RAG для выбора релевантных чанков большого контекста |
| `app/sources/file_extract.py` | Извлечение текста из файлов |
| `app/sources/url_fetch.py` | Импорт URL с SSRF-защитой |
| `app/sources/youtube_fetch.py` | YouTube transcripts |
| `app/sources/audio_transcribe.py` | Cloud/local Whisper для аудио |
| `app/sources/import_service.py` | Сборка внешних источников в единый context |
| `jobs.py` | SQLite jobs (`jobs.db`) для background запусков и интерактивного debate |
| `ui.py` | Streamlit frontend |
| `FUTURE_TODO.md` | Свернутые блоки задач на будущее |

## Текущие модели и роли

Конфигурация хранится в `agents_config.yaml`.

| Роль | Модель | Функция |
| --- | --- | --- |
| Продуктовый стратег | `openrouter/openai/gpt-5.1` | Бизнес-логика, рынок, структура, метрики и первые шаги |
| Креативный маркетолог | `openrouter/anthropic/claude-sonnet-4.6` | Тексты, офферы, виральность, каналы и нестандартная подача |
| Технический архитектор | `openrouter/~google/gemini-pro-latest` | Архитектура, инструменты, интеграции, технические риски и MVP |
| Модератор / финальный синтез | `openrouter/openai/gpt-5.1` | Сведение ответов в единый структурированный Markdown-документ |

## Режимы работы

### 1. Быстрый мозговой штурм

Кнопка в UI: `Запустить`.

Endpoint: `POST /brainstorm`.

Ответ отдаётся как SSE stream (`text/event-stream`): UI печатает ответы через `st.write_stream`, чтобы пользователь видел прогресс. Для старого блокирующего JSON-ответа есть `POST /brainstorm/sync`.

Как работает:

1. Пользователь вводит тему.
2. Backend параллельно вызывает всех экспертов из `agents_config.yaml`.
3. Каждый эксперт возвращает Markdown-ответ.
4. Модератор читает ответы экспертов и формирует итоговый синтез.
5. Frontend показывает ответы всех моделей и итоговый Markdown.
6. Результат можно скачать как Markdown-файл.

Можно добавить context из файлов, URL и YouTube через блок `Источники (NotebookLM)` в UI.

### 2. Спор моделей

Кнопка в UI: `Столкнуть модели`.

Endpoint: `POST /brainstorm/debate`.

Как работает:

1. Эксперты дают независимые первичные ответы.
2. Затем модели критикуют ответы друг друга: ищут слабые места, противоречия и предлагают улучшения.
3. После критики эксперты дорабатывают свои ответы.
4. Модератор собирает финальное отредактированное решение.
5. Пользователь получает два результата:
   - финальное решение в Markdown;
   - отдельный скачиваемый Markdown-журнал спора моделей.

Журнал спора включает:

- первичные ответы;
- критику и предложения;
- доработанные ответы;
- итоговое решение модератора.

Режимы:

- `full`: первичные ответы → критика → доработка → синтез (~10 LLM-вызовов);
- `light`: первичные ответы → критика → синтез (~7 LLM-вызовов).
- `interactive_debate=true`: полный спор ставится на паузу после первого раунда (`waiting_for_user`), пользователь вводит критику, затем модели продолжают критику/доработку с её учётом.

### 3. Вопрос выбранной модели

Кнопка в UI: `Спросить выбранную модель`.

Endpoint: `POST /agents/ask`.

Как работает:

1. Пользователь выбирает модель по названию и функции:
   - GPT-5.1 — бизнес-логика, рынок и структура;
   - Claude Sonnet 4.6 — тексты, виральность и нестандартная подача;
   - Gemini Pro Latest — архитектура, инструменты и техническая реализация;
   - GPT-5.1 Модератор — финальный синтез и устранение противоречий.
2. Пользователь задает вопрос выбранной модели.
3. Опционально можно включить чекбокс `Использовать последний результат как контекст`.
4. Backend вызывает только выбранную модель.
5. Ответ показывается как Markdown и может быть скачан отдельным файлом.

### 4. Повторный запуск с контекстом

UI-блок: `Повторный мозговой штурм с контекстом`.

Можно:

- выбрать запись из истории текущей сессии;
- добавить новые файлы;
- добавить URL;
- добавить YouTube-ссылки;
- запустить повторно быстрый brainstorm или спор моделей.

Контекст собирается в Markdown и отправляется в поле `context`.

Перед отправкой UI показывает примерную оценку токенов (тема + комментарии + выбранные файлы). Текстовые файлы считаются через `tiktoken`, бинарные оцениваются по размеру.

## API endpoints

### `GET /health`

Проверяет доступность backend и возвращает:

- статус `ok` / `degraded`;
- список загруженных экспертов из YAML;
- конфигурацию модератора;
- доступность OpenRouter API key;
- лимиты concurrency;
- описание режимов debate;
- `supported_context_types` — список расширений файлов, которые backend принимает;
- `context_features` — включены ли URL, YouTube и audio transcription.

Используется frontend-ом для sidebar, списка моделей и синхронизации допустимых типов файлов.

### `POST /brainstorm`

Быстрый режим мозгового штурма с SSE streaming.

Request:

```json
{
  "topic": "Тема мозгового штурма",
  "context": "Опциональный Markdown-контекст",
  "comments": "Опциональные комментарии пользователя",
  "debate_mode": "full"
}
```

Stream events:

- `chunk`: фрагмент Markdown-текста для `st.write_stream`;
- `final`: итоговый JSON результата;
- `error`: безопасное описание ошибки.

Финальный result содержит:

- `topic`;
- `agent_responses`;
- `final_synthesis`;
- `partial`;
- `failed_agents`.

### `POST /brainstorm/debate`

Запускает спор моделей в фоне. Сразу возвращает `job_id`; результат — через polling.

Request:

```json
{
  "topic": "Тема",
  "debate_mode": "full",
  "context": null,
  "comments": null
}
```

`debate_mode`: `full` (4 этапа, ~10 LLM) или `light` (3 этапа, ~7 LLM, без доработки экспертов).

Response: `{ "job_id", "status", "debate_mode", "poll_url" }`.

Если `interactive_debate=true`, job после первого раунда переходит в `status=waiting_for_user`; затем UI вызывает `POST /jobs/{job_id}/continue`.

### `GET /jobs/{job_id}`

Статус задачи, прогресс по этапам, `partial`, финальный `result` при `status=done`.

Jobs хранятся в SQLite-файле `jobs.db`, поэтому результат можно получить после рестарта uvicorn, пока запись не удалена TTL-cleanup.

### `POST /jobs/{job_id}/continue`

Продолжает интерактивный debate после статуса `waiting_for_user`.

```json
{
  "comment": "Что пользователь хочет раскритиковать или уточнить после первого раунда"
}
```

Response: `{ "job_id", "status", "poll_url" }`.

### `POST /brainstorm/debate/sync`

Блокирующий спор (legacy), тот же pipeline без job.

### `POST /context/extract`

Загрузка файла → текст для контекста. Поддерживаются форматы, близкие к NotebookLM:

- документы: PDF (OCR), DOCX, RTF, ODT, EPUB, TXT/MD, HTML;
- презентации: PPTX/PPT;
- таблицы: XLSX/XLS, CSV, JSON;
- изображения: PNG/JPG/WebP и др. (OCR);
- аудио: MP3/WAV/M4A/OGG/FLAC/WebM (транскрипт Whisper, cloud или local).

Лимиты: `MAX_UPLOAD_MB`, для аудио — `MAX_AUDIO_UPLOAD_MB`, итог обрезается `MAX_CONTEXT_CHARS`.

Response:

```json
{
  "filename": "source.pdf",
  "kind": "file",
  "text": "Извлеченный текст",
  "warning": null
}
```

Для аудио `kind` будет `audio`; текст формируется через Whisper.

### `POST /context/import`

Импорт внешних источников без файла:

```json
{
  "urls": ["https://example.com/article"],
  "youtube_urls": ["https://www.youtube.com/watch?v=..."]
}
```

Response: `{ "sources": [{ "kind", "ref", "text", "warning" }], "combined_text" }`.

- URL: httpx + trafilatura/BeautifulSoup, защита от SSRF;
- YouTube: субтитры через `youtube-transcript-api` (опционально yt-dlp).

Переменные: `ENABLE_URL_IMPORT`, `ENABLE_YOUTUBE_IMPORT`, `ENABLE_AUDIO_TRANSCRIBE`, `URL_FETCH_*`, `AUDIO_TRANSCRIBE_MODE`, `WHISPER_MODEL`.

`GET /health` возвращает `supported_context_types` и `context_features` для UI.

Endpoint защищен тем же `API_SECRET`, если он задан, и rate limit через `slowapi`.

### `POST /brainstorm/jobs`

Фоновый быстрый brainstorm (опционально, через job + polling).

### `POST /agents/ask`

Вопрос одной выбранной модели.

Request:

```json
{
  "role": "Технический архитектор",
  "question": "Как лучше реализовать backend?",
  "context": "Опциональный Markdown-контекст"
}
```

Response содержит:

- `role`;
- `model`;
- `configured_model`;
- `question`;
- `response`;
- `success`;
- `error`.

## Надежность и обработка ошибок

- LLM-вызовы идут через общий helper `_completion_content()`.
- Есть timeout на один вызов модели: `MODEL_TIMEOUT_S`.
- Есть retry-настройки:
  - `MODEL_RETRY_ATTEMPTS`;
  - `MODEL_RETRY_BACKOFF_S`.
- Если отдельный эксперт падает в обычном режиме, backend сохраняет ошибку в ответе конкретного эксперта.
- В debate-режиме каждый этап проверяет, что хотя бы одна модель успешно ответила.
- Пользователю возвращаются безопасные ошибки без полного сырого traceback провайдера.

## Frontend-возможности

Streamlit UI умеет:

- показывать состояние backend;
- отображать список моделей из `/health`;
- запускать быстрый brainstorm;
- запускать спор моделей;
- задавать вопрос выбранной модели;
- показывать ответы в Markdown;
- хранить историю текущей сессии;
- использовать последний результат как контекст для вопроса модели;
- добавлять файлы в контекст через `/context/extract` (документы, OCR, аудио);
- импортировать URL и YouTube через `/context/import` (блок «Источники (NotebookLM)»);
- получать список поддерживаемых типов из `/health` → `supported_context_types`;
- видеть примерную оценку токенов перед запуском;
- получать быстрый brainstorm как streaming-вывод;
- запускать интерактивный спор с паузой после первого круга;
- выбирать режим спора: полный или быстрый;
- экспортировать/импортировать историю сессии (JSON);
- скачивать результаты в Markdown.

## Источники контекста в стиле NotebookLM

Контекст можно собрать из файлов и внешних источников. Это не полный клон NotebookLM: в проекте пока нет цитирования по чанкам и Audio Overview. Сейчас источники конвертируются в Markdown-context для brainstorm/debate.

Для больших context backend включает локальный RAG: текст режется на чанки (`langchain-text-splitters`), векторизуется (`sentence-transformers`) и ищется через FAISS (`faiss-cpu`). В промпт отправляются только top-K релевантных фрагментов по теме. Если RAG-зависимости недоступны, backend безопасно возвращается к обычной обрезке контекста.

### Файлы

Поддерживаемые типы backend возвращает в `/health` → `supported_context_types`.

Основные категории:

| Категория | Форматы |
| --- | --- |
| Документы | `pdf`, `docx`, `rtf`, `odt`, `epub`, `doc`, `txt`, `md`, `html`, `htm` |
| Презентации | `pptx`, `ppt` |
| Таблицы и данные | `xlsx`, `xlsm`, `xls`, `csv`, `json`, `yaml`, `yml`, `xml` |
| Изображения OCR | `png`, `jpg`, `jpeg`, `webp`, `gif`, `bmp`, `tiff`, `tif` |
| Аудио | `mp3`, `wav`, `m4a`, `ogg`, `flac`, `webm`, `mpeg`, `mpga` |

Особенности:

- PDF: сначала извлекается текстовый слой, если его нет — OCR через Tesseract.
- Изображения: OCR через Tesseract.
- DOC: надежность зависит от `antiword`; если его нет, backend просит сохранить в DOCX/PDF.
- Старый PPT: может быть ограниченно поддержан; надежнее PPTX/PDF.
- Аудио: cloud Whisper (`OPENAI_API_KEY`) или local `faster-whisper`.

### URL

`POST /context/import` загружает публичные страницы через `httpx`, извлекает основной текст через `trafilatura`, fallback — BeautifulSoup.

Безопасность:

- разрешены только `http` и `https`;
- заблокированы `localhost`, private IP, link-local и metadata endpoints;
- можно включить allowlist через `URL_FETCH_ALLOWED_HOSTS`.

### YouTube

YouTube-ссылки обрабатываются через `youtube-transcript-api`. Если субтитров нет, endpoint вернет warning. Опциональный fallback через `yt-dlp` управляется `YOUTUBE_USE_YTDLP`.

## Настройки окружения

Основные переменные описаны в `.env.example`.

Минимально нужен:

```env
OPENROUTER_API_KEY=
```

Полезные настройки:

```env
BACKEND_URL=http://127.0.0.1:8000
CORS_ALLOW_ORIGINS=http://localhost:8501,http://127.0.0.1:8501
AGENTS_CONFIG_PATH=agents_config.yaml
MODEL_TIMEOUT_S=120
MODEL_RETRY_ATTEMPTS=2
MODEL_RETRY_BACKOFF_S=1.5
LLM_MAX_CONCURRENT=3
MAX_TOPIC_CHARS=2000
MAX_CONTEXT_CHARS=80000
MAX_COMMENTS_CHARS=10000
MAX_UPLOAD_MB=25
MAX_AUDIO_UPLOAD_MB=50
API_SECRET=
RATE_LIMIT_PER_MINUTE=30
JOBS_DB_PATH=jobs.db
ENABLE_URL_IMPORT=true
ENABLE_YOUTUBE_IMPORT=true
ENABLE_AUDIO_TRANSCRIBE=true
URL_FETCH_TIMEOUT_S=15
URL_FETCH_MAX_BYTES=5000000
URL_FETCH_ALLOWED_HOSTS=
YOUTUBE_USE_YTDLP=false
AUDIO_TRANSCRIBE_MODE=cloud
WHISPER_MODEL=whisper-1
WHISPER_LOCAL_MODEL=base
ENABLE_CONTEXT_RAG=true
RAG_MIN_CONTEXT_CHARS=12000
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=150
RAG_TOP_K=8
RAG_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
JOB_TTL_HOURS=24
DEBATE_JOB_MAX_SECONDS=1800
TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
PDF_OCR_DPI=200
BRAINSTORM_MODEL=openrouter/openai/gpt-5.1
SYNTHESIS_MODEL=openrouter/openai/gpt-5.1
PORT=8000
```

Для полной читаемости сканированных PDF нужен системный Tesseract OCR. Если `tesseract.exe` не доступен в `PATH`, укажите путь в `TESSERACT_PATH`, например:

```env
TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Если API доступен не только локально, задайте `API_SECRET`. UI будет отправлять его в заголовке `X-API-Key`, если переменная также доступна Streamlit-процессу.

Для cloud-аудио транскрипции нужен `OPENAI_API_KEY`. Для local-режима установите `requirements-audio.txt`; на сервере также нужен `ffmpeg`.

## Установка зависимостей

| Сценарий | Команда |
|----------|---------|
| Только Streamlit frontend (UI → удалённый API) | `pip install -r requirements.txt` |
| Локально: API + UI / backend | `pip install -r requirements-backend.txt` |
| Тесты | `pip install -r requirements-dev.txt` |
| Локальная транскрипция аудио (опционально) | `pip install -r requirements-audio.txt` |

**Ошибка «Error installing requirements» на Streamlit Cloud:** теперь `requirements.txt` специально лёгкий и подходит для Cloud. Тяжёлые зависимости (`litellm`, `pymupdf`, `trafilatura`, `faiss-cpu`, `sentence-transformers` и др.) находятся в `requirements-backend.txt`. Бэкенд поднимайте на Render/Railway/Docker с `requirements-backend.txt`.

**Локально в VS Code:** если запускаете весь проект (API + UI), выберите интерпретатор `.venv`, затем `pip install -r requirements-backend.txt`. Не используйте `requirements-audio.txt`, если не нужен offline Whisper (~сотни МБ).

Версия Python: **3.12** (см. `.python-version`). На 3.13 часть пакетов может собираться дольше или падать без MSVC.

### Что где деплоить

| Компонент | Где запускать | Файл зависимостей |
| --- | --- | --- |
| Streamlit UI | Streamlit Cloud или локально | `requirements.txt` |
| FastAPI API | Render/Railway/VPS/Docker/локально | `requirements-backend.txt` |
| Offline Whisper | локально/VPS с ресурсами | `requirements-audio.txt` |

Для Streamlit Cloud обязательно задайте `BACKEND_URL` в Secrets. Он должен указывать на публичный API, не на `127.0.0.1`.

## Запуск

Backend:

```powershell
.\.venv\Scripts\python.exe main.py
```

Frontend:

```powershell
.\.venv\Scripts\streamlit.exe run ui.py
```

## Проверки

```powershell
.\.venv\Scripts\pip.exe install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Smoke-check работающего API:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_check.py http://127.0.0.1:8000
```

Docker:

```powershell
docker compose up --build
```

## Текущий статус проверок

На момент последней проверки:

- `pip install -r requirements.txt` устанавливает лёгкий frontend-набор;
- `pip install -r requirements-backend.txt` устанавливает полный backend-набор;
- тесты: `26 passed`;
- live smoke-check проверяет `/health`, `/context/extract`, `/context/import`;
- `supported_context_types`: 39 типов.

## Ограничения

- In-memory jobs не подходят для нескольких независимых uvicorn workers без Redis/БД.
- URL import не работает с paywall/login-only сайтами.
- YouTube без субтитров требует тяжелый fallback через `yt-dlp` + распознавание речи.
- DOC/PPT старых форматов лучше конвертировать в DOCX/PPTX/PDF.
- NotebookLM export не поддержан без реального образца JSON/ZIP.
