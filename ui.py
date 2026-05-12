"""Streamlit UI for AI Brainstorm — calls deployed FastAPI backend."""

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

st.set_page_config(page_title="AI Brainstorm", layout="wide")
st.title("AI Brainstorm")
st.caption(f"Бэкенд: `{BACKEND_URL}`")

topic = st.text_input("Тема мозгового штурма", placeholder="Например: запуск MVP за 2 недели")

if st.button("Запустить", type="primary"):
    if not topic or not topic.strip():
        st.warning("Введите тему.")
    else:
        payload = {"topic": topic.strip()}
        try:
            logger.info("POST %s payload=%s", BRAINSTORM_URL, json.dumps(payload, ensure_ascii=False))
            response = requests.post(
                BRAINSTORM_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=300,
            )
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as exc:
            body = ""
            if exc.response is not None:
                try:
                    body = exc.response.text[:2000]
                except Exception as read_exc:
                    logger.exception("Failed to read error response body: %s", read_exc)
            logger.exception(
                "HTTP error from backend: %s status=%s body=%s",
                exc,
                getattr(exc.response, "status_code", None),
                body,
            )
            st.error(f"Ошибка HTTP: {exc}\n\n{body}")
        except requests.RequestException as exc:
            logger.exception("Request to backend failed: %s", exc)
            st.error(f"Не удалось связаться с бэкендом: {exc}")
        except ValueError as exc:
            logger.exception("Invalid JSON from backend: %s", exc)
            st.error(f"Некорректный ответ сервера (не JSON): {exc}")
        else:
            st.subheader("Тема")
            st.write(data.get("topic", ""))
            st.subheader("Ответы экспертов")
            for item in data.get("agent_responses") or []:
                with st.expander(item.get("role", "Эксперт")):
                    st.markdown(item.get("response", "") or "_пусто_")
            st.subheader("Итоговый синтез")
            st.markdown(data.get("final_synthesis", "") or "_пусто_")
