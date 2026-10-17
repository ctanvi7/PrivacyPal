# PrivacyPal Database and Session Data Design

## 1. Purpose and decision

This document defines how the MVP stores and clears application data. It accompanies ARCHITECTURE.md, SECURITY.md, the product requirements, and design.md.

**Current implementation:** a persistent SQLite database stores approved conversation history. Active session and workflow state remains process-local and is lost on backend restart.

**Implemented:** use local SQLite for conversation history only. Persist user questions and returned AI answers for no more than 30 days. Do not add cloud storage, analytics, or application-managed backups. The SQLite file belongs in the operating system per-user application-data directory, outside the repository and temporary upload directory. SQLite is not encrypted by default; no encryption is implemented.

## 2. Data-flow and retention rule

The browser, FastAPI backend, Ollama/Gemma, document extraction, and OCR run on the same user's computer in the MVP. Original files, extracted text, findings, drafts, placeholder mappings, and active approval state stay in memory or restrictive temporary storage; none belong in SQLite. Only the exact sanitized request explicitly approved by the user may be sent to the configured external answer provider. Conversation history is implemented in local SQLite, subject to the successful-answer and retention rules below.

Provider-side retention is outside PrivacyPal's control. The UI must say which provider receives the approved request and must not promise that clearing a local session deletes content already sent externally.

| Data | MVP location | Retention |
|---|---|---|
| Original upload bytes | Request memory or restrictive temporary file | Only while extracting/processing; delete on all exits |
| Pasted source text | In-memory session | Until workflow completion, clear, expiry, or process exit |
| Extracted/OCR text and page references | In-memory session | Until workflow completion, clear, expiry, or process exit |
| User question | Local SQLite conversation history, stored only with a successfully returned answer | Up to 30 days; failed requests do not retain sensitive question content |
| Sensitive findings and raw matched values | In-memory workflow state | Until workflow completion, clear, expiry, or process exit |
| Placeholder-to-original mapping | In-memory workflow state only | Until clear, expiry, or process exit |
| Sanitized draft and privacy result | In-memory workflow state | Until completed, cancelled, clear, expiry, or process exit |
| Approval state and draft fingerprint | In-memory workflow state | One workflow version; discard after use, cancel, clear, expiry, or process exit |
| Returned AI answer | Local SQLite conversation history only after a confirmed returned answer | Up to 30 days; never persist a failed/unreturned answer |
| Provider API key and credentials | Backend environment/configuration only | Never persisted in application data |
| Operational logs | Local logs, if enabled | Minimum necessary; no content or secrets |

Use a finite idle timeout for active sessions. Current default: expire a session after 30 minutes without activity. Enforce expiry on the backend before every sensitive operation, not only in the browser. Process restart discards active in-memory sessions and workflows; it does not erase separately persisted conversation history. History retention is an absolute maximum of 30 days per message, independent of session idle expiry.

Temporary file handling:
- Use a dedicated temporary directory with restrictive permissions.
- Generate random filenames; never use an uploaded filename as a path.
- Do not serve the temporary directory over HTTP.
- Delete temp files in cleanup paths for success, failure, cancellation, and session clear.
- At startup, clean stale app-owned temp files left by a crash, without traversing arbitrary user directories.
- Do not promise forensic erasure from SSDs, swap, backups, or OS caches.

## 3. Runtime data model

These are temporary Python objects, not database tables. Use explicit typed models and avoid serializing an entire session object.

### Session

Fields:
- session_id: cryptographically random opaque identifier.
- created_at and last_activity_at: timestamps.
- expires_at: server-enforced expiration.
- status: ACTIVE, CLEARING, or EXPIRED.
- workflows: only identifiers/references to active workflow state.

Do not encode a name, email, filename, or other personal value in session_id. Bind each API operation to the session stored in the HttpOnly cookie and verify the requested session matches it.

### DocumentContext

Fields:
- document_id and session_id: random identifiers.
- source_type: pasted_text, text_pdf, scanned_pdf, png, jpeg, or webp.
- display_name: optional UI-only filename; treat it as untrusted and do not log it.
- extracted_text: temporary text used for analysis.
- page/region references and extraction_status: temporary metadata.
- created_at: timestamp.

Do not persist original bytes, extracted text, or document metadata in SQLite.

### WorkflowRun

Fields:
- workflow_run_id, session_id, and optional document_id.
- question reference and status.
- draft_version: incremented whenever question, source, provider, privacy decision, or sanitized text changes.
- findings, privacy review, sanitized draft, approval state, and transient provider result.
- created_at, updated_at, and safe error_code.

