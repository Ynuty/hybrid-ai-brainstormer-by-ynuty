"""Backward-compatible re-export. Prefer app.file_extract."""

from app.file_extract import extract_text_from_bytes, is_supported_filename

__all__ = ["extract_text_from_bytes", "is_supported_filename"]
