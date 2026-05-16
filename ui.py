"""Streamlit UI for AI Brainstorm — calls deployed FastAPI backend."""

from datetime import datetime
import json
import logging
import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
BRAINSTORM_URL = f"{BACKEND_URL}/brainstorm"
DEBATE_URL = f"{BACKEND_URL}/brainstorm/debate"
ASK_AGENT_URL = f"{BACKEND_URL}/agents/ask"
HEALTH_URL = f"{BACKEND_URL}/health"

MODEL_DESCRIPTIONS = {
    "openrouter/openai/gpt-5.1": "GPT-5.1 от OpenAI — сильная стратегия, рассуждения и структура.",
    "openrouter/anthropic/claude-sonnet-4.6": (
        "Claude Sonnet 4.6 от Anthropic — тексты, виральность, подача и нестандартный подход."
    ),
    "openrouter/~google/gemini-pro-latest": (
        "Gemini Pro Latest от Google — архитектура, инструменты и техническая реализация."
    ),
}

ROLE_FUNCTIONS = {
    "Продуктовый стратег": "бизнес-логика, рынок и структура",
    "Креативный маркетолог": "тексты, виральность и нестандартная подача",
    "Технический архитектор": "архитектура, инструменты и техническая реализация",
    "Модератор": "финальный синтез и устранение противоречий",
}

MODEL_LABELS = {
    "openrouter/openai/gpt-5.1": "GPT-5.1",
    "openrouter/anthropic/claude-sonnet-4.6": "Claude Sonnet 4.6",
    "openrouter/~google/gemini-pro-latest": "Gemini Pro Latest",
}

st.set_page_config(page_title="AI Brainstorm", layout="wide")
st.title("AI Brainstorm")
st.caption(f"Бэкенд: `{BACKEND_URL}`")

if "brainstorm_history" not in st.session_state:
    st.session_state.brainstorm_history = []

if "health_data" not in st.session_state:
    st.session_state.health_data = {}

if "selected_history_index" not in st.session_state:
    st.session_state.selected_history_index = None


def _backend_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:1000] or "Бэкенд вернул ошибку без описания."
    return str(data.get("detail") or data)[:1000]


def _model_display_name(model: str, role: str = "") -> str:
    base_name = MODEL_LABELS.get(model, model)
    if role == "Модератор":
        return f"{base_name} Модератор"
    return base_name


def _agent_option_label(item: dict) -> str:
    model = item.get("model", "unknown")
    role = item.get("role", "")
    function = ROLE_FUNCTIONS.get(role, role or "универсальная помощь")
    return f"{_model_display_name(model, role)} · {function}"


def _history_mode_label(mode: str | None) -> str:
    labels = {
        "fast": "быстрый",
        "debate": "спор",
        "ask_agent": "вопрос",
        "fast_rerun": "повтор",
        "debate_rerun": "повтор спора",
    }
    return labels.get(mode or "", "быстрый")


def _history_title(entry: dict) -> str:
    topic = entry.get("topic") or "без темы"
    if len(topic) > 60:
        topic = f"{topic[:57]}..."
    return f"{entry.get('created_at', '--:--')} · {_history_mode_label(entry.get('mode'))} · {topic}"


def _result_to_markdown(data: dict) -> str:
    expert_sections = []
    for item in data.get("agent_responses") or []:
        status = "готов" if item.get("success") else "ошибка"
        body = item.get("response") or item.get("error") or "_нет ответа_"
        configured_model = item.get("configured_model") or item.get("model", "unknown")
        used_model = item.get("model", "unknown")
        expert_sections.append(
            f"## {item.get('role', 'Эксперт')}\n\n"
            f"**Статус:** {status}\n\n"
            f"**Модель по конфигу:** `{configured_model}`\n\n"
            f"**Фактически ответила:** `{used_model}`\n\n"
            f"{body}"
        )

    return "\n\n".join(
        [
            f"# Brainstorm: {data.get('topic', '')}",
            "## Ответы экспертов",
            "\n\n".join(expert_sections),
            "## Итоговый синтез",
            data.get("final_synthesis") or "_пусто_",
        ]
    )


