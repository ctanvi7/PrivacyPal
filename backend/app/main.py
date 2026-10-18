"""Loopback-only API for local privacy review and explicitly approved answers."""

from __future__ import annotations

import re
import hmac
import threading
import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.config import get_settings
from app.conversation_store import ConversationStore
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
from app.model.ollama_adapter import ModelBusyError, ModelError, OllamaAnalyzer
from app.privacy.grounding import AnswerGroundingError, review_outbound_identity, validate_answer_grounding
from app.privacy.pipeline import (
    Finding,
    PrivacyCheckError,
    ResidualReview,
    review_residual_risk,
    scan_sensitive_data,
)
from app.provider.answer_provider import (
    ApprovedRequest,
    OpenAICompatibleProvider,
)
from app.tools.registry import (
    ToolContext,
    ToolRegistry,
    ToolValidationError,
    privacy_workflow_complete,
)

settings = get_settings()
MAX_QUESTION_CHARS = 2_000
app = FastAPI(
    title="PrivacyPal API",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


def _local_frontend_origins(origin: str) -> list[str]:
    """Accept Vite's two standard IPv4 loopback spellings on the configured port."""
    parsed = urlparse(origin)
    hosts = {parsed.hostname}
    if parsed.hostname == "localhost":
        hosts.add("127.0.0.1")
    elif parsed.hostname == "127.0.0.1":
        hosts.add("localhost")
    return [f"{parsed.scheme}://{host}:{parsed.port}" for host in hosts]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_local_frontend_origins(settings.frontend_origin),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

SESSION_COOKIE = "privacypal_session"


@dataclass
class PrivacyWorkflow:
    workflow_id: str
    document_id: str
    question: str
    draft: str
    findings: tuple[Finding, ...]
    placeholder_map: dict[str, str] = field(repr=False)
    residual: ResidualReview | None = None
    contextual_flags: tuple[str, ...] = ()
    semantic_values: tuple[str, ...] | None = field(default=None, repr=False)
    local_checks: dict[str, str] = field(default_factory=dict)
    version: int = 1
    review_complete: bool = True
    acknowledged: bool = False
    send_state: Literal[
        "review", "sending", "sent", "delivery_unknown", "answer_withheld", "cancelled"
    ] = "review"
    answer: str | None = None
    pages_used: tuple[int, ...] = ()
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


@dataclass
class Session:
    document_id: str | None = None
    document: ExtractedDocument | None = None
    workflow: PrivacyWorkflow | None = None
    touched_at: float = 0.0
    requests: dict[str, "ReviewRequest"] | None = None
    status: Literal["active", "clearing", "expired"] = "active"
    conversation_id: str | None = None
    analysis_id: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

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


class SessionCreate(BaseModel):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=80)


class DraftUpdate(BaseModel):
    version: int = Field(ge=1)
    draft: str = Field(min_length=1, max_length=8_000)


class WorkflowVersion(BaseModel):
    version: int = Field(ge=1)


class Approval(WorkflowVersion):
    restore_placeholders: bool = False


