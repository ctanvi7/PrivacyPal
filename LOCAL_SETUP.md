# Run the local document flow

PrivacyPal supports document upload or pasted text, local extraction/OCR, Gemma-guided local privacy checks, a sanitized-request review and approval gate, and selectable configured answer providers including optional Sarvam. Sarvam translation and speech features are separate opt-in actions. No answer request is made until the current draft passes required checks and the user approves it.

## Requirements

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
# Optional: configure an OpenAI-compatible answer service before launching the backend.
# Keep the API key private; never commit it or paste it into chat.
$env:ANSWER_PROVIDER_NAME = "Your chosen provider"
$env:ANSWER_PROVIDER_URL = "https://provider.example/v1/chat/completions"
$env:ANSWER_PROVIDER_MODEL = "your-model-name"
$env:ANSWER_PROVIDER_API_KEY = "your-private-key"
# Optional: expose Sarvam as another answer provider and enable its language tools.
# Enter the key at the hidden prompt; never paste it into a saved command or source file.
$secureSarvamKey = Read-Host "Sarvam API key" -AsSecureString
$env:SARVAM_API_KEY = [System.Net.NetworkCredential]::new("", $secureSarvamKey).Password
python backend/run.py
```

In a second PowerShell window, also from the repository root:

```powershell
cd .\frontend
npm install
npm run dev
```

Open the local address Vite prints, normally `http://127.0.0.1:5173`.

## Input limits

- Pasted text: 25,000 characters.
- PDF: 10 MiB, at most 25 pages, and 25,000 extracted characters.
- PNG, JPEG, and WebP: 10 MiB and at most 8,000 pixels per dimension.
- Encrypted, unreadable, unsupported, empty, or over-limit documents stop with an error. There is no cloud extraction or OCR fallback.
- Documents and extracted text stay in temporary in-memory sessions. Sessions expire after 30 minutes idle, when cleared, or when the backend stops.

Gemma runs a sequence of five native, allowlisted local tool calls for inspection, sensitive-data checks, relevance selection, sanitization, and residual review. Any missing, malformed, repeated, or out-of-order call fails closed. The review screen shows the exact draft and configured destination. Editing the draft increments its version, clears acknowledgement, and re-runs local deterministic and Gemma checks. Remaining warnings require explicit acknowledgement. High-risk patterns block approval. Approval is consumed before the provider call and cannot be replayed; ambiguous provider failures are not retried.

The provider URL must use HTTPS. The provider name and endpoint are shown before approval. The adapter sends one user message containing only the approved sanitized draft and does not send source text or placeholder mappings. Placeholder restoration, if selected, happens locally on the returned answer.

Sarvam can be selected as the answer provider when `SARVAM_API_KEY` is configured. Translation sends only the reviewed request or the displayed answer after a separate consent action. A translated request is only a preview until you choose to use it; that choice updates the draft and reruns the privacy checks. Masked placeholders must remain unchanged. Speech-to-text sends selected audio only after consent and returns a transcript for review; it never submits the transcript automatically. Text-to-speech sends the displayed answer only after a separate consent action. Sarvam Vision is not enabled: documents and OCR remain local.
