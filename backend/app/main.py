"""Loopback-only API for local privacy review and explicitly approved answers."""

from __future__ import annotations

import re
import time
import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile as FastAPIUploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
from app.model.ollama_adapter import ModelError, OllamaAnalyzer
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
    ProviderError,
)
from app.provider.sarvam import (
    MAX_AUDIO_BYTES,
    MAX_TTS_CHARS,
    MAX_TRANSLATION_CHARS,
    SarvamClient,
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@dataclass
class PrivacyWorkflow:
    workflow_id: str
    document_id: str
    question: str
    draft: str
    findings: tuple[Finding, ...]
    placeholder_map: dict[str, str] = field(repr=False)
    provider_id: str = "default"
    residual: ResidualReview | None = None
    contextual_flags: tuple[str, ...] = ()
    version: int = 1
    review_complete: bool = True
    acknowledged: bool = False
    send_state: Literal[
        "review", "sending", "sent", "delivery_unknown", "cancelled"
    ] = "review"
    answer: str | None = None
    pages_used: tuple[int, ...] = ()


@dataclass
class Session:
    document_id: str | None = None
    document: ExtractedDocument | None = None
    workflow: PrivacyWorkflow | None = None
    touched_at: float = 0.0
    requests: dict[str, "ReviewRequest"] | None = None
    conversation_id: str | None = None
    answer_digest: str | None = field(default=None, repr=False)

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
    provider_id: str = Field(default="default", min_length=1, max_length=32)


class TranslationRequest(BaseModel):
    # Explicit confirmation is required for every outbound translation operation.
    consent: bool
    source_language: str = Field(min_length=2, max_length=12)
    target_language: str = Field(min_length=2, max_length=12)
    version: int = Field(ge=1)


class SpeechOutputRequest(BaseModel):
    consent: bool
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    language: str = Field(min_length=2, max_length=12)


class AnswerTranslationRequest(BaseModel):
    consent: bool
    text: str = Field(min_length=1, max_length=MAX_TRANSLATION_CHARS)
    source_language: str = Field(min_length=2, max_length=12)
    target_language: str = Field(min_length=2, max_length=12)


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

    def _expire_idle(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, value in self.items.items()
            if now - value.touched_at > self.idle_seconds
        ]
        for key in expired:
            _discard_sensitive_active_content(self.items[key])
            del self.items[key]

    def create(self, conversation_id: str | None = None) -> str:
        self._expire_idle()
        if len(self.items) >= self.max_sessions:
            raise HTTPException(
                status_code=429,
                detail="Too many active local sessions. Clear one and try again.",
            )
        session_id = str(uuid4())
        self.items[session_id] = Session(
            touched_at=time.monotonic(), conversation_id=conversation_id
        )
        return session_id

    def remove_conversation(self, conversation_id: str) -> int:
        matched = [
            key for key, session in self.items.items()
            if session.conversation_id == conversation_id
        ]
        for key in matched:
            _discard_sensitive_active_content(self.items[key])
            del self.items[key]
        return len(matched)

    def get(self, session_id: str) -> Session:
        self._expire_idle()
        if session_id not in self.items:
            raise HTTPException(
                status_code=404,
                detail="Session expired. Start a new session.",
            )
        session = self.items[session_id]
        session.touched_at = time.monotonic()
        return session


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
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get(
        "origin"
    ) != settings.frontend_origin:
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
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    code = {
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
        return _error(413, "FILE_TOO_LARGE", "The upload exceeds the 10 MiB size limit.")
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


def _provider_view(provider_id: str = "default") -> dict[str, object]:
    if provider_id == "sarvam":
        return {
            "id": "sarvam",
            "name": "Sarvam AI",
            "endpoint": "https://api.sarvam.ai/v1/chat/completions",
            "configured": bool(settings.sarvam_api_key),
            "model": settings.sarvam_chat_model,
        }
    if provider_id != "default":
        return {"id": provider_id, "name": "Unavailable provider", "endpoint": "", "configured": False}
    return {
        "id": "default",
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
        "acknowledged": workflow.acknowledged,
        "send_state": workflow.send_state,
        "provider": _provider_view(workflow.provider_id),
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
    if workflow.document_id != session.document_id:
        raise HTTPException(
            status_code=409,
            detail="The document changed. Start a new review.",
        )
    return session, workflow


def _discard_sensitive_active_content(session: Session, *, preserve_answer_digest: bool = False) -> None:
    """Release document/workflow content while retaining only retry-safe status IDs."""
    session.document = None
    session.document_id = None
    if not preserve_answer_digest:
        session.answer_digest = None
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
        workflow.answer = None
        workflow.pages_used = ()


def _verify_last_answer(session: Session, text: str) -> None:
    expected = session.answer_digest
    received = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not expected or not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=409, detail="Only the answer returned in this active session can be sent to Sarvam.")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/providers")
def list_answer_providers() -> dict[str, object]:
    options = [_provider_view("default"), _provider_view("sarvam")]
    return {"items": [item for item in options if item["configured"]]}


def _sarvam_client() -> SarvamClient:
    if not settings.sarvam_api_key:
        raise HTTPException(status_code=503, detail="Sarvam is not configured on this computer.")
    return SarvamClient(settings.sarvam_api_key, settings.sarvam_timeout_seconds)


TRANSLATION_LANGUAGES = {"en-IN", "hi-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN", "gu-IN", "kn-IN", "ml-IN", "pa-IN", "od-IN", "as-IN", "ur-IN", "brx-IN", "doi-IN", "kok-IN", "ks-IN", "mai-IN", "mni-IN", "ne-IN", "sa-IN", "sat-IN", "sd-IN"}
SPEECH_LANGUAGES = {"en-IN", "hi-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN", "gu-IN", "kn-IN", "ml-IN", "pa-IN", "od-IN"}


def _validate_language(language: str, *, speech: bool = False) -> None:
    supported = SPEECH_LANGUAGES if speech else TRANSLATION_LANGUAGES
    if language not in supported:
        raise HTTPException(status_code=422, detail="Choose a supported Sarvam language.")


@app.post("/api/v1/sessions", status_code=201)
async def create_session(payload: SessionCreate | None = None) -> dict[str, object]:
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
    return {
        "session_id": session_id,
        "expires_in_seconds": 1_800,
        "conversation_id": conversation_id,
    }


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
                or not isinstance(entries[0][1], StarletteUploadFile)
            ):
                for _, value in entries:
                    if isinstance(value, StarletteUploadFile):
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
                        "The upload exceeds the 10 MiB size limit.",
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
    session.document_id = document_id
    session.document = document
    session.answer_digest = None
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
    if session.document is None or payload.document_id != session.document_id:
        raise HTTPException(
            status_code=409,
            detail="Add a document before asking a question.",
        )
    question = payload.question.strip()
    if not question:
        raise HTTPException(
            status_code=422,
            detail="Enter a question about the document.",
        )
    if payload.provider_id not in {"default", "sarvam"}:
        raise HTTPException(status_code=422, detail="Choose an available answer provider.")
    if payload.provider_id == "sarvam" and not settings.sarvam_api_key:
        raise HTTPException(status_code=503, detail="Sarvam is not configured on this computer.")
    doc_id = session.document_id
    document = session.document
    session.answer_digest = None
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
        analyzer = OllamaAnalyzer(
            settings.ollama_base_url,
            settings.gemma_model,
            settings.model_timeout_seconds,
        )
        await analyzer.run_privacy_workflow(context, ToolRegistry())
        if (
            not privacy_workflow_complete(context)
            or context.draft is None
            or context.residual_review is None
        ):
            raise ModelError("The local privacy review did not complete.")
    except (ValueError, ModelError, ToolValidationError) as exc:
        _discard_sensitive_active_content(session)
        raise HTTPException(
            status_code=503,
            detail=(
                "Local Gemma or a required privacy check failed. "
                "No request was sent externally."
            ),
        ) from exc
    except Exception as exc:
        _discard_sensitive_active_content(session)
        raise HTTPException(
            status_code=503,
            detail=(
                "Local privacy analysis could not complete. "
                "No request was sent externally."
            ),
        ) from exc
    if (
        session_id not in sessions.items
        or sessions.items[session_id] is not session
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
        provider_id=payload.provider_id,
        residual=context.residual_review,
        contextual_flags=context.contextual_flags,
        pages_used=context.inspected_pages,
    )
    session.workflow = workflow
    return _workflow_view(workflow)


@app.patch("/api/v1/sessions/{session_id}/workflows/{workflow_id}/draft")
async def edit_draft(
    session_id: str,
    workflow_id: str,
    payload: DraftUpdate,
) -> dict[str, object]:
    _, workflow = _get_workflow(session_id, workflow_id)
    if payload.version != workflow.version or workflow.send_state != "review":
        raise HTTPException(
            status_code=409,
            detail=(
                "This review changed or is no longer editable. "
                "Reload it before continuing."
            ),
        )
    text = payload.draft.strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="The reviewed request cannot be empty.",
        )
    workflow.version += 1
    target_version = workflow.version
    workflow.draft = text
    workflow.acknowledged = False
    workflow.review_complete = False
    workflow.residual = ResidualReview(
        "needs_review",
        (),
        ("The edited request is being checked locally.",),
    )
    try:
        scan = scan_sensitive_data(text)
        flags = await OllamaAnalyzer(
            settings.ollama_base_url,
            settings.gemma_model,
            settings.model_timeout_seconds,
        ).review_edited_draft(workflow.question, text)
        residual = review_residual_risk(
            text,
            contextual_flags=flags,
            contextual_review_complete=True,
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
        except PrivacyCheckError:
            findings = ()
        flags = ()
        residual = review_residual_risk(
            text,
            contextual_review_complete=False,
        )
    if workflow.version == target_version and workflow.send_state == "review":
        workflow.findings = findings
        workflow.contextual_flags = flags
        workflow.residual = residual
        workflow.review_complete = residual.status != "blocked" and not (
            residual.reasons
            and residual.reasons[0]
            == "Contextual residual-risk review did not complete."
        )
    return _workflow_view(workflow)


@app.post("/api/v1/sessions/{session_id}/workflows/{workflow_id}/acknowledge")
async def acknowledge_review(
    session_id: str,
    workflow_id: str,
    payload: WorkflowVersion,
) -> dict[str, object]:
    _, workflow = _get_workflow(session_id, workflow_id)
    if payload.version != workflow.version or workflow.send_state != "review":
        raise HTTPException(
            status_code=409,
            detail=(
                "This review changed. Check the latest version before "
                "acknowledging it."
            ),
        )
    if (
        not workflow.review_complete
        or workflow.residual is None
        or workflow.residual.status == "blocked"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The required privacy checks have not completed, or a "
                "high-risk value is blocked."
            ),
        )
    workflow.acknowledged = True
    return _workflow_view(workflow)