class SessionStore:
    """Temporary process-local content and workflow state; no content is persisted."""

    def __init__(self) -> None:
        self.items: dict[str, Session] = {}
        self.idle_seconds = 30 * 60
        self.max_sessions = 20
        self.lock = threading.RLock()

    def _expire_idle(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, value in self.items.items()
            if now - value.touched_at > self.idle_seconds
        ]
        for key in expired:
            session = self.items.pop(key)
            with session.lock:
                session.status = "expired"
                _discard_sensitive_active_content(session)
                session.workflow = None
                session.analysis_id = None

    def create(self, conversation_id: str | None = None) -> str:
        with self.lock:
            self._expire_idle()
            if len(self.items) >= self.max_sessions:
                raise HTTPException(status_code=429, detail="Too many active local sessions. Clear one and try again.")
            session_id = str(uuid4())
            self.items[session_id] = Session(touched_at=time.monotonic(), conversation_id=conversation_id)
            return session_id

    def remove_conversation(self, conversation_id: str) -> int:
        with self.lock:
            matched = [key for key, session in self.items.items()
                       if session.conversation_id == conversation_id]
            for key in matched:
                self.clear(key)
            return len(matched)

    def get(self, session_id: str) -> Session:
        with self.lock:
            self._expire_idle()
            session = self.items.get(session_id)
            if session is None or session.status != "active":
                raise HTTPException(status_code=404, detail="Session expired. Start a new session.")
            session.touched_at = time.monotonic()
            return session

    def is_active(self, session_id: str, expected: Session) -> bool:
        with self.lock:
            self._expire_idle()
            return self.items.get(session_id) is expected and expected.status == "active"

    def contains_active(self, session_id: str) -> bool:
        with self.lock:
            self._expire_idle()
            return session_id in self.items and self.items[session_id].status == "active"

    def clear(self, session_id: str, expected: Session | None = None) -> None:
        with self.lock:
            session = self.items.get(session_id)
            if session is None or (expected is not None and session is not expected):
                raise HTTPException(status_code=404, detail="Session expired. Start a new session.")
            with session.lock:
                session.status = "clearing"
                _discard_sensitive_active_content(session)
                session.workflow = None
                session.analysis_id = None
                self.items.pop(session_id, None)


sessions = SessionStore()
app.state.answer_provider = None
app.state.conversation_store = None


def _conversation_store() -> ConversationStore:
    store = app.state.conversation_store
    if store is None:
        store = ConversationStore(settings.database_path)
        app.state.conversation_store = store
    return store


@app.middleware("http")
async def local_browser_origin(request: Request, call_next):
    # The AWS gateway validates the user's real HTTPS origin before forwarding.
    # Only its authenticated private connection may reach hosted API routes.
    if settings.deployment_mode == "aws" and request.url.path != "/health":
        supplied = request.headers.get("x-privacypal-proxy-token", "")
        if not hmac.compare_digest(supplied.encode(), settings.proxy_token.encode()):
            return _error(403, "PRIVATE_PROXY_REQUIRED", "Use the protected PrivacyPal interface.")
    # CORS preflights carry no session cookie, so let the CORS middleware
    # validate and answer them before enforcing request/session ownership.
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get(
        "origin"
    ) not in _local_frontend_origins(settings.frontend_origin):
        return _error(
            403,
            "LOCAL_ORIGIN_REQUIRED",
            "Request must come from the local PrivacyPal interface.",
        )
    host = urlparse(f"//{request.headers.get('host', '')}").hostname
    if host and host.lower() not in {
        "127.0.0.1",
        "localhost",
        "::1",
        "testserver",
    }:
        return _error(
            403,
            "LOCAL_HOST_REQUIRED",
            "PrivacyPal accepts local connections only.",
        )
    session_match = None if request.url.path == "/api/v1/sessions" else re.match(r"^/api/v1/sessions/([^/]+)(?:/|$)", request.url.path)
    if session_match:
        path_session_id = session_match.group(1)
        cookie_session_id = request.cookies.get(SESSION_COOKIE)
        if sessions.contains_active(path_session_id) and cookie_session_id != path_session_id:
            return _error(403, "SESSION_OWNERSHIP_REQUIRED", "This request is not authorized for the active local session.")
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code = {
        404: "UNKNOWN_SESSION",
        409: "INVALID_STATE",
        422: "INVALID_INPUT",
        429: "TOO_MANY_SESSIONS",
        502: "PROVIDER_FAILED",
        503: "LOCAL_ANALYSIS_FAILED",
    }.get(exc.status_code, "REQUEST_FAILED")
    if exc.status_code == 404:
        code = (
            "UNKNOWN_SESSION"
            if "session expired" in str(exc.detail).casefold()
            else "NOT_FOUND"
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": str(exc.detail),
                "retryable": False,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_INPUT",
                "message": "Check the supplied text and try again.",
                "retryable": False,
            }
        },
    )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _map_extraction_error(error: ExtractionError) -> JSONResponse:
    """Map extraction failures to safe API errors without exposing parser details."""

    message = str(error).casefold()
    if "upload limit" in message:
        return _error(413, "FILE_TOO_LARGE", f"The upload exceeds the {settings.pdf_max_bytes // (1024 * 1024)} MiB size limit.")
    if "time limit" in message or "timeout" in message:
        return _error(
            504,
            "PDF_EXTRACTION_TIMEOUT",
            "PDF extraction exceeded the 15-second time limit.",
        )
    if "password-protected" in message or "encrypted" in message:
        return _error(
            422,
            "ENCRYPTED_PDF",
            "Encrypted or password-protected PDFs are not supported.",
        )
    if "page limit" in message:
        return _error(422, "TOO_MANY_PAGES", "The PDF exceeds the 25-page limit.")
    if "character limit" in message:
        return _error(
            422,
            "TEXT_TOO_LONG",
            "Extracted text exceeds the 25,000-character limit.",
        )
    if "no readable text" in message or "no extractable text" in message:
        return _error(
            422,
            "NO_EXTRACTABLE_TEXT",
            "No extractable text was found in the document.",
        )
    if "empty" in message:
        return _error(422, "EMPTY_PDF", "The uploaded document is empty.")
    if (
        "type" in message
        or "choose a pdf" in message
        or "supported image" in message
    ):
        return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload a supported document file.")
    return _error(422, "INVALID_PDF", "The document is malformed or unreadable.")