def _render_result(data: dict) -> None:
    st.subheader("Тема")
    st.write(data.get("topic", ""))

    agent_responses = data.get("agent_responses") or []
    success_count = len([item for item in agent_responses if item.get("success")])
    failed_count = len(agent_responses) - success_count

    metric_cols = st.columns(3)
    metric_cols[0].metric("Экспертов", len(agent_responses))
    metric_cols[1].metric("Готово", success_count)
    metric_cols[2].metric("Ошибок", failed_count)

    st.subheader("Ответы всех AI-моделей")
    for item in agent_responses:
        configured_model = item.get("configured_model") or item.get("model", "unknown")
        used_model = item.get("model", "unknown")
        model_note = MODEL_DESCRIPTIONS.get(configured_model, configured_model)
        status = "готов" if item.get("success") else "ошибка"

        st.markdown(f"### {item.get('role', 'Эксперт')}")
        st.caption(f"{model_note} Статус: {status}.")
        if used_model != configured_model:
            st.warning(f"Фактически ответила fallback-модель: `{used_model}`")
        else:
            st.caption(f"Модель: `{used_model}`")

        if item.get("success"):
            st.markdown(item.get("response", "") or "_пусто_")
        else:
            st.error(item.get("error") or "Эксперт не ответил.")
        st.divider()

    st.subheader("Итоговый синтез")
    st.markdown(data.get("final_synthesis", "") or "_пусто_")

    markdown_export = _result_to_markdown(data)
    st.download_button(
        "Скачать результат в Markdown",
        data=markdown_export,
        file_name="brainstorm.md",
        mime="text/markdown",
        key="download_fast_result",
    )


def _render_response_list(title: str, responses: list[dict]) -> None:
    st.markdown(f"### {title}")
    for item in responses:
        status = "готов" if item.get("success") else "ошибка"
        st.markdown(f"#### {item.get('role', 'Эксперт')}")
        st.caption(f"Модель: `{item.get('model', 'unknown')}` · Статус: {status}")
        if item.get("success"):
            st.markdown(item.get("response", "") or "_пусто_")
        else:
            st.error(item.get("error") or "Эксперт не ответил.")
        st.divider()


def _debate_final_to_markdown(data: dict) -> str:
    return "\n\n".join(
        [
            f"# Итоговое решение: {data.get('topic', '')}",
            data.get("final_synthesis", "") or "_пусто_",
        ]
    )


def _debate_all_to_markdown(data: dict) -> str:
    return "\n\n".join(
        [
            _debate_final_to_markdown(data),
            "## Ход дискуссии",
            data.get("debate_report", "") or "_журнал спора пуст_",
        ]
    )


def _render_debate_result(data: dict) -> None:
    st.subheader("Финальное отредактированное решение")
    st.caption("Это итоговый Markdown-документ после спора моделей и внесения правок.")
    st.markdown(data.get("final_synthesis", "") or "_пусто_")

    debate_report = data.get("debate_report", "") or "_журнал спора пуст_"
    download_cols = st.columns(3)
    download_cols[0].download_button(
        "Скачать итоговое решение",
        data=_debate_final_to_markdown(data),
        file_name="final_solution.md",
        mime="text/markdown",
        key="download_debate_final",
    )
    download_cols[1].download_button(
        "Скачать ход дискуссии",
        data=debate_report,
        file_name="model_debate_discussion.md",
        mime="text/markdown",
        key="download_debate_discussion",
    )
    download_cols[2].download_button(
        "Скачать всё вместе",
        data=_debate_all_to_markdown(data),
        file_name="debate_full_result.md",
        mime="text/markdown",
        key="download_debate_all",
    )

    with st.expander("Ход обсуждения"):
        _render_response_list("Раунд 1: первичные ответы", data.get("initial_responses") or [])
        _render_response_list("Раунд 2: критика и предложения", data.get("critiques") or [])
        _render_response_list("Доработанные ответы", data.get("revised_responses") or [])


def _ask_result_to_markdown(data: dict) -> str:
    return "\n\n".join(
        [
            f"# Ответ модели: {data.get('role', 'Модель')}",
            f"**Модель:** `{data.get('model', 'unknown')}`",
            f"## Вопрос\n{data.get('question', '')}",
            f"## Ответ\n{data.get('response', '') or data.get('error') or '_пусто_'}",
        ]
    )


def _render_ask_result(data: dict) -> None:
    st.subheader(f"Ответ: {data.get('role', 'Модель')}")
    st.caption(f"Модель: `{data.get('model', 'unknown')}`")
    if data.get("success"):
        st.markdown(data.get("response", "") or "_пусто_")
    else:
        st.error(data.get("error") or "Модель не ответила.")

    st.download_button(
        "Скачать ответ в Markdown",
        data=_ask_result_to_markdown(data),
        file_name="agent_answer.md",
        mime="text/markdown",
        key="download_ask_answer",
    )


