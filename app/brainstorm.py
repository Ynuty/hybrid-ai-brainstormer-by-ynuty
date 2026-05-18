import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.rag import relevant_context_for_prompt
from app.schemas import BrainstormRequest
from app.services import call_expert, failed_agents, synthesize_results
from app.state import active_agents


async def run_brainstorm(payload: BrainstormRequest) -> dict:
    topic = payload.topic.strip()
    context = relevant_context_for_prompt(
        query=f"{topic}\n{payload.comments or ''}",
        context=payload.context,
    )
    tasks = [call_expert(agent, topic, context, payload.comments) for agent in active_agents()]
    agent_responses = await asyncio.gather(*tasks)
    failed = failed_agents(agent_responses)
    success_count = len(agent_responses) - len(failed)

    if success_count == 0:
        details = "; ".join(f"{item['role']}: {item['error']}" for item in failed)
        raise RuntimeError(f"Все эксперты не ответили: {details}")

    final_synthesis = await synthesize_results(
        topic, agent_responses, context, payload.comments
    )
    return {
        "topic": topic,
        "agent_responses": agent_responses,
        "final_synthesis": final_synthesis,
        "partial": bool(failed),
        "failed_agents": failed,
    }


def _text_chunks(text: str, chunk_size: int = 80) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]


async def stream_brainstorm_events(payload: BrainstormRequest) -> AsyncIterator[dict[str, Any]]:
    """Run brainstorm and yield UI-friendly streaming events.

    LiteLLM calls remain regular calls for provider compatibility; the UI still receives
    expert sections as soon as each model finishes instead of waiting for the full run.
    """

    topic = payload.topic.strip()
    context = relevant_context_for_prompt(
        query=f"{topic}\n{payload.comments or ''}",
        context=payload.context,
    )
    yield {"event": "chunk", "text": f"## Мозговой штурм: {topic}\n\n"}
    yield {"event": "chunk", "text": "_Эксперты начали работу. Ответы появятся по мере готовности._\n\n"}

    async def _call(agent):
        return await call_expert(agent, topic, context, payload.comments)

    tasks = [_call(agent) for agent in active_agents()]
    agent_responses: list[dict[str, Any]] = []
    for completed in asyncio.as_completed(tasks):
        item = await completed
        agent_responses.append(item)
        role = item.get("role", "Эксперт")
        body = item.get("response") or item.get("error") or "_пусто_"
        prefix = f"### {role}\n\n"
        if not item.get("success"):
            prefix += "**Ошибка модели:**\n\n"
        for chunk in _text_chunks(prefix + body + "\n\n"):
            yield {"event": "chunk", "text": chunk}

    failed = failed_agents(agent_responses)
    success_count = len(agent_responses) - len(failed)
    if success_count == 0:
        details = "; ".join(f"{item['role']}: {item['error']}" for item in failed)
        yield {"event": "error", "detail": f"Все эксперты не ответили: {details}"}
        return

    yield {"event": "chunk", "text": "## Итоговый синтез\n\n_Модератор собирает итог..._\n\n"}
    final_synthesis = await synthesize_results(topic, agent_responses, context, payload.comments)
    for chunk in _text_chunks(final_synthesis + "\n"):
        yield {"event": "chunk", "text": chunk}

    yield {
        "event": "final",
        "result": {
            "topic": topic,
            "agent_responses": agent_responses,
            "final_synthesis": final_synthesis,
            "partial": bool(failed),
            "failed_agents": failed,
        },
    }