def _provider_view() -> dict[str, object]:
    return {
        "name": settings.answer_provider_name,
        "endpoint": settings.answer_provider_url,
        "configured": bool(
            settings.answer_provider_url
            and settings.answer_provider_model
            and settings.answer_provider_api_key
        ),
    }


def _workflow_view(workflow: PrivacyWorkflow) -> dict[str, object]:
    residual = workflow.residual
    return {
        "workflow_id": workflow.workflow_id,
        "version": workflow.version,
        "question": workflow.question,
        "draft": workflow.draft,
        "findings": [finding.public_view() for finding in workflow.findings],
        "residual_review": (
            residual.public_view()
            if residual
            else {
                "status": "needs_review",
                "findings": [],
                "reasons": ["Privacy review has not completed."],
            }
        ),
        "review_complete": workflow.review_complete,
        "local_checks": dict(workflow.local_checks),
        "acknowledged": workflow.acknowledged,
        "send_state": workflow.send_state,
        "provider": _provider_view(),
        "pages_used": list(workflow.pages_used),
    }


def _get_workflow(
    session_id: str,
    workflow_id: str,
) -> tuple[Session, PrivacyWorkflow]:
    session = sessions.get(session_id)
    workflow = session.workflow
    if workflow is None or workflow.workflow_id != workflow_id:
        raise HTTPException(
            status_code=404,
            detail="This review is no longer active. Start a new question.",
        )
    if workflow.send_state == "review" and workflow.document_id != session.document_id:
        raise HTTPException(
            status_code=409,
            detail="The document changed. Start a new review.",
        )
    return session, workflow


