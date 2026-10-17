"""FastAPI application entry point for PrivacyPal."""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.config import get_settings
from app.extraction.pdf_service import PdfDocumentError, PdfTextExtractionService

SESSION_TTL_SECONDS = 1800


@dataclass
class StoredDocument:
    """Document metadata and extracted text held only in process memory."""

    text: str
    page_count: int


@dataclass
class SessionState:
    """Temporary state owned by a single local session."""

    expires_at: float
    documents: dict[str, StoredDocument] = field(default_factory=dict)


app = FastAPI(title="PrivacyPal API", version="0.1.0")
app.state.sessions = {}
app.state.pdf_extractor = None


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _active_session(session_id: str) -> SessionState | None:
    sessions: dict[str, SessionState] = app.state.sessions
    session = sessions.get(session_id)
    if session is not None and session.expires_at <= time.monotonic():
        del sessions[session_id]
        return None
    return session


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Report that the HTTP application is running."""

    return {"status": "ok"}


@app.post("/api/v1/sessions", status_code=201, tags=["sessions"])
def create_session() -> dict[str, str | int]:
    """Create an opaque, temporary session."""

    now = time.monotonic()
    sessions: dict[str, SessionState] = app.state.sessions
    expired = [key for key, value in sessions.items() if value.expires_at <= now]
    for key in expired:
        del sessions[key]

    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = SessionState(expires_at=now + SESSION_TTL_SECONDS)
    return {"session_id": session_id, "expires_in_seconds": SESSION_TTL_SECONDS}


@app.post(
    "/api/v1/sessions/{session_id}/documents",
    status_code=201,
    tags=["documents"],
)
async def upload_document(
    session_id: str,
    request: Request,
) -> JSONResponse:
    """Extract a supported PDF locally and keep its text in session memory."""

    session = _active_session(session_id)
    if session is None:
        return _error(404, "UNKNOWN_SESSION", "The session was not found or has expired.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "multipart/form-data":
        return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload one text-based PDF file.")
    try:
        form = await request.form()
    except Exception:
        return _error(422, "EMPTY_PDF", "A single PDF file is required.")
    entries = list(form.multi_items())
    if not entries:
        return _error(422, "EMPTY_PDF", "A PDF file is required.")
    if len(entries) != 1 or entries[0][0] != "file" or not isinstance(entries[0][1], UploadFile):
        for _, value in entries:
            if isinstance(value, UploadFile):
                await value.close()
        return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload exactly one PDF file in the file part.")
    file = entries[0][1]

    filename_is_pdf = bool(file.filename) and file.filename.lower().endswith(".pdf")
    content_type_is_pdf = file.content_type == "application/pdf"
    if not filename_is_pdf or not content_type_is_pdf:
        await file.close()
        return _error(415, "UNSUPPORTED_FILE_TYPE", "Upload a text-based PDF file.")

    settings = get_settings()
    data = await file.read(settings.pdf_max_bytes + 1)
    await file.close()
    if len(data) > settings.pdf_max_bytes:
        return _error(413, "FILE_TOO_LARGE", "The PDF exceeds the 10 MiB size limit.")

    extractor = app.state.pdf_extractor
    if extractor is None:
        extractor = PdfTextExtractionService(settings)
    try:
        result = extractor.extract(data)
    except PdfDocumentError as exc:
        status_code, code, message = _map_pdf_error(exc)
        return _error(status_code, code, message)
    except Exception:
        return _error(500, "INTERNAL_ERROR", "The PDF could not be processed.")

    document_id = str(uuid.uuid4())
    session.documents[document_id] = StoredDocument(
        text=result.text,
        page_count=result.page_count,
    )
    return JSONResponse(
        status_code=201,
        content={
            "document_id": document_id,
            "source_type": "pdf",
            "status": "ready",
            "page_count": result.page_count,
            "extracted_character_count": len(result.text),
        },
    )


def _map_pdf_error(error: PdfDocumentError) -> tuple[int, str, str]:
    """Translate extraction failures to the documented safe API errors."""

    if error.code == "file_too_large":
        return 413, "FILE_TOO_LARGE", "The PDF exceeds the 10 MiB size limit."
    if error.code == "parse_timeout":
        return 504, "PDF_EXTRACTION_TIMEOUT", "PDF extraction exceeded the 15-second time limit."
    if error.code == "encrypted_pdf":
        return 422, "ENCRYPTED_PDF", "Encrypted or password-protected PDFs are not supported."
    if error.code == "too_many_pages":
        return 422, "TOO_MANY_PAGES", "The PDF exceeds the 25-page limit."
    if error.code == "text_too_long":
        return 422, "TEXT_TOO_LONG", "The PDF text exceeds the 25,000-character limit."
    if error.code == "no_extractable_text":
        return 422, "NO_EXTRACTABLE_TEXT", "No extractable text was found in the PDF."
    if error.code == "empty_input":
        return 422, "EMPTY_PDF", "The PDF file is empty."
    return 422, "INVALID_PDF", "The PDF is malformed or unreadable."
