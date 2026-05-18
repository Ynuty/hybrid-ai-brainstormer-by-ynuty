import asyncio
import logging
from collections.abc import Awaitable, Callable

import jobs
from app.config import get_settings
from app.debate import build_debate_report, execute_debate
from app.rag import relevant_context_for_prompt
from app.schemas import BrainstormRequest
from app.services import (
    run_debate_round,
    run_initial_expert_round,
    run_revision_round,
    synthesize_debate_results,
)
from jobs import JobStatus

logger = logging.getLogger(__name__)


async def run_debate_job(job_id: str, payload: BrainstormRequest) -> None:
    if payload.interactive_debate:
        await run_interactive_debate_until_pause(job_id, payload)
        return

    settings = get_settings()
    started = asyncio.get_event_loop().time()

    async def on_progress(stage: str, stage_index: int, stage_total: int, message: str) -> None:
        def _update(job: jobs.JobState) -> None:
            job.status = JobStatus.RUNNING
            job.set_progress(stage, stage_index, stage_total, message)

        await jobs.update_job(job_id, _update)

    async def on_partial(partial: dict) -> None:
        def _save(job: jobs.JobState) -> None:
            job.partial = partial

        await jobs.update_job(job_id, _save)

    def _mark_started(job: jobs.JobState) -> None:
        job.status = JobStatus.RUNNING

    await jobs.update_job(job_id, _mark_started)

    try:
        elapsed = asyncio.get_event_loop().time() - started
        if elapsed > settings.debate_job_max_seconds:
            raise RuntimeError("Превышено максимальное время выполнения спора моделей.")
        result = await execute_debate(payload, on_progress, on_partial=on_partial)

        def _mark_done(job: jobs.JobState) -> None:
            job.status = JobStatus.DONE
            job.result = result
            job.error = None

        await jobs.update_job(job_id, _mark_done)
    except Exception as exc:
        logger.exception("debate job %s failed: %s", job_id, exc)
        public_error = (
            str(exc)
            if isinstance(exc, RuntimeError)
            else "Не удалось завершить спор моделей. Попробуйте повторить запрос позже."
        )

        def _mark_failed(job: jobs.JobState) -> None:
            job.status = JobStatus.FAILED
            job.error = public_error

        await jobs.update_job(job_id, _mark_failed)


async def run_interactive_debate_until_pause(job_id: str, payload: BrainstormRequest) -> None:
    topic = payload.topic.strip()
    context = relevant_context_for_prompt(
        query=f"{topic}\n{payload.comments or ''}",
        context=payload.context,
    )

    def _mark_started(job: jobs.JobState) -> None:
        job.status = JobStatus.RUNNING
        job.set_progress("initial", 1, 4, "Эксперты дают первичные ответы")

    await jobs.update_job(job_id, _mark_started)

    try:
        initial_responses = await run_initial_expert_round(topic, context, payload.comments)
        if not any(item.get("success") for item in initial_responses):
            raise RuntimeError("all agents failed at stage: initial")

        def _pause(job: jobs.JobState) -> None:
            job.status = JobStatus.WAITING_FOR_USER
            job.set_progress(
                "waiting_for_user",
                2,
                4,
                "Первичный раунд готов. Введите свою критику, чтобы продолжить спор.",
            )
            job.partial = {
                "initial_responses": initial_responses,
                "context": context,
                "comments": payload.comments,
            }

        await jobs.update_job(job_id, _pause)
    except Exception as exc:
        logger.exception("interactive debate job %s failed before pause: %s", job_id, exc)

        def _mark_failed(job: jobs.JobState) -> None:
            job.status = JobStatus.FAILED
            job.error = str(exc) if isinstance(exc, RuntimeError) else "Не удалось начать интерактивный спор."

        await jobs.update_job(job_id, _mark_failed)


