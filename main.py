import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from litellm import acompletion
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Brainstorm API")


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://localhost:8501", "http://127.0.0.1:8501"]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("%s must be a number — using %.1f", name, default)
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("%s must be an integer — using %d", name, default)
        return default


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_MODEL = os.getenv("BRAINSTORM_MODEL", "openrouter/openai/gpt-4o")
SYNTHESIS_MODEL = os.getenv("SYNTHESIS_MODEL", DEFAULT_MODEL)
CONFIG_PATH = Path(os.getenv("AGENTS_CONFIG_PATH", "agents_config.yaml"))
MODEL_TIMEOUT_S = _env_float("MODEL_TIMEOUT_S", 120)
MODEL_RETRY_ATTEMPTS = max(1, _env_int("MODEL_RETRY_ATTEMPTS", 2))
MODEL_RETRY_BACKOFF_S = _env_float("MODEL_RETRY_BACKOFF_S", 1.5)

_AGENTS: list["AgentSpec"] = []
_SYNTHESIS: "SynthesisSpec | None" = None

# Fallback, если YAML отсутствует или пуст
EXPERT_ROLES = [
    "Продуктовый стратег",
    "Креативный маркетолог",
    "Технический архитектор",
]


@dataclass(frozen=True)
class AgentSpec:
    role: str
    model: str
    system_prompt: str
    temperature: float = 0.7
    fallback_model: str | None = None


@dataclass(frozen=True)
class SynthesisSpec:
    model: str
    system_prompt: str
    temperature: float = 0.4
    fallback_model: str | None = None


def _default_synthesis_prompt() -> str:
    return (
        "Ты — Главный Стратег. Твоя задача — изучить ответы различных экспертов по теме "
        "мозгового штурма, найти лучшие идеи, учесть критику и составить единый пошаговый "
        "план действий или финальное резюме."
    )


def _coerce_temperature(value: Any, default: float, label: str) -> float:
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        logger.warning("%s has invalid temperature=%r — using %.1f", label, value, default)
        return default

    if not 0 <= temperature <= 2:
        logger.warning("%s temperature %.2f is outside 0..2 — using %.1f", label, temperature, default)
        return default
    return temperature


def _structured_expert_prompt(system_prompt: str) -> str:
    return (
        f"{system_prompt}\n\n"
        "Ответь строго в Markdown со следующими разделами:\n"
        "## Краткий вывод\n"
        "## Идеи\n"
        "## Риски\n"
        "## Метрики успеха\n"
        "## Первые шаги"
    )


def _structured_synthesis_prompt(system_prompt: str) -> str:
    return (
        f"{system_prompt}\n\n"
        "Верни итог строго в Markdown со следующими разделами:\n"
        "## Резюме\n"
        "## Лучшие идеи\n"
        "## Риски и ограничения\n"
        "## План на 1-2 недели\n"
        "## Что проверить первым"
    )


def _public_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: модель временно недоступна или вернула ошибку"


