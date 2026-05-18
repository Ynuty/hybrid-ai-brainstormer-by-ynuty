"""Lightweight local RAG for reducing large uploaded context before LLM calls."""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.context_utils import truncate_for_prompt

logger = logging.getLogger(__name__)


def relevant_context_for_prompt(
    *,
    query: str,
    context: str | None,
    settings: Settings | None = None,
) -> str | None:
    """Return the most relevant context chunks for a query.

    Uses FAISS + sentence-transformers when backend dependencies are installed.
    Falls back to the existing safe truncation if anything is unavailable.
    """

    settings = settings or get_settings()
    if not context or not context.strip():
        return context

    context = context.strip()
    if not settings.enable_context_rag or len(context) < settings.rag_min_context_chars:
        return truncate_for_prompt(context, settings.max_context_chars)

    try:
        chunks = _split_context(context, settings)
        if len(chunks) <= settings.rag_top_k:
            return truncate_for_prompt(context, settings.max_context_chars)
        selected = _select_with_faiss(query, chunks, settings)
    except Exception as exc:
        logger.warning("RAG unavailable; using truncated context: %s", exc)
        return truncate_for_prompt(context, settings.max_context_chars)

    if not selected:
        return truncate_for_prompt(context, settings.max_context_chars)

    body = "\n\n".join(
        f"### Релевантный фрагмент {index + 1}\n{chunk}"
        for index, chunk in enumerate(selected)
    )
    rag_context = (
        "[Контекст сокращён локальным RAG: выбраны наиболее релевантные фрагменты "
        "по теме пользователя.]\n\n"
        f"{body}"
    )
    return truncate_for_prompt(rag_context, settings.max_context_chars)


def _split_context(context: str, settings: Settings) -> list[str]:
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        return _simple_split(context, settings.rag_chunk_size, settings.rag_chunk_overlap)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        separators=["\n\n## ", "\n\n", "\n", ". ", " ", ""],
    )
    return [chunk.strip() for chunk in splitter.split_text(context) if chunk.strip()]


def _simple_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


@lru_cache(maxsize=2)
def _embedding_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def _select_with_faiss(query: str, chunks: list[str], settings: Settings) -> list[str]:
    import faiss
    import numpy as np

    model = _embedding_model(settings.rag_embedding_model)
    corpus_embeddings = model.encode(
        chunks,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    query_embedding = model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    corpus_embeddings = np.asarray(corpus_embeddings, dtype="float32")
    query_embedding = np.asarray(query_embedding, dtype="float32")

    index = faiss.IndexFlatIP(corpus_embeddings.shape[1])
    index.add(corpus_embeddings)
    top_k = min(settings.rag_top_k, len(chunks))
    _scores, indices = index.search(query_embedding, top_k)
    selected_indices = sorted(int(item) for item in indices[0] if item >= 0)
    return [chunks[index] for index in selected_indices]