@app.post("/api/v1/sessions/{session_id}/workflows/{workflow_id}/approve")
async def approve_and_send(
    session_id: str,
    workflow_id: str,
    payload: Approval,
) -> dict[str, object]:
    session, workflow = _get_workflow(session_id, workflow_id)
    if payload.version != workflow.version or workflow.send_state != "review":
        raise HTTPException(
            status_code=409,
            detail="This approval is stale, already used, or no longer active.",
        )
    provider_view = _provider_view(workflow.provider_id)
    if not provider_view["configured"]:
        raise HTTPException(
            status_code=503,
            detail=(
                "Configure the answer provider in the backend environment "
                "before approving a send."
            ),
        )
    if (
        not workflow.review_complete
        or workflow.residual is None
        or workflow.residual.status == "blocked"
    ):
        raise HTTPException(
            status_code=409,
            detail="The privacy checks are incomplete or a high-risk value remains.",
        )
    if workflow.residual.status == "needs_review" and not workflow.acknowledged:
        raise HTTPException(
            status_code=409,
            detail="Review and acknowledge the remaining privacy warnings first.",
        )
    try:
        final_scan = scan_sensitive_data(workflow.draft)
    except PrivacyCheckError as exc:
        raise HTTPException(
            status_code=409,
            detail="The final privacy check could not complete; nothing was sent.",
        ) from exc
    if any(finding.action == "block" for finding in final_scan.findings):
        workflow.residual = ResidualReview(
            "blocked",
            final_scan.findings,
            ("A high-risk value remains in the exact request.",),
        )
        workflow.acknowledged = False
        raise HTTPException(
            status_code=409,
            detail="A high-risk value is still present; edit the request before approval.",
        )

    # Consume approval before the first await, so double-clicks/replays cannot send twice.
    workflow.send_state = "sending"
    approved = ApprovedRequest(
        workflow_id=workflow.workflow_id,
        version=workflow.version,
        provider_name=str(provider_view["name"]),
        provider_url=str(provider_view["endpoint"]),
        content=workflow.draft,
    )
    try:
        if workflow.provider_id == "sarvam":
            if not isinstance(approved, ApprovedRequest):
                raise ProviderError("Only the approved draft can be sent.")
            answer = await _sarvam_client().chat(
                model=settings.sarvam_chat_model,
                content=approved.content,
            )
        else:
            provider = OpenAICompatibleProvider(
                url=settings.answer_provider_url,
                model=settings.answer_provider_model,
                api_key=settings.answer_provider_api_key,
                timeout_seconds=settings.answer_provider_timeout_seconds,
            )
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
    try:
        answer_findings = scan_sensitive_data(answer)
    except PrivacyCheckError as exc:
        workflow.send_state = "sent"
        _discard_sensitive_active_content(session)
        raise HTTPException(
            status_code=502,
            detail="The provider response could not be safely returned or saved.",
        ) from exc
    if any(finding.action == "block" for finding in answer_findings.findings):
        workflow.send_state = "sent"
        _discard_sensitive_active_content(session)
        raise HTTPException(
            status_code=502,
            detail="The provider response contained a blocked high-risk value and was withheld.",
        )
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
    if session.conversation_id:
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
        "provider": _provider_view(workflow.provider_id),
        "pages_used": list(workflow.pages_used),
        "send_state": workflow.send_state,
        "history_saved": history_saved,
    }
    session.answer_digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()
    _discard_sensitive_active_content(session, preserve_answer_digest=True)
    return response