Each run is isolated. A new workflow cannot inherit approval from an earlier workflow.

### DetectionFinding

Fields:
- finding_id and workflow_run_id.
- category and risk_level.
- proposed_action: KEEP, MASK, REMOVE, or BLOCK.
- source location and safe display label.
- raw matched value only when algorithmically necessary, in memory only.

Never persist or log raw finding values. Show a minimally revealing summary in the UI.

### PlaceholderMapping

Fields:
- workflow_run_id.
- placeholder token and original value.
- category.

Mappings are reversible sensitive data. Keep them in memory only, never send them to Gemma after minimization unless strictly necessary for local analysis, and never send them to the external provider. Restore only exact placeholders and only when the user enabled restoration.

### SanitizedDraft and PrivacyReview

Fields:
- draft_version and exact sanitized_text, in memory only.
- selected provider identifier and relevant request options.
- review status: PENDING, PASSED, or FAILED.
- safe findings summary and blocking count.
- reviewed_at.

Any change to content, provider, source selection, or relevant privacy decisions invalidates the review and increments the draft version.

### ApprovalRecord

Fields:
- random approval_id.
- session_id and workflow_run_id.
- draft_version and a short-lived fingerprint of the canonical outbound payload.
- status: APPROVED, CONSUMED, CANCELLED, or EXPIRED.
- approved_at and expires_at.

Approval is valid only when it matches the current session, current workflow, current draft version, current provider, and a passing current privacy review with no blocking secret. Consume it once. A fingerprint is a consistency check, not encryption or proof of safety; keep it only as long as needed and do not log it.

### ProviderResult

Fields:
- provider identifier, safe status, timestamps, safe error code.
- answer text and validated source references in memory only.

Do not persist provider request bodies or raw provider response bodies as operational records. A successfully returned answer may be saved as conversation history under the planned history policy. Provider-side retention is outside PrivacyPal's control.

## 4. Approval and concurrency

The in-memory implementation still needs atomic behavior. Use a per-workflow lock or equivalent so an edit, clear, expiry, or second approval cannot race a provider call.

Immediately before sending, the backend must:
1. Confirm the session is active and owns the workflow.
2. Confirm workflow state is AWAITING_USER_REVIEW.
3. Confirm the current draft version and provider match the reviewed version.
4. Confirm the privacy review passed and no blocking secret remains.
5. Confirm the approval is valid, unexpired, and unused.
6. Mark approval consumed atomically.
7. Send only the payload associated with that approval.

Double-clicking Approve must cause at most one provider request. Editing invalidates the approval. A timeout after possible transmission must be shown as DELIVERY_STATUS_UNKNOWN; do not blindly resend.

Clear Session must set the session to CLEARING before removing data, reject new work, invalidate approvals, cancel work that has not entered the provider call, clear all associated state, delete temporary files, and then remove the session. If a provider request has already started, explain that clearing local state cannot recall it.

## 5. Logging and diagnostics

Permitted fields: random correlation ID, workflow stage, duration, safe error code, tool name/status, coarse file type/size bucket, and aggregate finding counts when they cannot expose content.

Never log:
- File bytes, filenames by default, extracted text, OCR output, questions, messages, prompts, model outputs, raw findings, mappings, sanitized request text, provider answers, credentials, cookies, or approval fingerprints.
- Full request/response bodies from any model or provider.

Do not include document-derived content in crash reports or analytics. Any future telemetry requires a separate product decision and privacy disclosure.

## 6. Clear and expiration behavior

Clear Session removes active temporary state, not persisted history by default. It must remove:
- Original and extracted document content.
- Active chat/workflow intermediates, findings, and sanitized drafts.
- Placeholder mappings, approvals, and active provider results.
- Temporary files and relevant browser state.

Saved conversation history remains unless the user explicitly chooses to delete it. Conversation deletion must remove that conversation's persisted question/answer records and also clear any associated active workflow, document context, extracted text, mappings, approvals, and app-owned temporary files. Delete cleanup must be best-effort, report incomplete cleanup accurately, and never claim that local deletion removes content already transmitted to an external provider.

Failed requests must not retain sensitive request or answer content. Interrupted or delivery-uncertain requests do not currently retain even a minimal status record. Temporary documents, extracted text, and active workflow data are cleaned on completion, cancellation, session clear, expiry, failure, document removal, and conversation deletion.

