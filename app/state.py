import logging

from app.config import get_settings
from app.models import AgentSpec, SynthesisSpec

logger = logging.getLogger(__name__)

EXPERT_ROLES = [
    "Продуктовый стратег",
    "Креативный маркетолог",
    "Технический архитектор",
]

_agents: list[AgentSpec] = []
_synthesis: SynthesisSpec | None = None
_openrouter_required: bool = False
_llm_ready: bool = True
_readiness_message: str | None = None


def agents_from_yaml() -> list[AgentSpec]:
    return list(_agents)


def synthesis_config() -> SynthesisSpec | None:
    return _synthesis


def active_agents() -> list[AgentSpec]:
    if _agents:
        return _agents
    settings = get_settings()
    from app.prompts import default_agent_prompt

    return [
        AgentSpec(
            role=role,
            model=settings.brainstorm_model,
            system_prompt=default_agent_prompt(role),
            temperature=0.7,
        )
        for role in EXPERT_ROLES
    ]


def active_synthesis() -> SynthesisSpec:
    settings = get_settings()
    if _synthesis:
        return _synthesis
    from app.prompts import default_synthesis_prompt

    return SynthesisSpec(
        model=settings.synthesis_model_resolved,
        system_prompt=default_synthesis_prompt(),
        temperature=0.4,
    )


def uses_openrouter() -> bool:
    return _openrouter_required


def llm_ready() -> bool:
    return _llm_ready


def readiness_message() -> str | None:
    return _readiness_message


def set_runtime_config(agents: list[AgentSpec], synthesis: SynthesisSpec | None) -> None:
    global _agents, _synthesis, _openrouter_required, _llm_ready, _readiness_message
    _agents = agents
    _synthesis = synthesis
    _openrouter_required = _models_use_openrouter(active_agents(), synthesis)
    settings = get_settings()
    if _openrouter_required and not settings.openrouter_api_key.strip():
        _llm_ready = False
        _readiness_message = "OPENROUTER_API_KEY is required for configured openrouter/ models."
        logger.warning(_readiness_message)
    else:
        _llm_ready = True
        _readiness_message = None


def _models_use_openrouter(agents: list[AgentSpec], synthesis: SynthesisSpec | None) -> bool:
    settings = get_settings()
    models = [agent.model for agent in agents]
    models.extend(agent.fallback_model for agent in agents if agent.fallback_model)
    if synthesis:
        models.append(synthesis.model)
        if synthesis.fallback_model:
            models.append(synthesis.fallback_model)
    else:
        models.append(settings.synthesis_model_resolved)
    return any(model.startswith("openrouter/") for model in models)
