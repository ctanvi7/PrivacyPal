# PrivacyPal backend

This backend provides a local FastAPI health endpoint and an independently testable service for extracting text from text-based PDFs. API routes, OCR, Gemma, and answer-provider integration are not implemented yet.

The PDF service uses `pypdf` locally. Initial limits follow `SECURITY.md`: 10 MiB per PDF, 25 pages, 25,000 extracted characters, and a 15-second parsing timeout. These values can be configured with `PDF_MAX_BYTES`, `PDF_MAX_PAGES`, `PDF_MAX_CHARS`, and `PDF_TIMEOUT_SECONDS`. Encrypted, malformed, oversized, and text-empty PDFs are rejected; this service does not perform OCR.

## Local setup

From the repository root, create and activate a virtual environment, then install the backend and development dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
```

Set `APP_HOST` to a loopback IP address and `APP_PORT` to an available port if the defaults are unsuitable. The application reads environment variables directly and does not load a `.env` file. `.env.example` documents the current settings; export the desired values in your shell before starting the app. Local `.env` files are ignored by Git.

## Run locally

From the repository root:

```powershell
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8000"
python backend/run.py
```

The launcher validates `APP_HOST` and only accepts a loopback IP address, then binds Uvicorn to the validated `APP_HOST` and `APP_PORT`. Do not bypass this launcher with a separate Uvicorn `--host` override. Then request `http://127.0.0.1:8000/health`; the response is `{"status":"ok"}`.

## Test

From the repository root:

```powershell
python -m pytest backend/tests -q -p no:cacheprovider
```
