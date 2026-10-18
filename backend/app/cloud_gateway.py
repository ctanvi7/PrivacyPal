"""Password-protected Lambda UI and proxy to one private AWS backend.

The backend and Gemma share one long-running EC2 instance. Session state is
never kept in Lambda, and no original document is stored in an artifact bucket.
"""

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
from html import escape
import ipaddress
import os
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
import httpx

MAX_REQUEST_BYTES = 4 * 1024 * 1024 + 64 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
ACCESS_COOKIE = "__Host-privacypal_access"
ACCESS_SECONDS = 8 * 60 * 60
LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in | PrivacyPal</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#07080b;color:#eeedf3;font:16px/1.6 system-ui,sans-serif}
main{width:100%;max-width:430px;padding:32px;background:#19181f;border:1px solid #3b3745;border-radius:24px}
h1{font-size:28px;margin:0 0 8px}p{color:#bdb6c9;margin:0 0 24px}label{display:block;margin-top:18px;font-weight:600}
input{display:block;width:100%;margin-top:7px;padding:12px;border:1px solid #61556f;border-radius:10px;background:#0f0e14;color:#fff;font:inherit}
button{width:100%;margin-top:26px;padding:12px;border:0;border-radius:12px;background:#8529d9;color:white;font:600 16px system-ui;cursor:pointer}
input:focus-visible,button:focus-visible{outline:3px solid #c58bff;outline-offset:3px}.error{color:#ffb6bf;margin:16px 0 0}.privacy{margin:24px 0 0;font-size:14px}
</style></head><body><main><h1>Sign in to PrivacyPal</h1>
<p>Use the credentials provided for this private workspace.</p><!--ERROR-->
<form method="post" action="/login"><label for="username">Username</label>
<input id="username" name="username" autocomplete="username" required maxlength="256">
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="1024">
<button type="submit">Sign in</button></form><p class="privacy">Documents you upload are processed in AWS. You review what may be sent to the answer provider.</p>
</main></body></html>"""


@dataclass(frozen=True)
class GatewayConfig:
    backend_url: str
    public_origin: str
    username: str
    password: str = field(repr=False)
    proxy_token: str = field(repr=False)
    static_dir: Path = Path("static")

    def __post_init__(self):
        backend = urlparse(self.backend_url)
        try:
            address = ipaddress.ip_address(backend.hostname or "")
        except ValueError as exc:
            raise ValueError("Backend must use a private IPv4 address") from exc
        networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        if (backend.scheme != "http" or backend.port != 8000
                or not any(address in ipaddress.ip_network(network) for network in networks)
                or backend.username or backend.password or backend.path not in {"", "/"}
                or backend.query or backend.fragment):
            raise ValueError("Backend must use its private network on port 8000")
        origin = urlparse(self.public_origin)
        if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
                or origin.path not in {"", "/"} or origin.query or origin.fragment):
            raise ValueError("Gateway requires an exact public HTTPS origin")
        if not self.username or len(self.password) < 32 or len(self.proxy_token) < 32:
            raise ValueError("Gateway credentials and private proxy token are required")


def _authorized(header: str, config: GatewayConfig) -> bool:
    try:
        scheme, encoded = header.split(" ", 1)
        if scheme.casefold() != "basic":
            return False
        username, password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
        return _credentials_match(username, password, config)
    except (ValueError, UnicodeError):
        return False


def _credentials_match(username: str, password: str, config: GatewayConfig) -> bool:
    def digest(value):
        return hashlib.sha256(value.encode("utf-8")).digest()
    return (hmac.compare_digest(digest(username), digest(config.username))
        & hmac.compare_digest(digest(password), digest(config.password)))


def _access_token(expires: int, config: GatewayConfig) -> str:
    message = f"login:{config.public_origin}:{config.username}:{config.password}:{expires}".encode()
    signature = hmac.new(config.proxy_token.encode(), message, hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def _cookie_authorized(value: str, config: GatewayConfig) -> bool:
    try:
        if len(value) > 100:
            return False
        expires = int(value.split(".", 1)[0])
        now = int(time.time())
        return now < expires <= now + ACCESS_SECONDS and hmac.compare_digest(value, _access_token(expires, config))
    except (ValueError, TypeError):
        return False


def create_app(config: GatewayConfig | None = None, *, transport=None) -> FastAPI:
    if config is None:
        config = GatewayConfig(
            backend_url=os.environ["PRIVACYPAL_BACKEND_URL"],
            public_origin=os.environ["PUBLIC_ORIGIN"].rstrip("/"),
            username=os.environ["PRIVACYPAL_DEMO_USERNAME"],
            password=os.environ["PRIVACYPAL_DEMO_PASSWORD"],
            proxy_token=os.environ["PRIVACYPAL_PROXY_TOKEN"],
            static_dir=Path(os.environ.get("PRIVACYPAL_STATIC_DIR", "/var/task/static")),
        )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def access_guard(request: Request, call_next):
        if request.url.path == "/health" and request.method == "GET":
            return await call_next(request)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") != config.public_origin.rstrip("/"):
                return JSONResponse({"error": {"code": "ORIGIN_REQUIRED", "message": "Use the protected PrivacyPal interface."}}, status_code=403)
        is_login = request.url.path == "/login" and request.method in {"GET", "POST"}
        if not is_login and not (_authorized(request.headers.get("authorization", ""), config)
                or _cookie_authorized(request.cookies.get(ACCESS_COOKIE, ""), config)):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"error": {"code": "LOGIN_REQUIRED", "message": "Sign in to PrivacyPal to continue.", "retryable": False}}, status_code=401,
                    headers={"Cache-Control": "no-store"})
            return RedirectResponse("/login", status_code=303, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # A no-referrer policy makes native form POSTs send Origin: null.
        # Preserve same-origin login submissions without disclosing referrers
        # to other sites; API requests still require the exact trusted Origin.
        response.headers["Referrer-Policy"] = "same-origin" if is_login else "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/login")
    async def login_page():
        return _login_response()

    @app.post("/login")
    async def login(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/x-www-form-urlencoded":
            return _login_response("Use the sign-in form to continue.", 415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                return _login_response("Sign-in details are too long.", 413)
        try:
            fields = parse_qs(body.decode("utf-8"), max_num_fields=2, strict_parsing=True)
            username, = fields.get("username", [])
            password, = fields.get("password", [])
        except (ValueError, UnicodeError):
            return _login_response("Enter a username and password.", 400)
        if not _credentials_match(username, password, config):
            return _login_response("The username or password is incorrect.", 401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(ACCESS_COOKIE, _access_token(int(time.time()) + ACCESS_SECONDS, config),
            max_age=ACCESS_SECONDS, secure=True, httponly=True, samesite="strict", path="/")
        return response

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"])
    async def proxy(request: Request, path: str):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES:
                return JSONResponse({"error": {"code": "FILE_TOO_LARGE", "message": "AWS demo uploads are limited to 4 MiB."}}, status_code=413)
        url = httpx.URL(config.backend_url).copy_with(path=request.url.path, query=request.url.query.encode() or None)
        headers = {name: request.headers[name] for name in ("content-type", "accept") if name in request.headers}
        # The access cookie terminates at the gateway; only workflow ownership
        # reaches the processing backend.
        if "privacypal_session" in request.cookies:
            headers["cookie"] = f"privacypal_session={request.cookies['privacypal_session']}"
        headers.update({"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:5173",
            "x-privacypal-proxy-token": config.proxy_token})
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(390), follow_redirects=False, transport=transport) as client:
                async with client.stream(request.method, url, headers=headers, content=bytes(body)) as upstream:
                    content = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE_BYTES:
                            raise ValueError("Backend response exceeded the limit")
                    response = Response(bytes(content), status_code=upstream.status_code,
                        headers={"content-type": upstream.headers.get("content-type", "application/json")})
                    response.raw_headers.extend((b"set-cookie", value.encode("latin-1"))
                        for value in upstream.headers.get_list("set-cookie"))
                    return response
        except Exception:
            return JSONResponse({"error": {"code": "BACKEND_UNAVAILABLE",
                "message": "The AWS processing service is starting or unavailable. A send may have occurred; do not retry an approval.",
                "retryable": False}}, status_code=502)

    app.mount("/", StaticFiles(directory=str(config.static_dir), html=True), name="ui")
    return app


def _login_response(error: str = "", status: int = 200) -> HTMLResponse:
    note = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    return HTMLResponse(LOGIN_HTML.replace("<!--ERROR-->", note), status_code=status, headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        "Cache-Control": "no-store",
    })
