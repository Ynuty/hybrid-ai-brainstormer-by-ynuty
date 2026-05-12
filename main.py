import asyncio
import logging
import os
from typing import Any

import uvicorn
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

DEFAULT_MODEL = os.getenv("BRAINSTORM_MODEL", "openai/gpt-4o")
SYNTHESIS_MODEL = os.getenv("SYNTHESIS_MODEL", DEFAULT_MODEL)

EXPERT_ROLES = [
    "Продуктовый стратег",
    "Креативный маркетолог",
    "Технический архитектор",
]


class BrainstormRequest(BaseModel):
    topic: str


async def call_expert(role: str, topic: str) -> str:
    system_prompt = (
        f"Ты — {role}. Дай практичный и структурированный вклад в мозговой штурм. "
        "Предложи идеи, обозначь риски и критерии успеха."
    )
    user_prompt = f"Тема мозгового штурма: {topic}"

    try:
        response = await acompletion(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""
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

    synthesis_system_prompt = (
        "Ты — Главный Стратег. Твоя задача — изучить ответы различных экспертов по теме "
        "мозгового штурма, найти лучшие идеи, учесть критику и составить единый пошаговый "
        "план действий или финальное резюме."
    )

    synthesis_user_prompt = (
        f"Тема: {topic}\n\n"
        "Ответы экспертов:\n"
        f"{joined_responses}\n\n"
        "Сформируй единый итог: краткое резюме и пошаговый план."
    )

    try:
        response = await acompletion(
            model=SYNTHESIS_MODEL,
            messages=[
                {"role": "system", "content": synthesis_system_prompt},
                {"role": "user", "content": synthesis_user_prompt},
            ],
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.exception("synthesize_results failed model=%s: %s", SYNTHESIS_MODEL, exc)
        raise


@app.post("/brainstorm")
async def brainstorm(payload: BrainstormRequest):
    topic = payload.topic.strip()
    if not topic:
        logger.warning("brainstorm: empty topic rejected")
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    tasks = [call_expert(role, topic) for role in EXPERT_ROLES]
    try:
        results = await asyncio.gather(*tasks)
    except Exception as exc:
        logger.exception("brainstorm: expert agents failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to get responses from expert agents: {exc}",
        ) from exc

    agent_responses = [
        {"role": role, "response": result}
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting uvicorn host=0.0.0.0 port=%s", port)
    uvicorn.run("main:app", host="0.0.0.0", port=port)
