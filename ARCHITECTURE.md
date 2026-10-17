# PrivacyPal Architecture

## 1. Purpose and decisions

This document is the implementation source of truth for PrivacyPal's MVP architecture. It defines the application boundary, core workflow, component responsibilities, failure behavior, and security invariants. Follow it with the product requirements, SECURITY.md, DATABASE.md, and design.md.

PrivacyPal is a local-first AI workspace. In the hackathon MVP, the browser UI, FastAPI backend, Gemma model runtime, document extraction, and OCR all run on the same user's computer. The app sends no original file or unminimized source text to a cloud AI. After local analysis and user review, it may send only the exact sanitized request the user approves to the configured external answer provider.

### Locked MVP decisions

| Concern | Decision |
|---|---|
| Product form | Desktop-first local web application, opened in the user's browser |
| Frontend | React + Vite; preserve the repository's existing setup if it already matches |
| Backend | Python + FastAPI |
| Local model runtime | Ollama, running locally |
| Local model | A configured Gemma model that passes the native tool-call smoke test described below |
| Text PDF extraction | Local PDF text extraction |
| Image and scanned-PDF extraction | Local OCR adapter; use the installed Tesseract engine and render PDF pages locally |
| Sensitive-data checks | Deterministic detectors plus Gemma contextual analysis |
| Active session/workflow storage | In-memory, process-local state; active state is not restored after restart |
| Conversation history | Local SQLite history containing successful user questions and returned answers for up to 30 days |
| External answer AI | Server-side provider adapter; provider/model chosen through configuration |
| Deployment | Local demo on one machine; do not describe a hosted backend as on-device/local |

Do not add a cloud OCR service, cloud file storage, telemetry, or account system. Conversation persistence stores only successful question/answer pairs in local history; active workflow state remains ephemeral. See DATABASE.md for storage scope and retention.

## 2. System overview

The browser UI talks only to the local FastAPI backend. The backend extracts text and performs OCR locally, asks local Gemma to analyze the question and document, validates and executes Gemma's requested privacy tools, and prepares a sanitized request. The user reviews the exact request and destination. Only an explicit approval of the current validated version can invoke the external answer provider. The answer returns to the same chat.

The original file is never modified. PrivacyPal reduces disclosure risk but does not guarantee perfect detection, anonymity, or safety.

### End-to-end flow

1. The user uploads a supported document or pastes text and asks a question in the same chat.
2. The backend validates the request and file, binds work to the current session, and extracts text locally. Scanned pages and images use local OCR.
3. Gemma receives the question and necessary extracted content through the Ollama adapter. Gemma requests tools using the runtime's native tool-call interface.
4. The backend validates each requested tool against the allowlist and schema, enforces limits, and executes it.
5. Deterministic detectors identify known sensitive patterns. Gemma contributes contextual relevance and residual-risk analysis.
6. PrivacyPal minimizes the request, removes or replaces sensitive values, and blocks high-risk secrets.
7. A residual privacy check runs on the exact sanitized draft.
8. The UI shows findings, edits, the exact outbound request, and the selected external provider.
9. The user edits, approves, or cancels. Any edit invalidates the previous review and approval and triggers revalidation.
10. On explicit approval, the backend validates the current draft and sends only that payload to the configured answer provider.
11. The answer appears in the same chat. Placeholder restoration, if enabled, occurs locally and only for exact known placeholders.
12. Clearing the active session removes temporary content, mappings, files, and approval state. Saved history remains unless the user explicitly deletes it.

## 3. Trust boundaries

| Boundary | Data crossing it | Required control |
|---|---|---|
| Browser to local backend | User text, file bytes, session actions | Treat as untrusted; validate type, size, state, origin, and session server-side |
| Document to Gemma/OCR | Extracted text, metadata, embedded instructions | Treat as untrusted data; document instructions cannot change policy or authorize sending |
| Gemma to tool registry | Tool names and arguments | Native tool calls only; validate allowlist, JSON schema, size, count, and workflow state |
| Local backend to external answer provider | Approved sanitized request | Backend-only adapter; exact current request; explicit approval; no original file or mapping |
| Provider response to browser | Generated answer and references | Treat as untrusted output; render safely; validate citations and never execute returned markup |

Gemma is a planner and analyst, not an authorization boundary. The backend owns tool execution, privacy enforcement, session ownership, and the approval gate.

## 4. Runtime and local-service security

