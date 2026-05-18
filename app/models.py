from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    role: str
    model: str
    system_prompt: str
    temperature: float = 0.7
    fallback_model: str | None = None
    display_name: str | None = None
    description: str | None = None

    def public_dict(self) -> dict:
        return {
            "role": self.role,
            "model": self.model,
            "fallback_model": self.fallback_model,
            "display_name": self.display_name or self.role,
            "description": self.description or "",
        }


@dataclass(frozen=True)
class SynthesisSpec:
    model: str
    system_prompt: str
    temperature: float = 0.4
    fallback_model: str | None = None
    display_name: str | None = None
    description: str | None = None

    def public_dict(self) -> dict:
        return {
            "model": self.model,
            "fallback_model": self.fallback_model,
            "display_name": self.display_name or "Модератор",
            "description": self.description or "финальный синтез и устранение противоречий",
        }
