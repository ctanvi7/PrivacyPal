"""Loopback-only API for document input and local Gemma analysis."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.config import get_settings
from app.extraction.document_service import ExtractionError, ExtractedDocument, extract_pasted_text, extract_upload
from app.model.ollama_adapter import ModelError, OllamaAnalyzer

settings = get_settings()
MAX_QUESTION_CHARS = 2_000
app = FastAPI(title="PrivacyPal API", version="0.1.0", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@dataclass
class Session:
    document_id: str | None = None
    document: ExtractedDocument | None = None
    touched_at: float = 0.0


class PastedText(BaseModel):
    pasted_text: str = Field(min_length=1, max_length=settings.pdf_max_chars)


class Question(BaseModel):
    document_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class SessionStore:
    """Temporary process-local content. No source text is written to disk or logs."""

    def __init__(self) -> None:
        self.items: dict[str, Session] = {}
        self.idle_seconds = 30 * 60
        self.max_sessions = 20

    def _expire_idle(self) -> None:
        now = time.monotonic()
        for key in [key for key, value in self.items.items() if now - value.touched_at > self.idle_seconds]:
            del self.items[key]

    def create(self) -> str:
        self._expire_idle()
        if len(self.items) >= self.max_sessions:
            raise HTTPException(status_code=429, detail="Too many active local sessions. Clear one and try again.")
        session_id = str(uuid4())
        self.items[session_id] = Session(touched_at=time.monotonic())
        return session_id

    def get(self, session_id: str) -> Session:
        self._expire_idle()
        if session_id not in self.items:
            raise HTTPException(status_code=404, detail="Session expired. Start a new session.")
        self.items[session_id].touched_at = time.monotonic()
        return self.items[session_id]


sessions = SessionStore()


@app.middleware("http")
async def local_browser_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("origin") != settings.frontend_origin:
        return JSONResponse(status_code=403, content={"error": {"code": "LOCAL_ORIGIN_REQUIRED", "message": "Request must come from the local PrivacyPal interface.", "retryable": False}})
    host = urlparse(f"//{request.headers.get('host', '')}").hostname
    if host and host.lower() not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse(status_code=403, content={"error": {"code": "LOCAL_HOST_REQUIRED", "message": "PrivacyPal accepts local connections only.", "retryable": False}})
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code = {404: "SESSION_EXPIRED", 409: "INVALID_STATE", 422: "INVALID_INPUT", 429: "TOO_MANY_SESSIONS", 503: "LOCAL_ANALYSIS_FAILED"}.get(exc.status_code, "REQUEST_FAILED")
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": str(exc.detail), "retryable": False}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "INVALID_INPUT", "message": "Check the supplied text and try again.", "retryable": False}})


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/sessions", status_code=201)
async def create_session() -> dict[str, object]:
    return {"session_id": sessions.create(), "expires_in_seconds": 1_800}


@app.post("/api/v1/sessions/{session_id}/documents", status_code=201)
async def attach_document(session_id: str, request: Request) -> dict[str, object]:
    session = sessions.get(session_id)
    try:
        content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
        if content_type == "application/json":
            payload = PastedText.model_validate(await request.json())
            document = extract_pasted_text(payload.pasted_text)
        else:
            form = await request.form(max_files=1, max_fields=1, max_part_size=settings.pdf_max_bytes)
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise ExtractionError("Paste text or choose a PDF, PNG, JPEG, or WebP file.")
            raw = await file.read(settings.pdf_max_bytes + 1)
            document = extract_upload(raw, file.content_type or "application/octet-stream", file.filename or "", settings=settings)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The document could not be processed.") from exc
    session.document_id = str(uuid4())
    session.document = document
    return {"document_id": session.document_id, "source_type": document.source_type, "page_count": len(document.pages), "character_count": len(document.text), "status": "ready"}


@app.post("/api/v1/sessions/{session_id}/questions", status_code=200)
async def ask_question(session_id: str, payload: Question) -> dict[str, object]:
    session = sessions.get(session_id)
    if session.document is None or payload.document_id != session.document_id:
        raise HTTPException(status_code=409, detail="Add a document before asking a question.")
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Enter a question about the document.")
    try:
        result = await OllamaAnalyzer(settings.ollama_base_url, settings.gemma_model, settings.model_timeout_seconds).analyze(
            question, [{"page": page.page, "text": page.text} for page in session.document.pages]
        )
    except (ValueError, ModelError) as exc:
        raise HTTPException(status_code=503, detail="Local Gemma is unavailable or failed its native tool-call check.") from exc
    return {"answer": result.answer, "pages_used": list(result.pages_used), "analysis_location": "Local Gemma via Ollama"}


@app.delete("/api/v1/sessions/{session_id}/documents/{document_id}")
async def remove_document(session_id: str, document_id: str) -> dict[str, str]:
    session = sessions.get(session_id)
    if session.document_id != document_id:
        raise HTTPException(status_code=409, detail="This document is no longer attached to the session.")
    session.document = None
    session.document_id = None
    return {"status": "removed"}


@app.post("/api/v1/sessions/{session_id}/clear")
async def clear_session(session_id: str) -> dict[str, str]:
    sessions.get(session_id)
    del sessions.items[session_id]
    return {"status": "cleared"}
