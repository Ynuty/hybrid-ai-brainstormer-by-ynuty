from fastapi.testclient import TestClient

from app.main import app


def test_context_import_requires_payload():
    with TestClient(app) as client:
        response = client.post("/context/import", json={"urls": [], "youtube_urls": []})
        assert response.status_code == 400


def test_context_import_invalid_youtube():
    with TestClient(app) as client:
        response = client.post(
            "/context/import",
            json={"urls": [], "youtube_urls": ["not-a-youtube-url"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["sources"]) == 1
        assert "Некорректная" in data["sources"][0]["text"] or data["sources"][0]["warning"]