@app.post("/api/v1/sessions/{session_id}/workflows/{workflow_id}/translate-draft")
async def translate_approved_draft(
    session_id: str,
    workflow_id: str,
    payload: TranslationRequest,
) -> dict[str, object]:
    _, workflow = _get_workflow(session_id, workflow_id)
    if not payload.consent:
        raise HTTPException(status_code=403, detail="Confirm before sending the reviewed request to Sarvam for translation.")
    if payload.version != workflow.version or workflow.send_state != "review":
        raise HTTPException(status_code=409, detail="This reviewed request changed. Review the current version before translating.")
    if not workflow.review_complete or workflow.residual is None or workflow.residual.status == "blocked":
        raise HTTPException(status_code=409, detail="The privacy review must complete before translation.")
    if workflow.residual.status == "needs_review" and not workflow.acknowledged:
        raise HTTPException(status_code=409, detail="Review and acknowledge remaining privacy warnings before sending text for translation.")
    _validate_language(payload.source_language)
    _validate_language(payload.target_language)
    if len(workflow.draft) > MAX_TRANSLATION_CHARS:
        raise HTTPException(status_code=413, detail="The reviewed request is longer than Sarvam's 2,000-character translation limit.")
    try:
        scan = scan_sensitive_data(workflow.draft)
        if any(item.action == "block" for item in scan.findings):
            raise HTTPException(status_code=409, detail="A high-risk value remains in the request. Edit it before translation.")
        translated = await _sarvam_client().translate(
            workflow.draft,
            source_language=payload.source_language,
            target_language=payload.target_language,
            model=settings.sarvam_translation_model,
        )
        translated_scan = scan_sensitive_data(translated)
        if any(item.action == "block" for item in translated_scan.findings):
            raise HTTPException(status_code=502, detail="The translated draft contained a blocked high-risk value and was withheld.")
    except HTTPException:
        raise
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Translation could not be safely completed.") from exc
    return {
        "workflow_id": workflow.workflow_id,
        "version": workflow.version,
        "target_language": payload.target_language,
        "translated_text": translated,
        "provider": "Sarvam AI",
    }


