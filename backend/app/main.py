"""Loopback-only API for document input and local Gemma analysis."""

from __future__ import annotations

import time
from dataclasses import dataclass
import re
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.config import get_settings
from app.answer_provider import (
    AnswerProvider,
    AnswerProviderError,
    AnswerProviderNotConfigured,
    require_provider_configuration,
)
from app.extraction.document_service import (
    ExtractedDocument,
    ExtractionError,
    extract_pasted_text,
    extract_upload,
)
from app.model.ollama_adapter import ModelError, OllamaAnalyzer

settings = get_settings()
MAX_QUESTION_CHARS = 2_000
MAX_DRAFT_CHARS = 8_000
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
SECRET_PATTERNS = (
    re.compile(r"\b(?:password|passwd|api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}", re.IGNORECASE),
)
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
    requests: dict[str, "ReviewRequest"] | None = None

    def __post_init__(self) -> None:
        if self.requests is None:
            self.requests = {}


@dataclass
class ReviewRequest:
    proposed_request: str
    findings: list[dict[str, str]]
    risk_flags: list[dict[str, str]]
    privacy_check: str
    draft_version: int = 1
    status: str = "awaiting_review"
    answer: str | None = None
    approved_text: str | None = None


class PastedText(BaseModel):
    pasted_text: str = Field(min_length=1, max_length=settings.pdf_max_chars)


class Question(BaseModel):
    document_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class EditRequest(BaseModel):
    expected_draft_version: int = Field(ge=1)
    proposed_request: str = Field(min_length=1, max_length=MAX_DRAFT_CHARS)


class Approval(BaseModel):
    draft_version: int = Field(ge=1)
    approved: bool


class SessionStore:
    """Temporary process-local content. No source text is written to disk or logs."""

    def __init__(self) -> None:
        self.items: dict[str, Session] = {}
        self.idle_seconds = 30 * 60
        self.max_sessions = 20

    def _expire_idle(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, value in self.items.items()
            if now - value.touched_at > self.idle_seconds
        ]
        for key in expired:
            del self.items[key]

    def create(self) -> str:
        self._expire_idle()
        if len(self.items) >= self.max_sessions:
            raise HTTPException(
                status_code=429,
                detail="Too many active local sessions. Clear one and try again.",
            )
        session_id = str(uuid4())
        self.items[session_id] = Session(touched_at=time.monotonic())
        return session_id

    def get(self, session_id: str) -> Session:
        self._expire_idle()
        if session_id not in self.items:
            raise HTTPException(status_code=404, detail="Session expired. Start a new session.")
        session = self.items[session_id]
        session.touched_at = time.monotonic()
        return session


sessions = SessionStore()
app.state.answer_provider = None