def _discard_sensitive_active_content(session: Session) -> None:
    """Release document/workflow content while retaining only retry-safe status IDs."""
    session.document = None
    session.document_id = None
    if session.requests is not None:
        session.requests.clear()
    workflow = session.workflow
    if workflow is not None:
        workflow.question = ""
        workflow.draft = ""
        workflow.findings = ()
        workflow.placeholder_map.clear()
        workflow.residual = None
        workflow.contextual_flags = ()
        workflow.semantic_values = None
        workflow.local_checks.clear()
        workflow.answer = None
        workflow.pages_used = ()


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/sessions", status_code=201)
async def create_session(payload: SessionCreate | None = None) -> JSONResponse:
    store = _conversation_store()
    conversation_id = payload.conversation_id if payload else None
    try:
        if conversation_id is not None and not store.exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found or expired.")
        if conversation_id is None:
            conversation_id = store.create()["conversation_id"]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Conversation history is unavailable."
        ) from exc
    try:
        session_id = sessions.create(conversation_id)
    except HTTPException:
        if payload is None or payload.conversation_id is None:
            try:
                store.delete(conversation_id)
            except Exception:
                pass
        raise
    response = JSONResponse({
        "session_id": session_id,
        "expires_in_seconds": 1_800,
        "conversation_id": conversation_id,
    }, status_code=201)
    response.set_cookie(SESSION_COOKIE, session_id, httponly=True,
                        secure=settings.deployment_mode == "aws", samesite="strict",
                        path="/api/v1/sessions", max_age=1_800)
    return response


@app.post("/api/v1/conversations", status_code=201)
async def create_conversation() -> dict[str, str]:
    try:
        return _conversation_store().create()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Conversation history is unavailable."
        ) from exc


@app.get("/api/v1/conversations")
async def list_conversations(
    limit: int = 50, offset: int = 0
) -> dict[str, object]:
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(status_code=422, detail="Invalid history page size or offset.")
    try:
        items = _conversation_store().list(limit=limit, offset=offset)
        return {"items": items, "limit": limit, "offset": offset}
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Conversation history is unavailable."
        ) from exc


@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, object]:
    try:
        result = _conversation_store().get(conversation_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Conversation history is unavailable."
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found or expired.")
    return result


@app.delete("/api/v1/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> JSONResponse:
    # Active state is memory-only today; remove it first so no later operation can
    # use its document/workflow while the persisted conversation is being deleted.
    sessions.remove_conversation(conversation_id)
    try:
        deleted = _conversation_store().delete(conversation_id)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "CONVERSATION_CLEANUP_INCOMPLETE",
                    "message": "Active temporary data was cleared, but saved history could not be deleted.",
                    "retryable": True,
                }
            },
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found or expired.")
    return JSONResponse(status_code=200, content={"status": "deleted"})