@app.post("/api/v1/sessions/{session_id}/speech/transcribe")
async def transcribe_speech(
    session_id: str,
    consent: bool = Form(...),
    file: FastAPIUploadFile = File(...),
) -> dict[str, str]:
    sessions.get(session_id)
    if not consent:
        raise HTTPException(status_code=403, detail="Confirm before sending audio to Sarvam for transcription.")
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    await file.close()
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Choose an audio file up to 10 MiB.")
    mime = file.content_type or ""
    extension = {
        "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
        "audio/aac": "aac", "audio/flac": "flac", "audio/ogg": "ogg", "audio/opus": "opus",
        "audio/webm": "webm", "audio/aiff": "aiff", "audio/x-aiff": "aiff", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
        "video/mp4": "mp4", "audio/amr": "amr", "audio/x-ms-wma": "wma", "audio/pcm": "pcm",
    }.get(mime.lower().split(";")[0].strip(), "audio")
    try:
        transcript = await _sarvam_client().transcribe(audio, filename=f"speech.{extension}", content_type=mime)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"transcript": transcript, "review_required": True}


@app.post("/api/v1/sessions/{session_id}/translate-answer")
async def translate_answer(session_id: str, payload: AnswerTranslationRequest) -> dict[str, str]:
    session = sessions.get(session_id)
    if not payload.consent:
        raise HTTPException(status_code=403, detail="Confirm before sending this displayed answer text to Sarvam for translation.")
    _verify_last_answer(session, payload.text)
    _validate_language(payload.source_language)
    _validate_language(payload.target_language)
    try:
        scan = scan_sensitive_data(payload.text)
        if any(item.action == "block" for item in scan.findings):
            raise HTTPException(status_code=409, detail="Text containing a blocked high-risk value cannot be sent for translation.")
        translated = await _sarvam_client().translate(
            payload.text,
            source_language=payload.source_language,
            target_language=payload.target_language,
            model=settings.sarvam_translation_model,
        )
        result_scan = scan_sensitive_data(translated)
        if any(item.action == "block" for item in result_scan.findings):
            raise HTTPException(status_code=502, detail="The translated answer contained a blocked high-risk value and was withheld.")
    except HTTPException:
        raise
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"translated_text": translated, "target_language": payload.target_language}


