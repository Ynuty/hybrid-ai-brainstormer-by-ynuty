from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "agents" in data
        assert data["agents_from_yaml"] == 3
        assert "pdf" in data.get("supported_context_types", [])
        assert "url_import" in data.get("context_features", {})
