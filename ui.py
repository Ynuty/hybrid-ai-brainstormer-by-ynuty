"""Streamlit UI for AI Brainstorm — calls deployed FastAPI backend."""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import time
import uuid

import requests
import streamlit as st
import tiktoken
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env.main")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("%s must be an integer; using %d", name, default)
        return default


BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
BRAINSTORM_URL = f"{BACKEND_URL}/brainstorm"
DEBATE_URL = f"{BACKEND_URL}/brainstorm/debate"
ASK_AGENT_URL = f"{BACKEND_URL}/agents/ask"
HEALTH_URL = f"{BACKEND_URL}/health"
EXTRACT_URL = f"{BACKEND_URL}/context/extract"
IMPORT_URL = f"{BACKEND_URL}/context/import"
API_SECRET = os.getenv("API_SECRET", "").strip()
API_HEADERS = {"X-API-Key": API_SECRET} if API_SECRET else {}
JSON_HEADERS = {**API_HEADERS, "Content-Type": "application/json"}
JOB_POLL_INTERVAL_S = 2
JOB_POLL_TIMEOUT_S = 1800

DEBATE_MODE_OPTIONS = {
    "light": (
        "Быстрый спор",
        "3 этапа · ~7 вызовов LLM · дешевле и быстрее. "
        "Первичные ответы → критика → итог модератора (без доработки экспертов).",
    ),
    "full": (
        "Полный спор",
        "4 этапа · ~10 вызовов LLM · максимум качества. "
        "Первичные ответы → критика → доработка каждого эксперта → итог модератора.",
    ),
}
DEFAULT_SUPPORTED_CONTEXT_FILE_TYPES = [
    "pdf",
    "pptx",
    "ppt",
    "xlsx",
    "xlsm",
    "xls",
    "docx",
    "rtf",
    "odt",
    "epub",
    "doc",
    "json",
    "csv",
    "txt",
    "md",
    "html",
    "htm",
    "yaml",
    "yml",
    "xml",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "mp3",
    "wav",
    "m4a",
    "ogg",
    "flac",
    "webm",
]

TEXT_TOKEN_ESTIMATE_EXTENSIONS = {
    "txt",
    "md",
    "markdown",
    "json",
    "csv",
    "py",
    "yaml",
    "yml",
    "xml",
    "html",
    "htm",
    "log",
    "srt",
    "vtt",
}
BYTES_PER_TOKEN_ESTIMATE = 4
TOKEN_BUDGET_NOTICE_THRESHOLD = 20_000
TOKEN_BUDGET_WARNING_THRESHOLD = 80_000


def _supported_file_types() -> list[str]:
    types = (st.session_state.get("health_data") or {}).get("supported_context_types")
    if types:
        return types
    return DEFAULT_SUPPORTED_CONTEXT_FILE_TYPES


@st.cache_resource
def _token_encoder():
    return tiktoken.get_encoding("cl100k_base")


