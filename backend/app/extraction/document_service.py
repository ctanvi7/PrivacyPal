"""Local, bounded extraction for pasted text, PDFs, and common images."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Literal

import fitz
from PIL import Image, UnidentifiedImageError
from app.config import Settings, get_settings
from app.extraction.pdf_service import PdfDocumentError, PdfTextExtractionService

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGES = 25
MAX_TEXT_CHARS = 25_000
MAX_IMAGE_DIMENSION = 8_000
MAX_IMAGE_PIXELS = 25_000_000
SUPPORTED_IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class ExtractionError(ValueError):
    """Safe extraction failure suitable for mapping to a user-facing error."""


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    pages: tuple[PageText, ...]
    source_type: Literal["pasted_text", "pdf", "image"]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


def _check_text_limit(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise ExtractionError("No readable text was found. Check the document and try again.")
    if len(normalized) > MAX_TEXT_CHARS:
        raise ExtractionError("The extracted text exceeds the 25,000 character limit.")
    return normalized


def extract_pasted_text(text: str) -> ExtractedDocument:
    if len(text) > MAX_TEXT_CHARS:
        raise ExtractionError("Pasted text exceeds the 25,000 character limit.")
    return ExtractedDocument((PageText(page=1, text=_check_text_limit(text)),), "pasted_text")


def extract_upload(data: bytes, content_type: str, filename: str, settings: Settings | None = None) -> ExtractedDocument:
    if not data:
        raise ExtractionError("The selected file is empty.")
    settings = settings or get_settings()
    if len(data) > settings.pdf_max_bytes:
        raise ExtractionError("The file exceeds the configured upload limit.")
    extension = PurePath(filename).suffix.casefold()
    if extension == ".pdf":
        if content_type not in {"application/pdf", "application/octet-stream"}:
            raise ExtractionError("The file type does not match its PDF contents.")
        return _extract_pdf(data, settings)
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ExtractionError("Choose a PDF, PNG, JPEG, or WebP image.")
    if content_type not in {*SUPPORTED_IMAGE_TYPES.values(), "application/octet-stream"}:
        raise ExtractionError("Choose a PDF, PNG, JPEG, or WebP image.")
    return _extract_image(data, content_type, filename)


def _ocr_image(image: Image.Image) -> str:
    if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
        raise ExtractionError("The image dimensions exceed the local processing limit.")
    try:
        import pytesseract

        return pytesseract.image_to_string(image, timeout=15)
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ExtractionError("Local OCR is unavailable. Install the project requirements and Tesseract.") from exc
    except Exception as exc:
        # Tesseract errors can contain paths or input details; return only a safe message.
        raise ExtractionError("Local OCR could not read this image. Check that Tesseract is installed.") from exc


def _extract_image(data: bytes, content_type: str, filename: str) -> ExtractedDocument:
    try:
        with Image.open(BytesIO(data)) as image:
            fmt = image.format
            if fmt not in SUPPORTED_IMAGE_TYPES:
                raise ExtractionError("Choose a PNG, JPEG, or WebP image.")
            expected_type = SUPPORTED_IMAGE_TYPES[fmt]
            if content_type not in {expected_type, "application/octet-stream"}:
                raise ExtractionError("The file type does not match its image contents.")
            allowed_extensions = {"PNG": {".png"}, "JPEG": {".jpg", ".jpeg"}, "WEBP": {".webp"}}
            if PurePath(filename).suffix.casefold() not in allowed_extensions[fmt]:
                raise ExtractionError("The file extension does not match its image contents.")
            if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
                raise ExtractionError("The image dimensions exceed the local processing limit.")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ExtractionError("The image pixel count exceeds the local processing limit.")
            image.verify()
        with Image.open(BytesIO(data)) as image:
            return ExtractedDocument((PageText(1, _check_text_limit(_ocr_image(image))),), "image")
    except UnidentifiedImageError as exc:
        raise ExtractionError("The file is not a supported image or PDF.") from exc


def _extract_pdf(data: bytes, settings: Settings) -> ExtractedDocument:
    try:
        extracted = PdfTextExtractionService(settings).extract(data)
        extracted_pages = list(extracted.pages)
    except PdfDocumentError as exc:
        if exc.code != "no_extractable_text":
            raise ExtractionError(exc.message) from exc
        extracted_pages = []
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ExtractionError("The PDF is damaged or could not be opened.") from exc
    try:
        if document.is_encrypted:
            raise ExtractionError("Password-protected PDFs are not supported.")
        if not extracted_pages:
            extracted_pages = [""] * document.page_count
        if len(extracted_pages) != document.page_count:
            raise ExtractionError("The PDF pages could not be read consistently.")
        pages: list[PageText] = []
        for index, (page, extracted_text) in enumerate(zip(document, extracted_pages), start=1):
            text = extracted_text.strip()
            if len(text) < 10:
                if page.rect.width * 1.5 > MAX_IMAGE_DIMENSION or page.rect.height * 1.5 > MAX_IMAGE_DIMENSION:
                    raise ExtractionError("A PDF page exceeds the local OCR dimension limit.")
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image = Image.open(BytesIO(pixmap.tobytes("png")))
                text = _ocr_image(image).strip()
            if text:
                pages.append(PageText(index, text))
            if sum(len(item.text) for item in pages) > MAX_TEXT_CHARS:
                raise ExtractionError("The extracted text exceeds the 25,000 character limit.")
        if not pages:
            raise ExtractionError("No readable text was found in the PDF.")
        return ExtractedDocument(tuple(pages), "pdf")
    finally:
        document.close()
