import asyncio

import jobs
from jobs import JobStatus


def test_job_lifecycle():
    async def run():
        job = await jobs.create_job(job_type="debate", topic="test", debate_mode="light")
        assert job.status == JobStatus.QUEUED

        def mark_running(state: jobs.JobState) -> None:
            state.status = JobStatus.RUNNING
            state.set_progress("initial", 1, 3, "start")

        await jobs.update_job(job.job_id, mark_running)
        loaded = await jobs.get_job(job.job_id)
        assert loaded is not None
        assert loaded.status == JobStatus.RUNNING
        assert loaded.progress is not None

    asyncio.run(run())
