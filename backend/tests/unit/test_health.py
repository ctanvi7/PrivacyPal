from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_documentation_pages_and_openapi_routes_load() -> None:
    client = TestClient(app)

    docs_response = client.get("/docs")
    redoc_response = client.get("/redoc")
    openapi_response = client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert "swagger-ui" in docs_response.text
    assert redoc_response.status_code == 200
    assert "redoc" in redoc_response.text.lower()
    assert openapi_response.status_code == 200
    paths = openapi_response.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/sessions" in paths
    assert "/api/v1/sessions/{session_id}/documents" in paths
