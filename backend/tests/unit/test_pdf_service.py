from dataclasses import replace
from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.config import get_settings
from app.extraction.pdf_service import PdfDocumentError, PdfTextExtractionService


def _make_pdf(page_texts: list[str]) -> bytes:
    """Build a small synthetic PDF with a valid cross-reference table."""

    page_ids = [3 + 2 * index for index in range(len(page_texts))]
    font_id = 3 + 2 * len(page_texts)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids [{ ' '.join(f'{page_id} 0 R' for page_id in page_ids) }] "
            f"/Count {len(page_ids)} >>"
        ).encode("ascii"),
    ]

    for index, text in enumerate(page_texts):
        page_id = page_ids[index]
        content_id = page_id + 1
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
        objects.extend(
            [
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                    f"/Contents {content_id} 0 R >>"
                ).encode("ascii"),
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                + stream
                + b"\nendstream",
            ]
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, value in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{object_number} 0 obj\n".encode("ascii"))
        document.extend(value)
        document.extend(b"\nendobj\n")

    xref_offset = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)


def _make_encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(user_password="synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _service(**overrides: int | float) -> PdfTextExtractionService:
    settings = replace(get_settings(), **overrides)
    return PdfTextExtractionService(settings)


def test_extracts_text_from_local_text_pdf() -> None:
    result = PdfTextExtractionService().extract(_make_pdf(["Synthetic monthly report"]))

    assert result.text == "Synthetic monthly report"
    assert result.page_count == 1


@pytest.mark.parametrize("pdf_bytes", [b"", None])
def test_rejects_empty_input(pdf_bytes: bytes | None) -> None:
    with pytest.raises(PdfDocumentError) as error:
        PdfTextExtractionService().extract(pdf_bytes)  # type: ignore[arg-type]

    assert error.value.code == "empty_input"


def test_rejects_file_over_documented_size_limit() -> None:
    with pytest.raises(PdfDocumentError) as error:
        _service(pdf_max_bytes=10).extract(b"%PDF-1.4\n" + b"x" * 10)

    assert error.value.code == "file_too_large"


def test_rejects_non_pdf_signature() -> None:
    with pytest.raises(PdfDocumentError) as error:
        PdfTextExtractionService().extract(b"not a PDF")

    assert error.value.code == "invalid_pdf"


def test_rejects_malformed_pdf() -> None:
    with pytest.raises(PdfDocumentError) as error:
        PdfTextExtractionService().extract(b"%PDF-1.4\nthis is not a valid PDF")

    assert error.value.code == "invalid_pdf"


def test_rejects_encrypted_pdf() -> None:
    with pytest.raises(PdfDocumentError) as error:
        PdfTextExtractionService().extract(_make_encrypted_pdf())

    assert error.value.code == "encrypted_pdf"


def test_rejects_pdf_over_documented_page_limit() -> None:
    with pytest.raises(PdfDocumentError) as error:
        _service(pdf_max_pages=1).extract(_make_pdf(["One", "Two"]))

    assert error.value.code == "too_many_pages"


def test_rejects_pdf_over_documented_character_limit() -> None:
    with pytest.raises(PdfDocumentError) as error:
        _service(pdf_max_chars=5).extract(_make_pdf(["six chars"]))

    assert error.value.code == "text_too_long"


def test_rejects_pdf_without_extractable_text() -> None:
    with pytest.raises(PdfDocumentError) as error:
        PdfTextExtractionService().extract(_make_pdf([""]))

    assert error.value.code == "no_extractable_text"


def test_enforces_configured_parser_timeout() -> None:
    with pytest.raises(PdfDocumentError) as error:
        _service(pdf_timeout_seconds=0.001).extract(_make_pdf(["Synthetic text"]))

    assert error.value.code == "parse_timeout"
