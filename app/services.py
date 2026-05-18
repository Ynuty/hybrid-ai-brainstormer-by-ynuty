import asyncio
import logging
from typing import Any

from app.context_utils import truncate_for_prompt
from app.config import get_settings
from app.llm import completion_content, public_error
from app.models import AgentSpec
from app.prompts import (
    agent_question_prompt,
    debate_critique_prompt,
    debate_revision_prompt,
    debate_synthesis_prompt,
    structured_expert_prompt,
    structured_synthesis_prompt,
)
from app.state import active_agents, active_synthesis

logger = logging.getLogger(__name__)


def build_topic_prompt(
    topic: str,
    context: str | None = None,
    comments: str | None = None,
) -> str:
    settings = get_settings()
    context = truncate_for_prompt(context, settings.max_context_chars)
    comments = truncate_for_prompt(comments, settings.max_comments_chars)
    parts = [f"Тема мозгового штурма: {topic}"]
    if context:
        parts.append(f"Контекст предыдущих результатов и файлов:\n{context}")
    if comments:
        parts.append(f"Комментарии пользователя к повторному запуску:\n{comments}")
        parts.append("Переработай решение с учётом этих комментариев и контекста.")
    return "\n\n".join(parts)


def format_responses_for_prompt(responses: list[dict[str, Any]]) -> str:
    sections = []
    for item in responses:
        status = "успешно" if item.get("success") else "ошибка"
        body = item.get("response") or item.get("error") or "нет ответа"
        sections.append(
            f"### {item.get('role', 'Эксперт')}\n"
            f"Модель: {item.get('model', 'unknown')}\n"
            f"Статус: {status}\n\n"
            f"{body}"
        )
    return "\n\n".join(sections)


def failed_agents(responses: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"role": item.get("role", "unknown"), "error": item.get("error") or "unknown error"}
        for item in responses
        if not item.get("success")
    ]


async def call_expert(
    agent: AgentSpec,
    topic: str,
    context: str | None = None,
    comments: str | None = None,
) -> dict[str, Any]:
    user_prompt = build_topic_prompt(topic, context, comments)
    try:
        content, used_model = await completion_content(
            model=agent.model,
            temperature=agent.temperature,
            fallback_model=agent.fallback_model,
            log_context=f"call_expert role={agent.role}",
            messages=[
                {"role": "system", "content": structured_expert_prompt(agent.system_prompt)},
                {"role": "user", "content": user_prompt},
            ],
        )
        return {
            "role": agent.role,
            "model": used_model,
            "configured_model": agent.model,
            "response": content,
            "success": True,
            "error": None,
        }
    except Exception as exc:
        logger.exception("call_expert failed role=%s model=%s: %s", agent.role, agent.model, exc)
        return {
            "role": agent.role,
            "model": agent.model,
            "configured_model": agent.model,
            "response": "",
            "success": False,
            "error": public_error(exc),
        }


