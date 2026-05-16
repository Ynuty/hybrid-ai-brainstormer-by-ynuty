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
HEALTH_URL = f"{BACKEND_URL}/health"

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
        expert_sections.append(
            f"## {item.get('role', 'Эксперт')} ({status})\n\n"
            f"Модель: `{item.get('model', 'unknown')}`\n\n"
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

    st.subheader("Ответы экспертов")
    for item in agent_responses:
        status_icon = "OK" if item.get("success") else "ERROR"
        title = f"{status_icon} {item.get('role', 'Эксперт')} · {item.get('model', 'unknown')}"
        with st.expander(title, expanded=not item.get("success")):
            if item.get("success"):
                st.markdown(item.get("response", "") or "_пусто_")
            else:
                st.error(item.get("error") or "Эксперт не ответил.")

    st.subheader("Итоговый синтез")
    st.markdown(data.get("final_synthesis", "") or "_пусто_")

    markdown_export = _result_to_markdown(data)
    st.download_button(
        "Скачать результат в Markdown",
        data=markdown_export,
        file_name="brainstorm.md",
        mime="text/markdown",
    )


with st.sidebar:
    st.header("Состояние")
    try:
        health = requests.get(HEALTH_URL, timeout=5)
        health.raise_for_status()
        health_data = health.json()
        st.success("Бэкенд доступен")
        st.caption(f"Экспертов из YAML: {health_data.get('agents_from_yaml', 0)}")
    except requests.RequestException:
        st.warning("Бэкенд пока недоступен")

    st.header("История")
    if not st.session_state.brainstorm_history:
        st.caption("Запросов пока нет.")
    for item in reversed(st.session_state.brainstorm_history[-5:]):
        st.caption(f"{item['created_at']} · {item['topic']}")


topic = st.text_input("Тема мозгового штурма", placeholder="Например: запуск MVP за 2 недели")

run_clicked = st.button("Запустить", type="primary")

if run_clicked:
    if not topic or not topic.strip():
        st.warning("Введите тему.")
    else:
        payload = {"topic": topic.strip()}
        try:
            with st.status("Запускаю мозговой штурм...", expanded=True) as status:
                st.write("Отправляю тему на бэкенд.")
                logger.info("POST %s payload=%s", BRAINSTORM_URL, json.dumps(payload, ensure_ascii=False))
                response = requests.post(
                    BRAINSTORM_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=300,
                )
                st.write("Получаю ответы экспертов и итоговый синтез.")
                if response.status_code >= 400:
                    raise requests.HTTPError(_backend_error_message(response), response=response)
                data = response.json()
                status.update(label="Мозговой штурм готов", state="complete", expanded=False)
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
                    "data": data,
                }
            )
            _render_result(data)
elif st.session_state.brainstorm_history:
    st.info("Показан последний результат из истории текущей сессии.")
    _render_result(st.session_state.brainstorm_history[-1]["data"])
