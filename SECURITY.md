# PrivacyPal Security Requirements

> Authorized hosted demo exception (18 October 2026): uploads and Gemma processing
> may run in AWS. The local-only assumptions below apply to default local mode.
> Hosted mode requires HTTPS, browser authentication, exact Origin checks, a
> private backend token, VPC restrictions, Secure ownership cookies, and explicit
> AWS processing disclosure. The approved-request provider boundary is unchanged.
> See [the hosted threat boundary and runbook](deploy/aws/README.md).

**Status:** Security requirements for the desktop-first hackathon MVP
**Product behavior:** `PrivacyPal_PRD.md`
**Code conventions:** `upload/CODE_STYLE.md`

This document defines implementation requirements. It is not evidence that an implementation is secure, a guarantee that every sensitive detail will be detected, or a compliance certification. Security claims must be supported by code, tests, and review.

## 1. Product security context

PrivacyPal processes user-selected sensitive documents locally, uses Gemma for contextual analysis, then may send a minimized, user-approved text request to an external answer AI. The source file and its full extracted text must never be sent to the answer provider.

### MVP assumptions

- One user operates the app on their own computer in a browser.
- The frontend, FastAPI backend, and Ollama/Gemma runtime run on that same computer.
- The backend listens on loopback only. It is not a LAN or public service.
- There are no accounts, roles, shared workspaces, remote database, cloud file storage, or long-term chat history in the MVP.
- MVP inputs are pasted text, PDFs, PNG, JPEG, and WebP. Text extraction and OCR are local; never add a hosted OCR fallback. Keep scanned/image OCR failures fail-closed.
- The user selects each file explicitly. The app does not monitor folders, the clipboard, other apps, or the device.
- Only a sanitized request approved by the user may be sent to a configured external answer provider.

If the app is exposed beyond loopback, gains multiple users, stores data persistently, or adds integrations, pause release and update the threat model and controls first.

### Assets and threats

Protect the source file, extracted text, sensitive findings, sanitized request, placeholder mapping, chat answer, provider credentials, approval state, and local service.

Consider malicious or malformed PDFs, indirect prompt injection in document text, missed or false-positive findings, unsafe Gemma tool calls, browser-origin attacks against the local API, accidental logging/storage, provider failures, and untrusted provider output. PrivacyPal reduces disclosure risk; it cannot guarantee anonymity, perfect detection, or safe answers.

## 2. Data handling and retention

| Data | Where it may be processed | May leave the device? | MVP retention |
|---|---|---|---|
| Original file | Browser and local backend/parser | **No** | Session only; remove on clear/close and clean temporary files |
| Full extracted text | Local backend and local Gemma | **No** | Session only |
| Findings and source locations | Local backend and UI | **No**, except facts deliberately represented in the approved sanitized request | Session only |
| Sanitized request | Local backend and UI preview | **Only after explicit approval** | Session only; do not log |
| Placeholder-to-original mapping | Local backend only | **Never** | Memory only; clear with the session |
| Provider answer | External provider returns it; then local UI | It originates externally; do not resend it unless user explicitly approves a new request | Session only |
| Provider API key | Backend configuration or later OS credential store | **Never in browser code or requests to the frontend** | Outside source control |

For the MVP, do not add persistent storage or browser local storage/IndexedDB for source files, extracted text, findings, prompts, answers, or placeholder mappings. If a parser needs a temporary file, create it with restrictive local permissions, use a generated name in a private temporary directory, and delete it on success, error, cancellation, and session clear. At startup, remove stale PrivacyPal temporary files safely.

The interface and documentation must say precisely what happens: **the original file and full extracted text stay local; only the exact sanitized request shown and approved by the user is sent to the named external provider.** Never use an unqualified “nothing leaves this device” claim.

## 3. Local service and browser boundary

- Bind FastAPI and Ollama to loopback only (for example, `127.0.0.1`); do not bind to `0.0.0.0` or expose either service to the network.
- Restrict CORS to the exact local frontend origin(s) used by the app. Do not use wildcard origins with credentials.
- Validate expected `Host` and `Origin` values on local API requests. CORS alone is not a complete defense against cross-origin requests to a local service.
- For state-changing browser endpoints, require an unguessable per-launch/session capability or CSRF token in a request header and reject missing or invalid tokens. Do not put tokens in URLs, logs, or browser bundles served to unrelated origins.
- Limit request size, concurrent processing, and expensive operations. Do not expose interactive API documentation or debug routes in a release build unless deliberately protected.
- Return safe errors without internal paths, prompts, stack traces, provider responses, or secrets.
- Use HTTPS/TLS for external provider calls. Local Ollama traffic may use loopback HTTP only while the service remains local and inaccessible from the LAN.
- Do not make network requests from the frontend to answer providers. Provider traffic must pass through the backend approval gate.

## 4. Identity, authentication, and authorization

