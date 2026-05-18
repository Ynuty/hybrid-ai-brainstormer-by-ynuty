"""Backward-compatible re-export."""

from app.sources.file_extract import extract_text_from_bytes, is_supported_filename

__all__ = ["extract_text_from_bytes", "is_supported_filename"]
