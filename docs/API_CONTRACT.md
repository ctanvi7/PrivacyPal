# PrivacyPal API Contract — Draft

Status: Proposal for team review
Version: MVP draft

## Purpose

This contract defines how the frontend communicates with the local backend for the document-to-answer flow.

The backend owns document processing, Gemma calls, privacy checks, workflow state, and approval. The frontend displays results and collects user actions. It must not call Gemma or the answer provider directly.

## MVP flow

1. Create a temporary session.
2. Upload a supported document or provide pasted text.
3. Ask a question about the document.
4. Receive Gemma’s proposed minimized request and privacy findings.
5. Review and, optionally, edit the proposed request.
6. Approve the current version.
7. Receive the answer in the chat.

Initial implementation can use synchronous requests. Add polling or streaming only if actual processing time makes it necessary.

---

## 1. Create a session

`POST /api/v1/sessions`

Creates temporary state for one user’s local app session.

### Response — `201 Created`

```json
{
  "session_id": "opaque-random-id",
  "expires_in_seconds": 1800
}
```

## 2. Upload a PDF

`POST /api/v1/sessions/{session_id}/documents`

Accepts one text-based PDF per request. Pasted text, scanned PDFs, and images are out of scope for this milestone. PDF text is extracted locally with pypdf; OCR is not performed.

### Request — file

`multipart/form-data` with a `file` part containing the source document.

PDF limits are 10 MiB, 25 pages, 25,000 extracted characters, and 15 seconds for extraction. Encrypted, malformed, empty, and text-empty PDFs are rejected.

### Response — `201 Created`

```json
{
  "document_id": "opaque-document-id",
  "source_type": "pdf",
  "status": "ready",
  "page_count": 1,
  "extracted_character_count": 42
}
```

The backend keeps extracted text in in-memory session state. The API does not return extracted document contents. The original file is processed in memory and is not persisted.

## 3. Ask a question and prepare a draft

`POST /api/v1/sessions/{session_id}/requests`

Starts local analysis of the selected document and returns Gemma's proposed minimized request and privacy review. This draft contract uses a synchronous response; the team may revisit that choice if measured processing times require polling or streaming.

### Request

```json
{
  "document_id": "opaque-document-id",
  "question": "What monthly expenses are listed?"
}
```

### Response — `201 Created`

```json
{
  "request_id": "opaque-request-id",
  "status": "awaiting_review",
  "draft_version": 1,
  "proposed_request": "Summarize the listed monthly expenses: rent, utilities, and transport.",
  "findings": [
    {
      "category": "personal_identifier",
      "action": "masked",
      "description": "A personal identifier was replaced."
    }
  ],
  "risk_flags": [
    {
      "code": "residual_identity_risk",
      "severity": "review",
      "description": "Some remaining details may identify the person."
    }
  ],
  "privacy_check": "passed"
}
```

Finding details and risk flags must not expose unnecessary raw sensitive values. A failed or inconclusive required check must return an error and must not create an approvable draft.

## 4. Edit a draft and rerun privacy checks

`PATCH /api/v1/sessions/{session_id}/requests/{request_id}`

Edits the proposed outbound text. The client supplies the version it reviewed. The backend rejects stale versions, increments the version for an accepted edit, invalidates all previous review/approval state, and reruns required privacy checks before returning the updated draft.

### Request

```json
{
  "expected_draft_version": 1,
  "proposed_request": "Summarize the monthly expenses without identifying details."
}
```

### Response — `200 OK`

```json
{
  "request_id": "opaque-request-id",
  "status": "awaiting_review",
  "draft_version": 2,
  "proposed_request": "Summarize the monthly expenses without identifying details.",
  "findings": [],
  "risk_flags": [],
  "privacy_check": "passed"
}
```

The response is not approval. A failed check leaves the request blocked from approval.

## 5. Approve the current draft and receive an answer

`POST /api/v1/sessions/{session_id}/requests/{request_id}/approve`

