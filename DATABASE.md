# PrivacyPal Database and Session Data Design

> Authorized AWS demo mode retains process-local in-memory sessions on one EC2
> backend, shared by all Lambda gateway invocations. No document database or
> persistent history is added. AWS processes uploads; restarting the backend
> loses sessions. See [the deployment runbook](deploy/aws/README.md).

## 1. Purpose and decision

This document defines how the MVP stores and clears application data. It accompanies ARCHITECTURE.md, SECURITY.md, the product requirements, and design.md.

**MVP decision: PrivacyPal has no persistent application database.** Use process-local in-memory session state. This is intentional: the hackathon product handles sensitive files and does not need durable history to deliver its core workflow.

Do not add SQLite, PostgreSQL, cloud storage, analytics, or chat-history persistence unless a concrete product requirement is approved and this document is updated first.

## 2. Data-flow and retention rule

The browser, FastAPI backend, Ollama/Gemma, document extraction, and OCR run on the same user's computer in the MVP. Original files, extracted text, findings, drafts, and placeholder mappings stay in temporary local state. Only the exact sanitized request explicitly approved by the user may be sent to the configured external answer provider.

Provider-side retention is outside PrivacyPal's control. The UI must say which provider receives the approved request and must not promise that clearing a local session deletes content already sent externally.

| Data | MVP location | Retention |
|---|---|---|
| Original upload bytes | Request memory or restrictive temporary file | Only while extracting/processing; delete on all exits |
| Pasted source text | In-memory session | Until workflow completion, clear, expiry, or process exit |
| Extracted/OCR text and page references | In-memory session | Until workflow completion, clear, expiry, or process exit |
| User question and chat turns | In-memory session | Until clear, expiry, or process exit |
| Sensitive findings and raw matched values | In-memory workflow state | Until workflow completion, clear, expiry, or process exit |
| Placeholder-to-original mapping | In-memory workflow state only | Until clear, expiry, or process exit |
| Sanitized draft and privacy result | In-memory workflow state | Until completed, cancelled, clear, expiry, or process exit |
| Approval state and draft fingerprint | In-memory workflow state | One workflow version; discard after use, cancel, clear, expiry, or process exit |
| External provider answer | In-memory session | Until clear, expiry, or process exit |
| Provider API key and credentials | Backend environment/configuration only | Never persisted in application data |
| Operational logs | Local logs, if enabled | Minimum necessary; no content or secrets |

Use a finite idle timeout. MVP default: expire a session after 30 minutes without activity. Enforce expiry on the backend before every sensitive operation, not only in the browser. Process restart discards active in-memory sessions.

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

Do not persist original bytes or extracted text.

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

Do not persist request or response bodies. Provider-side retention is outside the local session store.

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

Clear Session must remove:
- Original and extracted document content.
- Chat turns, findings, model/tool intermediates, and sanitized drafts.
- Placeholder mappings, approvals, and provider answers.
- Temporary files and relevant browser state.

Backend expiry is checked before every sensitive operation. Expired sessions cannot be revived or approved; require a new session and upload. Clear success should be reported only after cleanup completes. If cleanup partially fails, report that accurately and continue best-effort cleanup.

Clearing cannot delete information already transmitted to an external provider. State this clearly in the UI.

## 7. Persistent storage: out of scope

The MVP does not need database migrations, tables, backups, or database credentials. Do not implement the optional SQLite schema from earlier drafts; it adds work without serving the core demo.

If a future requirement needs persistence, first document:
1. The specific fields and use case that need to survive a process restart.
2. Why in-memory state is insufficient.
3. Whether any field is personal, document-derived, sensitive, or reversible.
4. Retention, deletion, access control, encryption/key management, backups, and user disclosure.
5. How approval remains tied to the exact current sanitized request.

A future persistent store must keep document bytes, extracted text, conversations, findings, placeholder mappings, sanitized request bodies, provider answers, and credentials out of persistent tables unless a separately reviewed product decision explicitly changes that rule.

## 8. Tests and acceptance criteria

Use synthetic data only. Tests must prove behavior, not only that a helper function ran.

Required tests:
- Session IDs are random and do not encode identity.
- Expired, cleared, and cross-session operations are rejected.
- Clear Session removes all in-memory state and app-owned temporary files on success and failure paths.
- Raw source text, findings, mappings, prompts, drafts, answers, and credentials never enter logs or persistent storage.
- High-risk secrets never reach the provider mock.
- Provider is called only after approval for the current draft and provider.
- Editing after review invalidates the prior check and approval.
- Concurrent/double approval produces at most one provider call.
- Session clear races prevent a not-yet-started send.
- Provider timeout does not trigger blind duplicate sends.
- Provider mock receives exactly the approved sanitized request and no original text or placeholder mapping.

**Critical acceptance criterion:** zero provider calls occur without explicit approval of the exact, currently validated sanitized request.

## 9. Agent checklist

- [ ] Use process-local in-memory session state; no persistent database in the MVP.
- [ ] Keep document bytes and OCR temp files short-lived and clean them up on every path.
- [ ] Never log content, raw findings, mappings, prompts, payloads, answers, credentials, or cookies.
- [ ] Enforce session ownership, idle expiry, and clear behavior on the backend.
- [ ] Bind approval to the exact current draft and provider and consume it once.
- [ ] Re-run privacy checks after edits.
- [ ] Block high-risk secrets from outbound content.
- [ ] Test the provider boundary with a mock and synthetic secrets.
- [ ] Document what goes to the selected external provider and what local clearing cannot remove.

