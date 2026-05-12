import asyncio
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from litellm import acompletion
from pydantic import BaseModel


app = FastAPI(title="AI Brainstorm API")

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

    response = await acompletion(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


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

    response = await acompletion(
        model=SYNTHESIS_MODEL,
        messages=[
            {"role": "system", "content": synthesis_system_prompt},
            {"role": "user", "content": synthesis_user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


@app.post("/brainstorm")
async def brainstorm(payload: BrainstormRequest):
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    tasks = [call_expert(role, topic) for role in EXPERT_ROLES]
    try:
        results = await asyncio.gather(*tasks)
    except Exception as exc:
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
        raise HTTPException(
            status_code=502,
            detail=f"Failed during synthesis stage: {exc}",
        ) from exc

    return {
        "topic": topic,
        "agent_responses": agent_responses,
        "final_synthesis": final_synthesis,
    }