@app.post("/api/v1/sessions/{session_id}/documents", status_code=201)
async def attach_document(session_id: str, request: Request) -> JSONResponse:
    session = sessions.get(session_id)
    try:
        content_type = (
            request.headers.get("content-type", "")
            .split(";", maxsplit=1)[0]
            .lower()
        )
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
                return _error(
                    415,
                    "UNSUPPORTED_FILE_TYPE",
                    "Upload exactly one document input.",
                )
            entries = list(form.multi_items())
            if (
                len(entries) != 1
                or entries[0][0] != "file"
                or not isinstance(entries[0][1], UploadFile)
            ):
                for _, value in entries:
                    if isinstance(value, UploadFile):
                        await value.close()
                return _error(
                    415,
                    "UNSUPPORTED_FILE_TYPE",
                    "Upload exactly one document in the file part.",
                )
            file = entries[0][1]
            try:
                raw = await file.read(settings.pdf_max_bytes + 1)
                if len(raw) > settings.pdf_max_bytes:
                    return _error(
                        413,
                        "FILE_TOO_LARGE",
                        f"The upload exceeds the {settings.pdf_max_bytes // (1024 * 1024)} MiB size limit.",
                    )
                document = extract_upload(
                    raw,
                    file.content_type or "application/octet-stream",
                    file.filename or "",
                    settings=settings,
                )
            finally:
                await file.close()
        else:
            return _error(
                415,
                "UNSUPPORTED_FILE_TYPE",
                "Upload a supported document file.",
            )
    except ExtractionError as exc:
        return _map_extraction_error(exc)
    except RequestValidationError:
        return _error(422, "INVALID_INPUT", "Check the supplied input and try again.")
    except Exception:
        return _error(500, "INTERNAL_ERROR", "The document could not be processed.")

    document_id = str(uuid4())
    with sessions.lock, session.lock:
        if sessions.items.get(session_id) is not session or session.status != "active":
            raise HTTPException(status_code=409, detail="The session was cleared while the document was processing.")
        session.document_id = document_id
        session.document = document
        session.workflow = None
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
    question = payload.question.strip()
    if not question:
        raise HTTPException(
            status_code=422,
            detail="Enter a question about the document.",
        )
    analysis_id = str(uuid4())
    with sessions.lock, session.lock:
        if sessions.items.get(session_id) is not session or session.status != "active":
            raise HTTPException(status_code=409, detail="The session was cleared. Start a new session.")
        if session.analysis_id is not None:
            raise HTTPException(status_code=409, detail="A local analysis is already running for this session. Wait for it to finish before retrying.")
        if session.document is None or payload.document_id != session.document_id:
            raise HTTPException(status_code=409, detail="Add a document before asking a question.")
        doc_id = session.document_id
        document = session.document
        session.analysis_id = analysis_id
        session.workflow = None
    context = ToolContext(
        session_id=session_id,
        workflow_id=str(uuid4()),
        question=question,
        document_pages=tuple(
            {"page": page.page, "text": page.text} for page in document.pages
        ),
    )
    try:
        try:
            analyzer = OllamaAnalyzer(
                settings.ollama_base_url,
                settings.gemma_model,
                settings.model_timeout_seconds,
                keep_alive_seconds=settings.ollama_keep_alive_seconds,
            )
            await analyzer.run_privacy_workflow(context, ToolRegistry())
            if (
                not privacy_workflow_complete(context)
                or context.draft is None
                or context.residual_review is None
            ):
                raise ModelError("The local privacy review did not complete.")
        except ModelBusyError:
            return JSONResponse(status_code=429, content={"error": {
                "code": "MODEL_BUSY",
                "message": "Gemma is busy with another privacy review. Wait for it to finish, then retry.",
                "retryable": True,
                "local_checks": {"sensitive": "pending", "relevant": "pending", "residual": "pending"},
            }})
        except (ValueError, ModelError, ToolValidationError) as exc:
            # Report confirmed progress without creating an approvable workflow,
            # returning partial findings, or exposing model output/source values.
            detected = "detect_sensitive_data" in context.executed_tools
            prepared = "propose_sanitized_request" in context.executed_tools
            checks = {
                "sensitive": "completed" if detected else "failed",
                "relevant": "completed" if prepared else "failed" if detected else "pending",
                "residual": "failed" if prepared else "pending",
            }
            stage = "residual" if prepared else "relevant" if detected else "sensitive"
            label = {"sensitive": "Sensitive-detail detection", "relevant": "Request preparation",
                "residual": "Remaining-clue review"}[stage]
            timed_out = isinstance(exc, ModelError) and exc.cause_type in {"ReadTimeout", "ConnectTimeout", "TimeoutError"}
            failure = 'timed out' if timed_out else 'reached its generation limit' if isinstance(exc, ModelError) and exc.cause_type == 'GenerationLimit' else 'could not complete'
            message = f"{label} {failure}. "
            message += "Retry the local review. Approval is unavailable. No request was sent externally."
            return JSONResponse(status_code=503, content={"error": {
                "code": "LOCAL_ANALYSIS_FAILED", "message": message, "retryable": True,
                "local_checks": checks,
            }})
        if (
            not sessions.is_active(session_id, session)
            or session.document_id != doc_id
        ):
            raise HTTPException(
                status_code=409,
                detail="The session or document changed during local analysis. Start again.",
            )
        workflow = PrivacyWorkflow(
            workflow_id=context.workflow_id,
            document_id=doc_id,
            question=question,
            draft=context.draft.text,
            findings=context.draft.findings,
            placeholder_map=dict(context.draft.placeholder_map),
            residual=context.residual_review,
            review_complete=context.residual_review.status != "blocked",
            contextual_flags=context.contextual_flags,
            semantic_values=tuple(f._value for f in context.semantic_findings) if context.semantic_detection_complete else None,
            local_checks={"sensitive": "completed", "relevant": "completed",
                "residual": "blocked" if context.residual_review.status == "blocked" else "completed"},
            pages_used=context.selected_pages,
        )
        with sessions.lock, session.lock:
            if (
                sessions.items.get(session_id) is not session
                or session.status != "active"
                or session.document_id != doc_id
                or session.analysis_id != analysis_id
            ):
                raise HTTPException(status_code=409, detail="The session or document changed during local analysis. Start again.")
            session.workflow = workflow
        return _workflow_view(workflow)
    finally:
        with sessions.lock, session.lock:
            if session.analysis_id == analysis_id:
                session.analysis_id = None


