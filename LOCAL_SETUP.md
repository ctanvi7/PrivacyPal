# Run the local document flow

PrivacyPal supports document upload or pasted text, local extraction/OCR, Gemma-guided local privacy checks, a sanitized-request review and approval gate, and an optional OpenAI-compatible answer provider. No external request is made until the current draft passes required checks and the user approves it.

## Requirements

For the optional fully hosted AWS CPU demo, deployment, login, and shutdown
instructions are in [deploy/aws/README.md](deploy/aws/README.md). That mode
processes uploaded documents in AWS and limits uploads to 4 MiB.

- Python 3.11 or newer.
- Node.js 20 or newer with npm.
- Ollama installed and running, with `gemma4:e4b` pulled.
- Tesseract installed and on PATH for images and scanned PDF pages. Pasted text and text PDFs do not require Tesseract.

## Windows PowerShell

In the first PowerShell window, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8000"
$env:FRONTEND_ORIGIN = "http://127.0.0.1:5173"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:GEMMA_MODEL = "gemma4:e4b"
# Create the backend-only local settings file once, then edit it privately.
# Skip this copy if backend/.env already exists.
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
# In backend/.env, fill ANSWER_PROVIDER_MODEL with your chosen Groq model ID
# and ANSWER_PROVIDER_API_KEY (or GROQ_API_KEY) with your private key.
python backend/run.py
```

In a second PowerShell window, also from the repository root:

```powershell
cd .\frontend
npm install
npm run dev
```

Open the local address Vite prints. Both `http://127.0.0.1:5173` and `http://localhost:5173` are supported.

## Input limits

- Pasted text: 25,000 characters.
- PDF: 10 MiB, at most 25 pages, and 25,000 extracted characters.
- PNG, JPEG, and WebP: 10 MiB and at most 8,000 pixels per dimension.
- Encrypted, unreadable, unsupported, empty, or over-limit documents stop with an error. There is no cloud extraction or OCR fallback.
- Documents and extracted text stay in temporary in-memory sessions. Sessions expire after 30 minutes idle, when cleared, or when the backend stops.

Gemma normally makes two native, allowlisted local tool calls: combined inspection/sensitive-data detection, then a separate residual review. The detection call supplies bounded search terms and verified source-span proposals; the backend performs both operations in order before deterministic relevance selection and sanitization. Any missing, malformed, repeated, or out-of-order call fails closed. The review screen shows the exact draft and configured destination. Editing the draft increments its version, clears acknowledgement, and re-runs local deterministic and Gemma checks. Remaining warnings require explicit acknowledgement. High-risk patterns block approval. Approval is consumed before the provider call and cannot be replayed; ambiguous provider failures are not retried.

The backend loads `backend/.env` regardless of the working directory; process environment values override file values. Keep keys backend-only, never in `VITE_*` variables. `ANSWER_PROVIDER_API_KEY` takes precedence over `GROQ_API_KEY` within the same source; either process key overrides file credentials. Restart the backend after changing settings, then run a new local review. No Groq model is assumed: set `ANSWER_PROVIDER_MODEL` explicitly. Missing URL, model, or key keeps approval disabled.

The default provider is Groq at `https://api.groq.com/openai/v1`. The adapter appends `/chat/completions` to base URLs and also accepts an existing full endpoint. The provider URL must use HTTPS. The provider name and endpoint are shown before approval. The adapter sends fixed grounding instructions plus one user message containing only the approved sanitized draft and does not send source text or placeholder mappings. Placeholder restoration, if selected, happens locally on the returned answer.


Answer grounding: the provider is instructed to use only the approved draft, keep placeholders, and omit unavailable personal/document facts. Local checks recheck known source identifiers before sending and withhold returned answers containing unapproved personal-looking details. A withheld answer consumes approval and is not retried. Blocked or uncertain identity reviews require editing/rechecking or cancellation. Detection is conservative and not exhaustive; ordinary factual hallucinations are not fully verified.

Generic questions such as "explain this please", "Can you explain this?", and
"Please summarize" refer to the document already attached to the session.
They select bounded complete source sentences and still run masking and the
independent residual review. Questions containing a specific topic continue to
select matching passages; unrelated questions do not fall back to the full
document. A failed review displays incomplete status and cannot enable approval.

Only one complete Gemma workflow may run at a time in the backend process,
including edited-draft checks. Additional questions receive a retryable
`429 MODEL_BUSY` with all checks still pending, rather than waiting inside
Ollama until their request timeout. Capacity is released on completion, errors,
and cancellation. Run the session backend as a single worker.

Local inference keeps the configured Gemma model loaded for 900 seconds after each request, reducing reloads between questions. Set `OLLAMA_KEEP_ALIVE_SECONDS` in `backend/.env` to a positive number to change that duration. This controls local model residency, not conversation history or approval. The final audit retains its reasoning budget and source isolation. Backend logs contain stage timing and aggregate token counts, never prompts, source values, responses, or reasoning.

For an optional local performance check with synthetic data only, run `python backend/scripts/benchmark_local_inference.py`. Add `--audit` to check masked content, exposed identity values, contextual identity clues, and embedded instructions. `--baseline backups/<your-backup>.zip` runs the archived adapter/registry from a trusted local source backup without overwriting working files. These checks contact only local Ollama and never invoke the answer provider; normal automated tests use mocks. Timings depend on CPU load, prompt caching, and whether model weights are already loaded.

In the local Gemma smoke check, masked content and an exposed name were handled correctly, but the unchanged final audit missed the `contextual_clue` fixture about a person being the only member of a particular role. `--audit` deliberately exits nonzero on that miss. This is a model detection limitation; fewer model requests do not establish exhaustive privacy detection.
