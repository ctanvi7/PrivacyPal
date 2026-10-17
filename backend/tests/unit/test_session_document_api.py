from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import get_settings
from app.extraction import document_service
from app.extraction.document_service import ExtractionError
from app.main import app, sessions


def _make_pdf(page_texts: list[str]) -> bytes:
    """Build a small synthetic text PDF with a valid cross-reference table."""

    page_ids = [3 + 2 * index for index in range(len(page_texts))]
    font_id = 3 + 2 * len(page_texts)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids [{ ' '.join(f'{page_id} 0 R' for page_id in page_ids) }] "
            f"/Count {len(page_ids)} >>"
        ).encode("ascii"),
    ]
    for page_id, text in zip(page_ids, page_texts):
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
        document.extend(value + b"\nendobj\n")
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


def _encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(user_password="synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def client() -> TestClient:
    sessions.items.clear()
    with TestClient(app) as test_client:
        yield test_client
    sessions.items.clear()


def _session_id(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 201
    assert response.json()["expires_in_seconds"] == 1800
    return response.json()["session_id"]


def _upload(client: TestClient, session_id: str, data: bytes, filename: str = "report.pdf", content_type: str = "application/pdf"):
    return client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files={"file": (filename, data, content_type)},
        headers={"Origin": "http://127.0.0.1:5173"},
    )


def test_create_session_returns_contract_response(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions",
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 201
    assert set(response.json()) == {"session_id", "expires_in_seconds"}
    assert response.json()["expires_in_seconds"] == 1800


def test_upload_returns_metadata_and_keeps_text_in_memory(client: TestClient) -> None:
    session_id = _session_id(client)
    response = _upload(client, session_id, _make_pdf(["Synthetic monthly report"]))

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "document_id": body["document_id"],
        "source_type": "pdf",
        "status": "ready",
        "page_count": 1,
        "character_count": len("Synthetic monthly report"),
        "extracted_character_count": len("Synthetic monthly report"),
    }
    assert "text" not in body
    document = sessions.items[session_id].document
    assert document is not None
    assert document.text == "Synthetic monthly report"
    assert len(document.pages) == 1


def test_upload_rejects_unknown_session(client: TestClient) -> None:
    response = _upload(client, "unknown", _make_pdf(["text"]))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


def test_upload_rejects_oversized_file(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = _session_id(client)
    settings = replace(get_settings(), pdf_max_bytes=8)
    monkeypatch.setattr("app.main.settings", settings)
    response = _upload(client, session_id, b"%PDF-1.4\n123456")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("report.txt", "text/plain")],
)
def test_upload_rejects_unsupported_type(
    client: TestClient, filename: str, content_type: str
) -> None:
    response = _upload(client, _session_id(client), b"not a pdf", filename, content_type)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_multiple_inputs(client: TestClient) -> None:
    session_id = _session_id(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[
            ("file", ("report.pdf", _make_pdf(["text"]), "application/pdf")),
            ("extra", (None, "pasted text")),
        ],
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.parametrize(
    ("data", "expected_code"),
    [
        (b"", "EMPTY_PDF"),
        (b"%PDF-1.4\nmalformed", "INVALID_PDF"),
        (_encrypted_pdf(), "ENCRYPTED_PDF"),
        (_make_pdf([""]), "NO_EXTRACTABLE_TEXT"),
    ],
)
def test_upload_maps_invalid_pdf_categories(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    expected_code: str,
) -> None:
    if expected_code == "NO_EXTRACTABLE_TEXT":
        monkeypatch.setattr(document_service, "_ocr_image", lambda _image: "")
    response = _upload(client, _session_id(client), data)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected_code


def test_upload_maps_page_and_character_limits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = _session_id(client)
    settings = replace(get_settings(), pdf_max_pages=1)
    monkeypatch.setattr("app.main.settings", settings)
    page_response = _upload(client, session_id, _make_pdf(["one", "two"]))
    assert page_response.status_code == 422
    assert page_response.json()["error"]["code"] == "TOO_MANY_PAGES"

    settings = replace(settings, pdf_max_chars=5)
    monkeypatch.setattr("app.main.settings", settings)
    char_response = _upload(client, session_id, _make_pdf(["six chars"]))
    assert char_response.status_code == 422
    assert char_response.json()["error"]["code"] == "TEXT_TOO_LONG"


def test_upload_maps_extraction_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*_args, **_kwargs):
        raise ExtractionError("PDF processing exceeded the configured time limit.")

    monkeypatch.setattr("app.main.extract_upload", timeout)
    response = _upload(client, _session_id(client), _make_pdf(["text"]))

    assert response.status_code == 504
    assert response.json() == {
        "error": {
            "code": "PDF_EXTRACTION_TIMEOUT",
            "message": "PDF extraction exceeded the 15-second time limit.",
        }
    }


def test_unexpected_extraction_error_is_safe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args, **_kwargs):
        raise RuntimeError("secret document text and traceback")

    monkeypatch.setattr("app.main.extract_upload", broken)
    response = _upload(client, _session_id(client), _make_pdf(["text"]))

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "The document could not be processed."}
    }
    assert "secret document text" not in response.text