async def continue_interactive_debate_job(job_id: str, user_comment: str) -> None:
    job = await jobs.get_job(job_id)
    if job is None:
        return
    if job.status != JobStatus.WAITING_FOR_USER:
        return

    payload_data = job.request_payload or {}
    partial = job.partial or {}
    topic = str(payload_data.get("topic") or job.topic)
    context = partial.get("context") or payload_data.get("context")
    base_comments = partial.get("comments") or payload_data.get("comments") or ""
    comments = "\n\n".join(
        item
        for item in [
            str(base_comments).strip(),
            f"Комментарий пользователя после первого раунда:\n{user_comment.strip()}",
        ]
        if item
    )
    initial_responses = partial.get("initial_responses") or []

    def _mark_running(job_state: jobs.JobState) -> None:
        job_state.status = JobStatus.RUNNING
        job_state.set_progress("critique", 2, 4, "Эксперты учитывают критику пользователя")

    await jobs.update_job(job_id, _mark_running)

    try:
        critiques = await run_debate_round(topic, initial_responses, context, comments)
        if not any(item.get("success") for item in critiques):
            raise RuntimeError("all agents failed at stage: critique")

        def _save_critiques(job_state: jobs.JobState) -> None:
            job_state.partial = {
                "initial_responses": initial_responses,
                "critiques": critiques,
                "context": context,
                "comments": comments,
                "user_comment": user_comment,
            }
            job_state.set_progress("revision", 3, 4, "Эксперты дорабатывают ответы")

        await jobs.update_job(job_id, _save_critiques)

        revised_responses = await run_revision_round(topic, initial_responses, critiques, context, comments)
        if not any(item.get("success") for item in revised_responses):
            raise RuntimeError("all agents failed at stage: revision")

        def _save_revisions(job_state: jobs.JobState) -> None:
            job_state.partial = {
                "initial_responses": initial_responses,
                "critiques": critiques,
                "revised_responses": revised_responses,
                "context": context,
                "comments": comments,
                "user_comment": user_comment,
            }
            job_state.set_progress("synthesis", 4, 4, "Модератор собирает итог")

        await jobs.update_job(job_id, _save_revisions)

        final_synthesis = await synthesize_debate_results(topic, revised_responses, critiques, context, comments)
        result = {
            "topic": topic,
            "mode": "debate",
            "debate_mode": "full",
            "interactive_debate": True,
            "user_comment": user_comment,
            "initial_responses": initial_responses,
            "critiques": critiques,
            "revised_responses": revised_responses,
            "final_synthesis": final_synthesis,
            "debate_report": build_debate_report(
                topic,
                initial_responses,
                critiques,
                revised_responses,
                final_synthesis,
                debate_mode="full",
            ),
        }

        def _mark_done(job_state: jobs.JobState) -> None:
            job_state.status = JobStatus.DONE
            job_state.result = result
            job_state.error = None

        await jobs.update_job(job_id, _mark_done)
    except Exception as exc:
        logger.exception("interactive debate continuation %s failed: %s", job_id, exc)

        def _mark_failed(job_state: jobs.JobState) -> None:
            job_state.status = JobStatus.FAILED
            job_state.error = str(exc) if isinstance(exc, RuntimeError) else "Не удалось продолжить спор моделей."

        await jobs.update_job(job_id, _mark_failed)


async def run_brainstorm_job(job_id: str, payload: BrainstormRequest) -> None:
    from app.brainstorm import run_brainstorm

    async def on_progress(stage: str, stage_index: int, stage_total: int, message: str) -> None:
        def _update(job: jobs.JobState) -> None:
            job.status = JobStatus.RUNNING
            job.set_progress(stage, stage_index, stage_total, message)

        await jobs.update_job(job_id, _update)

    def _mark_started(job: jobs.JobState) -> None:
        job.status = JobStatus.RUNNING
        job.set_progress("experts", 1, 2, "Эксперты отвечают")

    await jobs.update_job(job_id, _mark_started)

    try:
        await on_progress("experts", 1, 2, "Эксперты отвечают")
        result = await run_brainstorm(payload)
        await on_progress("synthesis", 2, 2, "Модератор собирает итог")

        def _mark_done(job: jobs.JobState) -> None:
            job.status = JobStatus.DONE
            job.result = result
            job.error = None

        await jobs.update_job(job_id, _mark_done)
    except Exception as exc:
        logger.exception("brainstorm job %s failed: %s", job_id, exc)
        public_error = str(exc) if isinstance(exc, RuntimeError) else "Brainstorm failed."

        def _mark_failed(job: jobs.JobState) -> None:
            job.status = JobStatus.FAILED
            job.error = public_error

        await jobs.update_job(job_id, _mark_failed)