@app.patch("/api/v1/sessions/{session_id}/workflows/{workflow_id}/draft")
async def edit_draft(
    session_id: str,
    workflow_id: str,
    payload: DraftUpdate,
) -> dict[str, object]:
    session, workflow = _get_workflow(session_id, workflow_id)
    with sessions.lock, session.lock, workflow.lock:
        if sessions.items.get(session_id) is not session or session.status != "active" or session.workflow is not workflow:
            raise HTTPException(status_code=409, detail="The session or review is no longer active.")
        if payload.version != workflow.version or workflow.send_state != "review":
            raise HTTPException(status_code=409, detail="This review changed or is no longer editable. Reload it before continuing.")
    text = payload.draft.strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="The reviewed request cannot be empty.",
        )
    with workflow.lock:
        if payload.version != workflow.version or workflow.send_state != "review":
            raise HTTPException(status_code=409, detail="This review changed or is no longer editable. Reload it before continuing.")
        workflow.version += 1
        target_version = workflow.version
        workflow.draft = text
        workflow.acknowledged = False
        workflow.review_complete = False
        workflow.local_checks = {}
        workflow.residual = ResidualReview("needs_review", (), ("The edited request is being checked locally.",))
    detection_completed = False
    residual_completed = False
    try:
        scan = scan_sensitive_data(text)
        detection_completed = True
        flags = await OllamaAnalyzer(
            settings.ollama_base_url,
            settings.gemma_model,
            settings.model_timeout_seconds,
            keep_alive_seconds=settings.ollama_keep_alive_seconds,
        ).review_edited_draft(workflow.question, text)
        residual_completed = True
        residual = review_residual_risk(
            text,
            contextual_flags=flags,
            contextual_review_complete=True,
        )
        if session.document is None:
            raise PrivacyCheckError("The source review is unavailable.")
        residual = review_outbound_identity(
            text, "\n\n".join(page.text for page in session.document.pages), workflow.question, residual,
            known_values=workflow.semantic_values,
        )
        findings = scan.findings
    except PrivacyCheckError:
        findings = ()
        flags = ()
        residual = ResidualReview(
            "blocked",
            (),
            ("A required deterministic privacy check could not complete.",),
        )
    except ModelError:
        try:
            findings = scan_sensitive_data(text).findings
            detection_completed = True
        except PrivacyCheckError:
            findings = ()
        flags = ()
        residual = review_residual_risk(
            text,
            contextual_review_complete=False,
        )
    with workflow.lock:
        if workflow.version == target_version and workflow.send_state == "review":
            workflow.findings = findings
            workflow.contextual_flags = flags
            workflow.residual = residual
            workflow.review_complete = residual.status != "blocked" and not (
                residual.reasons and residual.reasons[0] == "Contextual residual-risk review did not complete."
            )
            workflow.local_checks = {
                "sensitive": "completed" if detection_completed else "failed",
                "relevant": "completed",
                "residual": ("blocked" if residual.status == "blocked" else "completed") if residual_completed else "failed",
            }
    return _workflow_view(workflow)


