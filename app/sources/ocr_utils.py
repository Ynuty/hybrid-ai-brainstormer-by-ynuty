"""Shared OCR helpers for PDF pages and images."""

from __future__ import annotations

import io
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def configure_tesseract() -> None:
    try:
        import pytesseract
    except ImportError:
        return
    settings = get_settings()
    if settings.tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_path


def ocr_pil_image(image) -> str:
    try:
        import pytesseract
    except ImportError:
        return "[OCR недоступен: установите pillow и pytesseract.]"

    configure_tesseract()
    try:
        return pytesseract.image_to_string(image, lang="rus+eng").strip()
    except Exception:
        try:
            return pytesseract.image_to_string(image, lang="eng").strip()
        except Exception as exc:
            logger.exception("OCR failed: %s", exc)
            return f"[OCR не удалось: {exc}]"


def ocr_image_bytes(raw: bytes) -> str:
    try:
        from PIL import Image
    except ImportError:
        return "[Изображение не прочитано: установите pillow.]"

    try:
        image = Image.open(io.BytesIO(raw))
    except Exception as exc:
        return f"[Изображение не открыто: {exc}]"

    text = ocr_pil_image(image)
    return text or "_текст на изображении не найден_"
