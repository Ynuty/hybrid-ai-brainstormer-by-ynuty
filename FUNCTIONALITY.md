# AI Brainstorm: функционал проекта

## Назначение

AI Brainstorm — приложение для мозгового штурма с несколькими AI-моделями. Пользователь вводит тему, а система получает ответы от разных экспертных ролей, собирает итоговый Markdown-документ и позволяет отдельно задавать вопросы выбранной модели.

## На чем работает

- Backend: FastAPI в `main.py`.
- Frontend: Streamlit в `ui.py`.
- LLM-вызовы: LiteLLM через OpenRouter.
- Конфигурация моделей: `agents_config.yaml`.
- Переменные окружения: `.env` / `.env.main`, пример в `.env.example`.
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

Режим спора моделей.

Request:

```json
{
  "topic": "Тема мозгового штурма"
}
```

Response содержит:

- `topic`;
- `mode`;
- `initial_responses`;
- `critiques`;
- `revised_responses`;
- `final_synthesis`;
- `debate_report`.

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
BRAINSTORM_MODEL=openrouter/openai/gpt-5.1
SYNTHESIS_MODEL=openrouter/openai/gpt-5.1
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

Проверка Python-синтаксиса:

```powershell
.\.venv\Scripts\python.exe -m py_compile main.py ui.py
```

Проверка YAML:

```powershell
.\.venv\Scripts\python.exe -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('agents_config.yaml').read_text(encoding='utf-8')); print('YAML OK')"
```

Проверка зарегистрированных FastAPI routes:

```powershell
.\.venv\Scripts\python.exe -c "import main; print('\n'.join(sorted(route.path for route in main.app.routes)))"
```
