import asyncio

import app.brainstorm as brainstorm
from app.models import AgentSpec
from app.schemas import BrainstormRequest


def test_stream_brainstorm_events(monkeypatch):
    agents = [AgentSpec(role="Tester", model="fake", system_prompt="test")]

    async def fake_call_expert(agent, topic, context, comments):
        return {
            "role": agent.role,
            "model": agent.model,
            "configured_model": agent.model,
            "response": f"answer for {topic}",
            "success": True,
            "error": None,
        }

    async def fake_synthesize(topic, agent_responses, context, comments):
        return "final answer"

    monkeypatch.setattr(brainstorm, "active_agents", lambda: agents)
    monkeypatch.setattr(brainstorm, "call_expert", fake_call_expert)
    monkeypatch.setattr(brainstorm, "synthesize_results", fake_synthesize)

    async def collect():
        payload = BrainstormRequest(topic="stream test")
        return [event async for event in brainstorm.stream_brainstorm_events(payload)]

    events = asyncio.run(collect())
    assert any(event["event"] == "chunk" and "Tester" in event["text"] for event in events)
    final = next(event for event in events if event["event"] == "final")
    assert final["result"]["final_synthesis"] == "final answer"
