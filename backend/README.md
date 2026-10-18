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

Set `APP_HOST` to a loopback IP address and `APP_PORT` to an available port if the defaults are unsuitable. Copy `backend/.env.example` to `backend/.env` once and edit it privately. The backend loads that file regardless of the launch working directory; process environment values take precedence. Local `.env` files are already ignored by Git. Restart the backend after changes and start a new review.

The default answer provider is Groq, with base URL `https://api.groq.com/openai/v1`. Set `ANSWER_PROVIDER_MODEL` to your chosen Groq model ID (no default model is assumed) and `ANSWER_PROVIDER_API_KEY`, or its fallback `GROQ_API_KEY`. Within the same source, the primary key wins; either process key overrides file credentials. Keep keys backend-only, out of `VITE_*` variables, source control, logs, and chat. Missing URL, model, or key leaves local analysis available and approval disabled. Invalid provider URLs fail startup safely.

`ANSWER_PROVIDER_URL` accepts an HTTPS base URL or full `/chat/completions` endpoint; the adapter appends `/chat/completions` when needed. `ANSWER_PROVIDER_NAME` controls the name shown during review. The provider receives fixed grounding instructions plus one user message containing only the exact approved sanitized draft; it does not receive the original document, chat history, or placeholder mapping. Requests are not retried automatically.

## Run locally

From the repository root:

```powershell
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8000"
python backend/run.py
```

The launcher validates `APP_HOST` and only accepts a loopback IP address, then binds Uvicorn to the validated `APP_HOST` and `APP_PORT`. The frontend and Ollama must be running locally. The health endpoint is `http://127.0.0.1:8000/health` and returns `{"status":"ok"}`.


Answer grounding: the provider is instructed to use only the approved draft, keep placeholders, and omit unavailable personal/document facts. Local checks recheck known source identifiers before sending and withhold returned answers containing unapproved personal-looking details. A withheld answer consumes approval and is not retried. Blocked or uncertain identity reviews require editing/rechecking or cancellation. Detection is conservative and not exhaustive; ordinary factual hallucinations are not fully verified.


Gemma detection includes validated semantic source spans in addition to deterministic patterns, including table layouts where labels and values are extracted on separate lines. Gemma's exact source-value proposals are validated locally before placeholder replacement. Its final residual review is isolated to the sanitized draft. The UI reports individual completed checks independently from approval-blocking residual results. Restart the backend and submit a new question after updating this code; existing reviews are not reprocessed automatically.

Remaining verified draft spans may be automatically redacted once, followed by a fresh bounded residual review. Unresolved or malformed rechecks stay blocked. Automatic redaction does not grant approval; users still review and approve the final draft.

Local review normally uses two native Gemma calls: combined inspection/detection, followed by an independent residual review. The first call must supply both bounded search terms and exact sensitive-span proposals; the backend validates them and executes inspection and detection in order. It then runs deterministic selection and draft construction. One additional residual check is permitted after verified redaction. Tool generation uses temperature zero. Thinking is disabled for detection and enabled with a bounded output budget for the final contextual audit. Model reasoning is discarded and never logged or returned; invalid or incomplete responses still fail closed. Error responses preserve confirmed per-stage progress. Diagnostic logs contain stage names, elapsed milliseconds, aggregate runtime/token counters, and exception types. CPU-only inference latency depends on document length and machine load.

`OLLAMA_KEEP_ALIVE_SECONDS` defaults to 900, keeping model weights loaded between requests to reduce cold starts. It is backend-only and must be positive. `python backend/scripts/benchmark_local_inference.py` runs an opt-in synthetic local review and prints timing counters without document or model content. `--audit` additionally checks synthetic privacy cases. Neither mode calls an external answer provider.
