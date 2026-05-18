from collections.abc import Awaitable, Callable
from typing import Any, Literal

from app.schemas import BrainstormRequest
from app.services import (
    format_responses_for_prompt,
    run_debate_round,
    run_initial_expert_round,
    run_revision_round,
    synthesize_debate_results,
    synthesize_debate_results_light,
)

DebateMode = Literal["full", "light"]
ProgressCallback = Callable[[str, int, int, str], Awaitable[None]]


async def report_progress(
    callback: ProgressCallback | None,
    stage: str,
    stage_index: int,
    stage_total: int,
    message: str,
) -> None:
    if callback is not None:
        await callback(stage, stage_index, stage_total, message)


def build_debate_report(
    topic: str,
    initial_responses: list[dict[str, Any]],
    critiques: list[dict[str, Any]],
    revised_responses: list[dict[str, Any]],
    final_synthesis: str,
    *,
    debate_mode: DebateMode = "full",
) -> str:
    revision_section = (
        "_раунд доработки пропущен (режим «быстрый спор»)_"
        if debate_mode == "light"
        else format_responses_for_prompt(revised_responses)
    )
    mode_note = " (быстрый спор)" if debate_mode == "light" else " (полный спор)"
    return "\n\n".join(
        [
            f"# Журнал спора моделей{mode_note}: {topic}",
            "## Раунд 1: первичные ответы",
            format_responses_for_prompt(initial_responses),
            "## Раунд 2: критика и предложения",
            format_responses_for_prompt(critiques),
            "## Доработанные ответы экспертов",
            revision_section,
            "## Итоговое решение модератора",
            final_synthesis or "_пусто_",
        ]
    )


def require_any_success(responses: list[dict[str, Any]], stage_label: str) -> None:
    if not any(item.get("success") for item in responses):
        raise RuntimeError(f"all agents failed at stage: {stage_label}")


async def execute_debate_full(
    payload: BrainstormRequest,
    on_progress: ProgressCallback | None = None,
    *,
    on_partial: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    topic = payload.topic.strip()
    stage_total = 4

    await report_progress(on_progress, "initial", 1, stage_total, "Эксперты дают первичные ответы")
    initial_responses = await run_initial_expert_round(topic, payload.context, payload.comments)
    require_any_success(initial_responses, "initial")
    if on_partial:
        await on_partial({"initial_responses": initial_responses})

    await report_progress(on_progress, "critique", 2, stage_total, "Эксперты критикуют ответы друг друга")
    critiques = await run_debate_round(topic, initial_responses, payload.context, payload.comments)
    require_any_success(critiques, "critique")
    if on_partial:
        await on_partial({"initial_responses": initial_responses, "critiques": critiques})

    await report_progress(on_progress, "revision", 3, stage_total, "Эксперты дорабатывают свои ответы")
    revised_responses = await run_revision_round(
        topic, initial_responses, critiques, payload.context, payload.comments
    )
    require_any_success(revised_responses, "revision")
    if on_partial:
        await on_partial(
            {
                "initial_responses": initial_responses,
                "critiques": critiques,
                "revised_responses": revised_responses,
            }
        )

    await report_progress(on_progress, "synthesis", 4, stage_total, "Модератор собирает итог")
    final_synthesis = await synthesize_debate_results(
        topic, revised_responses, critiques, payload.context, payload.comments
    )

    return {
        "topic": topic,
        "mode": "debate",
        "debate_mode": "full",
        "initial_responses": initial_responses,
        "critiques": critiques,
        "revised_responses": revised_responses,
        "final_synthesis": final_synthesis,
        "debate_report": build_debate_report(
            topic, initial_responses, critiques, revised_responses, final_synthesis, debate_mode="full"
        ),
    }


async def execute_debate_light(
    payload: BrainstormRequest,
    on_progress: ProgressCallback | None = None,
    *,
    on_partial: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    topic = payload.topic.strip()
    stage_total = 3

    await report_progress(on_progress, "initial", 1, stage_total, "Эксперты дают первичные ответы")
    initial_responses = await run_initial_expert_round(topic, payload.context, payload.comments)
    require_any_success(initial_responses, "initial")
    if on_partial:
        await on_partial({"initial_responses": initial_responses})

    await report_progress(on_progress, "critique", 2, stage_total, "Эксперты критикуют ответы друг друга")
    critiques = await run_debate_round(topic, initial_responses, payload.context, payload.comments)
    require_any_success(critiques, "critique")
    if on_partial:
        await on_partial({"initial_responses": initial_responses, "critiques": critiques})

    await report_progress(
        on_progress, "synthesis", 3, stage_total, "Модератор собирает итог без доработки"
    )
    final_synthesis = await synthesize_debate_results_light(
        topic, initial_responses, critiques, payload.context, payload.comments
    )

    return {
        "topic": topic,
        "mode": "debate",
        "debate_mode": "light",
        "initial_responses": initial_responses,
        "critiques": critiques,
        "revised_responses": [],
        "final_synthesis": final_synthesis,
        "debate_report": build_debate_report(
            topic, initial_responses, critiques, [], final_synthesis, debate_mode="light"
        ),
    }


async def execute_debate(
    payload: BrainstormRequest,
    on_progress: ProgressCallback | None = None,
    *,
    on_partial: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    if payload.debate_mode == "light":
        return await execute_debate_light(payload, on_progress, on_partial=on_partial)
    return await execute_debate_full(payload, on_progress, on_partial=on_partial)
