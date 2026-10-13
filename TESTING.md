# PrivacyPal Testing Strategy

## Purpose

This document defines how PrivacyPal is validated. AI agents must run the tests and report their results; “the code looks correct” is not evidence that the application works.

Follow this plan with ARCHITECTURE.md, DATABASE.md, SECURITY.md, the product requirements, and design.md. The MVP uses a React + Vite web UI, FastAPI backend, local Ollama/Gemma, local PDF extraction and OCR, in-memory sessions, and an external answer-provider adapter.

Do not add tests for sign-up, checkout, or persistent database behavior: those are outside this MVP.

## 1. Testing goals

Critical functionality:

- Accept pasted text, text PDFs, scanned PDFs, and supported images; extract or OCR them locally.
- Verify Gemma uses the configured runtime's native tool-call interface and the backend validates every requested tool.
- Detect, minimize, redact, and block high-risk secrets from outbound requests.
- Show the exact sanitized request and destination before approval.
- Send only the exact, currently validated request after explicit user approval.
- Return the provider's answer in the same chat.
- Keep sessions isolated and enforce expiry, Clear Session, and temporary-file cleanup.
- Fail closed when extraction, OCR, model analysis, tool validation, detection, residual review, or approval validation fails.
- Reject unsafe local-service requests and keep credentials and document content out of logs and test output.
- Keep the critical workflow keyboard accessible, readable, and usable at narrow and desktop widths.

**Critical invariant:** zero external answer-provider calls occur without approval of the exact, current, sanitized request.

## 2. Test types

### Unit testing

Test isolated logic with deterministic data and no network or live model dependency.

Backend:

- File signature/type validation, size/page/dimension limits, and safe filename handling.
- Text extraction and OCR-result normalization, including empty, corrupt, and unsupported input.
- Sensitive-pattern detection, overlap handling, deduplication, masking, and placeholder generation.
- Question-aware selection and sanitized-request construction.
- Gemma native tool-call parsing, tool allowlist, schemas, argument validation, and call limits.
- Workflow state transitions and fail-closed behavior.
- Draft versioning, review invalidation, approval matching, one-time consumption, and session ownership.
- Session expiry, clear behavior, and temporary-file cleanup.
- Safe error mapping and content-free logging.

Frontend:

- File selection/removal, composer behavior, and loading, error, empty, and blocked states.
- Findings and sanitized-preview rendering.
- Edit, approve, cancel, and Clear Session interactions.
- Visibility of the exact request and provider destination before approval.
- Accessible names, keyboard interaction, visible focus, and responsive control behavior.

Query the UI through accessible roles, labels, and visible text. Avoid tests tied to component internals or CSS implementation details.

### Integration testing

Test application boundaries with controlled fakes for nondeterministic services.

- FastAPI routes with the session manager, workflow orchestrator, extraction/OCR adapters, and approval gate.
- Upload → extraction/OCR → local analysis → validated tool execution → privacy review → approval.
- Session cookie, Origin/Host checks, CSRF or equivalent same-origin protection, and cross-session authorization.
- The answer-provider adapter against a local mock server. Assert the exact request body and that original text, blocked secrets, and placeholder mappings are absent.
- Temporary-file cleanup after success, error, cancellation, and session clear.
- Local OCR using synthetic image and scanned-PDF fixtures. The test must use the installed local engine and must not call a remote OCR service.
- Provider error, timeout, malformed response, and uncertain-delivery behavior.
- An opt-in Ollama/Gemma smoke test that verifies native tool-call compatibility for the selected local model.

Do not call a real answer-provider API in the normal automated suite. Use synthetic data and a local mock provider.

### End-to-end testing

Use Playwright against the local application. The normal E2E suite must use deterministic local model/tool fixtures and a provider mock. Keep live Gemma and OCR-engine checks as separate opt-in smoke tests so routine CI is reproducible.

Cover the critical journeys in Section 5. Every E2E test that exercises approval must assert the provider mock's call count and, when allowed, the exact payload.

## 3. Testing tools

