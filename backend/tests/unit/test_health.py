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


def test_cors_accepts_both_vite_loopback_hostnames() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/v1/sessions",
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    for origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
        response = client.options(
            f"/api/v1/sessions/{session_id}/questions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"

    rejected = client.options(
        f"/api/v1/sessions/{session_id}/questions",
        headers={
            "Origin": "http://example.com:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert rejected.status_code == 400
    # The local origin guard must apply the same narrow loopback alias policy
    # to actual writes as CORS does to their preflight requests.
    alias_session = client.post(
        "/api/v1/sessions",
        headers={"Origin": "http://localhost:5173"},
    )
    assert alias_session.status_code == 201
    external_session = client.post(
        "/api/v1/sessions",
        headers={"Origin": "http://example.com:5173"},
    )
    assert external_session.status_code == 403
