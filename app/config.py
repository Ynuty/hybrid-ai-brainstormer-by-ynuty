from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env.main"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    cors_allow_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    agents_config_path: str = "agents_config.yaml"
    brainstorm_model: str = "openrouter/openai/gpt-5.1"
    synthesis_model: str = ""

    model_timeout_s: float = 120.0
    model_retry_attempts: int = 2
    model_retry_backoff_s: float = 1.5
    llm_max_concurrent: int = 3

    max_topic_chars: int = 2000
    max_context_chars: int = 80000
    max_comments_chars: int = 10000
    max_upload_mb: int = 25
    max_audio_upload_mb: int = 50

    api_secret: str = ""
    rate_limit_per_minute: int = 30

    enable_url_import: bool = True
    enable_youtube_import: bool = True
    enable_audio_transcribe: bool = True
    url_fetch_timeout_s: float = 15.0
    url_fetch_max_bytes: int = 5_000_000
    url_fetch_allowed_hosts: str = ""
    youtube_use_ytdlp: bool = False
    audio_transcribe_mode: str = "cloud"
    whisper_model: str = "whisper-1"
    whisper_local_model: str = "base"

    enable_context_rag: bool = True
    rag_min_context_chars: int = 12_000
    rag_chunk_size: int = 1_200
    rag_chunk_overlap: int = 150
    rag_top_k: int = 8
    rag_embedding_model: str = "openrouter/openai/text-embedding-3-small"
    rag_embedding_batch_size: int = 32

    tesseract_path: str = ""
    pdf_ocr_dpi: int = 200

    job_ttl_hours: int = 24
    debate_job_max_seconds: int = 1800

    port: int = 8000

    @property
    def config_path(self) -> Path:
        path = Path(self.agents_config_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def synthesis_model_resolved(self) -> str:
        return self.synthesis_model.strip() or self.brainstorm_model

    @property
    def cors_origins(self) -> list[str]:
        origins = [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]
        return origins or ["http://localhost:8501", "http://127.0.0.1:8501"]

    @property
    def api_auth_enabled(self) -> bool:
        return bool(self.api_secret.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
