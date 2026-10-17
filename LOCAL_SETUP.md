# Run the local document flow

PrivacyPal currently implements document upload or pasted text, local extraction/OCR, and local Gemma analysis through Ollama. Sensitive-data minimization, review/approval, and an external answer provider are not part of this implementation yet.

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

The first Gemma request must return Ollama's native `inspect_document` tool-call structure. The backend validates its tool name and arguments and returns only bounded matching passages to a second local Gemma call. It rejects text that merely imitates a tool call.