def _selected_history_entry() -> dict | None:
    history = st.session_state.brainstorm_history
    selected_index = st.session_state.selected_history_index
    if not history:
        return None
    if selected_index is None or not 0 <= selected_index < len(history):
        return history[-1]
    return history[selected_index]


def _history_entry_to_context(entry: dict | None) -> str:
    if not entry:
        return ""

    data = entry.get("data") or {}
    mode = entry.get("mode")

    if mode == "debate":
        return "\n\n".join(
            [
                f"# Контекст последнего спора моделей: {data.get('topic', '')}",
                "## Финальный синтез",
                data.get("final_synthesis") or "_пусто_",
            ]
        )

    if mode == "ask_agent":
        return "\n\n".join(
            [
                f"# Контекст предыдущего вопроса к модели: {data.get('role', '')}",
                f"## Вопрос\n{data.get('question', '')}",
                f"## Ответ\n{data.get('response', '') or data.get('error') or '_пусто_'}",
            ]
        )

    expert_sections = []
    for item in data.get("agent_responses") or []:
        expert_sections.append(
            f"## {item.get('role', 'Эксперт')}\n"
            f"{item.get('response', '') or item.get('error') or '_пусто_'}"
        )
    return "\n\n".join(
        [
            f"# Контекст последнего brainstorm: {data.get('topic', '')}",
            "## Ответы экспертов",
            "\n\n".join(expert_sections),
            "## Итоговый синтез",
            data.get("final_synthesis") or "_пусто_",
        ]
    )


def _last_history_context() -> str:
    return _history_entry_to_context(_selected_history_entry())


def _uploaded_files_context(uploaded_files: list | None) -> str:
    if not uploaded_files:
        return ""

    sections = []
    for uploaded_file in uploaded_files:
        raw = uploaded_file.getvalue()
        text = raw.decode("utf-8", errors="replace")
        if len(text) > 80000:
            text = f"{text[:80000]}\n\n[Файл обрезан до 80000 символов для контекста.]"
        sections.append(
            "\n\n".join(
                [
                    f"## Файл: {uploaded_file.name}",
                    text or "_файл пуст_",
                ]
            )
        )

    return "\n\n".join(["# Контекст из загруженных файлов", *sections])


def _merge_context_parts(*parts: str) -> str | None:
    context = "\n\n".join([part for part in parts if part and part.strip()])
    return context or None


with st.sidebar:
    st.header("Состояние")
    try:
        health = requests.get(HEALTH_URL, timeout=5)
        health.raise_for_status()
        health_data = health.json()
        st.session_state.health_data = health_data
        st.success("Бэкенд доступен")
        st.caption(f"Экспертов из YAML: {health_data.get('agents_from_yaml', 0)}")
        for agent in health_data.get("agents") or []:
            st.caption(f"{agent.get('role')}: `{agent.get('model')}`")
        synthesis = health_data.get("synthesis") or {}
        if synthesis.get("model"):
            st.caption(f"Модератор: `{synthesis.get('model')}`")
    except requests.RequestException:
        st.warning("Бэкенд пока недоступен")

    st.header("История")
    if not st.session_state.brainstorm_history:
        st.caption("Запросов пока нет.")
    else:
        history_indices = list(range(len(st.session_state.brainstorm_history)))
        for index in reversed(history_indices[-8:]):
            item = st.session_state.brainstorm_history[index]
            is_selected = index == st.session_state.selected_history_index
            label = f"{'Выбрано: ' if is_selected else ''}{_history_title(item)}"
            if st.button(label, key=f"show_history_{index}"):
                st.session_state.selected_history_index = index


topic = st.text_input("Тема мозгового штурма", placeholder="Например: запуск MVP за 2 недели")

button_cols = st.columns(2)
run_clicked = button_cols[0].button("Запустить", type="primary")
debate_clicked = button_cols[1].button("Столкнуть модели")

st.divider()
st.subheader("Повторный мозговой штурм с контекстом")

selected_history_entry = _selected_history_entry()
if selected_history_entry:
    st.caption(f"Выбранный контекст: {_history_title(selected_history_entry)}")
else:
    st.caption("История пока пуста. Можно добавить только комментарии и файлы.")

rerun_comments = st.text_area(
    "Комментарии к повторному запуску",
    placeholder="Например: сделай решение дешевле, убери лишние интеграции, добавь план на месяц",
)
use_selected_context = st.checkbox(
    "Использовать выбранную запись истории как контекст",
    value=bool(selected_history_entry),
    disabled=not selected_history_entry,
)
uploaded_context_files = st.file_uploader(
    "Добавить файлы в контекст",
    type=["txt", "md", "json", "csv", "py", "yaml", "yml"],
    accept_multiple_files=True,
)
rerun_cols = st.columns(2)
rerun_fast_clicked = rerun_cols[0].button("Повторить обычный brainstorm")
rerun_debate_clicked = rerun_cols[1].button("Повторить через столкновение моделей")

