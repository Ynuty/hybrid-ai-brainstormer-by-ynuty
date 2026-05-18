from app.sources.import_service import build_combined_text, normalize_import_request


def test_normalize_import_request():
    urls, youtube = normalize_import_request(
        ["https://a.com\nhttps://b.com"],
        ["https://youtu.be/abcdefghijk"],
    )
    assert urls == ["https://a.com", "https://b.com"]
    assert youtube == ["https://youtu.be/abcdefghijk"]


def test_build_combined_text_truncates():
    sources = [{"kind": "url", "ref": "https://x.com", "text": "x" * 100, "warning": None}]
    combined = build_combined_text(sources, max_chars=50)
    assert len(combined) <= 50 + len("\n\n[Контекст обрезан.]")
    assert "обрезан" in combined
