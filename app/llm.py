import asyncio
import logging
from typing import Any

from litellm import acompletion

from app.config import get_settings

logger = logging.getLogger(__name__)
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        settings = get_settings()
        _semaphore = asyncio.Semaphore(max(1, settings.llm_max_concurrent))
    return _semaphore


def public_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: модель временно недоступна или вернула ошибку"


async def acompletion_with_timeout(**kwargs: Any):
    settings = get_settings()
    return await asyncio.wait_for(acompletion(**kwargs), timeout=settings.model_timeout_s)


async def completion_content(
    *,
    model: str,
    temperature: float,
    messages: list[dict[str, str]],
    fallback_model: str | None,
    log_context: str,
) -> tuple[str, str]:
    settings = get_settings()
    models = [model]
    if fallback_model and fallback_model != model:
        models.append(fallback_model)

    last_exc: Exception | None = None
    for model_name in models:
        for attempt in range(1, settings.model_retry_attempts + 1):
            try:
                async with get_semaphore():
                    response = await acompletion_with_timeout(
                        model=model_name,
                        temperature=temperature,
                        messages=messages,
                    )
                choice = response.choices[0] if response.choices else None
                content = (choice.message.content if choice and choice.message else "") or ""
                if content.strip():
                    return content, model_name
                raise RuntimeError("empty model response")
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "%s failed model=%s attempt=%d/%d: %s",
                    log_context,
                    model_name,
                    attempt,
                    settings.model_retry_attempts,
                    exc,
                )
                if attempt < settings.model_retry_attempts:
                    await asyncio.sleep(settings.model_retry_backoff_s * attempt)

    if last_exc is None:
        raise RuntimeError("model call failed without exception")
    raise last_exc
