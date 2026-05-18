def truncate_for_prompt(text: str | None, max_chars: int) -> str | None:
    if not text or not text.strip():
        return text
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return (
        f"{stripped[:max_chars]}\n\n"
        f"[Контекст обрезан до {max_chars} символов для безопасной отправки в модель.]"
    )
