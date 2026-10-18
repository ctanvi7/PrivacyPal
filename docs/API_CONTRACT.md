# PrivacyPal API Contract — Draft

Status: Mixed contract. The numbered flow and examples are the earlier proposal; current conversation routes and current workflow routes are specified in the implemented sections below.
Version: MVP

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

The request body is optional for backward compatibility. When provided, it may contain `{ "conversation_id": "opaque-id" }` to attach the new session to an existing history record. Without it, the backend creates a new conversation and binds it to the session. The response includes `conversation_id` in addition to `session_id` and `expires_in_seconds`.

### Response — `201 Created`

```json
{
  "session_id": "opaque-random-id",
  "expires_in_seconds": 1800,
  "conversation_id": "opaque-conversation-id"
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

Provider destination disclosure is required before approval; whether the current UI fully provides it must be verified and is not claimed here. If delivery may have occurred but the result is unknown, the backend must report that uncertainty and must not silently retry.

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
- Current behavior: sessions and active workflows use temporary process-local state.
- Implemented: persist successful user questions and confirmed returned AI answers in local SQLite for up to 30 days per message. Detected high-risk credentials are not saved; failed, interrupted, and delivery-uncertain content is not persisted. Do not persist source documents, extracted text, findings, drafts, placeholder mappings, approval payloads, credentials, full provider requests, or failed/unreturned answers.
- Clearing an active session clears temporary state but leaves saved history unless the user explicitly requests history deletion. Conversation deletion must also clean associated active workflow and temporary document state.
- SQLite is not encrypted by default. Its planned location is the OS per-user application-data directory, outside the repository and temporary upload directory. Do not add application-managed backups. Local deletion cannot remove content already sent to an external provider. These storage, cleanup, and disclosure behaviors are not yet implemented.

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

## Conversation-history APIs

These endpoints provide local conversation history. They do not replace or alter the existing session, question, draft, acknowledgement, approval, or cancellation routes below.

**Implementation status:** `POST /api/v1/conversations`, `GET /api/v1/conversations`, `GET /api/v1/conversations/{conversation_id}`, and `DELETE /api/v1/conversations/{conversation_id}` are now implemented by the backend. Persistence remains local-only, is not encrypted by SQLite, and these routes do not restore active workflows. The create endpoint returns a new opaque conversation ID. List accepts optional `limit` (1–100, default 50) and `offset` (default 0) query parameters.

### List conversations

`GET /api/v1/conversations`

Returns non-expired conversations ordered by most recent activity as `{ "items": [...], "limit": 50, "offset": 0 }`. Each list item contains `conversation_id`, `created_at`, `updated_at`, and `preview` (up to 120 characters of the earliest retained user question, or `null`). It does not expose documents, drafts, findings, or provider payloads. Expired messages are removed individually after 30 days; later conversation activity does not extend their retention. Empty conversations expire after 30 days of inactivity.

### Retrieve a conversation

`GET /api/v1/conversations/{conversation_id}`

Returns one conversation and its retained messages in chronological order. Message fields are `message_id`, `role` (`user` or `assistant`), `content` (successful question or confirmed returned answer only), `created_at`, and `status`. Detected high-risk credentials are not saved. Failed, interrupted, and delivery-uncertain content is not persisted; no status-only record is currently written. This history is read-only and does not restore an active document, workflow, draft, approval, or session.

### Delete a conversation

`DELETE /api/v1/conversations/{conversation_id}`

Deletes the local conversation and messages, and clears any associated active in-memory workflow, document context, extracted text, mappings, and approval state. The current backend does not create document temp files. Returns `200 { "status": "deleted" }`, `404` if absent/expired, or `503 CONVERSATION_CLEANUP_INCOMPLETE` if active state was cleared but the SQLite deletion failed. Local host/origin protections apply; there is no account or multi-user authorization layer. Deletion cannot recall data already transmitted to an external provider.

The persistent schema is documented in DATABASE.md. SQLite history is not encrypted by default. A successful provider answer is returned even if the subsequent local history write fails; in that case the response includes `history_saved: false` and the chat should not claim persistence.

## Implemented workflow routes

The current FastAPI implementation uses these route names and fields (the proposal above remains useful as the behavioral contract):

- `POST /api/v1/sessions/{session_id}/questions` accepts optional `provider_id` (`default` or `sarvam`), binds that configured provider to the workflow, runs Gemma's ordered local tools, and returns `workflow_id`, `version`, the sanitized `draft`, safe `findings`, `residual_review`, and the selected provider name/endpoint/configuration status. It does not contact an answer provider.
- `PATCH /api/v1/sessions/{session_id}/workflows/{workflow_id}/draft` accepts `{ "version": 1, "draft": "..." }`, increments the version, clears acknowledgement, and reruns local checks, including Gemma's contextual review.
- `POST /api/v1/sessions/{session_id}/workflows/{workflow_id}/acknowledge` accepts the current version and records the user's acknowledgement of remaining non-blocking warnings.
- `POST /api/v1/sessions/{session_id}/workflows/{workflow_id}/approve` accepts the current version and optional `restore_placeholders`; the backend consumes approval before making one provider call and returns the answer in that response.
- `POST /api/v1/sessions/{session_id}/workflows/{workflow_id}/cancel` discards an unsent review.

The answer provider is configured through backend environment variables (`ANSWER_PROVIDER_NAME`, `ANSWER_PROVIDER_URL`, `ANSWER_PROVIDER_MODEL`, `ANSWER_PROVIDER_API_KEY`). The URL must use HTTPS. Its OpenAI-compatible adapter receives a fixed system instruction limiting answers to the approved content and forbidding invented personal/document details, plus one user message containing exactly the current approved draft. It does not receive source text, other chat history, or the placeholder mapping. Provider errors are not automatically retried; an ambiguous failure is reported as delivery-unknown.


### Outbound identity and answer-grounding checks

The current workflow scans labeled personal names, email/phone patterns, street addresses, and lease/reference identifiers in addition to the existing secret patterns. Known source identifiers are checked locally against the exact draft after editing and again before approval. Identity-seeking requests with unresolved or uncertain identifying context are returned as blocked reviews (`review_complete: false`); acknowledgement cannot authorize them. The user must edit and recheck, or cancel. Zero findings does not prove safety.

After provider delivery, the backend checks personal-looking answer details against the approved request before storing or returning the answer, and before any explicitly requested local placeholder restoration. If unsupported details are detected or this check fails, it withholds the entire answer, stores no answer text, consumes the approval with `send_state: "answer_withheld"`, and returns HTTP 502:

```json
{
  "error": {
    "code": "ANSWER_WITHHELD",
    "message": "The provider answer was withheld because its personal details could not be verified against the approved request. No automatic retry was made.",
    "retryable": false
  }
}
```

The frontend preserves the completed privacy review and shows an answer-withheld error without rendering the unverified answer. Retrying this approval is rejected. These conservative pattern and name-shape checks can miss details or flag benign text; they do not establish exhaustive detection or verify every document fact. The provider receives neither the local source comparison nor the placeholder mapping.


### Local semantic detection and per-step status

Gemma now sees the bounded source locally during `detect_sensitive_data` and may return `sensitive_spans`, an array of `{ "category": "person_name", "value": "exact source substring" }` proposals. The backend validates category, shape, count, length, and actual source occurrence (allowing PDF whitespace differences). Unknown values, malformed calls, and truncated responses fail closed. Verified model detections augment deterministic scanning; only backend code applies placeholders or omission. Values and source text are never added to the Groq payload or public detection metadata.

The final Gemma residual review receives only the current sanitized request, not source values from earlier tool history. Remaining identifying content can still block approval. A successful local check does not establish exhaustive detection.

Workflow responses include `local_checks` with `sensitive`, `relevant`, and `residual` statuses. These report completed work separately from the aggregate `review_complete` approval prerequisite. A blocked residual review can have completed detection and selection; the frontend must not label those successful steps as failed, and must still disable approval. Edits clear and recompute status.


If the final residual tool identifies exact `sensitive_spans` still in the draft, the backend validates and redacts them locally and permits exactly one fresh residual tool call. The changed draft is never treated as approved or clean merely because it was redacted. Missing, malformed, truncated, or unresolved second results remain unavailable or blocked, with no provider send. The local-analysis client timeout covers at most three bounded model calls (two normally, plus one residual recheck). Source spans are redacted before line-based relevance selection so multiline PDF values cannot be split into unmasked fragments.

Initial-review failures return HTTP 503 with `error.code = LOCAL_ANALYSIS_FAILED` and safe `error.local_checks` statuses (`sensitive`, `relevant`, `residual`: `completed`, `failed`, or `pending`). Completed checks stay completed in the UI; no workflow or partial findings are created for approval. Error messages identify detection, draft preparation, or residual review without exposing model output. The backend performs deterministic selection and draft construction after validated native detection, avoiding two empty-argument model round trips. Native final review remains mandatory.

Document overview requests such as "explain the attached document" select complete sentences in source order within the draft limit, including when generic words match only a heading. All selected content still passes local redaction and residual review. An empty context or an oversized sanitized draft fails preparation without creating an approvable workflow. `pages_used` reports pages contributing to the prepared context, tracked through redaction, rather than pages matching the model's initial keyword search. The provider is told that `Relevant context` contains extracted, privacy-filtered document text; it receives only the approved draft, never the attachment.

### Local inference round trips

The initial review now uses two model requests rather than three. Its first native `detect_sensitive_data` call requires both `terms` (1-8 bounded search terms) and `sensitive_spans`. The registry performs bound inspection, then validates and combines source spans with deterministic detection. All five internal operations still complete in order; the final residual audit remains a separate native call receiving only the sanitized draft. A single additional audit is permitted after verified redaction. Missing arguments, invalid source spans, repeated calls, and incomplete output still prevent approval. HTTP routes and review response fields are unchanged. The frontend allows 390 seconds for three bounded model calls plus orchestration.

Backend-only `OLLAMA_KEEP_ALIVE_SECONDS` defaults to 900. The launcher enables content-free adapter diagnostics: stage durations, model load/prompt/generation durations, and token counts. No raw model output or document content is logged. The original audit instructions and reasoning budget are retained.

### Merge integration: completed requests and history

Successful approval responses retain `history_saved` alongside the provider, pages, answer and consumed send state. Both credential scanning and answer grounding run before any restoration, response or history write. Withheld and uncertain answers are never saved. Completion releases source documents, semantic values, mappings and active review text; another question requires a new upload. Session creation returns a conversation ID and an HttpOnly ownership cookie. Session clear and conversation deletion invalidate pending analyses; a provider result already in flight cannot revive cleared state or create a new history entry. Groq model selection remains explicit, and process settings override `backend/.env`, including `PRIVACYPAL_DATABASE_PATH`.

### Sarvam language and speech integration

All routes remain behind the existing Origin/Host, session-ownership, and hosted-proxy checks. The subscription key stays on the backend. No caller can select an arbitrary remote host or provider model.

| Route | Request | Result |
| --- | --- | --- |
| `GET /api/v1/providers` | none | Configured provider `items` with safe ID/name/endpoint metadata |
| `POST /api/v1/sessions/{id}/questions` | existing fields plus optional `provider_id: "default"` or `"sarvam"` | Existing review response bound to the selected provider |
| `POST /api/v1/sessions/{id}/workflows/{workflow}/translate-draft` | `{version, source_language, target_language, consent: true}` | `{workflow_id, version, translated_text, target_language, provider}` preview |
| `POST /api/v1/sessions/{id}/speech/transcribe` | multipart `file` and `consent=true` | `{transcript, review_required: true}`; never submits a question |
| `POST /api/v1/sessions/{id}/translate-answer` | `{text, source_language, target_language, consent: true}` | `{translated_text, target_language}` |
| `POST /api/v1/sessions/{id}/speech/synthesize` | `{text, language, consent: true}` | `{audio_base64, content_type: "audio/wav"}` |

Draft translation reads only the server-held current reviewed text. It repeats deterministic and source-identity checks before sending; unresolved warnings must first be acknowledged. Editing, approval, and duplicate draft translation cannot proceed while that translation is in flight. A cleared or replaced session/review invalidates the returned preview. Applying a translation uses the existing versioned draft PATCH route and repeats local checks; translation itself grants no approval.

The provider ID is bound to the workflow, so changing client fields at approval cannot redirect a reviewed request. Sarvam chat receives the same fixed grounding instructions and exact approved user message as the existing provider. The existing one-use approval, no automatic retry, answer scan/grounding, and history rules apply.

Only a SHA-256 digest of the successfully displayed answer is retained in active session state for subsequent language actions; its text must match exactly. The digest is invalidated on a new document/question, clear, expiry, or failure. Historical answers are not automatically authorized for resending. Translations and audio are temporary and are not added to persisted conversation history. Both translated output and provider answers are treated as untrusted text.

Sarvam response bodies are bounded during streaming. Translation protects placeholder markers and rejects missing, duplicated, invented, or corrupted markers. TTS explicitly requests WAV and rejects invalid base64 or non-WAV output. The protected AWS gateway permits at most 5 MiB for the speech-response JSON, below its 6 MiB Lambda response envelope; other routes retain the 512 KiB limit. Audio uploads retain the gateway's existing 4 MiB limit.