st.divider()
st.subheader("Спросить выбранную модель")

health_data = st.session_state.health_data or {}
agent_options = [
    {
        "role": agent.get("role", ""),
        "model": agent.get("model", "unknown"),
    }
    for agent in health_data.get("agents", [])
    if agent.get("role")
]
synthesis = health_data.get("synthesis") or {}
if synthesis.get("model"):
    agent_options.append({"role": "Модератор", "model": synthesis.get("model", "unknown")})

if not agent_options:
    agent_options = [
        {"role": "Продуктовый стратег", "model": "openrouter/openai/gpt-5.1"},
        {"role": "Креативный маркетолог", "model": "openrouter/anthropic/claude-sonnet-4.6"},
        {"role": "Технический архитектор", "model": "openrouter/~google/gemini-pro-latest"},
        {"role": "Модератор", "model": "openrouter/openai/gpt-5.1"},
    ]

selected_agent_label = st.selectbox(
    "Выберите модель",
    options=[_agent_option_label(item) for item in agent_options],
)
selected_agent = agent_options[
    [_agent_option_label(item) for item in agent_options].index(selected_agent_label)
]
st.caption(f"Внутренняя роль: {selected_agent['role']} · `{selected_agent['model']}`")
agent_question = st.text_area(
    "Ваш вопрос",
    placeholder="Например: распиши техническую реализацию backend-части подробнее",
)
use_last_context = st.checkbox(
    "Использовать последний результат как контекст",
    value=bool(st.session_state.brainstorm_history),
    disabled=not st.session_state.brainstorm_history,
)
ask_clicked = st.button("Спросить выбранную модель")


def _render_history_entry(entry: dict) -> None:
    if entry.get("mode") == "debate":
        st.info("Показан последний debate-результат из истории текущей сессии.")
        _render_debate_result(entry["data"])
    elif entry.get("mode") == "ask_agent":
        st.info("Показан последний ответ выбранной модели из истории текущей сессии.")
        _render_ask_result(entry["data"])
    else:
        st.info("Показан последний быстрый результат из истории текущей сессии.")
        _render_result(entry["data"])


if run_clicked or debate_clicked:
    if not topic or not topic.strip():
        st.warning("Введите тему.")
    else:
        payload = {"topic": topic.strip()}
        is_debate = debate_clicked
        request_url = DEBATE_URL if is_debate else BRAINSTORM_URL
        mode = "debate" if is_debate else "fast"
        status_title = "Столкновение моделей запущено..." if is_debate else "Запускаю мозговой штурм..."
        status_done = "Спор моделей завершён" if is_debate else "Мозговой штурм готов"
        timeout_s = 900 if is_debate else 300
        try:
            with st.status(status_title, expanded=True) as status:
                st.write("Отправляю тему на бэкенд.")
                logger.info("POST %s payload=%s", request_url, json.dumps(payload, ensure_ascii=False))
                response = requests.post(
                    request_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout_s,
                )
                if is_debate:
                    st.write("Модели дают первичные ответы, критикуют друг друга и дорабатывают решение.")
                else:
                    st.write("Получаю ответы экспертов и итоговый синтез.")
                if response.status_code >= 400:
                    raise requests.HTTPError(_backend_error_message(response), response=response)
                data = response.json()
                status.update(label=status_done, state="complete", expanded=False)
        except requests.HTTPError as exc:
            logger.exception(
                "HTTP error from backend: %s status=%s",
                exc,
                getattr(exc.response, "status_code", None),
            )
            st.error(f"Ошибка бэкенда: {exc}")
        except requests.RequestException as exc:
            logger.exception("Request to backend failed: %s", exc)
            st.error(f"Не удалось связаться с бэкендом: {exc}")
        except ValueError as exc:
            logger.exception("Invalid JSON from backend: %s", exc)
            st.error(f"Некорректный ответ сервера (не JSON): {exc}")
        else:
            st.session_state.brainstorm_history.append(
                {
                    "created_at": datetime.now().strftime("%H:%M"),
                    "topic": data.get("topic", ""),
                    "mode": mode,
                    "data": data,
                }
            )
            st.session_state.selected_history_index = len(st.session_state.brainstorm_history) - 1
            if is_debate:
                _render_debate_result(data)
            else:
                _render_result(data)
