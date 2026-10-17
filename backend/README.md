# PrivacyPal backend

This backend provides a loopback-only FastAPI service for document input, local extraction/OCR, Gemma-guided local privacy checks, sanitized-request review and approval, and an optional OpenAI-compatible answer provider. No provider request is made before the user approves the exact reviewed draft.

PDF parsing uses `pypdf` in an isolated worker. Scanned PDF pages and PNG, JPEG, and WebP images use local Tesseract OCR. Gemma uses Ollama's native tool-call API to run bounded document inspection, deterministic sensitive-data checks, question-aware selection, draft construction, and residual-risk review. Initial limits are 10 MiB per upload, 25 PDF pages, 25,000 extracted characters, and a 15-second PDF parsing timeout. Encrypted, malformed, oversized, and unreadable documents are rejected.

## Local setup

From the repository root, create and activate a virtual environment, then install the backend and development dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
```

Set `APP_HOST` to a loopback IP address and `APP_PORT` to an available port if the defaults are unsuitable. The application reads environment variables directly and does not load a `.env` file. `backend/.env.example` documents the current settings; export the desired values in your shell before starting the app. Local `.env` files are ignored by Git.

To enable external answers, set `ANSWER_PROVIDER_NAME`, `ANSWER_PROVIDER_URL` (an HTTPS OpenAI-compatible `/chat/completions` endpoint), `ANSWER_PROVIDER_MODEL`, and `ANSWER_PROVIDER_API_KEY` in the backend environment. Keep the key out of source control and do not share it in chat. Without all four settings, local analysis and review work, but sending remains disabled. The provider receives one user message containing only the exact approved sanitized draft; it does not receive the original document, chat history, or placeholder mapping. Requests are not retried automatically.

## Run locally

From the repository root:

```powershell
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8000"
python backend/run.py
```

The launcher validates `APP_HOST` and only accepts a loopback IP address, then binds Uvicorn to the validated `APP_HOST` and `APP_PORT`. The frontend and Ollama must be running locally. The health endpoint is `http://127.0.0.1:8000/health` and returns `{"status":"ok"}`.