| Scope | Tool | Purpose |
|---|---|---|
| Backend unit/integration | pytest | Fixtures, parametrization, assertions, and test discovery |
| FastAPI routes | FastAPI TestClient + HTTPX | Exercise API behavior without a public server |
| Backend coverage | pytest-cov | Measure coverage of privacy-critical modules |
| Python lint | Ruff | Catch common errors and enforce configured style |
| Python type checking | mypy | Check annotated backend modules |
| Frontend unit/component | Vitest + React Testing Library + user-event | Test UI behavior through user-facing interactions |
| Frontend lint/typecheck | ESLint + TypeScript compiler | Check frontend source and types |
| Browser E2E | Playwright Test | Verify full browser journeys and responsive behavior |
| Local model smoke | Ollama/Gemma via the application adapter | Verify native tool-call integration on the demo machine |
| Local OCR smoke | Tesseract via the OCR adapter | Verify local OCR with synthetic fixtures |

Use versions and package managers already present in the repository. Do not add a duplicate framework if an equivalent is configured. Official references: [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/), [Vitest](https://vitest.dev/guide/), [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/), and [Playwright Test](https://playwright.dev/docs/intro).

## 4. Test file structure

The following structure matches the architecture. Adapt it to existing repository conventions instead of creating duplicate folders.

    tests/
    ├── backend/
    │   ├── unit/
    │   │   ├── test_detection.py
    │   │   ├── test_redaction.py
    │   │   ├── test_tool_registry.py
    │   │   ├── test_approval_gate.py
    │   │   └── test_sessions.py
    │   ├── integration/
    │   │   ├── test_upload_analysis_flow.py
    │   │   ├── test_api_security.py
    │   │   ├── test_provider_boundary.py
    │   │   └── test_local_extraction_ocr.py
    │   └── fixtures/
    │       ├── synthetic_statement.pdf
    │       ├── synthetic_scan.pdf
    │       └── synthetic_scan.png
    └── frontend/
        ├── unit/
        │   ├── ChatWorkspace.test.tsx
        │   ├── PrivacyReview.test.tsx
        │   └── FileUpload.test.tsx
        └── e2e/
            ├── successful-flow.spec.ts
            ├── blocked-secret.spec.ts
            └── session-lifecycle.spec.ts

Place tests beside source only if that is already the project convention. Fixtures must contain fabricated data and fake secrets only.

## 5. Critical user flows

### Flow A — Upload, review, approve, and receive an answer

Steps:

1. Create a session and upload a synthetic text PDF, scanned PDF, or image.
2. Enter a question in the same chat.
3. Confirm local extraction/OCR and local Gemma analysis complete; Gemma requests an allowlisted tool through native tool calling.
4. Review findings, redactions, the exact sanitized request, and the named answer provider.
5. Approve the current request.
6. Receive the mocked provider answer in the same chat.

Expected result:

- Original file content and placeholder mappings remain local.
- The provider mock is called exactly once with the exact approved sanitized request.
- The answer is displayed without exposing the original source to the provider.

### Flow B — High-risk secret is blocked

Steps:

1. Upload a synthetic document containing TEST_SECRET_DO_NOT_SEND_12345.
2. Ask a question that does not require the secret.
3. Review the privacy result and attempt to proceed.

Expected result:

- The secret is blocked from the outbound draft.
- If a blocking secret remains, approval is unavailable.
- The provider mock receives zero calls and the secret never appears in logs.

### Flow C — Edit invalidates review and approval

Steps:

1. Reach the review screen with a passing sanitized draft.
2. Edit the question or sanitized request.
3. Attempt to use the previous approval state.

Expected result:

- The draft version changes and prior privacy review/approval is invalidated.
- Required checks run again.
- No provider call occurs until the changed request is revalidated and explicitly approved.

### Flow D — Cancel or clear the session

Steps:

1. Reach the review screen and cancel, or clear the active session.
2. Attempt to read or approve the old workflow.

Expected result:

- The request is cancelled or the session is cleared.
- The old approval cannot be reused.
- No not-yet-started provider call occurs.
- Session data and app-owned temporary files are removed.

### Flow E — Fail closed

Steps:

1. Simulate an unreadable file, OCR failure, unavailable local Gemma, malformed/unknown tool call, detector failure, or failed residual check.
2. Continue through the UI as far as possible.

Expected result:

- The UI reports a useful failure and recovery action.
- The workflow cannot be approved.
- The provider mock receives zero calls; no fallback sends raw text.

### Flow F — Session and local-service isolation

Steps:

1. Start two separate sessions.
2. Try to access one session's document or workflow using the other session.
3. Send a mutation from an unexpected Origin or Host.

Expected result:

- Cross-session access and unexpected origins/hosts are rejected.
- No document content is returned and no provider call occurs.

### Flow G — Keyboard and responsive review

Steps:

1. Open the review flow at desktop and narrow/mobile widths.
2. Navigate findings, request preview, provider destination, and actions using only the keyboard.

Expected result:

- Focus is visible and follows a logical order.
- Approve, edit, and cancel remain understandable and operable.
- The provider destination and exact request remain available before approval.

## 6. Coverage

Practical target:

- Reach at least **80% line coverage** across backend privacy, workflow/approval, and session modules.
- Exercise every success and rejection branch of the approval gate, including stale draft, blocked secret, failed check, expired session, cancellation, replay, and concurrent/double approval.
- Cover the main UI states and every critical journey listed above. Do not chase a high whole-repository percentage by adding low-value tests.

Coverage is supporting evidence, not a substitute for assertions about actual behavior. The provider-boundary tests must verify call count and payload content directly.

## 7. Commands

The commands below assume the architecture's frontend/ and backend/ folders. Keep equivalent scripts documented if the actual repository uses a different layout.

Test:

- Backend unit and integration: `cd backend && python -m pytest tests -q`
- Frontend unit/component: `cd frontend && npm run test -- --run`
- Browser E2E: `cd frontend && npx playwright test`
- Coverage report: `cd backend && python -m pytest tests --cov=app.privacy --cov=app.orchestrator --cov=app.sessions --cov-branch --cov-report=term-missing`

Lint:

- Backend: `cd backend && python -m ruff check .`
- Frontend: `cd frontend && npm run lint`

Build:

- Frontend production build: `cd frontend && npm run build`

Type check:

- Backend: `cd backend && python -m mypy app`
- Frontend: `cd frontend && npm run typecheck`

The frontend package scripts should map test to Vitest, lint to ESLint, typecheck to the TypeScript compiler with no emit, and build to Vite. Add pytest-cov, Ruff, and mypy to the backend development dependencies if they are not already present. Do not mark a command as passing unless it was actually run.

Optional demo-machine smoke checks:

- Run the documented local OCR test with Tesseract installed.
- Run the opt-in Ollama/Gemma tool-call compatibility test with the selected Gemma model available.
- Keep both out of normal CI if those local system dependencies are not installed there.

## 8. Definition of Done

- [ ] Backend unit and integration tests pass.
- [ ] Frontend unit/component tests pass.
- [ ] Critical Playwright flows pass against the local app.
- [ ] Local OCR smoke tests pass on synthetic image and scanned-PDF fixtures.
- [ ] The configured Gemma model passes the native tool-call smoke test on the demo machine.
- [ ] Provider mock records zero calls before approval, after cancel, after a blocking finding, and after a failed check.
- [ ] Provider mock receives exactly the approved sanitized request, with no original text, blocked secret, or placeholder mapping.
- [ ] Editing invalidates the old review and approval; double approval causes at most one provider call.
- [ ] Session isolation, expiry, Clear Session, and temporary-file cleanup pass.
- [ ] Unexpected local origins/hosts are rejected.
- [ ] Lint, frontend build, and frontend/backend type checks pass.
- [ ] Keyboard navigation, visible focus, and responsive review flow are verified.
- [ ] Fixtures are synthetic; no real credentials or personal documents are used.
- [ ] README documents test commands and optional local model/OCR setup.

Do not declare the product tested based only on static inspection, screenshots, or a successful build. Passing tests do not prove perfect detection or guarantee that no identifying clue remains in a sanitized request.

