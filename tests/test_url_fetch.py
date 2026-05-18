import pytest

from app.config import Settings
from app.sources.url_fetch import parse_url_lines, validate_url


def test_parse_url_lines():
    text = "https://example.com\n\n# comment\nhttps://other.org/page"
    assert parse_url_lines(text) == ["https://example.com", "https://other.org/page"]


def test_validate_url_blocks_localhost():
    settings = Settings(enable_url_import=True, url_fetch_allowed_hosts="")
    with pytest.raises(ValueError, match="SSRF"):
        validate_url("http://localhost/secret", settings)


def test_validate_url_blocks_private_ip():
    settings = Settings(enable_url_import=True, url_fetch_allowed_hosts="")
    with pytest.raises(ValueError, match="SSRF"):
        validate_url("http://127.0.0.1/admin", settings)


def test_validate_url_allowlist():
    settings = Settings(
        enable_url_import=True,
        url_fetch_allowed_hosts="example.com",
    )
    validate_url("https://example.com/page", settings)
    with pytest.raises(ValueError, match="allowlist"):
        validate_url("https://other.com/page", settings)
