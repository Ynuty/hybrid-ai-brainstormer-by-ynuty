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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_MODEL = os.getenv("BRAINSTORM_MODEL", "openrouter/openai/gpt-4o")
SYNTHESIS_MODEL = os.getenv("SYNTHESIS_MODEL", DEFAULT_MODEL)
CONFIG_PATH = Path(os.getenv("AGENTS_CONFIG_PATH", "agents_config.yaml"))
MODEL_TIMEOUT_S = float(os.getenv("MODEL_TIMEOUT_S", "120"))

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


@dataclass(frozen=True)
class SynthesisSpec:
    model: str
    system_prompt: str
    temperature: float = 0.4


def _default_synthesis_prompt() -> str:
    return (
        "Ты — Главный Стратег. Твоя задача — изучить ответы различных экспертов по теме "
        "мозгового штурма, найти лучшие идеи, учесть критику и составить единый пошаговый "
        "план действий или финальное резюме."
    )


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

    agents: list[AgentSpec] = []
    for item in experts_raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        model = str(item.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
        system_prompt = str(item.get("system_prompt", "")).strip()
        try:
            temperature = float(item.get("temperature", 0.7))
        except (TypeError, ValueError):
            temperature = 0.7
        if role and system_prompt:
            agents.append(
                AgentSpec(
                    role=role,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                )
            )

    synthesis_spec: SynthesisSpec | None = None
    if isinstance(synthesis_raw, dict) and synthesis_raw:
        smodel = str(synthesis_raw.get("model", SYNTHESIS_MODEL)).strip() or SYNTHESIS_MODEL
        sprompt = str(synthesis_raw.get("system_prompt", "")).strip() or _default_synthesis_prompt()
        try:
            stemp = float(synthesis_raw.get("temperature", 0.4))
        except (TypeError, ValueError):
            stemp = 0.4
        synthesis_spec = SynthesisSpec(model=smodel, system_prompt=sprompt, temperature=stemp)

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


async def call_expert_yaml(agent: AgentSpec, topic: str) -> str:
    user_prompt = f"Тема мозгового штурма: {topic}"
    try:
        response = await _acompletion_with_timeout(
            model=agent.model,
            temperature=agent.temperature,
            messages=[
                {"role": "system", "content": agent.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        choice = response.choices[0] if response.choices else None
        return (choice.message.content if choice and choice.message else "") or ""
    except Exception as exc:
        logger.exception("call_expert failed role=%s model=%s: %s", agent.role, agent.model, exc)
        raise


async def call_expert_fallback(role: str, topic: str) -> str:
    system_prompt = (
        f"Ты — {role}. Дай практичный и структурированный вклад в мозговой штурм. "
        "Предложи идеи, обозначь риски и критерии успеха."
    )
    user_prompt = f"Тема мозгового штурма: {topic}"
    try:
        response = await _acompletion_with_timeout(
            model=DEFAULT_MODEL,
            temperature=0.7,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        choice = response.choices[0] if response.choices else None
        return (choice.message.content if choice and choice.message else "") or ""
    except Exception as exc:
        logger.exception("call_expert failed role=%s model=%s: %s", role, DEFAULT_MODEL, exc)
        raise


async def synthesize_results(topic: str, agent_responses: list[Any]) -> str:
    joined_responses = "\n\n".join(
        [
            f"Эксперт #{index + 1} ({item.get('role', 'unknown')}):\n{item.get('response', '')}"
            for index, item in enumerate(agent_responses)
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
        response = await _acompletion_with_timeout(
            model=synthesis.model,
            temperature=synthesis.temperature,
            messages=[
                {"role": "system", "content": synthesis.system_prompt},
                {"role": "user", "content": synthesis_user_prompt},
            ],
        )
        choice = response.choices[0] if response.choices else None
        return (choice.message.content if choice and choice.message else "") or ""
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
        try:
            results = await asyncio.gather(*tasks)
        except Exception as exc:
            logger.exception("brainstorm: expert agents failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to get responses from expert agents: {exc}",
            ) from exc
        agent_responses = [
            {"role": a.role, "model": a.model, "response": r}
            for a, r in zip(agents, results)
        ]
    else:
        tasks = [call_expert_fallback(role, topic) for role in EXPERT_ROLES]
        try:
            results = await asyncio.gather(*tasks)
        except Exception as exc:
            logger.exception("brainstorm: expert agents failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to get responses from expert agents: {exc}",
            ) from exc
        agent_responses = [
            {"role": role, "model": DEFAULT_MODEL, "response": result}
            for role, result in zip(EXPERT_ROLES, results)
        ]

    try:
        final_synthesis = await synthesize_results(topic, agent_responses)
    except Exception as exc:
        logger.exception("brainstorm: synthesis stage failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed during synthesis stage: {exc}",
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
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting uvicorn host=0.0.0.0 port=%s", port)
    uvicorn.run("main:app", host="0.0.0.0", port=port)