Backend expiry is checked before every sensitive operation. Expired sessions cannot be revived or approved; require a new session and upload. Clear success should be reported only after cleanup completes. If cleanup partially fails, report that accurately and continue best-effort cleanup.

Clearing cannot delete information already transmitted to an external provider. State this clearly in the UI.

## 7. Persistent conversation history

The implementation uses a small local SQLite store located under the operating system's per-user application-data directory, outside the repository and temporary upload directory. `PRIVACYPAL_DATABASE_PATH` may override this with an absolute path; a custom path must be protected with equivalent per-user filesystem permissions. No application-managed backups are created. On POSIX systems, the application sets the database directory to mode `0700` and the database file to `0600`; on Windows, the default path relies on the per-user application-data directory's inherited OS permissions. SQLite is not encrypted by default, and encryption at rest is not implemented.

Schema:

### Conversation
- `conversation_id`: random opaque identifier (primary key).
- `created_at`, `updated_at`: UTC timestamps used for ordering and retention.

### Message
- `message_id`: random opaque identifier (primary key).
- `conversation_id`: foreign key with cascade deletion.
- `role`: `user` or `assistant`.
- `content`: question text for user messages or confirmed returned answer for assistant messages.
- `created_at`: UTC timestamp.
- `status`: `complete` for the successful question/answer pairs currently persisted; failed and delivery-uncertain turns are not stored.
- `workflow_id`: internal idempotency key, unique with conversation and role; not returned by history APIs.

Only successful question/answer pairs are retained, and only after an answer has been returned, with an absolute 30-day maximum per message. Retention is measured from each message's creation time; later activity in a conversation does not extend older messages' lifetime. Messages containing a detected high-risk credential are not persisted. A failed request must not persist its sensitive question or answer content. For an interrupted or delivery-uncertain call, no content is retained; the current implementation does not persist even a minimal status record. Do not persist original documents, extracted text, privacy findings, drafts, placeholder mappings, approval payloads/fingerprints, credentials, prompts, full provider requests, or unreturned/failed answers.

Delete expired history at startup and during history operations. Expired messages are removed individually; empty conversations are removed after 30 days of inactivity. Conversation creation, listing, retrieval, and deletion APIs are implemented; see docs/API_CONTRACT.md. Session clear deletes temporary active state but leaves saved history unless the user explicitly selects history deletion. Local deletion cannot recall content already transmitted to an external provider. File deletion is application-level deletion and is not a promise of forensic erasure from storage media, filesystem journals, or OS caches. A provider answer is still returned if the subsequent history write fails or is refused by the high-risk-content guard; the API reports `history_saved: false`.

## 8. Tests and acceptance criteria

Use synthetic data only. Tests must prove behavior, not only that a helper function ran.

Required tests:
- Session IDs are random and do not encode identity.
- Expired, cleared, and cross-session operations are rejected.
- Clear Session removes all in-memory state and app-owned temporary files on success and failure paths.
- Raw source text, findings, mappings, prompts, drafts, and credentials never enter logs or persistent storage. History stores only successful user questions and returned answers for up to 30 days.
- High-risk secrets never reach the provider mock.
- Provider is called only after approval for the current draft and provider.
- Editing after review invalidates the prior check and approval.
- Concurrent/double approval produces at most one provider call.
- Session clear races prevent a not-yet-started send.
- Provider timeout does not trigger blind duplicate sends.
- Provider mock receives exactly the approved sanitized request and no original text or placeholder mapping.

**Critical acceptance criterion:** zero provider calls occur without explicit approval of the exact, currently validated sanitized request.

## 9. Agent checklist

- [ ] Keep active session/workflow state in memory or restrictive temporary storage; never persist document or review payloads.
- [x] Persist only successful questions and returned answers in per-user local SQLite for up to 30 days; no application-managed backups.
- [ ] Keep document bytes and OCR temp files short-lived and clean them up on every path.
- [ ] Never log content, raw findings, mappings, prompts, payloads, answers, credentials, or cookies.
- [ ] Enforce session ownership, idle expiry, and clear behavior on the backend.
- [ ] Bind approval to the exact current draft and provider and consume it once.
- [ ] Re-run privacy checks after edits.
- [ ] Block high-risk secrets from outbound content.
- [ ] Test the provider boundary with a mock and synthetic secrets.
- [ ] Document what goes to the selected external provider and what local clearing cannot remove.