elif rerun_fast_clicked or rerun_debate_clicked:
    selected_context = _history_entry_to_context(selected_history_entry) if use_selected_context else ""
    files_context = _uploaded_files_context(uploaded_context_files)
    combined_context = _merge_context_parts(selected_context, files_context)
    rerun_topic = (topic or "").strip() or (selected_history_entry or {}).get("topic", "").strip()

    if not rerun_topic:
        st.warning("Введите тему или выберите запись истории для повторного запуска.")
    else:
        is_debate_rerun = rerun_debate_clicked
        request_url = DEBATE_URL if is_debate_rerun else BRAINSTORM_URL
        mode = "debate_rerun" if is_debate_rerun else "fast_rerun"
        payload = {
            "topic": rerun_topic,
            "context": combined_context,
            "comments": rerun_comments.strip() or None,
        }
        status_title = (
            "Повторное столкновение моделей запущено..."
            if is_debate_rerun
            else "Повторный мозговой штурм запущен..."
        )
        status_done = "Повторный запуск завершён"
        timeout_s = 900 if is_debate_rerun else 300

        try:
            with st.status(status_title, expanded=True) as status:
                st.write("Отправляю тему, контекст и комментарии на бэкенд.")
                logger.info("POST %s payload=%s", request_url, json.dumps(payload, ensure_ascii=False))
                response = requests.post(
                    request_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout_s,
                )
                if response.status_code >= 400:
                    raise requests.HTTPError(_backend_error_message(response), response=response)
                data = response.json()
                status.update(label=status_done, state="complete", expanded=False)
        except requests.HTTPError as exc:
            logger.exception(
                "HTTP error from backend: %s status=%s",
                exc,
                getattr(exc.response, "status_code", None),
            )
            st.error(f"Ошибка бэкенда: {exc}")
        except requests.RequestException as exc:
            logger.exception("Request to backend failed: %s", exc)
            st.error(f"Не удалось связаться с бэкендом: {exc}")
        except ValueError as exc:
            logger.exception("Invalid JSON from backend: %s", exc)
            st.error(f"Некорректный ответ сервера (не JSON): {exc}")
        else:
            st.session_state.brainstorm_history.append(
                {
                    "created_at": datetime.now().strftime("%H:%M"),
                    "topic": data.get("topic", rerun_topic),
                    "mode": mode,
                    "data": data,
                }
            )
            st.session_state.selected_history_index = len(st.session_state.brainstorm_history) - 1
            if is_debate_rerun:
                _render_debate_result(data)
            else:
                _render_result(data)
elif ask_clicked:
    if not agent_question or not agent_question.strip():
        st.warning("Введите вопрос для выбранной модели.")
    else:
        payload = {
            "role": selected_agent["role"],
            "question": agent_question.strip(),
            "context": _last_history_context() if use_last_context else None,
        }
        try:
            with st.status("Отправляю вопрос выбранной модели...", expanded=True) as status:
                logger.info("POST %s payload=%s", ASK_AGENT_URL, json.dumps(payload, ensure_ascii=False))
                response = requests.post(
                    ASK_AGENT_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=300,
                )
                st.write(f"Ожидаю ответ: {selected_agent['role']} · {selected_agent['model']}")
                if response.status_code >= 400:
                    raise requests.HTTPError(_backend_error_message(response), response=response)
                data = response.json()
                status.update(label="Ответ выбранной модели готов", state="complete", expanded=False)
        except requests.HTTPError as exc:
            logger.exception(
                "HTTP error from backend: %s status=%s",
                exc,
                getattr(exc.response, "status_code", None),
            )
            st.error(f"Ошибка бэкенда: {exc}")
        except requests.RequestException as exc:
            logger.exception("Request to backend failed: %s", exc)
            st.error(f"Не удалось связаться с бэкендом: {exc}")
        except ValueError as exc:
            logger.exception("Invalid JSON from backend: %s", exc)
            st.error(f"Некорректный ответ сервера (не JSON): {exc}")
        else:
            st.session_state.brainstorm_history.append(
                {
                    "created_at": datetime.now().strftime("%H:%M"),
                    "topic": data.get("question", ""),
                    "mode": "ask_agent",
                    "data": data,
                }
            )
            st.session_state.selected_history_index = len(st.session_state.brainstorm_history) - 1
            _render_ask_result(data)
elif st.session_state.brainstorm_history:
    _render_history_entry(_selected_history_entry() or st.session_state.brainstorm_history[-1])
