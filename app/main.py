import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import jobs
from app.agents import find_agent_by_role, is_synthesis_role, load_agents_yaml
from app.auth import verify_api_key
from app.brainstorm import run_brainstorm
from app.config import get_settings
from app.debate import execute_debate
from app.jobs_runner import run_brainstorm_job, run_debate_job
from app.file_extract import extract_text_from_bytes, is_supported_filename
from app.schemas import (
    AgentQuestionRequest,
    BrainstormRequest,
    BrainstormResponse,
    DebateResponse,
    HealthResponse,
    JobStartResponse,
)
from app.services import ask_synthesis, call_agent_custom
from app.prompts import agent_question_prompt
from app.state import (
    active_agents,
    active_synthesis,
    agents_from_yaml,
    llm_ready,
    readiness_message,
    set_runtime_config,
    synthesis_config,
    uses_openrouter,
)
from jobs import JobStatus, cleanup_expired_jobs

logger = logging.getLogger(__name__)


def _require_llm_ready() -> None:
    if not llm_ready():
        raise HTTPException(
            status_code=503,
            detail=readiness_message() or "LLM provider is not configured.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    agents, synthesis = load_agents_yaml()
    set_runtime_config(agents, synthesis)
    removed = await cleanup_expired_jobs(settings.job_ttl_hours)
    if removed:
        logger.info("Cleaned up %d expired jobs", removed)
    yield
    await cleanup_expired_jobs(settings.job_ttl_hours)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="AI Brainstorm API", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return application


app = create_app()


@app.get("/health", response_model=HealthResponse)
async def health():
    settings = get_settings()
    synthesis = synthesis_config()
    status = "ok" if llm_ready() else "degraded"
    agent_items = [agent.public_dict() for agent in agents_from_yaml() or active_agents()]
    return HealthResponse(
        status=status,
        agents_from_yaml=len(agents_from_yaml()),
        agents=agent_items,
        synthesis=synthesis.public_dict() if synthesis else active_synthesis().public_dict(),
        openrouter={
            "required": uses_openrouter(),
            "api_key_configured": bool(settings.openrouter_api_key.strip()),
        },
        llm_max_concurrent=settings.llm_max_concurrent,
        debate_modes={
            "full": {
                "stages": 4,
                "description": "Первичные ответы → критика → доработка → синтез (~10 вызовов LLM)",
            },
            "light": {
                "stages": 3,
                "description": "Первичные ответы → критика → синтез (~7 вызовов LLM)",
            },
        },
        readiness_message=readiness_message(),
    )


@app.post("/brainstorm", response_model=BrainstormResponse, dependencies=[Depends(verify_api_key)])
async def brainstorm(payload: BrainstormRequest):
    _require_llm_ready()
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")
    try:
        result = await run_brainstorm(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("brainstorm failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Не удалось получить итоговый синтез. Попробуйте повторить запрос позже.",
        ) from exc
    return BrainstormResponse(**result)


@app.post("/brainstorm/jobs", response_model=JobStartResponse, dependencies=[Depends(verify_api_key)])
async def start_brainstorm_job(payload: BrainstormRequest):
    _require_llm_ready()
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")
    job = await jobs.create_job(job_type="brainstorm", topic=topic)
    asyncio.create_task(run_brainstorm_job(job.job_id, payload))
    return JobStartResponse(
        job_id=job.job_id,
        status=job.status.value,
        poll_url=f"/jobs/{job.job_id}",
    )


@app.post("/brainstorm/debate", response_model=JobStartResponse, dependencies=[Depends(verify_api_key)])
async def start_debate_job(payload: BrainstormRequest):
    _require_llm_ready()
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")
    job = await jobs.create_job(
        job_type="debate",
        topic=topic,
        debate_mode=payload.debate_mode,
    )
    asyncio.create_task(run_debate_job(job.job_id, payload))
    return JobStartResponse(
        job_id=job.job_id,
        status=job.status.value,
        debate_mode=payload.debate_mode,
        poll_url=f"/jobs/{job.job_id}",
    )


@app.post("/brainstorm/debate/sync", response_model=DebateResponse, dependencies=[Depends(verify_api_key)])
async def brainstorm_debate_sync(payload: BrainstormRequest):
    _require_llm_ready()
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")
    try:
        return DebateResponse(**await execute_debate(payload))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("brainstorm_debate_sync failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Не удалось завершить спор моделей.",
        ) from exc


@app.get("/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
async def get_job_status(job_id: str):
    job = await jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.to_public_dict(include_result=True)


@app.get("/jobs/{job_id}/events", dependencies=[Depends(verify_api_key)])
async def stream_job_events(job_id: str):
    async def event_generator():
        last_payload: str | None = None
        while True:
            job = await jobs.get_job(job_id)
            if job is None:
                yield f"data: {json.dumps({'event': 'error', 'detail': 'Job not found'}, ensure_ascii=False)}\n\n"
                break
            payload = json.dumps(job.to_public_dict(include_result=True), ensure_ascii=False)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if job.status in (JobStatus.DONE, JobStatus.FAILED):
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/agents/ask", dependencies=[Depends(verify_api_key)])
async def ask_agent(payload: AgentQuestionRequest):
    _require_llm_ready()
    role = payload.role.strip()
    question = payload.question.strip()
    if not role:
        raise HTTPException(status_code=400, detail="Role cannot be empty.")
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    if is_synthesis_role(role):
        return await ask_synthesis(question, payload.context)

    agent = find_agent_by_role(role)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent role not found: {role}")

    from app.context_utils import truncate_for_prompt

    settings = get_settings()
    context = truncate_for_prompt(payload.context, settings.max_context_chars)
    context_block = f"\n\nКонтекст:\n{context}" if context else ""
    user_prompt = f"Вопрос пользователя:\n{question}{context_block}"
    result = await call_agent_custom(
        agent,
        system_prompt=agent_question_prompt(agent.system_prompt),
        user_prompt=user_prompt,
        log_context=f"ask_agent role={agent.role}",
    )
    result["question"] = question
    return result


@app.post("/context/extract", dependencies=[Depends(verify_api_key)])
async def extract_context(file: UploadFile = File(...)):
    settings = get_settings()
    raw = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.max_upload_mb} MB limit.",
        )
    filename = file.filename or "upload.bin"
    if not is_supported_filename(filename):
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported file type. Allowed: pdf, pptx, xlsx, xls, json, csv, txt, md "
                "and other text formats."
            ),
        )
    text = extract_text_from_bytes(raw, filename)
    if len(text) > settings.max_context_chars:
        text = text[: settings.max_context_chars] + "\n\n[Файл обрезан для контекста.]"
    return {"filename": filename, "text": text}
