"""Bounded local text extraction for text-based PDF documents."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic

from app.config import Settings, get_settings

PDF_SIGNATURE = b"%PDF-"
PDF_HEADER_SEARCH_BYTES = 1024
WORKER_SCRIPT = Path(__file__).with_name("pdf_worker.py")


class PdfDocumentError(ValueError):
    """A safe, user-displayable PDF processing error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PdfExtractionResult:
    """Extracted local text and basic page metadata."""

    text: str
    page_count: int
    pages: tuple[str, ...]


class PdfTextExtractionService:
    """Validate a PDF and extract its text locally under configured limits."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def extract(self, pdf_bytes: bytes) -> PdfExtractionResult:
        """Validate and extract text without writing the source PDF to disk."""

        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            raise PdfDocumentError("empty_input", "The PDF is empty.")
        if len(pdf_bytes) > self._settings.pdf_max_bytes:
            raise PdfDocumentError(
                "file_too_large",
                f"The PDF exceeds the {self._settings.pdf_max_bytes}-byte size limit.",
            )
        if PDF_SIGNATURE not in pdf_bytes[:PDF_HEADER_SEARCH_BYTES]:
            raise PdfDocumentError("invalid_pdf", "The file is not a valid PDF.")

        started_at = monotonic()
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(WORKER_SCRIPT),
                    str(self._settings.pdf_max_pages),
                    str(self._settings.pdf_max_chars),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            remaining = self._settings.pdf_timeout_seconds - (monotonic() - started_at)
            if remaining <= 0:
                process.kill()
                process.communicate()
                raise PdfDocumentError(
                    "parse_timeout",
                    "PDF processing exceeded the configured time limit.",
                )
            stdout, _ = process.communicate(
                input=pdf_bytes,
                timeout=remaining,
            )
            if process.returncode != 0:
                result = {"code": "invalid_pdf", "text": "", "page_count": 0}
            else:
                result = json.loads(stdout)
            if not isinstance(result, dict):
                result = {"code": "invalid_pdf", "text": "", "page_count": 0}
        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                process.communicate()
            raise PdfDocumentError(
                "parse_timeout",
                "PDF processing exceeded the configured time limit.",
            ) from None
        except PdfDocumentError:
            raise
        except Exception as exc:
            raise PdfDocumentError(
                "invalid_pdf", "The PDF could not be processed."
            ) from exc
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()

        code = result.get("code")
        text = result.get("text")
        page_count = result.get("page_count", 0)
        if code == "ok":
            pages = result.get("page_texts")
            if not isinstance(text, str) or not isinstance(page_count, int) or not isinstance(pages, list) or any(not isinstance(page, str) for page in pages) or len(pages) != page_count:
                raise PdfDocumentError("invalid_pdf", "The PDF is malformed or unreadable.")
            return PdfExtractionResult(text=text, page_count=page_count, pages=tuple(pages))
        if code == "encrypted_pdf":
            raise PdfDocumentError(
                code, "Encrypted or password-protected PDFs are not supported."
            )
        if code == "too_many_pages":
            raise PdfDocumentError(
                code,
                f"The PDF exceeds the {self._settings.pdf_max_pages}-page limit.",
            )
        if code == "text_too_long":
            raise PdfDocumentError(
                code,
                f"The PDF text exceeds the {self._settings.pdf_max_chars}-character limit.",
            )
        if code == "no_extractable_text":
            raise PdfDocumentError(
                code,
                "No machine-readable text was found in the PDF.",
            )
        raise PdfDocumentError("invalid_pdf", "The PDF is malformed or unreadable.")