The MVP is single-user and local to the OS account running it. Account registration, remote authentication, admin roles, tenancy, and shared workspaces are out of scope and must not be invented as MVP requirements.

Local deployment is not a reason to trust client input. The backend must enforce allowed operations, validate session ownership, and reject requests that do not belong to the active local session. If remote hosting or multiple users are introduced, authentication, server-side authorization, tenant isolation, session protection, and a separate security review become release blockers.

## 5. Gemma, prompt injection, and tool execution

Uploaded documents and model outputs are untrusted data. Instructions found in documents, OCR text, metadata, or quoted passages must never override the user's request or PrivacyPal's policy.

- Give Gemma only the data and capabilities required for the current local analysis.
- Clearly separate document content from trusted application instructions. Delimiters and prompt wording help but are not security boundaries.
- Gemma may request only explicitly registered, narrowly scoped tools. Use structured schemas and validate the tool name, argument types, length, ranges, and referenced finding IDs on the backend.
- The backend, not Gemma, decides whether a tool call is valid and executes it.
- Never provide tools for arbitrary shell/code execution, filesystem access, process control, unrestricted URL fetching, database access, or sending network requests.
- Do not let Gemma choose an arbitrary provider URL, model endpoint, API key, or outbound destination.
- Treat model-generated findings, keep/mask decisions, summaries, confidence, tool arguments, and answer text as proposals or untrusted output. Render output as text; never execute model-produced HTML, JavaScript, SQL, shell commands, or paths.
- Unknown tools, malformed arguments, model timeouts, or unavailable local Gemma must stop the workflow or request a safe retry; they must never cause a send.
- Keep a deterministic final outbound validator for high-risk secrets and payload limits. A model saying “safe” cannot override a blocked secret or failed validator.
- Instructions in a file cannot approve an outbound request, disable checks, reveal a placeholder mapping, or expand the tool allowlist.

Add synthetic adversarial tests for direct and indirect prompt injection, hidden text, malformed tool calls, unknown tools, and attempts to bypass approval. Prompt instructions alone do not mitigate prompt injection.

## 6. Sensitive-data policy and outbound approval gate

### Detection and minimization

- Combine deterministic checks for known high-risk patterns (such as credentials, API keys, and common structured identifiers) with Gemma's contextual analysis. Neither is sufficient alone.
- The backend must apply high-risk secret blocking to the final sanitized payload. High-risk secrets cannot be sent even if Gemma proposes keeping them.
- Show findings and the reason for proposed actions. Do not label a request “safe,” “anonymous,” or “guaranteed private”; use scoped language such as “no high-risk secrets detected.”
- A failed detector or privacy review is an error, not a clean scan. Fail closed.
- The source file remains unchanged. Never send the original file, full extracted text, or placeholder mapping to an answer provider.

### Approval must bind to the exact outbound request

- The preview must show the named provider and all user-specific content that will be sent, including the exact sanitized text and any attachments or other payload fields. The MVP sends text only; do not attach the source file.
- Build the preview from the exact immutable request object the backend will send. Do not let the browser construct a different outbound payload after approval.
- Approval must be bound server-side to the exact canonical payload, provider/model destination, and active session. Use a short-lived, single-use approval token or equivalent server-side state.
- On approval, revalidate the stored request and send that exact snapshot. If the question, provider, model, payload, or relevant privacy result changes, invalidate approval and rerun the privacy checks.
- Cancel, expiry, a failed check, or a mismatched payload must result in no provider call. Retries require a new valid approval.
- If the residual-identity check flags a risk, show it and require editing or explicit user acceptance as defined by the PRD. Never describe user acceptance as proof of anonymity.

Test and assert the invariant: **no external request occurs before approval, and the bytes sent match the reviewed payload.**

## 7. External providers and secrets

- Select providers only from a backend allowlist. Do not accept a URL or endpoint from document content or arbitrary frontend input.
- Send only the approved minimized text and the minimum provider metadata required. Do not send source files, extracted text, local mappings, filenames, local paths, detector results, or unrelated chat history.
- Keep provider API keys server-side in an ignored local environment file for development. Never put them in `VITE_*` variables, the browser bundle, URLs, logs, screenshots, or source control. Use synthetic placeholders in `.env.example`.
- Before enabling a provider, review its data-use, retention, and logging terms and disclose the selected provider to the user before approval.
- Never log request/response bodies, prompts, findings, file names, keys, tokens, or placeholder values. Operational logs may contain event type, random request/session ID, selected provider identifier, status, elapsed time, and bounded size/count metadata only.
- Use HTTPS and normal certificate verification. Do not disable TLS verification to work around a provider failure.
- If a key is exposed, revoke and rotate it; removing it from the latest commit is not sufficient.

## 8. File upload and parsing

### MVP limits

Use these initial fail-closed limits and tune only after testing on the hackathon machine:

- Pasted text: at most **25,000 characters**.
- PDF: at most **10 MiB**, **25 pages**, and **25,000 extracted characters**.
- PDF parsing timeout: **15 seconds**. Local model work must have a configurable timeout; a timeout or resource-limit error stops the workflow.
- One file per request. Reject encrypted/password-protected PDFs, unsupported formats, empty files, and over-limit input. Use the local OCR adapter for scanned PDF pages and images; fail clearly if OCR is unavailable or fails.

These are conservative starting limits, not claims that every allowed PDF is harmless. Keep limits configurable and enforce them in the backend, before expensive processing. Test on synthetic files and adjust only with documented measurements.

### Required handling

- Allowlist PDF, PNG, JPEG, WebP, and plain pasted text for the MVP. OCR must run locally with the configured Tesseract adapter and be covered by synthetic tests.
- Validate file size, extension, MIME type, and file signature; do not trust the filename or browser-supplied content type alone.
- Use generated server-side temporary names. Prevent path traversal, overwrite, and public serving of uploads.
- Parse in a maintained library with processing limits. Do not execute PDF JavaScript, embedded files, macros, links, or attachments. Do not follow URLs found in a document.
- Bound pages, extracted characters, parser time, memory where supported, and model input. Reject or safely truncate only when the user is clearly told and the resulting request is re-reviewed; never silently omit content.
- Keep the uploaded content out of static/public directories, caches, analytics, crash reports, and logs.
- Delete temporary files and in-memory state on success, failure, cancellation, session clear, and application shutdown where feasible.
- A malformed, oversized, encrypted, or unsupported file must not proceed to Gemma or the external provider.

These controls follow the OWASP File Upload guidance; revisit it when adding file types or OCR.

## 9. Storage, retention, and deletion

- The MVP does not provide a permanent file library or synced chat history.
- Keep document content, extracted text, findings, sanitized request, answer, and placeholder map only for the active session.
- Clearing a session must clear frontend state, backend session state, and temporary files. It must not merely hide them from the screen.
- Do not create backups or analytics records containing sensitive workflow data.
- If persistent storage, exports, or backups are added, define access, encryption, retention, deletion, and recovery behavior before implementation.

## 10. Errors, logs, and incidents

- Fail closed if parsing, scanning, Gemma analysis, secret validation, residual-risk review, approval validation, or local-session validation fails.
- Distinguish local analysis failures from external provider failures. Do not retry a provider request automatically after approval expiry or a changed payload.
- Display useful, non-sensitive errors. Keep protected diagnostics limited to operational metadata.
- Never log full file text, prompts, responses, sensitive findings, placeholder maps, or credentials.
- Use synthetic test and demo documents only. Do not place real user documents or secrets in source control, bug reports, or AI coding prompts.
- Before public release, document who handles suspected data exposure, how provider credentials are revoked, and how local temporary data is removed.

## 11. Security verification checklist

Before a demo build or release, verify the applicable items:

- [ ] Frontend, FastAPI, and Ollama listen only on loopback; no service is exposed to the LAN.
- [ ] Local API origin/host checks and state-changing request token are enforced.
- [ ] Unsupported, malformed, encrypted, oversized, and over-limit files fail before model processing.
- [ ] Prompt injection inside file content cannot expand tools, alter policy, or authorize sending.
- [ ] Gemma cannot execute arbitrary code, access the filesystem, or initiate network calls.
- [ ] High-risk secrets are blocked by backend validation even if the model says to keep them.
- [ ] No outbound call occurs before approval; edits, cancellation, expiry, and failures invalidate approval.
- [ ] Provider receives only the exact approved minimized text; no original file, full extraction, mapping, or hidden extra user content is included.
- [ ] Provider credentials remain server-side and are absent from logs, browser assets, and source control.
- [ ] Source files and prompts are absent from persistent storage, logs, telemetry, and crash reports.
- [ ] Session clear removes in-memory and temporary session content.
- [ ] Provider output and model output are rendered safely as text.
- [ ] Tests use synthetic data and cover the security invariants and failure paths.
- [ ] UI language does not promise perfect detection or claim that no data leaves the device when an approved request is sent externally.

## 12. Decisions that remain release gates

Resolve and record these before a public release or before changing the MVP assumptions:

- Which external answer provider/model is enabled and what are its data retention and training terms?
- How will users supply and store provider credentials on the demo machine and in any packaged release?
- Have the initial file/model limits been validated against the actual model and hackathon hardware?
- Who owns incident response and credential rotation for a public deployment?
- Are new formats, OCR, persistence, remote hosting, multi-user support, or integrations being added? If yes, define their threat model and controls first.

Do not claim regulatory certification or guaranteed privacy. The security of the product depends on implementing and testing these requirements, not merely keeping this document.

## References

- [OWASP Top 10 for Large Language Model Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [OWASP Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