The local demo consists of the React/Vite development server and FastAPI on loopback on the same computer.

- Bind both services to 127.0.0.1; do not bind to 0.0.0.0 by default.
- Use the Vite development proxy for API requests where practical. Allow only the exact configured frontend origin; never use wildcard CORS.
- Validate Host and Origin headers on state-changing requests. Reject unexpected origins, null origins, malformed hosts, and requests for public network interfaces.
- Use a high-entropy session identifier in an HttpOnly, SameSite=Strict cookie. Use Secure when served over HTTPS. Protect state-changing routes with a CSRF token or an equivalent same-origin request check.
- Do not accept a caller-supplied backend URL, Ollama URL, OCR executable path, or answer-provider URL from a document, model response, or ordinary browser request.
- Keep Ollama reachable only on loopback. Do not expose its port to the LAN.
- Configure the answer provider from trusted server-side settings. Restrict outbound calls to the configured provider endpoint; do not let Gemma select arbitrary URLs.
- Use HTTPS and appropriate authentication if the app is ever hosted. A hosted backend receives uploaded documents and is not fully local.
- Never put provider credentials in browser code, browser storage, prompts, source control, logs, or API responses.

## 5. Components

### 5.1 Frontend

Responsibilities:
- Provide one workspace for chat, file upload, local-analysis status, privacy findings, request preview, approval, and answer.
- Display the exact sanitized request and the external destination before approval.
- Allow editing and cancellation.
- Show clear loading, empty, error, blocked, and success states.
- Offer Clear Session.

The frontend is not a security boundary. It must not call Ollama or the external provider directly. Never display a successful send until the backend confirms the request was dispatched.

### 5.2 API and validation layer

Responsibilities:
- Validate payload shape, supported file type, size, page count, extracted-text length, and required fields.
- Bind every operation to an active session and workflow.
- Apply request-size limits, rate limits where appropriate, and timeouts.
- Enforce allowed state transitions and return safe structured errors.
- Reject requests using stale draft versions or approval state.

Do not trust client-supplied text as proof that it was sanitized or reviewed.

### 5.3 Workflow orchestrator

Responsibilities:
- Coordinate extraction, OCR, Gemma, tools, deterministic checks, minimization, residual review, approval, and answer generation.
- Own the state machine and request version.
- Run mandatory checks before an outbound draft can be approved.
- Bind approval to the exact draft, selected provider, and active session.
- Call the answer-provider adapter only after server-side approval validation.
- Fail closed if any mandatory analysis or check fails.

### 5.4 Extraction and local OCR

MVP inputs:
- Pasted text.
- Text-based PDF.
- Scanned PDF.
- PNG, JPEG, and WebP images.

Text-based PDFs use local text extraction. Scanned PDFs and images use a local OCR adapter backed by Tesseract; PDF pages are rendered locally before OCR. OCR must not use a hosted endpoint.

The adapter must:
- Validate file signatures and content types; do not trust filenames or extensions.
- Enforce configured upload-size, page-count, image-dimension, OCR-time, and output-length limits.
- Reject encrypted, corrupted, unsupported, empty, or over-limit files with a useful error.
- Preserve page/region references when available.
- Store temporary bytes only as long as needed and clean up temporary files on success, failure, cancellation, and session clear.
- Report OCR failure or low-confidence output; never present a failed extraction as complete.
- Never silently fall back to a remote OCR service.

If local OCR is unavailable, block processing and tell the user how to install or configure it. Do not continue with incomplete text without clearly marking the limitation and requiring user review.

### 5.5 Gemma adapter and native tool calling

Gemma runs through the local Ollama runtime. The adapter sends only the question and document content needed for local analysis.

Gemma must genuinely request tools using the configured runtime's native tool-call interface. Do not simulate tool use by parsing prose or treating arbitrary JSON text as an executed action. At startup and in integration tests, verify that the selected Gemma model emits a tool call and that the adapter returns its tool name and arguments correctly. If that test fails, stop the privacy workflow and show a local-model compatibility error.

Possible MVP tools:
- inspect_document: inspect available document text and page references.
- detect_sensitive_data: run or request categorized detection over a bounded input.
- select_relevant_content: identify facts related to the user's question.
- propose_sanitized_request: assemble a minimized draft using the permitted findings/actions.
- review_residual_risk: identify likely remaining identifying details in the sanitized draft.