def _count_text_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        return len(_token_encoder().encode(text))
    except Exception as exc:
        logger.warning("tiktoken estimate failed; using char fallback: %s", exc)
        return max(1, len(text) // BYTES_PER_TOKEN_ESTIMATE)


def _uploaded_file_token_estimate(uploaded_file) -> tuple[int, str]:
    raw = uploaded_file.getvalue()
    suffix = Path(uploaded_file.name).suffix.lstrip(".").lower()
    if suffix in TEXT_TOKEN_ESTIMATE_EXTENSIONS:
        text = raw.decode("utf-8", errors="replace")
        return _count_text_tokens(text), "text"
    return max(1, len(raw) // BYTES_PER_TOKEN_ESTIMATE), "bytes"


def _prompt_token_estimate(topic_text: str, comments_text: str, uploaded_files: list | None) -> dict:
    topic_tokens = _count_text_tokens(topic_text)
    comments_tokens = _count_text_tokens(comments_text)
    file_tokens = 0
    binary_files = 0
    file_count = len(uploaded_files or [])
    for uploaded_file in uploaded_files or []:
        tokens, source = _uploaded_file_token_estimate(uploaded_file)
        file_tokens += tokens
        if source == "bytes":
            binary_files += 1
    total_tokens = topic_tokens + comments_tokens + file_tokens
    return {
        "topic_tokens": topic_tokens,
        "comments_tokens": comments_tokens,
        "file_tokens": file_tokens,
        "file_count": file_count,
        "binary_files": binary_files,
        "total_tokens": total_tokens,
    }


def _render_prompt_token_info(estimate: dict) -> None:
    total = estimate["total_tokens"]
    file_count = estimate["file_count"]
    binary_files = estimate["binary_files"]
    suffix = ""
    if binary_files:
        suffix = (
            f" {binary_files} бинарн. файл(ов) оценены по размеру; "
            "после извлечения текста реальное число токенов может отличаться."
        )
    level = "нормальный"
    if total >= TOKEN_BUDGET_WARNING_THRESHOLD:
        level = "очень большой"
    elif total >= TOKEN_BUDGET_NOTICE_THRESHOLD:
        level = "крупный"
    st.info(
        "Оценка промпта перед отправкой: "
        f"~{total:,} токенов ({level}). "
        f"Тема: ~{estimate['topic_tokens']:,}, "
        f"комментарии: ~{estimate['comments_tokens']:,}, "
        f"файлы ({file_count}): ~{estimate['file_tokens']:,}."
        f"{suffix}".replace(",", " ")
    )

st.set_page_config(page_title="AI Brainstorm", layout="wide")
st.title("AI Brainstorm")
st.caption(f"Бэкенд: `{BACKEND_URL}`")

if "brainstorm_history" not in st.session_state:
    st.session_state.brainstorm_history = []

if "health_data" not in st.session_state:
    st.session_state.health_data = {}

if "selected_history_index" not in st.session_state:
    st.session_state.selected_history_index = None

if "interactive_debate_job" not in st.session_state:
    st.session_state.interactive_debate_job = None


def _backend_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:1000] or "Бэкенд вернул ошибку без описания."
    return str(data.get("detail") or data)[:1000]


def _post_json(url: str, payload: dict, *, timeout: int = 60) -> dict:
    response = requests.post(url, json=payload, headers=JSON_HEADERS, timeout=timeout)
    if response.status_code >= 400:
        raise requests.HTTPError(_backend_error_message(response), response=response)
    return response.json()


def _post_brainstorm_stream(payload: dict) -> dict:
    final_data: dict | None = None

    def _events():
        nonlocal final_data
        event_name = "message"
        data_lines: list[str] = []
        with requests.post(
            BRAINSTORM_URL,
            json=payload,
            headers={**JSON_HEADERS, "Accept": "text/event-stream"},
            timeout=300,
            stream=True,
        ) as response:
            if response.status_code >= 400:
                raise requests.HTTPError(_backend_error_message(response), response=response)
            for raw_line in response.iter_lines(decode_unicode=True):
                line = raw_line or ""
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").strip())
                    continue
                if line == "" and data_lines:
                    payload_text = "\n".join(data_lines)
                    data_lines = []
                    try:
                        event_payload = json.loads(payload_text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(f"Некорректный SSE payload: {exc}") from exc

                    current_event = event_payload.get("event") or event_name
                    event_name = "message"
                    if current_event == "chunk":
                        yield event_payload.get("text", "")
                    elif current_event == "final":
                        final_data = event_payload.get("result") or {}
                    elif current_event == "error":
                        raise RuntimeError(event_payload.get("detail") or "Streaming error")

    st.write_stream(_events())
    if not final_data:
        raise RuntimeError("Бэкенд завершил stream без финального результата.")
    return final_data


def _get_json(url: str, *, timeout: int = 30) -> dict:
    response = requests.get(url, headers=API_HEADERS, timeout=timeout)
    if response.status_code >= 400:
        raise requests.HTTPError(_backend_error_message(response), response=response)
    return response.json()


def _handle_api_errors(action):
    try:
        return action()
    except requests.HTTPError as exc:
        logger.exception("HTTP error: %s", exc)
        st.error(f"Ошибка бэкенда: {exc}")
    except requests.RequestException as exc:
        logger.exception("Request failed: %s", exc)
        st.error(f"Не удалось связаться с бэкендом: {exc}")
    except (ValueError, TimeoutError, RuntimeError) as exc:
        logger.exception("Operation failed: %s", exc)
        st.error(str(exc))
    return None


def _debate_history_mode(debate_mode: str, *, rerun: bool = False) -> str:
    suffix = "_rerun" if rerun else ""
    if debate_mode == "light":
        return f"debate_light{suffix}"
    return f"debate_full{suffix}"


def _poll_debate_job(job_id: str, status) -> dict:
    job_url = f"{BACKEND_URL}/jobs/{job_id}"
    deadline = time.time() + JOB_POLL_TIMEOUT_S
    progress_bar = st.progress(0.0)
    progress_caption = st.empty()

    while time.time() < deadline:
        job_data = _get_json(job_url, timeout=30)
        job_status = job_data.get("status")
        progress = job_data.get("progress") or {}
        stage_index = progress.get("stage_index") or 0
        stage_total = progress.get("stage_total") or 1
        message = progress.get("message") or "Выполняется..."
        if stage_total > 0:
            progress_bar.progress(min(stage_index / stage_total, 1.0))
        progress_caption.caption(f"Этап {stage_index}/{stage_total}: {message}")
        status.write(message)

        if job_status == "done":
            result = job_data.get("result")
            if not result:
                raise RuntimeError("Задача завершена, но результат пуст.")
            progress_bar.progress(1.0)
            return result
        if job_status == "waiting_for_user":
            progress_caption.caption("Интерактивный спор ждёт вашу критику.")
            status.write("Первичный раунд готов. Добавьте комментарий, чтобы продолжить.")
            return {
                "waiting_for_user": True,
                "job_id": job_id,
                "topic": job_data.get("topic"),
                "partial": job_data.get("partial") or {},
            }
        if job_status == "failed":
            raise RuntimeError(job_data.get("error") or "Спор моделей завершился с ошибкой.")
        time.sleep(JOB_POLL_INTERVAL_S)

    raise TimeoutError("Превышено время ожидания спора моделей. Проверьте бэкенд или повторите позже.")


def _run_debate_with_job(payload: dict, status, *, rerun: bool = False) -> tuple[dict, str]:
    logger.info("POST %s debate_mode=%s", DEBATE_URL, payload.get("debate_mode"))
    start_data = _post_json(DEBATE_URL, payload, timeout=60)
    job_id = start_data.get("job_id")
    if not job_id:
        raise RuntimeError("Бэкенд не вернул job_id для спора моделей.")
    status.write(f"Задача создана: `{job_id}`")
    result = _poll_debate_job(job_id, status)
    if result.get("waiting_for_user"):
        return result, "debate_interactive_waiting"
    history_mode = _debate_history_mode(result.get("debate_mode", payload.get("debate_mode", "full")), rerun=rerun)
    return result, history_mode


def _agent_option_label(item: dict) -> str:
    display = item.get("display_name") or item.get("role", "Модель")
    description = item.get("description") or item.get("role", "")
    return f"{display} · {description}"


def _history_mode_label(mode: str | None) -> str:
    labels = {
        "fast": "быстрый",
        "debate": "спор",
        "debate_full": "полный спор",
        "debate_light": "быстрый спор",
        "debate_interactive": "интерактивный спор",
        "debate_interactive_waiting": "интерактивный спор (пауза)",
        "ask_agent": "вопрос",
        "fast_rerun": "повтор",
        "debate_rerun": "повтор спора",
        "debate_full_rerun": "повтор полного спора",
        "debate_light_rerun": "повтор быстрого спора",
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

    if data.get("partial"):
        st.warning("Частичный результат: не все эксперты ответили успешно.")
        for failed in data.get("failed_agents") or []:
            st.caption(f"— {failed.get('role')}: {failed.get('error')}")

    st.subheader("Ответы всех AI-моделей")
    for item in agent_responses:
        configured_model = item.get("configured_model") or item.get("model", "unknown")
        used_model = item.get("model", "unknown")
        model_note = configured_model
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
        key=f"download_fast_result_{uuid.uuid4().hex}",
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
    debate_mode = data.get("debate_mode", "full")
    mode_label = DEBATE_MODE_OPTIONS.get(debate_mode, DEBATE_MODE_OPTIONS["full"])[0]
    st.caption(f"Режим спора: **{mode_label}** — {DEBATE_MODE_OPTIONS.get(debate_mode, ('', ''))[1]}")
    debate_report = data.get("debate_report", "") or "_журнал спора пуст_"
    download_cols = st.columns(3)
    download_cols[0].download_button(
        "Скачать итоговое решение",
        data=_debate_final_to_markdown(data),
        file_name="final_solution.md",
        mime="text/markdown",
        key=f"download_debate_final_{uuid.uuid4().hex}",
    )
    download_cols[1].download_button(
        "Скачать ход дискуссии",
        data=debate_report,
        file_name="model_debate_discussion.md",
        mime="text/markdown",
        key=f"download_debate_discussion_{uuid.uuid4().hex}",
    )
    download_cols[2].download_button(
        "Скачать всё вместе",
        data=_debate_all_to_markdown(data),
        file_name="debate_full_result.md",
        mime="text/markdown",
        key=f"download_debate_all_{uuid.uuid4().hex}",
    )

    with st.expander("Итоговое решение", expanded=True):
        st.caption("Это итоговый Markdown-документ после спора моделей и внесения правок.")
        st.markdown(data.get("final_synthesis", "") or "_пусто_")

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
        key=f"download_ask_answer_{uuid.uuid4().hex}",
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

    if (mode or "").startswith("debate"):
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


def _extract_file_via_backend(uploaded_file) -> str:
    try:
        response = requests.post(
            EXTRACT_URL,
            files={"file": (uploaded_file.name, uploaded_file.getvalue())},
            headers=API_HEADERS,
            timeout=120,
        )
        if response.status_code < 400:
            return response.json().get("text", "") or "_файл пуст_"
    except requests.RequestException as exc:
        logger.warning("Backend extract failed for %s: %s", uploaded_file.name, exc)
    return _uploaded_file_to_text_local(uploaded_file)


def _uploaded_file_to_text_local(uploaded_file) -> str:
    return uploaded_file.getvalue().decode("utf-8", errors="replace")


def _uploaded_files_context(uploaded_files: list | None) -> str:
    if not uploaded_files:
        return ""

    sections = []
    for uploaded_file in uploaded_files:
        text = _extract_file_via_backend(uploaded_file)
        sections.append(
            "\n\n".join(
                [
                    f"## Файл: {uploaded_file.name}",
                    text or "_файл пуст_",
                ]
            )
        )

    return "\n\n".join(["# Контекст из загруженных файлов", *sections])


def _import_remote_via_backend(urls_text: str, youtube_text: str) -> str:
    urls = [line.strip() for line in (urls_text or "").splitlines() if line.strip()]
    youtube_urls = [line.strip() for line in (youtube_text or "").splitlines() if line.strip()]
    if not urls and not youtube_urls:
        return ""

    try:
        response = requests.post(
            IMPORT_URL,
            json={"urls": urls, "youtube_urls": youtube_urls},
            headers=JSON_HEADERS,
            timeout=180,
        )
        if response.status_code < 400:
            data = response.json()
            for source in data.get("sources") or []:
                warning = source.get("warning")
                if warning:
                    st.warning(f"{source.get('ref')}: {warning}")
            return data.get("combined_text", "") or ""
        st.warning(f"Импорт URL/YouTube: {_backend_error_message(response)}")
    except requests.RequestException as exc:
        logger.warning("Backend import failed: %s", exc)
        st.warning(f"Не удалось импортировать URL/YouTube: {exc}")
    return ""


def _build_sources_context(
    uploaded_files: list | None,
    urls_text: str = "",
    youtube_text: str = "",
) -> str:
    parts = [
        _uploaded_files_context(uploaded_files),
        _import_remote_via_backend(urls_text, youtube_text),
    ]
    merged = _merge_context_parts(*parts)
    return merged or ""


def _merge_context_parts(*parts: str) -> str | None:
    context = "\n\n".join([part for part in parts if part and part.strip()])
    return context or None


with st.sidebar:
    st.header("Состояние")
    try:
        health = requests.get(HEALTH_URL, headers=API_HEADERS, timeout=5)
        health.raise_for_status()
        health_data = health.json()
        st.session_state.health_data = health_data
        if health_data.get("status") == "degraded":
            st.warning("Бэкенд degraded")
            st.caption(health_data.get("readiness_message") or "Проверьте ключи в .env.main")
        else:
            st.success("Бэкенд доступен")
        st.caption(f"Экспертов из YAML: {health_data.get('agents_from_yaml', 0)}")
        for agent in health_data.get("agents") or []:
            label = agent.get("display_name") or agent.get("role")
            st.caption(f"{label}: `{agent.get('model')}`")
        synthesis = health_data.get("synthesis") or {}
        if synthesis.get("model"):
            mod_label = synthesis.get("display_name") or "Модератор"
            st.caption(f"{mod_label}: `{synthesis.get('model')}`")
        openrouter = health_data.get("openrouter") or {}
        if openrouter.get("required") and not openrouter.get("api_key_configured"):
            st.warning("Добавьте OPENROUTER_API_KEY в .env.main")
    except requests.RequestException:
        st.warning("Бэкенд недоступен. Запустите API: python main.py")
        st.session_state.health_data = {}

    st.header("История")
    export_payload = json.dumps(
        {"schema_version": 1, "entries": st.session_state.brainstorm_history},
        ensure_ascii=False,
        indent=2,
    )
    st.download_button(
        "Экспорт истории",
        data=export_payload,
        file_name="brainstorm_history.json",
        mime="application/json",
        key=f"export_history_{uuid.uuid4().hex}",
    )
    imported = st.file_uploader("Импорт истории", type=["json"], key="import_history")
    if imported is not None:
        try:
            imported_data = json.loads(imported.getvalue().decode("utf-8"))
            if imported_data.get("schema_version") == 1:
                st.session_state.brainstorm_history = imported_data.get("entries") or []
                st.success(f"Импортировано записей: {len(st.session_state.brainstorm_history)}")
            else:
                st.error("Неподдерживаемый формат истории.")
        except (ValueError, json.JSONDecodeError) as exc:
            st.error(f"Не удалось прочитать JSON: {exc}")

    st.header("Записи")
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


topic_tab, comments_tab = st.tabs(["Тема", "Комментарии"])
with topic_tab:
    topic = st.text_input("Тема мозгового штурма", placeholder="Например: запуск MVP за 2 недели")
with comments_tab:
    initial_comments = st.text_area(
        "Что нужно получить и на чём сделать акцент",
        placeholder=(
            "Например: нужен практичный план запуска, акцент на дешёвую реализацию, "
            "B2B-аудиторию и быстрые тесты спроса"
        ),
    )
    with st.expander("Источники (NotebookLM)", expanded=False):
        st.caption("Сайты, YouTube и файлы ниже — в контекст первого запуска.")
        initial_context_urls = st.text_area(
            "Ссылки на статьи / сайты (по одной на строку)",
            key="initial_context_urls",
            placeholder="https://example.com/article",
        )
        initial_context_youtube = st.text_area(
            "YouTube-ссылки (по одной на строку)",
            key="initial_context_youtube",
            placeholder="https://www.youtube.com/watch?v=...",
        )
    initial_context_files = st.file_uploader(
        "Добавить файлы в контекст первого запуска",
        type=_supported_file_types(),
        accept_multiple_files=True,
        key="initial_context_files",
        help="PDF, Office, изображения (OCR), аудио (транскрипт), EPUB и др.",
    )

initial_prompt_estimate = _prompt_token_estimate(topic, initial_comments, initial_context_files)
_render_prompt_token_info(initial_prompt_estimate)

button_cols = st.columns(2)
run_clicked = button_cols[0].button("Запустить", type="primary")
debate_clicked = button_cols[1].button("Столкнуть модели")

st.subheader("Режим спора моделей")
debate_mode_labels = [DEBATE_MODE_OPTIONS[key][0] for key in DEBATE_MODE_OPTIONS]
debate_mode_keys = list(DEBATE_MODE_OPTIONS.keys())
selected_debate_label = st.radio(
    "Как запускать столкновение моделей",
    options=debate_mode_labels,
    index=debate_mode_labels.index(DEBATE_MODE_OPTIONS["full"][0]),
    horizontal=True,
)
selected_debate_mode = debate_mode_keys[debate_mode_labels.index(selected_debate_label)]
st.caption(DEBATE_MODE_OPTIONS[selected_debate_mode][1])
interactive_debate = st.checkbox(
    "Интерактивный спор: остановиться после первого круга и дать мой комментарий",
    value=False,
    help="Работает как полный спор: после первичных ответов job перейдёт в waiting_for_user.",
)
if interactive_debate and selected_debate_mode != "full":
    st.info("Интерактивный спор использует полный режим, чтобы был раунд доработки.")

if st.session_state.interactive_debate_job:
    pending = st.session_state.interactive_debate_job
    st.info(f"Интерактивный спор ждёт комментарий: `{pending.get('job_id')}`")
    partial = pending.get("partial") or {}
    with st.expander("Первичные ответы экспертов", expanded=True):
        for item in partial.get("initial_responses") or []:
            st.markdown(f"### {item.get('role', 'Эксперт')}")
            st.markdown(item.get("response") or item.get("error") or "_пусто_")
    user_debate_comment = st.text_area(
        "Ваша критика / уточнения для раунда доработки",
        key="interactive_debate_comment",
        placeholder="Например: учтите бюджет, уберите сложные интеграции, добавьте риски по срокам...",
    )
    continue_interactive_clicked = st.button("Продолжить спор с моим комментарием")
    if continue_interactive_clicked:
        if not user_debate_comment.strip():
            st.warning("Введите комментарий для продолжения спора.")
        else:
            try:
                with st.status("Продолжаю интерактивный спор...", expanded=True) as status:
                    _post_json(
                        f"{BACKEND_URL}/jobs/{pending['job_id']}/continue",
                        {"comment": user_debate_comment.strip()},
                        timeout=60,
                    )
                    data = _poll_debate_job(pending["job_id"], status)
                    status.update(label="Интерактивный спор завершён", state="complete", expanded=False)
                st.session_state.interactive_debate_job = None
                st.session_state.brainstorm_history.append(
                    {
                        "created_at": datetime.now().strftime("%H:%M"),
                        "topic": data.get("topic", ""),
                        "mode": "debate_interactive",
                        "data": data,
                    }
                )
                st.session_state.selected_history_index = len(st.session_state.brainstorm_history) - 1
                _render_debate_result(data)
            except (requests.HTTPError, requests.RequestException, ValueError, TimeoutError, RuntimeError) as exc:
                logger.exception("Interactive debate continuation failed: %s", exc)
                st.error(str(exc))

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
with st.expander("Источники (NotebookLM) для повтора", expanded=False):
    rerun_context_urls = st.text_area(
        "Ссылки на статьи / сайты",
        key="rerun_context_urls",
        placeholder="https://example.com/article",
    )
    rerun_context_youtube = st.text_area(
        "YouTube-ссылки",
        key="rerun_context_youtube",
        placeholder="https://www.youtube.com/watch?v=...",
    )
uploaded_context_files = st.file_uploader(
    "Добавить файлы в контекст",
    type=_supported_file_types(),
    accept_multiple_files=True,
    help="Backend: документы, OCR, аудио-транскрипт, таблицы и др.",
)
rerun_cols = st.columns(2)
rerun_fast_clicked = rerun_cols[0].button("Повторить обычный brainstorm")
rerun_debate_clicked = rerun_cols[1].button("Повторить через столкновение моделей")

st.divider()
st.subheader("Спросить выбранную модель")

health_data = st.session_state.health_data or {}
agent_options = list(health_data.get("agents") or [])
synthesis = health_data.get("synthesis") or {}
if synthesis.get("model"):
    agent_options.append(
        {
            "role": "Модератор",
            "model": synthesis.get("model", "unknown"),
            "display_name": synthesis.get("display_name", "Модератор"),
            "description": synthesis.get("description", ""),
        }
    )

if not agent_options:
    st.info("Список моделей появится после подключения к бэкенду (/health).")
    agent_options = [{"role": "", "model": "", "display_name": "—", "description": ""}]

selected_agent_label = st.selectbox(
    "Выберите модель",
    options=[_agent_option_label(item) for item in agent_options],
    disabled=not health_data.get("agents"),
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
    history_mode = entry.get("mode") or ""
    if history_mode.startswith("debate"):
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
        initial_sources_context = _build_sources_context(
            initial_context_files,
            st.session_state.get("initial_context_urls", ""),
            st.session_state.get("initial_context_youtube", ""),
        )
        payload = {
            "topic": topic.strip(),
            "context": initial_sources_context or None,
            "comments": initial_comments.strip() or None,
        }
        is_debate = debate_clicked
        status_title = "Столкновение моделей запущено..." if is_debate else "Запускаю мозговой штурм..."
        status_done = "Спор моделей завершён" if is_debate else "Мозговой штурм готов"
        try:
            with st.status(status_title, expanded=True) as status:
                if is_debate:
                    payload["debate_mode"] = "full" if interactive_debate else selected_debate_mode
                    payload["interactive_debate"] = bool(interactive_debate)
                    data, mode = _run_debate_with_job(payload, status)
                else:
                    st.write("Отправляю тему на бэкенд.")
                    logger.info("POST %s topic=%s", BRAINSTORM_URL, payload.get("topic"))
                    data = _post_brainstorm_stream(payload)
                    mode = "fast"
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
        except (ValueError, TimeoutError, RuntimeError) as exc:
            logger.exception("Debate/brainstorm failed: %s", exc)
            st.error(str(exc))
        else:
            if data.get("waiting_for_user"):
                st.session_state.interactive_debate_job = data
                st.info("Первичный раунд завершён. Введите критику в блоке интерактивного спора.")
                st.stop()
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
    sources_context = _build_sources_context(
        uploaded_context_files,
        st.session_state.get("rerun_context_urls", ""),
        st.session_state.get("rerun_context_youtube", ""),
    )
    combined_context = _merge_context_parts(selected_context, sources_context)
    rerun_topic = (topic or "").strip() or (selected_history_entry or {}).get("topic", "").strip()

    if not rerun_topic:
        st.warning("Введите тему или выберите запись истории для повторного запуска.")
    else:
        is_debate_rerun = rerun_debate_clicked
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

        try:
            with st.status(status_title, expanded=True) as status:
                if is_debate_rerun:
                    payload["debate_mode"] = "full" if interactive_debate else selected_debate_mode
                    payload["interactive_debate"] = bool(interactive_debate)
                    data, mode = _run_debate_with_job(payload, status, rerun=True)
                else:
                    st.write("Отправляю тему, контекст и комментарии на бэкенд.")
                    logger.info("POST %s topic=%s", BRAINSTORM_URL, payload.get("topic"))
                    data = _post_brainstorm_stream(payload)
                    mode = "fast_rerun"
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
        except (ValueError, TimeoutError, RuntimeError) as exc:
            logger.exception("Rerun failed: %s", exc)
            st.error(str(exc))
        else:
            if data.get("waiting_for_user"):
                st.session_state.interactive_debate_job = data
                st.info("Первичный раунд завершён. Введите критику в блоке интерактивного спора.")
                st.stop()
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
                logger.info("POST %s role=%s", ASK_AGENT_URL, selected_agent.get("role"))
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
