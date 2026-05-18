"""Transcribe audio files for LLM context."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import PurePath

from app.config import Settings

logger = logging.getLogger(__name__)


def transcribe_audio_bytes(raw: bytes, filename: str, settings: Settings) -> tuple[str, str | None]:
    if not settings.enable_audio_transcribe:
        return "", "Транскрипция аудио отключена (ENABLE_AUDIO_TRANSCRIBE=false)."

    suffix = PurePath(filename).suffix or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        if settings.audio_transcribe_mode == "local":
            return _transcribe_local(tmp_path, settings)
        return _transcribe_cloud(tmp_path, settings)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _transcribe_cloud(path: str, settings: Settings) -> tuple[str, str | None]:
    api_key = settings.openai_api_key.strip()
    if not api_key:
        return (
            "[Аудио: задайте OPENAI_API_KEY для cloud-режима или AUDIO_TRANSCRIBE_MODE=local.]",
            "missing_api_key",
        )
    try:
        import litellm
    except ImportError:
        return "[Аудио: установите litellm.]", "missing_dependency"

    try:
        with open(path, "rb") as audio_file:
            result = litellm.transcription(
                model=settings.whisper_model,
                file=audio_file,
                api_key=api_key,
            )
        text = getattr(result, "text", None) or (result.get("text") if isinstance(result, dict) else "")
        text = (text or "").strip()
        if not text:
            return "_Аудио без распознанной речи_", None
        return f"### Транскрипт аудио\n\n{text}", None
    except Exception as exc:
        logger.exception("Cloud transcription failed: %s", exc)
        return f"[Транскрипция не удалась: {exc}]", str(exc)


def _transcribe_local(path: str, settings: Settings) -> tuple[str, str | None]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return (
            "[Локальная транскрипция: установите faster-whisper (requirements-audio.txt).]",
            "missing_dependency",
        )

    try:
        model = WhisperModel(settings.whisper_local_model, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(path, beam_size=5)
        lines = [segment.text.strip() for segment in segments if segment.text.strip()]
        text = "\n".join(lines).strip()
        if not text:
            return "_Аудио без распознанной речи_", None
        return f"### Транскрипт аудио\n\n{text}", None
    except Exception as exc:
        logger.exception("Local transcription failed: %s", exc)
        return f"[Локальная транскрипция не удалась: {exc}]", str(exc)