Tool calls are proposals, not permissions. The backend must:
- Reject unknown tools and invalid or oversized arguments.
- Restrict tools to the current session and workflow.
- Limit calls, recursion, output size, and execution time.
- Make deterministic privacy rules non-overridable by Gemma.
- Prevent tools from accessing arbitrary files, executing code, opening URLs, or calling external answer providers.
- Treat tool output as untrusted data and pass only bounded results back to Gemma.
- Avoid logging raw arguments, sensitive values, or full tool results.

Document text, OCR output, and model output are untrusted. Prompt injection inside a document cannot change the system instructions, allowlist, privacy policy, or approval requirement.

### 5.6 Sensitive-data detection and minimization

Use deterministic detectors for known patterns such as email addresses, phone numbers, payment/account identifiers, and common credential formats. Use Gemma for context, question relevance, and candidate residual clues. Both can be wrong; the UI must not claim perfect detection.

The privacy pipeline must:
- Keep the original input unchanged.
- Select only facts needed to answer the question.
- Replace or remove personal identifiers according to the proposed action and user review.
- Block passwords, API keys, access tokens, and other defined high-risk secrets from outbound content.
- Use stable placeholders only within the active workflow when useful.
- Keep placeholder-to-original mappings in memory and never send them externally.
- Resolve overlapping findings deterministically or require review.
- Re-run required checks after any user edit.
- Prevent a failed or inconclusive mandatory scan from being labeled clean.

High-risk secrets remain blocked even if the user edits the preview. A residual-risk warning may require editing or explicit acknowledgement according to product policy, but it cannot override a blocking secret.

### 5.7 Approval gate

The approval gate presents:
- The exact outbound request.
- The selected external answer provider.
- A concise summary of detected and changed content.
- Edit, approve, and cancel actions.

The backend must verify that:
- The session is active and owns the workflow.
- The user is approving the current draft version and provider selection.
- The latest privacy review passed.
- No blocking secret remains.
- The approval has not already been consumed.
- The outbound payload matches the reviewed draft.

Editing the question, request, provider, or relevant privacy decisions invalidates the review and approval. Double clicks and replayed requests must result in at most one provider call.

### 5.8 Answer-provider adapter

This is the only component allowed to make a cloud answer request. It accepts a server-created approved request object, not arbitrary browser content.

It must:
- Use server-side credentials from environment configuration.
- Send only the exact approved sanitized request.
- Never receive the original file, full extracted text by default, or placeholder mappings.
- Apply request and response size limits, timeouts, and bounded retries.
- Avoid blind retries after an ambiguous timeout; report that delivery may have occurred.
- Return safe status and errors without logging request or response bodies.

The chosen provider is a runtime configuration decision. The provider name and endpoint must be visible to the user before approval. No provider is called during local analysis.

### 5.9 Session manager, temporary files, and planned history

The session manager owns active document, finding, draft, mapping, approval, and workflow state. Access must be scoped by session and workflow. Session clear removes active server-side temporary state and files as well as relevant browser state. A process restart may lose active sessions; re-upload is required to continue an active workflow.

Implemented: local SQLite conversation history in the operating system's per-user application-data directory, outside the repository and temporary upload directory. Persist only user questions and returned AI answers after a successful provider response, with a maximum 30-day retention per message. Detected high-risk credentials are not retained in history. Do not persist original documents, extracted text, findings, drafts, placeholder mappings, approval payloads, credentials, or full provider request bodies. No application-managed backups are created. SQLite is not encrypted by default. If the answer succeeds but history cannot be written, the answer response reports `history_saved: false`. Deleting local history cannot remove content already transmitted to an external answer provider. Session clear does not delete saved history unless the user explicitly chooses history deletion. See DATABASE.md for schema and cleanup behavior.

## 6. Workflow state machine

Each request follows these states:

1. RECEIVED
2. VALIDATING_INPUT
3. EXTRACTING
4. LOCAL_ANALYSIS
5. DETECTING_AND_MINIMIZING
6. RESIDUAL_PRIVACY_CHECK
7. AWAITING_USER_REVIEW
8. REVALIDATING after any edit
9. APPROVAL_VALIDATED
10. SENDING_SANITIZED_REQUEST
11. ANSWER_RECEIVED
12. COMPLETED

Terminal outcomes: FAILED, BLOCKED, CANCELLED, PROVIDER_FAILED, or DELIVERY_STATUS_UNKNOWN.

