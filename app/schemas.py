from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import get_settings

DebateMode = Literal["full", "light"]


def _limits():
    return get_settings()


class BrainstormRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2000)
    context: str | None = Field(None, max_length=80000)
    comments: str | None = Field(None, max_length=10000)
    debate_mode: DebateMode = Field(
        default="full",
        description="full: все раунды спора; light: без доработки экспертов",
    )


class AgentQuestionRequest(BaseModel):
    role: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    context: str | None = None


class FailedAgent(BaseModel):
    role: str
    error: str


class AgentResponseItem(BaseModel):
    role: str
    model: str
    configured_model: str
    response: str = ""
    success: bool
    error: str | None = None


class BrainstormResponse(BaseModel):
    topic: str
    agent_responses: list[dict[str, Any]]
    final_synthesis: str
    partial: bool = False
    failed_agents: list[FailedAgent] = Field(default_factory=list)


class DebateResponse(BaseModel):
    topic: str
    mode: str = "debate"
    debate_mode: DebateMode
    initial_responses: list[dict[str, Any]]
    critiques: list[dict[str, Any]]
    revised_responses: list[dict[str, Any]]
    final_synthesis: str
    debate_report: str


class JobStartResponse(BaseModel):
    job_id: str
    status: str
    debate_mode: DebateMode | None = None
    poll_url: str


class HealthAgent(BaseModel):
    role: str
    model: str
    fallback_model: str | None = None
    display_name: str
    description: str


class ContextSourceItem(BaseModel):
    kind: str
    ref: str
    text: str
    warning: str | None = None


class ContextImportRequest(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=20)
    youtube_urls: list[str] = Field(default_factory=list, max_length=20)


class ContextImportResponse(BaseModel):
    sources: list[ContextSourceItem]
    combined_text: str


class ContextExtractResponse(BaseModel):
    filename: str
    text: str
    kind: str = "file"
    warning: str | None = None


class HealthResponse(BaseModel):
    status: str
    agents_from_yaml: int
    agents: list[HealthAgent]
    synthesis: dict[str, Any]
    openrouter: dict[str, Any]
    llm_max_concurrent: int
    debate_modes: dict[str, Any]
    readiness_message: str | None = None
    supported_context_types: list[str] = Field(default_factory=list)
    context_features: dict[str, Any] = Field(default_factory=dict)
