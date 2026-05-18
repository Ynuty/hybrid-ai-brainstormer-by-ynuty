"""Entry point for uvicorn (Procfile: uvicorn main:app)."""

import logging

import uvicorn

from app.config import get_settings
from app.main import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port)
