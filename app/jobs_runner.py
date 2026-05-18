import asyncio
import logging
from collections.abc import Awaitable, Callable

import jobs
from app.config import get_settings
from app.debate import execute_debate
from app.schemas import BrainstormRequest
from jobs import JobStatus

logger = logging.getLogger(__name__)


async def run_debate_job(job_id: str, payload: BrainstormRequest) -> None:
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