Required invariants:
- The only path to SENDING_SANITIZED_REQUEST passes through APPROVAL_VALIDATED.
- No failed, missing, or stale privacy review can be approved.
- Any edit invalidates prior review and approval.
- Failures never fall back to the original file or unminimized text.
- A provider timeout never triggers an automatic duplicate send unless a documented provider idempotency mechanism makes retry safe.
- Session clear or expiry prevents any provider call that has not started.

## 7. API contracts

Route names may be adapted to the existing repository, but preserve these behaviors:

| Operation | Purpose |
|---|---|
| POST /api/v1/sessions | Create an ephemeral session and return safe session metadata |
| POST /api/v1/sessions/{session_id}/documents | Upload a text-based PDF and extract locally |
| POST /api/v1/sessions/{session_id}/requests | Start local analysis for a question |
| GET /api/v1/sessions/{session_id}/requests/{request_id} | Read status and safe review data for this session |
| PATCH /api/v1/sessions/{session_id}/requests/{request_id} | Edit the draft or privacy decisions; invalidate checks and approval |
| POST /api/v1/sessions/{session_id}/requests/{request_id}/approve | Validate approval and, if valid, call the provider |
| POST /api/v1/sessions/{session_id}/requests/{request_id}/cancel | Cancel a request waiting for review |
| POST /api/v1/sessions/{session_id}/clear | Clear session state and temporary files |

Every route must validate session ownership, input size, and workflow state. Do not expose an endpoint for arbitrary tool execution. Use structured error codes and user-safe messages; never return stack traces, prompts, credentials, or sensitive document values.

## 8. Configuration

Provide an .env.example with placeholder values only. Configure at minimum:
- Local app host and ports.
- Exact allowed frontend origin.
- Ollama base URL restricted to loopback.
- Gemma model name.
- External answer provider name, endpoint, model, and API key.
- Upload, page, text, tool-call, and model-response limits.
- Extraction/OCR/model/provider timeouts.
- Session idle timeout.

Validate required settings at startup without printing secret values. The demo README must document local model setup, OCR setup, provider setup, supported inputs, limitations, and the fact that the approved sanitized prompt is sent to the configured external provider.

## 9. Testing and acceptance criteria

Use deterministic fake model/provider adapters for most tests and synthetic data only. Add local integration tests for the selected Gemma model's native tool-call path.

Required tests:
- Pasted text, text PDF, scanned PDF, and image extraction; unreadable and over-limit inputs.
- Native Gemma tool call is parsed and executed only after schema validation.
- Unknown tools, prompt injection, malformed model output, and invalid arguments are rejected.
- High-risk credentials never appear in the final provider payload.
- The provider is not called before explicit approval of the current sanitized request.
- Editing, stale approval, cross-session access, cancellation, expiry, and duplicate approval are rejected.
- Provider mocks receive the exact approved request and never receive original text or mappings.
- Clear Session removes memory state and temp files.
- Logs/errors contain no raw document data, secrets, mappings, prompts, or full payloads.
- The complete upload → ask → analyze → sanitize → review → approve → answer flow works with synthetic data.

## 10. MVP scope and planned history

Implemented: local 30-day conversation history and backend create/list/retrieve/delete APIs. Frontend history navigation remains a separate task.

Do not implement in this version:
- Accounts, cloud sync, or multi-user hosting.
- Persistent storage of documents, extracted text, findings, drafts, mappings, approval payloads, credentials, or provider request bodies.
- Cloud OCR, cloud file processing, or automatic cloud fallback.
- Arbitrary web browsing, code execution, shell access, or model-selected network tools.
- Automatic sending without user review and approval.
- A claim of perfect detection, guaranteed anonymity, or complete erasure from external providers.

## 11. Agent implementation rules

1. Inspect the repository before changing it. Preserve working conventions and dependencies.
2. Treat this document, SECURITY.md, DATABASE.md, and the product requirements as a single contract.
3. Implement the end-to-end flow before adding secondary features.
4. Make focused changes; add meaningful tests for changes to extraction, tools, redaction, approval, or provider calls.
5. Use synthetic fixtures only.
6. Do not invent unsupported UI states or claim a privacy guarantee the implementation cannot prove.
7. Keep visual implementation aligned with design.md.
8. Update this document when a decision changes.

The critical invariant is: no original or unapproved content is sent to the external answer provider.

