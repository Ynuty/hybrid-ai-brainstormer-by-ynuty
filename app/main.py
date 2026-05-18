import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import jobs
from app.agents import find_agent_by_role, is_synthesis_role, load_agents_yaml
from app.auth import verify_api_key
from app.brainstorm import run_brainstorm
from app.config import get_settings
from app.debate import execute_debate
from app.jobs_runner import run_brainstorm_job, run_debate_job
from app.sources.audio_transcribe import transcribe_audio_bytes
from app.sources.file_extract import (
    extract_text_from_bytes,
    is_audio_filename,
    is_supported_filename,
    list_supported_file_extensions,
)
from app.sources.import_service import (
    build_combined_text,
    import_remote_sources,
    normalize_import_request,
)
from app.schemas import (
    AgentQuestionRequest,
    BrainstormRequest,
    BrainstormResponse,
    ContextExtractResponse,
    ContextImportRequest,
    ContextImportResponse,
    ContextSourceItem,
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
limiter = Limiter(key_func=get_remote_address)


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
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return application


def _context_rate_limit() -> str:
    return f"{get_settings().rate_limit_per_minute}/minute"


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
        supported_context_types=list_supported_file_extensions(),
        context_features={
            "url_import": settings.enable_url_import,
            "youtube_import": settings.enable_youtube_import,
            "audio_transcribe": settings.enable_audio_transcribe,
            "audio_mode": settings.audio_transcribe_mode,
        },
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


@app.post(
    "/context/extract",
    response_model=ContextExtractResponse,
    dependencies=[Depends(verify_api_key)],
)
@limiter.limit(_context_rate_limit)
async def extract_context(request: Request, file: UploadFile = File(...)):
    settings = get_settings()
    raw = await file.read()
    filename = file.filename or "upload.bin"
    is_audio = is_audio_filename(filename)

    if is_audio:
        if not settings.enable_audio_transcribe:
            raise HTTPException(status_code=415, detail="Audio transcription is disabled.")
        max_bytes = settings.max_audio_upload_mb * 1024 * 1024
    else:
        max_bytes = settings.max_upload_mb * 1024 * 1024

    if len(raw) > max_bytes:
        limit_mb = settings.max_audio_upload_mb if is_audio else settings.max_upload_mb
        raise HTTPException(status_code=413, detail=f"File exceeds {limit_mb} MB limit.")

    if not is_supported_filename(filename):
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. See /health supported_context_types.",
        )

    warning = None
    if is_audio:
        text, warning = await asyncio.to_thread(transcribe_audio_bytes, raw, filename, settings)
        kind = "audio"
    else:
        text = extract_text_from_bytes(raw, filename)
        kind = "file"

    if len(text) > settings.max_context_chars:
        text = text[: settings.max_context_chars] + "\n\n[Файл обрезан для контекста.]"

    return ContextExtractResponse(filename=filename, text=text, kind=kind, warning=warning)


@app.post(
    "/context/import",
    response_model=ContextImportResponse,
    dependencies=[Depends(verify_api_key)],
)
@limiter.limit(_context_rate_limit)
async def import_context(request: Request, payload: ContextImportRequest):
    settings = get_settings()
    urls, youtube_urls = normalize_import_request(payload.urls, payload.youtube_urls)
    if not urls and not youtube_urls:
        raise HTTPException(status_code=400, detail="Provide urls and/or youtube_urls.")

    sources_raw = await import_remote_sources(
        urls=urls,
        youtube_urls=youtube_urls,
        settings=settings,
    )
    combined_text = build_combined_text(sources_raw, settings.max_context_chars)
    sources = [ContextSourceItem(**item) for item in sources_raw]
    return ContextImportResponse(sources=sources, combined_text=combined_text)
