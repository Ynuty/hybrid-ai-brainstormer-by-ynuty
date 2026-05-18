"""Fetch YouTube video transcripts."""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from app.config import Settings

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def parse_youtube_lines(text: str) -> list[str]:
    urls: list[str] = []
    for line in text.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            urls.append(candidate)
    return urls


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().replace("www.", "")
    if host in {"youtu.be"}:
        video_id = parsed.path.lstrip("/").split("/")[0]
        return video_id if _VIDEO_ID_RE.match(video_id) else None
    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            ids = parse_qs(parsed.query).get("v", [])
            if ids and _VIDEO_ID_RE.match(ids[0]):
                return ids[0]
        if parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
            return video_id if _VIDEO_ID_RE.match(video_id) else None
    return None


def fetch_youtube_transcript(url: str, settings: Settings) -> tuple[str, str | None]:
    if not settings.enable_youtube_import:
        return "", "Импорт YouTube отключён (ENABLE_YOUTUBE_IMPORT=false)."

    video_id = extract_video_id(url)
    if not video_id:
        return f"[Некорректная YouTube-ссылка: {url}]", "invalid_url"

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
        )
    except ImportError:
        return "[YouTube: установите youtube-transcript-api.]", "missing_dependency"

    languages = ["ru", "en", "uk", "de", "fr", "es"]
    try:
        try:
            entries = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        except Exception:
            entries = YouTubeTranscriptApi.get_transcript(video_id)
        lines = [entry.get("text", "").strip() for entry in entries if entry.get("text")]
        text = "\n".join(lines).strip()
        if text:
            return f"### YouTube {video_id}\n\n{text}", None
        return "_Субтитры пусты_", None
    except (NoTranscriptFound, TranscriptsDisabled) as exc:
        if settings.youtube_use_ytdlp:
            return _fetch_via_ytdlp(url, video_id)
        return f"[Субтитры недоступны для {video_id}: {exc}]", str(exc)
    except VideoUnavailable as exc:
        return f"[Видео недоступно: {exc}]", str(exc)
    except Exception as exc:
        logger.exception("YouTube transcript failed %s: %s", url, exc)
        if settings.youtube_use_ytdlp:
            return _fetch_via_ytdlp(url, video_id)
        return f"[YouTube ошибка: {exc}]", str(exc)


def _fetch_via_ytdlp(url: str, video_id: str) -> tuple[str, str | None]:
    try:
        import yt_dlp
    except ImportError:
        return (
            f"[Субтитры не найдены для {video_id}. Включите YOUTUBE_USE_YTDLP и установите yt-dlp.]",
            "no_transcript",
        )

    options = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ru", "en"],
        "quiet": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        subtitles = info.get("subtitles") or {}
        automatic = info.get("automatic_captions") or {}
        for lang in ("ru", "en"):
            for source in (subtitles, automatic):
                tracks = source.get(lang)
                if not tracks:
                    continue
                for track in tracks:
                    if track.get("ext") == "vtt" and track.get("url"):
                        import httpx

                        response = httpx.get(track["url"], timeout=30)
                        response.raise_for_status()
                        text = response.text
                        return f"### YouTube {video_id}\n\n{text[:50000]}", None
    except Exception as exc:
        logger.warning("yt-dlp fallback failed %s: %s", url, exc)
        return f"[YouTube fallback не удался: {exc}]", str(exc)
    return f"[Субтитры не найдены для {video_id}]", "no_transcript"