def _load_agents_yaml(path: Path) -> tuple[list[AgentSpec], SynthesisSpec | None]:
    if not path.exists():
        logger.warning("agents_config not found at %s — using env defaults and EXPERT_ROLES", path)
        return [], None

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.exception("Failed to parse %s: %s", path, exc)
        return [], None

    experts_raw = raw.get("experts") or []
    synthesis_raw = raw.get("synthesis") or {}
    if experts_raw and not isinstance(experts_raw, list):
        logger.warning("agents_config experts must be a list — using fallback roles")
        experts_raw = []

    agents: list[AgentSpec] = []
    for index, item in enumerate(experts_raw, start=1):
        if not isinstance(item, dict):
            logger.warning("agents_config expert #%d is not an object — skipped", index)
            continue
        role = str(item.get("role", "")).strip()
        model = str(item.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        system_prompt = str(item.get("system_prompt", "")).strip()
        fallback_model = str(item.get("fallback_model", "")).strip() or None
        temperature = _coerce_temperature(item.get("temperature", 0.7), 0.7, f"expert #{index}")
        if role and system_prompt:
            agents.append(
                AgentSpec(
                    role=role,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    fallback_model=fallback_model,
                )
            )
        else:
            logger.warning(
                "agents_config expert #%d skipped: role and system_prompt are required",
                index,
            )

    synthesis_spec: SynthesisSpec | None = None
    if isinstance(synthesis_raw, dict) and synthesis_raw:
        smodel = str(synthesis_raw.get("model", SYNTHESIS_MODEL)).strip() or SYNTHESIS_MODEL
        sprompt = str(synthesis_raw.get("system_prompt", "")).strip() or _default_synthesis_prompt()
        sfallback = str(synthesis_raw.get("fallback_model", "")).strip() or None
        stemp = _coerce_temperature(synthesis_raw.get("temperature", 0.4), 0.4, "synthesis")
        synthesis_spec = SynthesisSpec(
            model=smodel,
            system_prompt=sprompt,
            temperature=stemp,
            fallback_model=sfallback,
        )
    elif synthesis_raw:
        logger.warning("agents_config synthesis must be an object — using default synthesis prompt")

    if not agents:
        logger.warning("No valid experts in %s — using EXPERT_ROLES fallback", path)
    else:
        logger.info("Loaded %d experts from %s", len(agents), path)

    return agents, synthesis_spec


@app.on_event("startup")
async def _startup() -> None:
    global _AGENTS, _SYNTHESIS
    agents, synthesis = _load_agents_yaml(CONFIG_PATH)
    _AGENTS = agents
    _SYNTHESIS = synthesis


class BrainstormRequest(BaseModel):
    topic: str


async def _acompletion_with_timeout(**kwargs: Any):
    return await asyncio.wait_for(acompletion(**kwargs), timeout=MODEL_TIMEOUT_S)


async def _completion_content(
    *,
    model: str,
    temperature: float,
    messages: list[dict[str, str]],
    fallback_model: str | None,
    log_context: str,
) -> tuple[str, str]:
    models = [model]
    if fallback_model and fallback_model != model:
        models.append(fallback_model)

    last_exc: Exception | None = None
    for model_name in models:
        for attempt in range(1, MODEL_RETRY_ATTEMPTS + 1):
            try:
                response = await _acompletion_with_timeout(
                    model=model_name,
                    temperature=temperature,
                    messages=messages,
                )
                choice = response.choices[0] if response.choices else None
                content = (choice.message.content if choice and choice.message else "") or ""
                if content.strip():
                    return content, model_name
                raise RuntimeError("empty model response")
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "%s failed model=%s attempt=%d/%d: %s",
                    log_context,
                    model_name,
                    attempt,
                    MODEL_RETRY_ATTEMPTS,
                    exc,
                )
                if attempt < MODEL_RETRY_ATTEMPTS:
                    await asyncio.sleep(MODEL_RETRY_BACKOFF_S * attempt)

    if last_exc is None:
        raise RuntimeError("model call failed without exception")
    raise last_exc


async def call_expert_yaml(agent: AgentSpec, topic: str) -> dict[str, Any]:
    user_prompt = f"Тема мозгового штурма: {topic}"
    try:
        content, used_model = await _completion_content(
            model=agent.model,
            temperature=agent.temperature,
            fallback_model=agent.fallback_model,
            log_context=f"call_expert role={agent.role}",
            messages=[
                {"role": "system", "content": _structured_expert_prompt(agent.system_prompt)},
                {"role": "user", "content": user_prompt},
            ],
        )
        return {
            "role": agent.role,
            "model": used_model,
            "response": content,
            "success": True,
            "error": None,
        }
    except Exception as exc:
        logger.exception("call_expert failed role=%s model=%s: %s", agent.role, agent.model, exc)
        return {
            "role": agent.role,
            "model": agent.model,
            "response": "",
            "success": False,
            "error": _public_error(exc),
        }


