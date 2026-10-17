"""Isolated pypdf worker used to enforce the parser timeout."""

from __future__ import annotations

from io import BytesIO
import json
import sys
from typing import Any


def _emit(code: str, text: str = "", page_count: int = 0, page_texts: list[str] | None = None) -> None:
    result: dict[str, Any] = {"code": code, "text": text, "page_count": page_count, "page_texts": page_texts or []}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode("ascii"))


def main() -> None:
    try:
        from pypdf import PdfReader

        max_pages = int(sys.argv[1])
        max_chars = int(sys.argv[2])
        reader = PdfReader(BytesIO(sys.stdin.buffer.read()), strict=True)
        if reader.is_encrypted:
            _emit("encrypted_pdf")
            return

        page_count = len(reader.pages)
        if page_count == 0:
            _emit("no_extractable_text")
            return
        if page_count > max_pages:
            _emit("too_many_pages", page_count=page_count)
            return

        page_texts: list[str] = []
        char_count = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            char_count += len(page_text) + (1 if page_texts else 0)
            if char_count > max_chars:
                _emit("text_too_long", page_count=page_count)
                return
            page_texts.append(page_text)

        text = "\n".join(page_texts)
        if not text.strip():
            _emit("no_extractable_text", page_count=page_count)
            return
        _emit("ok", text, page_count, page_texts)
    except Exception:
        # Parser errors can include document-derived data; only return a safe code.
        _emit("invalid_pdf")


if __name__ == "__main__":
    main()
