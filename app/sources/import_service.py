"""Combine URL/YouTube sources into context payloads."""

from __future__ import annotations

from app.config import Settings
from app.sources.url_fetch import fetch_url_text, parse_url_lines
from app.sources.youtube_fetch import fetch_youtube_transcript, parse_youtube_lines


def truncate_combined(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[Контекст обрезан.]"


def format_source_block(kind: str, ref: str, text: str) -> str:
    return f"## Источник ({kind}): {ref}\n\n{text}"


def build_combined_text(sources: list[dict], max_chars: int) -> str:
    if not sources:
        return ""
    blocks = [format_source_block(item["kind"], item["ref"], item["text"]) for item in sources if item.get("text")]
    header = "# Контекст из внешних источников"
    combined = "\n\n".join([header, *blocks]) if blocks else ""
    return truncate_combined(combined, max_chars)


async def import_remote_sources(
    *,
    urls: list[str],
    youtube_urls: list[str],
    settings: Settings,
) -> list[dict]:
    sources: list[dict] = []

    for url in urls:
        text, warning = await fetch_url_text(url, settings)
        sources.append({"kind": "url", "ref": url, "text": text or "_пусто_", "warning": warning})

    for url in youtube_urls:
        text, warning = fetch_youtube_transcript(url, settings)
        sources.append({"kind": "youtube", "ref": url, "text": text or "_пусто_", "warning": warning})

    return sources


def normalize_import_request(urls: list[str], youtube_urls: list[str]) -> tuple[list[str], list[str]]:
    url_list: list[str] = []
    for item in urls:
        url_list.extend(parse_url_lines(item))
    yt_list: list[str] = []
    for item in youtube_urls:
        yt_list.extend(parse_youtube_lines(item))
    return url_list[:20], yt_list[:20]
