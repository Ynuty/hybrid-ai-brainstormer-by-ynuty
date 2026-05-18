"""In-memory job store for long-running brainstorm/debate tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class JobProgress:
    stage: str
    stage_index: int
    stage_total: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_index": self.stage_index,
            "stage_total": self.stage_total,
            "message": self.message,
        }


@dataclass
class JobState:
    job_id: str
    job_type: str
    status: JobStatus
    topic: str
    debate_mode: str | None = None
    progress: JobProgress | None = None
    partial: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def set_progress(self, stage: str, stage_index: int, stage_total: int, message: str) -> None:
        self.progress = JobProgress(stage, stage_index, stage_total, message)
        self.touch()

    def to_public_dict(self, *, include_result: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "topic": self.topic,
            "debate_mode": self.debate_mode,
            "progress": self.progress.to_dict() if self.progress else None,
            "partial": self.partial,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_result and self.status == JobStatus.DONE and self.result is not None:
            payload["result"] = self.result
        return payload


_jobs: dict[str, JobState] = {}
_lock = asyncio.Lock()


async def create_job(*, job_type: str, topic: str, debate_mode: str | None = None) -> JobState:
    job = JobState(
        job_id=str(uuid4()),
        job_type=job_type,
        status=JobStatus.QUEUED,
        topic=topic,
        debate_mode=debate_mode,
    )
    async with _lock:
        _jobs[job.job_id] = job
    return job


async def get_job(job_id: str) -> JobState | None:
    async with _lock:
        return _jobs.get(job_id)


async def update_job(job_id: str, updater) -> JobState | None:
    async with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        updater(job)
        job.touch()
        return job


async def cleanup_expired_jobs(ttl_hours: int) -> int:
    if ttl_hours <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    removed = 0
    async with _lock:
        expired_ids = []
        for job_id, job in _jobs.items():
            try:
                updated = datetime.fromisoformat(job.updated_at)
            except ValueError:
                expired_ids.append(job_id)
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated < cutoff:
                expired_ids.append(job_id)
        for job_id in expired_ids:
            del _jobs[job_id]
            removed += 1
    return removed
