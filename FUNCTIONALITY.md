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

Как работает:

1. Пользователь вводит тему.
2. Backend параллельно вызывает всех экспертов из `agents_config.yaml`.
3. Каждый эксперт возвращает Markdown-ответ.
4. Модератор читает ответы экспертов и формирует итоговый синтез.
5. Frontend показывает ответы всех моделей и итоговый Markdown.
6. Результат можно скачать как Markdown-файл.

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

## API endpoints

### `GET /health`

Проверяет доступность backend и возвращает список загруженных экспертов из YAML.

Используется frontend-ом для sidebar и списка доступных моделей.

### `POST /brainstorm`

Быстрый режим мозгового штурма.

Request:

```json
{
  "topic": "Тема мозгового штурма"
}
```

Response содержит:

- `topic`;
- `agent_responses`;
- `final_synthesis`.

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

### `GET /jobs/{job_id}`

Статус задачи, прогресс по этапам, `partial`, финальный `result` при `status=done`.

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
- выбирать режим спора: полный или быстрый;
- экспортировать/импортировать историю сессии (JSON);
- скачивать результаты в Markdown.

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
TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
PDF_OCR_DPI=200
BRAINSTORM_MODEL=openrouter/openai/gpt-5.1
SYNTHESIS_MODEL=openrouter/openai/gpt-5.1
```

Для полной читаемости сканированных PDF нужен системный Tesseract OCR. Если `tesseract.exe` не доступен в `PATH`, укажите путь в `TESSERACT_PATH`, например:

```env
TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
```

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

Docker:

```powershell
docker compose up --build
```
