import base64
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cloud_gateway import ACCESS_COOKIE, GatewayConfig, MAX_REQUEST_BYTES, create_app
import app.main as main

PASSWORD = "synthetic-password-" + "x" * 32
TOKEN = "synthetic-proxy-" + "y" * 32
ORIGIN = "https://demo.example.test"
AUTH = "Basic " + base64.b64encode(f"demo:{PASSWORD}".encode()).decode()


@pytest.fixture
def config(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Private AWS workspace</h1>")
    return GatewayConfig("http://10.20.1.10:8000", ORIGIN, "demo", PASSWORD, TOKEN, tmp_path)


def test_gateway_requires_login_and_actual_https_origin(config):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})
    with TestClient(create_app(config, transport=httpx.MockTransport(handler))) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"
        assert 'name="password"' in client.get("/login").text
        assert client.get("/login").headers["referrer-policy"] == "same-origin"
        assert client.get("/", headers={"Authorization": "Basic invalid"}, follow_redirects=False).status_code == 303
        assert client.get("/api/v1/sessions/synthetic").status_code == 401
        assert client.get("/", headers={"Authorization": AUTH}).status_code == 200
        assert client.post("/api/v1/sessions", headers={"Authorization": AUTH}).status_code == 403
        assert client.post("/api/v1/sessions", headers={"Authorization": AUTH, "Origin": "https://evil.example.test"}).status_code == 403
    assert not requests


def test_form_login_protects_browser_api_and_keeps_access_cookie_at_gateway(config, monkeypatch):
    import app.cloud_gateway as gateway
    clock = [1000000]
    monkeypatch.setattr(gateway.time, "time", lambda: clock[0])
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})
    with TestClient(create_app(config, transport=httpx.MockTransport(handler)), base_url=ORIGIN) as client:
        assert client.post("/login", data={"username": "demo", "password": PASSWORD}).status_code == 403
        for origin in ("null", "https://evil.example.test"):
            assert client.post("/login", data={"username": "demo", "password": PASSWORD}, headers={"Origin": origin}).status_code == 403
        invalid = client.post("/login", data={"username": "demo", "password": "wrong"}, headers={"Origin": ORIGIN})
        assert invalid.status_code == 401 and "incorrect" in invalid.text
        assert invalid.headers["referrer-policy"] == "same-origin"
        assert ACCESS_COOKIE not in client.cookies
        created = client.post("/login", data={"username": "demo", "password": PASSWORD}, headers={"Origin": ORIGIN}, follow_redirects=False)
        assert created.status_code == 303 and created.headers["location"] == "/"
        cookie = created.headers["set-cookie"].lower()
        assert all(flag in cookie for flag in ("secure", "httponly", "samesite=strict", "path=/"))
        assert PASSWORD not in created.headers["set-cookie"]
        assert client.get("/").status_code == 200
        assert client.post("/api/v1/sessions", headers={"Origin": ORIGIN}).status_code == 200
        assert "cookie" not in requests[-1].headers
        clock[0] += gateway.ACCESS_SECONDS + 1
        assert client.post("/api/v1/sessions", headers={"Origin": ORIGIN, "Cookie": created.headers["set-cookie"].split(";", 1)[0]}).status_code == 401
        client.cookies.clear()
        client.cookies.set(ACCESS_COOKIE, "9999999.forged", domain="demo.example.test", path="/")
        assert client.get("/api/v1/sessions/synthetic").status_code == 401


def test_login_rejects_malformed_or_oversized_credentials_without_echo(config):
    with TestClient(create_app(config), base_url=ORIGIN) as client:
        for body, status in [("username=demo&password=a&password=b", 400), ("username=demo", 400), ("x" * 4097, 413)]:
            response = client.post("/login", content=body, headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"})
            assert response.status_code == status
            assert ACCESS_COOKIE not in client.cookies


def test_proxy_preserves_exact_body_and_cookies_without_forwarding_login(config):
    requests = []
    body = b'{"version":1,"draft":"Approved synthetic text [EMAIL_1]"}'
    def handler(request):
        requests.append(request)
        return httpx.Response(201, content=b'{"session_id":"synthetic"}', headers={
            "Content-Type": "application/json", "Set-Cookie": "privacypal_session=synthetic; HttpOnly; Secure; SameSite=strict; Path=/api/v1/sessions",
        })
    with TestClient(create_app(config, transport=httpx.MockTransport(handler)), base_url=ORIGIN) as client:
        response = client.post("/api/v1/sessions", content=body, headers={
            "Authorization": AUTH, "Origin": ORIGIN, "Content-Type": "application/json",
            "Cookie": "privacypal_session=existing", "X-PrivacyPal-Proxy-Token": "forged",
        })
    assert response.status_code == 201
    request = requests[0]
    assert str(request.url) == "http://10.20.1.10:8000/api/v1/sessions"
    assert request.content == body
    assert request.headers["cookie"] == "privacypal_session=existing"
    assert request.headers["origin"] == "http://127.0.0.1:5173"
    assert request.headers["x-privacypal-proxy-token"] == TOKEN
    assert "authorization" not in request.headers
    assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert TOKEN not in response.text and PASSWORD not in response.text


def test_gateway_rejects_oversized_body_before_forwarding(config):
    def handler(_request):
        raise AssertionError("Oversized upload reached backend")
    with TestClient(create_app(config, transport=httpx.MockTransport(handler))) as client:
        response = client.post("/api/v1/sessions", content=b"x" * (MAX_REQUEST_BYTES + 1),
            headers={"Authorization": AUTH, "Origin": ORIGIN})
    assert response.status_code == 413


def test_gateway_does_not_retry_an_ambiguous_upstream_send(config):
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_ERROR", request=request)
    with TestClient(create_app(config, transport=httpx.MockTransport(handler))) as client:
        response = client.post("/api/v1/sessions/synthetic/workflows/synthetic/approve", content=b'{"version":1}',
            headers={"Authorization": AUTH, "Origin": ORIGIN})
    assert response.status_code == 502
    assert response.json()["error"]["retryable"] is False
    assert len(requests) == 1
    assert "SYNTHETIC_PRIVATE_ERROR" not in response.text


@pytest.mark.parametrize("backend", ["http://127.0.0.1:8000", "http://8.8.8.8:8000", "https://10.20.1.10:8000", "http://10.20.1.10:80", "http://user:secret@10.20.1.10:8000"])
def test_gateway_rejects_unexpected_backend_destinations(config, backend):
    with pytest.raises(ValueError):
        replace(config, backend_url=backend)


def test_hosted_backend_requires_proxy_token_and_sets_secure_session_cookie(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, deployment_mode="aws", proxy_token=TOKEN))
    with TestClient(main.app, base_url="https://testserver") as client:
        assert client.post("/api/v1/sessions", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 403
        created = client.post("/api/v1/sessions", headers={"Origin": "http://127.0.0.1:5173", "X-PrivacyPal-Proxy-Token": TOKEN})
        assert created.status_code == 201
        assert "Secure" in created.headers["set-cookie"]
        sid = created.json()["session_id"]
        cleared = client.post(f"/api/v1/sessions/{sid}/clear", headers={"Origin": "http://127.0.0.1:5173", "X-PrivacyPal-Proxy-Token": TOKEN})
        assert cleared.status_code == 200
