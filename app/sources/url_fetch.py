"""Fetch and extract text from web URLs with SSRF protection."""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google",
}


def parse_url_lines(text: str) -> list[str]:
    urls: list[str] = []
    for line in text.splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            urls.append(candidate)
    return urls


def validate_url(url: str, settings: Settings) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Разрешены только ссылки http:// или https://.")

    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        raise ValueError("URL без хоста.")

    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise ValueError("Запрещённый хост (SSRF).")

    if settings.url_fetch_allowed_hosts:
        allowed = {item.strip().lower() for item in settings.url_fetch_allowed_hosts.split(",") if item.strip()}
        if host not in allowed and not any(host.endswith(f".{item}") for item in allowed):
            raise ValueError(f"Хост не в allowlist: {host}")

    _reject_private_ip(host)


def _reject_private_ip(host: str) -> None:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(addr):
            raise ValueError("Запрещённый IP (SSRF).")
        return

    try:
        for family, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            addr = ipaddress.ip_address(sockaddr[0])
            if _is_blocked_ip(addr):
                raise ValueError("Запрещённый IP после DNS (SSRF).")
    except socket.gaierror as exc:
        raise ValueError(f"Не удалось разрешить хост: {host}") from exc


def _is_blocked_ip(addr: ipaddress._BaseAddress) -> bool:
    return bool(
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _extract_html_text(html: str) -> str:
    try:
        import trafilatura
    except ImportError:
        trafilatura = None

    if trafilatura:
        extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        if extracted and extracted.strip():
            return extracted.strip()

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html[:50000]

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True) or "_страница без текста_"


async def fetch_url_text(url: str, settings: Settings) -> tuple[str, str | None]:
    if not settings.enable_url_import:
        return "", "Импорт URL отключён (ENABLE_URL_IMPORT=false)."

    try:
        validate_url(url, settings)
    except ValueError as exc:
        return f"[URL отклонён: {exc}]", str(exc)

    headers = {"User-Agent": "AI-Brainstorm/1.0 (+context-import)"}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=settings.url_fetch_timeout_s,
            headers=headers,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content[: settings.url_fetch_max_bytes]
            charset = response.encoding or "utf-8"
            html = content.decode(charset, errors="replace")
    except httpx.HTTPError as exc:
        logger.warning("URL fetch failed %s: %s", url, exc)
        return f"[Не удалось загрузить URL: {exc}]", str(exc)

    text = _extract_html_text(html)
    if len(text) > settings.max_context_chars:
        text = text[: settings.max_context_chars] + "\n\n[Текст страницы обрезан.]"
    return text, None