@app.post("/api/v1/sessions/{session_id}/speech/synthesize")
async def synthesize_speech(session_id: str, payload: SpeechOutputRequest) -> dict[str, str]:
    session = sessions.get(session_id)
    if not payload.consent:
        raise HTTPException(status_code=403, detail="Confirm before sending this text to Sarvam for speech generation.")
    _verify_last_answer(session, payload.text)
    _validate_language(payload.language, speech=True)
    try:
        scan = scan_sensitive_data(payload.text)
        if any(item.action == "block" for item in scan.findings):
            raise HTTPException(status_code=409, detail="Text containing a blocked high-risk value cannot be sent for speech generation.")
        audio_base64 = await _sarvam_client().synthesize(
            payload.text,
            language=payload.language,
            model=settings.sarvam_tts_model,
        )
    except HTTPException:
        raise
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"audio_base64": audio_base64, "content_type": "audio/wav"}


@app.post("/api/v1/sessions/{session_id}/workflows/{workflow_id}/cancel")
async def cancel_workflow(
    session_id: str,
    workflow_id: str,
) -> dict[str, str]:
    session, workflow = _get_workflow(session_id, workflow_id)
    if workflow.send_state != "review":
        raise HTTPException(
            status_code=409,
            detail="This workflow has already been consumed and cannot be cancelled.",
        )
    workflow.send_state = "cancelled"
    _discard_sensitive_active_content(session)
    session.workflow = None
    return {"status": "cancelled"}


@app.delete("/api/v1/sessions/{session_id}/documents/{document_id}")
async def remove_document(session_id: str, document_id: str) -> dict[str, str]:
    session = sessions.get(session_id)
    if session.document_id != document_id:
        raise HTTPException(
            status_code=409,
            detail="This document is no longer attached to the session.",
        )
    _discard_sensitive_active_content(session)
    session.workflow = None
    return {"status": "removed"}


@app.post("/api/v1/sessions/{session_id}/clear")
async def clear_session(session_id: str) -> dict[str, str]:
    session = sessions.get(session_id)
    _discard_sensitive_active_content(session)
    del sessions.items[session_id]
    return {"status": "cleared"}
