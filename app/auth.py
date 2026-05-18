from fastapi import Header, HTTPException

from app.config import get_settings


async def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    if not settings.api_auth_enabled:
        return

    token = (x_api_key or "").strip()
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if token != settings.api_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