@app.post("/api/v1/sessions/{session_id}/workflows/{workflow_id}/acknowledge")
async def acknowledge_review(
    session_id: str,
    workflow_id: str,
    payload: WorkflowVersion,
) -> dict[str, object]:
    _, workflow = _get_workflow(session_id, workflow_id)
    with workflow.lock:
        if payload.version != workflow.version or workflow.send_state != "review":
            raise HTTPException(status_code=409, detail="This review changed. Check the latest version before acknowledging it.")
        if not workflow.review_complete or workflow.residual is None or workflow.residual.status == "blocked":
            raise HTTPException(status_code=409, detail="The required privacy checks have not completed, or a high-risk value is blocked.")
        workflow.acknowledged = True
    return _workflow_view(workflow)


@app.post("/api/v1/sessions/{session_id}/workflows/{workflow_id}/approve")
async def approve_and_send(
    session_id: str,
    workflow_id: str,
    payload: Approval,
) -> dict[str, object]:
    session, workflow = _get_workflow(session_id, workflow_id)
    # Lock the synchronous validation and state transition: edit and approval
    # cannot both validate the same review version.
    with sessions.lock, session.lock, workflow.lock:
        if sessions.items.get(session_id) is not session or session.status != "active" or session.workflow is not workflow:
            raise HTTPException(status_code=409, detail="The session or review is no longer active.")
        if payload.version != workflow.version or workflow.send_state != "review":
            raise HTTPException(status_code=409, detail="This approval is stale, already used, or no longer active.")
        if not _provider_view()["configured"]:
            raise HTTPException(status_code=503, detail="Configure the answer provider in the backend environment before approving a send.")
        if not workflow.review_complete or workflow.residual is None or workflow.residual.status == "blocked":
            raise HTTPException(status_code=409, detail="The privacy checks are incomplete or a high-risk value remains.")
        if workflow.residual.status == "needs_review" and not workflow.acknowledged:
            raise HTTPException(status_code=409, detail="Review and acknowledge the remaining privacy warnings first.")
        try:
            final_scan = scan_sensitive_data(workflow.draft)
        except PrivacyCheckError as exc:
            raise HTTPException(status_code=409, detail="The final privacy check could not complete; nothing was sent.") from exc
        if any(finding.action == "block" for finding in final_scan.findings):
            workflow.residual = ResidualReview("blocked", final_scan.findings, ("A high-risk value remains in the exact request.",))
            workflow.acknowledged = False
            raise HTTPException(status_code=409, detail="A high-risk value is still present; edit the request before approval.")
        if session.document is None:
            raise HTTPException(status_code=409, detail="The source review is unavailable; nothing was sent.")
        try:
            identity_review = review_outbound_identity(
                workflow.draft, "\n\n".join(page.text for page in session.document.pages),
                workflow.question, workflow.residual,
                known_values=workflow.semantic_values,
            )
        except PrivacyCheckError as exc:
            raise HTTPException(status_code=409, detail="The final identity check failed; edit or cancel. Nothing was sent.") from exc
        if identity_review.status == "blocked":
            workflow.residual = identity_review
            workflow.review_complete = False
            workflow.acknowledged = False
            raise HTTPException(status_code=409, detail="Personal details remain or could not be confidently minimized; edit or cancel. Nothing was sent.")
        workflow.send_state = "sending"
        approved = ApprovedRequest(
            workflow_id=workflow.workflow_id,
            version=workflow.version,
            provider_name=settings.answer_provider_name,
            provider_url=settings.answer_provider_url,
            content=workflow.draft,
        )
    provider = OpenAICompatibleProvider(
        url=settings.answer_provider_url,
        model=settings.answer_provider_model,
        api_key=settings.answer_provider_api_key,
        timeout_seconds=settings.answer_provider_timeout_seconds,
    )
    try:
        answer = await provider.send(approved)
    except Exception as exc:
        workflow.send_state = "delivery_unknown"
        _discard_sensitive_active_content(session)
        raise HTTPException(
            status_code=502,
            detail=(
                "The provider failed. Delivery may have occurred; this "
                "approval cannot be retried."
            ),
        ) from exc
    # Serialize completion with clear/delete so an in-flight answer cannot
    # recreate history after cleanup has invalidated the active session.
    with sessions.lock, session.lock, workflow.lock:
        try:
            answer_findings = scan_sensitive_data(answer)
            if any(finding.action == "block" for finding in answer_findings.findings):
                raise AnswerGroundingError("The answer contains a high-risk value.")
            validate_answer_grounding(answer, approved.content)
        except (AnswerGroundingError, PrivacyCheckError):
            workflow.answer = None
            workflow.send_state = "answer_withheld"
            _discard_sensitive_active_content(session)
            return JSONResponse(status_code=502, content={"error": {
                "code": "ANSWER_WITHHELD",
                "message": "The provider answer was withheld because its personal details could not be verified against the approved request. No automatic retry was made.",
                "retryable": False,
            }})
        if payload.restore_placeholders:
            for placeholder, original in sorted(
                workflow.placeholder_map.items(),
                key=lambda pair: len(pair[0]),
                reverse=True,
            ):
                answer = answer.replace(placeholder, original)
        workflow.answer = answer
        workflow.send_state = "sent"
        history_saved = False
        if session.conversation_id and sessions.is_active(session_id, session):
            try:
                history_saved = _conversation_store().save_answer_pair(
                    session.conversation_id,
                    workflow.workflow_id,
                    workflow.question,
                    answer,
                )
            except Exception:
                # The provider answer is already confirmed. Preserve the successful
                # response, but tell the client the local history write did not finish.
                history_saved = False
        response = {
            "workflow_id": workflow.workflow_id,
            "version": workflow.version,
            "answer": answer,
            "provider": _provider_view(),
            "pages_used": list(workflow.pages_used),
            "send_state": workflow.send_state,
            "history_saved": history_saved,
        }
        _discard_sensitive_active_content(session)
        return response


