"""SQLite job store for long-running brainstorm/debate tasks."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "jobs.db"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
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
    request_payload: dict[str, Any] | None = None
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


_lock = asyncio.Lock()


def _db_path() -> Path:
    raw = os.getenv("JOBS_DB_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            topic TEXT NOT NULL,
            debate_mode TEXT,
            progress_json TEXT,
            partial_json TEXT,
            result_json TEXT,
            request_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
    if "request_json" not in columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN request_json TEXT")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at)")
    connection.commit()


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def _progress_from_dict(payload: dict[str, Any] | None) -> JobProgress | None:
    if not payload:
        return None
    return JobProgress(
        stage=str(payload.get("stage") or ""),
        stage_index=int(payload.get("stage_index") or 0),
        stage_total=int(payload.get("stage_total") or 0),
        message=str(payload.get("message") or ""),
    )


def _row_to_job(row: sqlite3.Row | None) -> JobState | None:
    if row is None:
        return None
    return JobState(
        job_id=row["job_id"],
        job_type=row["job_type"],
        status=JobStatus(row["status"]),
        topic=row["topic"],
        debate_mode=row["debate_mode"],
        progress=_progress_from_dict(_json_loads(row["progress_json"])),
        partial=_json_loads(row["partial_json"]),
        result=_json_loads(row["result_json"]),
        request_payload=_json_loads(row["request_json"]) if "request_json" in row.keys() else None,
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _save_job(connection: sqlite3.Connection, job: JobState) -> None:
    connection.execute(
        """
        INSERT INTO jobs (
            job_id, job_type, status, topic, debate_mode,
            progress_json, partial_json, result_json, request_json, error,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            job_type=excluded.job_type,
            status=excluded.status,
            topic=excluded.topic,
            debate_mode=excluded.debate_mode,
            progress_json=excluded.progress_json,
            partial_json=excluded.partial_json,
            result_json=excluded.result_json,
            request_json=excluded.request_json,
            error=excluded.error,
            created_at=excluded.created_at,
            updated_at=excluded.updated_at
        """,
        (
            job.job_id,
            job.job_type,
            job.status.value,
            job.topic,
            job.debate_mode,
            _json_dumps(job.progress.to_dict() if job.progress else None),
            _json_dumps(job.partial),
            _json_dumps(job.result),
            _json_dumps(job.request_payload),
            job.error,
            job.created_at,
            job.updated_at,
        ),
    )
    connection.commit()


async def create_job(
    *,
    job_type: str,
    topic: str,
    debate_mode: str | None = None,
    request_payload: dict[str, Any] | None = None,
) -> JobState:
    job = JobState(
        job_id=str(uuid4()),
        job_type=job_type,
        status=JobStatus.QUEUED,
        topic=topic,
        debate_mode=debate_mode,
        request_payload=request_payload,
    )
    async with _lock:
        with _connect() as connection:
            _save_job(connection, job)
    return job


async def get_job(job_id: str) -> JobState | None:
    async with _lock:
        with _connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            return _row_to_job(row)


async def update_job(job_id: str, updater) -> JobState | None:
    async with _lock:
        with _connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            job = _row_to_job(row)
            if job is None:
                return None
            updater(job)
            job.touch()
            _save_job(connection, job)
            return job


async def cleanup_expired_jobs(ttl_hours: int) -> int:
    if ttl_hours <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    async with _lock:
        with _connect() as connection:
            cursor = connection.execute("DELETE FROM jobs WHERE updated_at < ?", (cutoff.isoformat(),))
            connection.commit()
            return int(cursor.rowcount)