Explicitly approves the current reviewed version. The backend verifies the active session, exact current draft version, provider configuration, and passing required privacy checks. It sends only the current approved draft to the configured answer model. Approval is single-use; a stale version, changed draft, failed check, or repeated approval must not trigger another provider call.

### Request

```json
{
  "draft_version": 2,
  "approved": true
}
```

### Response — `200 OK`

```json
{
  "request_id": "opaque-request-id",
  "status": "completed",
  "draft_version": 2,
  "answer": "The listed monthly expenses are rent, utilities, and transport."
}
```

Provider destination disclosure must be available to the user before approval. Its exact response fields and whether approval returns synchronously remain open for team review. If delivery may have occurred but the result is unknown, the backend must report that uncertainty and must not silently retry.

## 6. Consistent error response

Errors from the session creation and PDF upload endpoints use this shape. Other endpoint status mappings remain for team review.

```json
{
  "error": {
    "code": "UNKNOWN_SESSION",
    "message": "The session was not found or has expired."
  }
}
```

Session and PDF upload error mappings:

| Status | Code | Meaning |
|---|---|---|
| 404 | `UNKNOWN_SESSION` | Session does not exist or has expired |
| 413 | `FILE_TOO_LARGE` | PDF exceeds 10 MiB |
| 415 | `UNSUPPORTED_FILE_TYPE` | Request is not exactly one PDF file part with a `.pdf` filename and PDF content type |
| 422 | `EMPTY_PDF` | No file was supplied or the file is empty |
| 422 | `INVALID_PDF` | PDF is malformed or unreadable |
| 422 | `ENCRYPTED_PDF` | PDF is encrypted or password-protected |
| 422 | `NO_EXTRACTABLE_TEXT` | PDF contains no extractable text |
| 422 | `TOO_MANY_PAGES` | PDF exceeds 25 pages |
| 422 | `TEXT_TOO_LONG` | Extracted text exceeds 25,000 characters |
| 504 | `PDF_EXTRACTION_TIMEOUT` | Extraction exceeds 15 seconds |
| 500 | `INTERNAL_ERROR` | Unexpected processing error |

All messages must be safe for display and must not include stack traces, document text, credentials, prompts, or provider response bodies. Unexpected errors return no exception details.

## Privacy and approval rules

- Source documents and full extracted text stay local and are never sent to the answer model.
- The backend owns validation, workflow state, privacy checks, session binding, and approval enforcement. Frontend state and model proposals are not authorization.
- Editing a draft invalidates its previous privacy review and any approval. Required checks run again against the edited version.
- The backend sends only the current draft version that passed required checks and the user explicitly approved. It must reject stale versions and consume approval at most once.
- High-risk secrets remain blocked from outbound content, even if a model proposes retaining them or the user edits the draft.
- Never log document contents, extracted text, prompts, findings with raw values, sanitized request bodies, answers, credentials, or placeholder mappings.
- Use temporary session state. Do not add persistent document or conversation storage through this API contract.

## Runtime AI requirement

The pitch flow must use live Gemma inference with real tool calls and a real configured answer-model API after approval. Canned responses and silent mock fallbacks are not allowed in the pitch flow. Test mocks are allowed; they must be explicit test configuration. Missing or failed live runtime configuration must produce a visible error and must never silently switch to a canned response or mock.

## Decisions for Members 1 and 2 to review

This document is a proposal, not an agreed implementation contract. Members 1 and 2 should review and decide:

- Pasted-text limits and OCR support beyond the text-based PDF upload milestone.
- Whether endpoints run synchronously or need polling/streaming based on measured model latency.
- Session transport and protection details, including cookie/token handling and CSRF/origin checks.
- Exact finding and risk-flag categories, severity values, and which risks block approval versus require user review.
- Provider/model selection, user-visible destination details, provider payload shape, credential configuration, and provider-specific response handling.
- HTTP status mappings, error codes, and retryability semantics for endpoints beyond session creation and PDF upload, especially provider timeout or uncertain delivery.
- Whether optional features such as placeholder restoration and source references are in scope and how they fit the API.