async def call_agent_custom(
    agent: AgentSpec,
    *,
    system_prompt: str,
    user_prompt: str,
    log_context: str,
) -> dict[str, Any]:
    try:
        content, used_model = await completion_content(
            model=agent.model,
            temperature=agent.temperature,
            fallback_model=agent.fallback_model,
            log_context=log_context,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return {
            "role": agent.role,
            "model": used_model,
            "configured_model": agent.model,
            "response": content,
            "success": True,
            "error": None,
        }
    except Exception as exc:
        logger.exception("%s failed role=%s model=%s: %s", log_context, agent.role, agent.model, exc)
        return {
            "role": agent.role,
            "model": agent.model,
            "configured_model": agent.model,
            "response": "",
            "success": False,
            "error": public_error(exc),
        }


async def run_initial_expert_round(
    topic: str,
    context: str | None = None,
    comments: str | None = None,
) -> list[dict[str, Any]]:
    tasks = [call_expert(agent, topic, context, comments) for agent in active_agents()]
    return await asyncio.gather(*tasks)


async def run_debate_round(
    topic: str,
    initial_responses: list[dict[str, Any]],
    context: str | None = None,
    comments: str | None = None,
) -> list[dict[str, Any]]:
    initial_context = format_responses_for_prompt(initial_responses)
    user_prompt = (
        f"{build_topic_prompt(topic, context, comments)}\n\n"
        "Ниже первичные ответы всех экспертов:\n\n"
        f"{initial_context}\n\n"
        "Проанализируй ответы других экспертов и дай конструктивную критику. "
        "Твоя цель — найти слабые места до финального ответа пользователю."
    )
    tasks = [
        call_agent_custom(
            agent,
            system_prompt=debate_critique_prompt(agent.system_prompt),
            user_prompt=user_prompt,
            log_context=f"debate_critique role={agent.role}",
        )
        for agent in active_agents()
    ]
    return await asyncio.gather(*tasks)


async def run_revision_round(
    topic: str,
    initial_responses: list[dict[str, Any]],
    critiques: list[dict[str, Any]],
    context: str | None = None,
    comments: str | None = None,
) -> list[dict[str, Any]]:
    critique_context = format_responses_for_prompt(critiques)
    tasks = []
    for agent in active_agents():
        own_initial = next((item for item in initial_responses if item.get("role") == agent.role), None)
        own_initial_text = (
            (own_initial or {}).get("response")
            or (own_initial or {}).get("error")
            or "Первичный ответ отсутствует."
        )
        user_prompt = (
            f"{build_topic_prompt(topic, context, comments)}\n\n"
            "Твой первичный ответ:\n\n"
            f"{own_initial_text}\n\n"
            "Критика и предложения других экспертов:\n\n"
            f"{critique_context}\n\n"
            "Доработай свой ответ так, чтобы финальный модератор мог собрать цельное решение "
            "без нерешённых противоречий."
        )
        tasks.append(
            call_agent_custom(
                agent,
                system_prompt=debate_revision_prompt(agent.system_prompt),
                user_prompt=user_prompt,
                log_context=f"debate_revision role={agent.role}",
            )
        )
    return await asyncio.gather(*tasks)


async def synthesize_results(
    topic: str,
    agent_responses: list[dict[str, Any]],
    context: str | None = None,
    comments: str | None = None,
) -> str:
    successful = [item for item in agent_responses if item.get("success") and item.get("response")]
    if not successful:
        raise RuntimeError("no successful expert responses")

    failed = failed_agents(agent_responses)
    joined = "\n\n".join(
        f"Эксперт #{index + 1} ({item.get('role', 'unknown')}):\n{item.get('response', '')}"
        for index, item in enumerate(successful)
    )
    synthesis = active_synthesis()
    failed_note = ""
    if failed:
        failed_note = (
            "\n\nНе ответили эксперты:\n"
            + "\n".join(f"- {item['role']}: {item['error']}" for item in failed)
            + "\nУкажи в итоге, что результат частичный."
        )

    user_prompt = (
        f"{build_topic_prompt(topic, context, comments)}\n\n"
        "Ответы экспертов:\n"
        f"{joined}{failed_note}\n\n"
        "Сформируй единый итог: краткое резюме и пошаговый план."
    )
    content, _ = await completion_content(
        model=synthesis.model,
        temperature=synthesis.temperature,
        fallback_model=synthesis.fallback_model,
        log_context="synthesize_results",
        messages=[
            {"role": "system", "content": structured_synthesis_prompt(synthesis.system_prompt)},
            {"role": "user", "content": user_prompt},
        ],
    )
    return content


async def synthesize_debate_results(
    topic: str,
    revised_responses: list[dict[str, Any]],
    critiques: list[dict[str, Any]],
    context: str | None = None,
    comments: str | None = None,
) -> str:
    successful = [item for item in revised_responses if item.get("success") and item.get("response")]
    if not successful:
        raise RuntimeError("no successful revised expert responses")
    synthesis = active_synthesis()
    user_prompt = (
        f"{build_topic_prompt(topic, context, comments)}\n\n"
        "Доработанные ответы экспертов:\n\n"
        f"{format_responses_for_prompt(successful)}\n\n"
        "Журнал критики и спора:\n\n"
        f"{format_responses_for_prompt(critiques)}\n\n"
        "Собери единый финальный ответ для пользователя."
    )
    content, _ = await completion_content(
        model=synthesis.model,
        temperature=synthesis.temperature,
        fallback_model=synthesis.fallback_model,
        log_context="synthesize_debate_results",
        messages=[
            {"role": "system", "content": debate_synthesis_prompt(synthesis.system_prompt)},
            {"role": "user", "content": user_prompt},
        ],
    )
    return content


async def synthesize_debate_results_light(
    topic: str,
    initial_responses: list[dict[str, Any]],
    critiques: list[dict[str, Any]],
    context: str | None = None,
    comments: str | None = None,
) -> str:
    successful = [item for item in initial_responses if item.get("success") and item.get("response")]
    if not successful:
        raise RuntimeError("no successful initial expert responses")
    synthesis = active_synthesis()
    user_prompt = (
        f"{build_topic_prompt(topic, context, comments)}\n\n"
        "Первичные ответы экспертов:\n\n"
        f"{format_responses_for_prompt(successful)}\n\n"
        "Журнал критики:\n\n"
        f"{format_responses_for_prompt(critiques)}\n\n"
        "Раунд доработки пропущен (быстрый спор). Собери финальный ответ."
    )
    content, _ = await completion_content(
        model=synthesis.model,
        temperature=synthesis.temperature,
        fallback_model=synthesis.fallback_model,
        log_context="synthesize_debate_results_light",
        messages=[
            {"role": "system", "content": debate_synthesis_prompt(synthesis.system_prompt)},
            {"role": "user", "content": user_prompt},
        ],
    )
    return content


async def ask_synthesis(question: str, context: str | None = None) -> dict[str, Any]:
    synthesis = active_synthesis()
    context_block = f"\n\nКонтекст:\n{context.strip()}" if context else ""
    user_prompt = f"Вопрос пользователя:\n{question.strip()}{context_block}"
    try:
        content, used_model = await completion_content(
            model=synthesis.model,
            temperature=synthesis.temperature,
            fallback_model=synthesis.fallback_model,
            log_context="ask_synthesis",
            messages=[
                {"role": "system", "content": agent_question_prompt(synthesis.system_prompt)},
                {"role": "user", "content": user_prompt},
            ],
        )
        return {
            "role": "Модератор",
            "model": used_model,
            "configured_model": synthesis.model,
            "question": question.strip(),
            "response": content,
            "success": True,
            "error": None,
        }
    except Exception as exc:
        logger.exception("ask_synthesis failed: %s", exc)
        return {
            "role": "Модератор",
            "model": synthesis.model,
            "configured_model": synthesis.model,
            "question": question.strip(),
            "response": "",
            "success": False,
            "error": public_error(exc),
        }