async def call_expert_fallback(role: str, topic: str) -> dict[str, Any]:
    system_prompt = (
        f"Ты — {role}. Дай практичный и структурированный вклад в мозговой штурм. "
        "Предложи идеи, обозначь риски и критерии успеха."
    )
    user_prompt = f"Тема мозгового штурма: {topic}"
    try:
        content, used_model = await _completion_content(
            model=DEFAULT_MODEL,
            temperature=0.7,
            fallback_model=None,
            log_context=f"call_expert fallback role={role}",
            messages=[
                {"role": "system", "content": _structured_expert_prompt(system_prompt)},
                {"role": "user", "content": user_prompt},
            ],
        )
        return {
            "role": role,
            "model": used_model,
            "response": content,
            "success": True,
            "error": None,
        }
    except Exception as exc:
        logger.exception("call_expert failed role=%s model=%s: %s", role, DEFAULT_MODEL, exc)
        return {
            "role": role,
            "model": DEFAULT_MODEL,
            "response": "",
            "success": False,
            "error": _public_error(exc),
        }


async def synthesize_results(topic: str, agent_responses: list[Any]) -> str:
    successful_responses = [item for item in agent_responses if item.get("success") and item.get("response")]
    if not successful_responses:
        raise RuntimeError("no successful expert responses")

    joined_responses = "\n\n".join(
        [
            f"Эксперт #{index + 1} ({item.get('role', 'unknown')}):\n{item.get('response', '')}"
            for index, item in enumerate(successful_responses)
        ]
    )

    synthesis = _SYNTHESIS or SynthesisSpec(
        model=SYNTHESIS_MODEL,
        system_prompt=_default_synthesis_prompt(),
        temperature=0.4,
    )

    synthesis_user_prompt = (
        f"Тема: {topic}\n\n"
        "Ответы экспертов:\n"
        f"{joined_responses}\n\n"
        "Сформируй единый итог: краткое резюме и пошаговый план."
    )

    try:
        content, _used_model = await _completion_content(
            model=synthesis.model,
            temperature=synthesis.temperature,
            fallback_model=synthesis.fallback_model,
            log_context="synthesize_results",
            messages=[
                {"role": "system", "content": _structured_synthesis_prompt(synthesis.system_prompt)},
                {"role": "user", "content": synthesis_user_prompt},
            ],
        )
        return content
    except Exception as exc:
        logger.exception("synthesize_results failed model=%s: %s", synthesis.model, exc)
        raise


@app.post("/brainstorm")
async def brainstorm(payload: BrainstormRequest):
    topic = payload.topic.strip()
    if not topic:
        logger.warning("brainstorm: empty topic rejected")
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    agents = _AGENTS
    if agents:
        tasks = [call_expert_yaml(a, topic) for a in agents]
        agent_responses = await asyncio.gather(*tasks)
    else:
        tasks = [call_expert_fallback(role, topic) for role in EXPERT_ROLES]
        agent_responses = await asyncio.gather(*tasks)

    failed_count = len([item for item in agent_responses if not item.get("success")])
    if failed_count:
        logger.warning("brainstorm: %d/%d expert agents failed", failed_count, len(agent_responses))

    try:
        final_synthesis = await synthesize_results(topic, agent_responses)
    except Exception as exc:
        logger.exception("brainstorm: synthesis stage failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Не удалось получить итоговый синтез. Попробуйте повторить запрос позже.",
        ) from exc

    return {
        "topic": topic,
        "agent_responses": agent_responses,
        "final_synthesis": final_synthesis,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "agents_from_yaml": len(_AGENTS)}


if __name__ == "__main__":
    port = _env_int("PORT", 8000)
    logger.info("Starting uvicorn host=0.0.0.0 port=%s", port)
    uvicorn.run("main:app", host="0.0.0.0", port=port)
