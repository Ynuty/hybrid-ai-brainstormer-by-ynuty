import logging
from typing import Any

import yaml

from app.config import get_settings
from app.models import AgentSpec, SynthesisSpec
from app.prompts import default_agent_prompt, default_synthesis_prompt

logger = logging.getLogger(__name__)


def coerce_temperature(value: Any, default: float, label: str) -> float:
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        logger.warning("%s has invalid temperature=%r — using %.1f", label, value, default)
        return default
    if not 0 <= temperature <= 2:
        logger.warning("%s temperature %.2f is outside 0..2 — using %.1f", label, temperature, default)
        return default
    return temperature


def load_agents_yaml() -> tuple[list[AgentSpec], SynthesisSpec | None]:
    settings = get_settings()
    path = settings.config_path
    default_model = settings.brainstorm_model
    synthesis_default = settings.synthesis_model_resolved

    if not path.exists():
        logger.warning("agents_config not found at %s — using env defaults and EXPERT_ROLES", path)
        return [], None

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.exception("Failed to parse %s: %s", path, exc)
        return [], None

    experts_raw = raw.get("experts") or []
    synthesis_raw = raw.get("synthesis") or {}
    if experts_raw and not isinstance(experts_raw, list):
        logger.warning("agents_config experts must be a list — using fallback roles")
        experts_raw = []

    agents: list[AgentSpec] = []
    for index, item in enumerate(experts_raw, start=1):
        if not isinstance(item, dict):
            logger.warning("agents_config expert #%d is not an object — skipped", index)
            continue
        role = str(item.get("role", "")).strip()
        model = str(item.get("model", default_model)).strip() or default_model
        system_prompt = str(item.get("system_prompt", "")).strip()
        fallback_model = str(item.get("fallback_model", "")).strip() or None
        display_name = str(item.get("display_name", "")).strip() or None
        description = str(item.get("description", "")).strip() or None
        temperature = coerce_temperature(item.get("temperature", 0.7), 0.7, f"expert #{index}")
        if role and system_prompt:
            agents.append(
                AgentSpec(
                    role=role,
                    model=model,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    fallback_model=fallback_model,
                    display_name=display_name,
                    description=description,
                )
            )
        else:
            logger.warning(
                "agents_config expert #%d skipped: role and system_prompt are required",
                index,
            )

    synthesis_spec: SynthesisSpec | None = None
    if isinstance(synthesis_raw, dict) and synthesis_raw:
        smodel = str(synthesis_raw.get("model", synthesis_default)).strip() or synthesis_default
        sprompt = str(synthesis_raw.get("system_prompt", "")).strip() or default_synthesis_prompt()
        sfallback = str(synthesis_raw.get("fallback_model", "")).strip() or None
        stemp = coerce_temperature(synthesis_raw.get("temperature", 0.4), 0.4, "synthesis")
        synthesis_spec = SynthesisSpec(
            model=smodel,
            system_prompt=sprompt,
            temperature=stemp,
            fallback_model=sfallback,
            display_name=str(synthesis_raw.get("display_name", "")).strip() or "GPT-5.1 Модератор",
            description=str(synthesis_raw.get("description", "")).strip()
            or "финальный синтез и устранение противоречий",
        )
    elif synthesis_raw:
        logger.warning("agents_config synthesis must be an object — using default synthesis prompt")

    if agents:
        logger.info("Loaded %d experts from %s", len(agents), path)
    else:
        logger.warning("No valid experts in %s — using EXPERT_ROLES fallback", path)

    return agents, synthesis_spec


def find_agent_by_role(role: str) -> AgentSpec | None:
    normalized_role = role.strip().lower()
    for agent in active_agents_import():
        if agent.role.strip().lower() == normalized_role:
            return agent
    return None


def is_synthesis_role(role: str) -> bool:
    normalized_role = role.strip().lower()
    return normalized_role in {
        "модератор",
        "финальный синтез",
        "синтез",
        "главный стратег",
    }


def active_agents_import():
    from app.state import active_agents

    return active_agents()