@app.middleware("http")
async def local_browser_origin(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get(
        "origin"
    ) != settings.frontend_origin:
        return _error(
            403,
            "LOCAL_ORIGIN_REQUIRED",
            "Request must come from the local PrivacyPal interface.",
        )
    host = urlparse(f"//{request.headers.get('host', '')}").hostname
    if host and host.lower() not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return _error(403, "LOCAL_HOST_REQUIRED", "PrivacyPal accepts local connections only.")
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code = {
        404: "UNKNOWN_SESSION",
        409: "INVALID_STATE",
        422: "INVALID_INPUT",
        429: "TOO_MANY_SESSIONS",
        503: "LOCAL_ANALYSIS_FAILED",
    }.get(exc.status_code, "REQUEST_FAILED")
    message = str(exc.detail) if exc.status_code < 500 else "The request could not be completed."
    return _error(exc.status_code, code, message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, _exc: RequestValidationError
) -> JSONResponse:
    return _error(422, "INVALID_INPUT", "Check the supplied input and try again.")


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _map_extraction_error(error: ExtractionError) -> JSONResponse:
    """Map extraction failures to safe API errors without exposing parser details."""

    message = str(error).casefold()
    if "upload limit" in message:
        return _error(413, "FILE_TOO_LARGE", "The upload exceeds the 10 MiB size limit.")
    if "time limit" in message or "timeout" in message:
        return _error(504, "PDF_EXTRACTION_TIMEOUT", "PDF extraction exceeded the 15-second time limit.")
    if "password-protected" in message or "encrypted" in message:
        return _error(422, "ENCRYPTED_PDF", "Encrypted or password-protected PDFs are not supported.")
    if "page limit" in message:
        return _error(422, "TOO_MANY_PAGES", "The PDF exceeds the 25-page limit.")
    if "character limit" in message:
        return _error(422, "TEXT_TOO_LONG", "Extracted text exceeds the 25,000-character limit.")
    if "no readable text" in message or "no extractable text" in message:
        return _error(422, "NO_EXTRACTABLE_TEXT", "No extractable text was found in the document.")
    if "empty" in message:
        return _error(422, "EMPTY_PDF", "The uploaded document is empty.")
    if "type" in message or "choose a pdf" in message or "supported image" in message:
        return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload a supported document file.")
    return _error(422, "INVALID_PDF", "The document is malformed or unreadable.")


def _review_outbound_text(text: str) -> tuple[str, list[dict[str, str]], bool]:
    """Mask common identifiers and fail closed on obvious high-risk credentials."""

    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        return text, [], False

    findings: list[dict[str, str]] = []
    sanitized = EMAIL_PATTERN.sub(lambda match: _record_mask(findings, "email", match.group()), text)
    sanitized = PHONE_PATTERN.sub(lambda match: _record_mask(findings, "phone", match.group()), sanitized)
    return sanitized, findings, True


def _record_mask(findings: list[dict[str, str]], kind: str, _value: str) -> str:
    findings.append(
        {
            "category": "personal_identifier",
            "action": "masked",
            "description": f"A personal {kind} was replaced.",
        }
    )
    return f"[{kind.upper()}]"


def _find_request(session: Session, request_id: str) -> ReviewRequest:
    request = session.requests.get(request_id) if session.requests is not None else None
    if request is None:
        raise HTTPException(status_code=404, detail="Request was not found in this session.")
    return request


def _request_payload(request_id: str, draft: ReviewRequest) -> dict[str, object]:
    return {
        "request_id": request_id,
        "status": draft.status,
        "draft_version": draft.draft_version,
        "proposed_request": draft.proposed_request,
        "findings": draft.findings,
        "risk_flags": draft.risk_flags,
        "privacy_check": draft.privacy_check,
    }


def _answer_provider() -> AnswerProvider:
    provider = app.state.answer_provider
    if provider is not None:
        return provider
    require_provider_configuration(settings.answer_provider_name, settings.answer_provider_api_key)
    raise AnswerProviderNotConfigured


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/sessions", status_code=201)
async def create_session() -> dict[str, object]:
    return {"session_id": sessions.create(), "expires_in_seconds": 1_800}


@app.post("/api/v1/sessions/{session_id}/documents", status_code=201)
async def attach_document(session_id: str, request: Request) -> JSONResponse:
    session = sessions.get(session_id)
    try:
        content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
        if content_type == "application/json":
            payload = PastedText.model_validate(await request.json())
            document = extract_pasted_text(payload.pasted_text)
        elif content_type == "multipart/form-data":
            try:
                form = await request.form(
                    max_files=2,
                    max_fields=2,
                    max_part_size=settings.pdf_max_bytes,
                )
            except Exception:
                return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload exactly one document input.")
            entries = list(form.multi_items())
            if len(entries) != 1 or entries[0][0] != "file" or not isinstance(entries[0][1], UploadFile):
                for _, value in entries:
                    if isinstance(value, UploadFile):
                        await value.close()
                return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload exactly one document in the file part.")
            file = entries[0][1]
            try:
                raw = await file.read(settings.pdf_max_bytes + 1)
                if len(raw) > settings.pdf_max_bytes:
                    return _error(413, "FILE_TOO_LARGE", "The upload exceeds the 10 MiB size limit.")
                document = extract_upload(
                    raw,
                    file.content_type or "application/octet-stream",
                    file.filename or "",
                    settings=settings,
                )
            finally:
                await file.close()
        else:
            return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload a supported document file.")
    except ExtractionError as exc:
        return _map_extraction_error(exc)
    except RequestValidationError:
        return _error(422, "INVALID_INPUT", "Check the supplied input and try again.")
    except Exception:
        return _error(500, "INTERNAL_ERROR", "The document could not be processed.")

    document_id = str(uuid4())
    session.document_id = document_id
    session.document = document
    character_count = len(document.text)
    return JSONResponse(
        status_code=201,
        content={
            "document_id": document_id,
            "source_type": document.source_type,
            "page_count": len(document.pages),
            "character_count": character_count,
            "extracted_character_count": character_count,
            "status": "ready",
        },
    )


@app.post("/api/v1/sessions/{session_id}/questions", status_code=200)
async def ask_question(session_id: str, payload: Question) -> dict[str, object]:
    session = sessions.get(session_id)
    if session.document is None or payload.document_id != session.document_id:
        raise HTTPException(status_code=409, detail="Add a document before asking a question.")
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Enter a question about the document.")
    try:
        result = await OllamaAnalyzer(
            settings.ollama_base_url,
            settings.gemma_model,
            settings.model_timeout_seconds,
        ).analyze(
            question,
            [{"page": page.page, "text": page.text} for page in session.document.pages],
        )
    except (ValueError, ModelError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Local Gemma is unavailable or failed its native tool-call check.",
        ) from exc
    return {
        "answer": result.answer,
        "pages_used": list(result.pages_used),
        "analysis_location": "Local Gemma via Ollama",
    }


@app.post("/api/v1/sessions/{session_id}/requests", status_code=201)
async def create_review_request(session_id: str, payload: Question) -> JSONResponse:
    session = sessions.get(session_id)
    if session.document is None or payload.document_id != session.document_id:
        raise HTTPException(status_code=409, detail="Add a document before preparing a request.")
    try:
        analysis = await OllamaAnalyzer(
            settings.ollama_base_url,
            settings.gemma_model,
            settings.model_timeout_seconds,
        ).analyze(
            payload.question.strip(),
            [{"page": page.page, "text": page.text} for page in session.document.pages],
        )
    except (ValueError, ModelError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Local Gemma is unavailable or failed its native tool-call check.",
        ) from exc

    document_text = session.document.text.strip()
    summary = analysis.answer.strip()
    if document_text and (summary == document_text or document_text in summary):
        return _error(422, "PRIVACY_CHECK_FAILED", "The local review could not safely minimize the document text.")
    candidate = f"Answer this question: {payload.question.strip()}\nRelevant information: {summary}"
    if document_text and document_text in candidate:
        return _error(422, "PRIVACY_CHECK_FAILED", "The local review could not safely minimize the document text.")
    sanitized, findings, passed = _review_outbound_text(candidate)
    if not passed:
        return _error(422, "PRIVACY_CHECK_FAILED", "The proposed request contains a high-risk secret.")

    request_id = str(uuid4())
    draft = ReviewRequest(
        proposed_request=sanitized,
        findings=findings,
        risk_flags=[],
        privacy_check="passed",
    )
    session.requests[request_id] = draft
    return JSONResponse(status_code=201, content=_request_payload(request_id, draft))


@app.patch("/api/v1/sessions/{session_id}/requests/{request_id}")
async def edit_review_request(
    session_id: str,
    request_id: str,
    payload: EditRequest,
) -> JSONResponse:
    session = sessions.get(session_id)
    draft = _find_request(session, request_id)
    if draft.status != "awaiting_review":
        raise HTTPException(status_code=409, detail="This request can no longer be edited.")
    if payload.expected_draft_version != draft.draft_version:
        raise HTTPException(status_code=409, detail="Review the latest request version before editing.")

    sanitized, findings, passed = _review_outbound_text(payload.proposed_request)
    draft.draft_version += 1
    draft.answer = None
    draft.approved_text = None
    if not passed:
        draft.status = "blocked"
        draft.privacy_check = "failed"
        draft.findings = []
        draft.proposed_request = ""
        return _error(422, "PRIVACY_CHECK_FAILED", "The edited request contains a high-risk secret.")
    draft.proposed_request = sanitized
    draft.findings = findings
    draft.risk_flags = []
    draft.privacy_check = "passed"
    return JSONResponse(status_code=200, content=_request_payload(request_id, draft))


@app.post("/api/v1/sessions/{session_id}/requests/{request_id}/cancel")
async def cancel_review_request(session_id: str, request_id: str) -> dict[str, str]:
    session = sessions.get(session_id)
    draft = _find_request(session, request_id)
    if draft.status != "awaiting_review":
        raise HTTPException(status_code=409, detail="This request can no longer be cancelled.")
    draft.status = "cancelled"
    draft.approved_text = None
    return {"request_id": request_id, "status": draft.status}


@app.post("/api/v1/sessions/{session_id}/requests/{request_id}/approve")
async def approve_review_request(
    session_id: str,
    request_id: str,
    payload: Approval,
) -> JSONResponse:
    session = sessions.get(session_id)
    draft = _find_request(session, request_id)
    if not payload.approved:
        raise HTTPException(status_code=409, detail="Explicit approval is required before sending.")
    if draft.status != "awaiting_review":
        raise HTTPException(status_code=409, detail="This request is no longer awaiting approval.")
    if payload.draft_version != draft.draft_version:
        raise HTTPException(status_code=409, detail="Review the current request version before approving.")
    if draft.privacy_check != "passed":
        raise HTTPException(status_code=409, detail="The privacy review did not pass.")

    try:
        provider = _answer_provider()
    except AnswerProviderNotConfigured:
        return _error(
            503,
            "ANSWER_PROVIDER_NOT_CONFIGURED",
            "Select an answer provider and configure its server-side credentials before approval.",
        )

    approved_text = draft.proposed_request
    draft.approved_text = approved_text
    draft.status = "sending"
    try:
        answer = await provider.answer(approved_text)
    except AnswerProviderError as exc:
        draft.status = "delivery_status_unknown" if exc.delivery_unknown else "provider_failed"
        code = "DELIVERY_STATUS_UNKNOWN" if exc.delivery_unknown else "ANSWER_PROVIDER_FAILED"
        message = (
            "The provider may have received the request, but its result is unknown. Do not retry automatically."
            if exc.delivery_unknown
            else "The answer provider could not complete the request."
        )
        return _error(502, code, message)
    except Exception:
        draft.status = "delivery_status_unknown"
        return _error(
            502,
            "DELIVERY_STATUS_UNKNOWN",
            "The provider may have received the request, but its result is unknown. Do not retry automatically.",
        )

    if not isinstance(answer, str) or not answer.strip():
        draft.status = "provider_failed"
        return _error(502, "ANSWER_PROVIDER_FAILED", "The answer provider returned an unusable response.")
    draft.answer = answer
    draft.status = "completed"
    return JSONResponse(
        status_code=200,
        content={
            "request_id": request_id,
            "status": "completed",
            "draft_version": draft.draft_version,
            "answer": answer,
        },
    )


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
