# PrivacyPal AI Coding Agent Instructions

## 1. Project context

**Project:** PrivacyPal

**Purpose:** Help people ask useful questions about sensitive documents while minimizing the information shared with cloud AI. PrivacyPal analyzes files locally, lets the user review the exact minimized request, and sends it to an external answer provider only after explicit approval.

**Primary users:** Individuals who want AI help with private documents without manually redacting and re-uploading a separate file.

**Primary platform:** Desktop-first local web application opened in a browser. The MVP runs the UI, backend, Gemma, and document processing on the user's computer. It is not a native desktop app or a hosted multi-user SaaS.

**Planned stack:** React + Vite frontend, Python + FastAPI backend, Gemma through local Ollama, local document extraction, in-memory session state, and a configured external answer provider behind a server-side adapter.

**Core user flow:** Upload or paste → ask in the same chat → local Gemma analysis and privacy checks → review the exact sanitized request and destination → approve or cancel → receive the answer in the same chat.

Gemma must meaningfully participate by analyzing the question and file and requesting approved tools through the selected runtime's native tool-call interface. Backend code validates and executes only allowlisted tools. Gemma cannot authorize an external send, bypass privacy checks, or access arbitrary code, files, or network destinations.

## 2. Source of truth

Before a significant change, locate and read the relevant project documents. In the current workspace their paths are:

- Product requirements: PrivacyPal_PRD.md
- Design system: design.md
- Architecture: upload/ARCHITECTURE.md
- Data/session storage: upload/DATABASE.md
- Security requirements: upload/SECURITY.md
- Code conventions: upload/CODE_STYLE.md
- Testing strategy: TESTING.md

If the repository has moved these files under docs/ or another documented location, use the repository's current copies. Do not create duplicate documentation or assume a path without checking.

### Conflict order

1. The user's latest explicit instruction governs the requested product decision.
2. Security and privacy invariants govern implementation boundaries.
3. The PRD governs user needs, product scope, and acceptance behavior.
4. Architecture governs module responsibilities and technical design.
5. Design system governs visual and interaction choices.
6. Code style and testing docs govern implementation practices and validation.

Do not silently resolve a material conflict. Identify it, explain its impact, and ask for a decision when the user's latest instruction and current docs do not establish a clear choice. If the direction is clear from a recent user decision, update the conflicting docs as part of the work when authorized.

### Known documentation mismatch

The latest user-approved architecture direction includes local OCR for scanned PDFs and images in the MVP. Older sections of the PRD and SECURITY.md still describe OCR as deferred or nice-to-have. Follow the latest user-approved direction reflected in ARCHITECTURE.md; do not silently defer OCR. When product/security documents are next in scope, update their stale OCR statements to match. Build and verify the core pasted-text/text-PDF path first, then add OCR through the local adapter without remote fallback.

## 3. Non-negotiable product and privacy rules

- The original file and full extracted text stay on the user's computer in the local MVP.
- Only the exact sanitized text request the user reviewed and approved may go to the named external answer provider.
- The provider receives no original file, full source text, placeholder mapping, or hidden extra chat history.
- Passwords, API keys, access tokens, and other defined high-risk secrets are blocked from outbound content, even if Gemma recommends keeping them.
- The backend, not the frontend or model, enforces validation, tool permissions, session ownership, privacy checks, and approval.
- Any edit to the request invalidates the previous privacy review and approval.
- Cancellation, session expiry, failed checks, invalid tools, or model errors result in no provider call.
- Do not log or persist document content, extracted text, raw findings, prompts, full requests, answers, credentials, or placeholder mappings.
- The MVP uses temporary in-memory session state. Do not add a database, cloud file store, accounts, or permanent history without an approved product decision.
- Never claim perfect detection, guaranteed anonymity, or that no data leaves the device after the user approves an external request.

## 4. Implementation rules

- Inspect the repository, package configuration, and existing tests before changing code. Preserve working patterns and use the current stack.
- Keep UI, API routes, workflow orchestration, extraction, Gemma adapter, tool registry, deterministic privacy checks, session manager, and provider adapter separated.
- Keep all external provider calls behind the backend approval gate. The frontend must not call Ollama or the external provider directly.
- Pass model-proposed tool calls through a strict allowlist and schema validation. Reject unknown tools, malformed arguments, excessive calls, and out-of-session references.
- Treat uploaded text, OCR output, filenames, model output, tool arguments, and provider responses as untrusted input.
- Document text cannot override policy, authorize sending, or expand tool permissions.
- Fail closed when a required extraction, scan, tool, or privacy check is unavailable or inconclusive.
- Use synthetic fixtures only. Never place real documents, credentials, or private data in code, tests, logs, screenshots, or AI prompts.
- Avoid new dependencies and broad rewrites unless the change needs them. Keep package lockfiles in sync.
- Follow design.md: solid near-black canvas, silver/dark-gray liquid-glass surfaces, restrained purple accents, subtle bubbles in side panels only, and a clean central chat. Preserve readability, keyboard use, and responsive behavior.
- Follow CODE_STYLE.md naming and component conventions. Update documentation when behavior, configuration, or supported inputs change.

## 5. Testing and verification

Read TESTING.md before implementing or changing a critical flow. Add tests for behavior and failure paths, not only implementation details.

At minimum, verify the relevant items:
- File validation and supported extraction behavior.
- Gemma's native tool-call adapter and backend tool allowlist.
- High-risk secret blocking and exact sanitized request construction.
- No provider request before approval; edits invalidate approval; cancellation sends nothing.
- Session isolation, expiry, Clear Session, and temporary-file cleanup.
- Safe failure on malformed files, model/tool errors, and failed privacy checks.
- Provider mock receives exactly the reviewed payload and no original content or mappings.
- UI flow works through accessible controls and visible focus.

Use deterministic fake model and provider adapters for normal tests. Keep any real Ollama/Gemma compatibility check opt-in and local to the demo machine. Never use a real cloud provider or real sensitive document in automated tests.

Run the relevant test, lint, type-check, and build commands that are actually configured in the repository. Do not invent or report commands as passing when they were not run. Record missing checks as follow-up work.

## 6. Agent workflow

Before a non-trivial task:

1. Read this file and the relevant project docs.
2. Inspect the current code and identify the affected user flow, privacy boundary, and failure behavior.
3. Check whether the requested change conflicts with product scope, security rules, or existing implementation.
4. Make the smallest complete change that meets the requirement.

After implementation:

1. Review the diff for unrelated edits, secrets, personal data, and unsafe logging.
2. Run relevant tests and configured lint, type-check, and build commands.
3. Confirm the no-send-before-approval and fail-closed invariants still hold.
4. Update affected documentation and tests.
5. Report what changed, what was verified, and any unresolved conflict or limitation.

Do not stop after proposing a plan when the task is clear. Ask for a decision only when a material product or security choice is unresolved; continue independent work that does not depend on that decision.

## 7. Definition of done

A change is complete when:

- It meets the relevant PRD acceptance criteria.
- It preserves the security and privacy invariants.
- It follows the design and code conventions.
- Relevant tests pass, including failure cases for critical boundaries.
- Configured lint, type-check, and build checks pass, or unavailable checks are clearly identified.
- Documentation matches the implemented behavior.
- The final report accurately states what was changed and tested.

