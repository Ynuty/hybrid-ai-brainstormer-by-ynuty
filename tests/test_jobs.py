import asyncio
import os

import jobs
from jobs import JobStatus


def test_job_lifecycle(tmp_path):
    os.environ["JOBS_DB_PATH"] = str(tmp_path / "jobs.db")

    async def run():
        job = await jobs.create_job(job_type="debate", topic="test", debate_mode="light")
        assert job.status == JobStatus.QUEUED

        def mark_running(state: jobs.JobState) -> None:
            state.status = JobStatus.RUNNING
            state.set_progress("initial", 1, 3, "start")
            state.partial = {"stage": "initial"}

        await jobs.update_job(job.job_id, mark_running)
        loaded = await jobs.get_job(job.job_id)
        assert loaded is not None
        assert loaded.status == JobStatus.RUNNING
        assert loaded.progress is not None
        assert loaded.partial == {"stage": "initial"}

        reloaded = await jobs.get_job(job.job_id)
        assert reloaded is not None
        assert reloaded.job_id == job.job_id
        assert reloaded.progress is not None
        assert reloaded.progress.message == "start"

        interactive = await jobs.create_job(
            job_type="debate",
            topic="interactive",
            debate_mode="full",
            request_payload={"topic": "interactive", "interactive_debate": True},
        )

        def wait_for_user(state: jobs.JobState) -> None:
            state.status = JobStatus.WAITING_FOR_USER
            state.partial = {"initial_responses": [{"role": "Tester"}]}

        await jobs.update_job(interactive.job_id, wait_for_user)
        loaded_interactive = await jobs.get_job(interactive.job_id)
        assert loaded_interactive is not None
        assert loaded_interactive.status == JobStatus.WAITING_FOR_USER
        assert loaded_interactive.request_payload == {"topic": "interactive", "interactive_debate": True}

    try:
        asyncio.run(run())
    finally:
        os.environ.pop("JOBS_DB_PATH", None)
