# PrivacyPal backend

This backend provides a loopback-only FastAPI service with in-memory sessions for PDF, PNG, JPEG, WebP, and pasted-text input. It performs document extraction and OCR locally, and uses Gemma through Ollama for local privacy analysis and sanitization. Users can review and edit the sanitized request before approval; only the exact approved draft is sent to a configured OpenAI-compatible answer provider. Source documents are not sent to that provider.

PDF parsing uses `pypdf` in an isolated worker. Scanned PDF pages and PNG, JPEG, and WebP images use local Tesseract OCR. Gemma uses Ollama's native tool-call API to run bounded document inspection, deterministic sensitive-data checks, question-aware selection, draft construction, and residual-risk review. Initial limits are 10 MiB per upload, 25 PDF pages, 25,000 extracted characters, and a 15-second PDF parsing timeout. Encrypted, malformed, oversized, and unreadable documents are rejected.

## Local setup

From the repository root, create and activate a virtual environment, then install the backend and development dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
```

Set `APP_HOST` to a loopback IP address and `APP_PORT` to an available port if the defaults are unsuitable. The application reads environment variables directly and does not load a `.env` file. `backend/.env.example` documents the current settings; export the desired values in your shell before starting the app. Local `.env` files are ignored by Git.

To enable Groq answers, set `GROQ_API_KEY` in the same PowerShell window before starting the backend. When set, PrivacyPal defaults to Groq's OpenAI-compatible chat-completions endpoint and the `openai/gpt-oss-120b` model. You can override the defaults with `ANSWER_PROVIDER_NAME`, `ANSWER_PROVIDER_URL`, `ANSWER_PROVIDER_MODEL`, and `ANSWER_PROVIDER_API_KEY`. Alternatively, configure those four variables for another HTTPS OpenAI-compatible provider. Keep API keys out of source control and do not share them in chat. Without a complete provider configuration, local analysis and review work, but sending remains disabled. The provider receives one user message containing only the exact approved sanitized draft; it does not receive the original document, chat history, or placeholder mapping. Requests are not retried automatically.

For a hidden-key PowerShell prompt, run these commands in the window you will use to start the backend:

```powershell
$secureGroqKey = Read-Host "Groq API key" -AsSecureString
$env:GROQ_API_KEY = [System.Net.NetworkCredential]::new("", $secureGroqKey).Password
python backend/run.py
```

After stopping the backend, remove the key from that PowerShell process with `Remove-Item Env:GROQ_API_KEY`. The application reads environment variables directly and does not load `.env` files automatically.

## Run locally

From the repository root:

```powershell
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8000"
python backend/run.py
```

The launcher validates `APP_HOST` and only accepts a loopback IP address, then binds Uvicorn to the validated `APP_HOST` and `APP_PORT`. The frontend and Ollama must be running locally. The health endpoint is `http://127.0.0.1:8000/health` and returns `{"status":"ok"}`.