@app.post("/api/v1/sessions/{session_id}/workflows/{workflow_id}/cancel")
async def cancel_workflow(
    session_id: str,
    workflow_id: str,
) -> dict[str, str]:
    session, workflow = _get_workflow(session_id, workflow_id)
    with sessions.lock, session.lock, workflow.lock:
        if sessions.items.get(session_id) is not session or session.status != "active" or session.workflow is not workflow:
            raise HTTPException(status_code=409, detail="The session or review is no longer active.")
        if workflow.send_state != "review":
            raise HTTPException(status_code=409, detail="This workflow has already been consumed and cannot be cancelled.")
        workflow.send_state = "cancelled"
        _discard_sensitive_active_content(session)
        session.workflow = None
    return {"status": "cancelled"}


@app.delete("/api/v1/sessions/{session_id}/documents/{document_id}")
async def remove_document(session_id: str, document_id: str) -> dict[str, str]:
    session = sessions.get(session_id)
    with sessions.lock, session.lock:
        if sessions.items.get(session_id) is not session or session.status != "active":
            raise HTTPException(status_code=409, detail="The session was cleared. Start a new session.")
        if session.document_id != document_id:
            raise HTTPException(status_code=409, detail="This document is no longer attached to the session.")
        workflow = session.workflow
        if workflow is not None:
            with workflow.lock:
                if workflow.send_state == "sending":
                    raise HTTPException(status_code=409, detail="An approved provider request is already in progress; wait for its result before removing the document.")
                workflow.send_state = "cancelled"
        _discard_sensitive_active_content(session)
        session.workflow = None
    return {"status": "removed"}


@app.post("/api/v1/sessions/{session_id}/clear")
async def clear_session(session_id: str) -> JSONResponse:
    session = sessions.get(session_id)
    sessions.clear(session_id, session)
    response = JSONResponse({"status": "cleared"})
    response.delete_cookie(SESSION_COOKIE, path="/api/v1/sessions", httponly=True, samesite="strict")
    return response
