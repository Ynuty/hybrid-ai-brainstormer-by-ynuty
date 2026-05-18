from app.config import Settings
from app.rag import _simple_split, relevant_context_for_prompt


def test_rag_returns_small_context_without_vector_search():
    settings = Settings(enable_context_rag=True, rag_min_context_chars=1000, max_context_chars=5000)
    context = "small context about pricing"
    assert relevant_context_for_prompt(query="pricing", context=context, settings=settings) == context


def test_rag_can_be_disabled():
    settings = Settings(enable_context_rag=False, max_context_chars=20)
    context = "x" * 100
    result = relevant_context_for_prompt(query="anything", context=context, settings=settings)
    assert result is not None
    assert "обрезан" in result


def test_simple_split_uses_overlap():
    chunks = list(_simple_split("abcdefghij", chunk_size=4, overlap=2))
    assert chunks[:3] == ["abcd", "cdef", "efgh"]


def test_rag_module_does_not_import_local_ml():
    import app.rag as rag

    source_names = set(rag.__dict__)
    assert "SentenceTransformer" not in source_names
