import asyncio

from app.schemas import BrainstormRequest
from app.services import call_expert, failed_agents, synthesize_results
from app.state import active_agents


async def run_brainstorm(payload: BrainstormRequest) -> dict:
    topic = payload.topic.strip()
    tasks = [call_expert(agent, topic, payload.context, payload.comments) for agent in active_agents()]
    agent_responses = await asyncio.gather(*tasks)
    failed = failed_agents(agent_responses)
    success_count = len(agent_responses) - len(failed)

    if success_count == 0:
        details = "; ".join(f"{item['role']}: {item['error']}" for item in failed)
        raise RuntimeError(f"Все эксперты не ответили: {details}")

    final_synthesis = await synthesize_results(
        topic, agent_responses, payload.context, payload.comments
    )
    return {
        "topic": topic,
        "agent_responses": agent_responses,
        "final_synthesis": final_synthesis,
        "partial": bool(failed),
        "failed_agents": failed,
    }
