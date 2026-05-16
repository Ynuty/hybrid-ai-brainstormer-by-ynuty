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
HEALTH_URL = f"{BACKEND_URL}/health"

MODEL_DESCRIPTIONS = {
    "openrouter/openai/gpt-4o": "GPT-4o от OpenAI — холодный рассудок, бизнес-логика и структура.",
    "openrouter/anthropic/claude-3.5-sonnet": (
        "Claude 3.5 Sonnet от Anthropic — тексты, виральность, подача и нестандартный подход."
    ),
    "openrouter/google/gemini-1.5-pro": (
        "Gemini 1.5 Pro от Google — архитектура, инструменты и техническая реализация."
    ),
}

st.set_page_config(page_title="AI Brainstorm", layout="wide")
st.title("AI Brainstorm")
st.caption(f"Бэкенд: `{BACKEND_URL}`")

if "brainstorm_history" not in st.session_state:
    st.session_state.brainstorm_history = []


def _backend_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:1000] or "Бэкенд вернул ошибку без описания."
    return str(data.get("detail") or data)[:1000]


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


def _render_debate_result(data: dict) -> None:
    st.subheader("Финальное отредактированное решение")
    st.caption("Это итоговый Markdown-документ после спора моделей и внесения правок.")
    st.markdown(data.get("final_synthesis", "") or "_пусто_")

    debate_report = data.get("debate_report", "") or "_журнал спора пуст_"
    st.download_button(
        "Скачать журнал спора в Markdown",
        data=debate_report,
        file_name="model_debate_report.md",
        mime="text/markdown",
        key="download_debate_report",
    )

    with st.expander("Ход обсуждения"):
        _render_response_list("Раунд 1: первичные ответы", data.get("initial_responses") or [])
        _render_response_list("Раунд 2: критика и предложения", data.get("critiques") or [])
        _render_response_list("Доработанные ответы", data.get("revised_responses") or [])


with st.sidebar:
    st.header("Состояние")
    try:
        health = requests.get(HEALTH_URL, timeout=5)
        health.raise_for_status()
        health_data = health.json()
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
    for item in reversed(st.session_state.brainstorm_history[-5:]):
        mode_label = "спор" if item.get("mode") == "debate" else "быстрый"
        st.caption(f"{item['created_at']} · {mode_label} · {item['topic']}")


topic = st.text_input("Тема мозгового штурма", placeholder="Например: запуск MVP за 2 недели")

button_cols = st.columns(2)
run_clicked = button_cols[0].button("Запустить", type="primary")
debate_clicked = button_cols[1].button("Столкнуть модели")


def _render_history_entry(entry: dict) -> None:
    if entry.get("mode") == "debate":
        st.info("Показан последний debate-результат из истории текущей сессии.")
        _render_debate_result(entry["data"])
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
            if is_debate:
                _render_debate_result(data)
            else:
                _render_result(data)
elif st.session_state.brainstorm_history:
    _render_history_entry(st.session_state.brainstorm_history[-1])
