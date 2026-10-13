# PrivacyPal Code Style & AI Agent Guidelines

**Status:** Project-specific baseline for the hackathon MVP
**Product source of truth:** `PrivacyPal_PRD.md`
**Security source of truth:** `SECURITY.md`

This guide records the conventions for PrivacyPal and for code produced with AI coding tools. The checked-in source, package configuration, and tests remain authoritative for implementation details. If the repository later differs from this planned baseline, follow the repository and update this guide.

## 1. Product and architecture boundaries

PrivacyPal is a desktop-first browser app for one local user. The planned stack is:

- **Frontend:** React with Vite.
- **Backend:** Python with FastAPI, running on the same computer and bound to loopback.
- **Local analysis:** Gemma through a local Ollama endpoint.
- **Answer generation:** A configured external AI provider, called by the backend only after explicit user approval.

The main flow is: **upload or paste → ask → local analysis and privacy checks → review exact outbound request → approve or cancel → receive the answer in the same chat**.

Keep these responsibilities separate:

- React renders state and collects user choices. It does not decide whether sensitive data may be sent, store provider secrets, or execute model-requested actions.
- FastAPI validates API inputs, coordinates the workflow, runs approved tools, enforces privacy and approval gates, and calls the selected external provider.
- Gemma may analyze document content and request only the explicitly allowlisted tools. Backend code validates tool names and arguments and decides whether an action is allowed.
- The provider adapter sends only the exact approved sanitized payload. It never receives the original file, extracted source text, or placeholder mapping.

Do not claim that all data stays on-device when an approved sanitized request is sent to an external provider. UI copy must distinguish local analysis and original-file handling from the approved outbound request.

## 2. Naming and file conventions

Follow existing names if the repository has already established a convention. For new code, use:

| Item | Convention |
|---|---|
| React components and component files | PascalCase, e.g. `ReviewRequestCard.jsx` |
| JavaScript variables and functions | camelCase |
| JavaScript constants | UPPER_SNAKE_CASE only for true module-level constants |
| Python modules, functions, and variables | snake_case |
| Python classes and exception types | PascalCase |
| Environment variables | UPPER_SNAKE_CASE |
| Python tests | `test_*.py` |
| Frontend tests | Match the configured test runner; keep names beside the feature or in the established test directory |

Use product terms consistently: **source file**, **extracted text**, **finding**, **sanitized request**, **approval**, **answer provider**, and **placeholder mapping**. Avoid using “redacted file” when the system sends a minimized text request rather than a modified document.

## 3. Structure and dependencies

- Keep UI, API clients, backend routes, workflow orchestration, model adapters, provider adapters, and deterministic privacy checks in clearly separated modules.
- Reuse existing components and utilities. Search before creating a duplicate.
- Do not impose a new folder structure on an existing repository. If scaffolding a new repository, keep the frontend and backend clearly separated.
- Do not add a dependency, framework, formatter, or model provider solely because an AI agent prefers it. Explain material dependencies and keep package lockfiles in sync.
- Do not load remote fonts, scripts, icons, analytics, or other third-party assets in the local-first UI without an explicit product decision and security review.
- Never place provider API keys, local service credentials, or security decisions in the browser bundle.

## 4. Components, APIs, and state

- Use semantic HTML, accessible labels, keyboard interaction, and visible focus states.
- Keep loading, unsupported-file, scan-failed, review-required, cancelled, provider-failed, and success states explicit.
- Keep business rules on the backend. Frontend validation improves usability but never replaces server validation.
- Validate request and response boundaries with the project's existing schema/type tools. Treat file content, model output, provider responses, and client-supplied state as untrusted.
- Do not persist source files, extracted text, findings, prompts, answers, or placeholder mappings in browser local storage, IndexedDB, analytics, or telemetry for the MVP.
- Keep session data in memory where feasible. Any temporary disk data must follow `SECURITY.md` cleanup rules.
- Do not build alternate or mock-only implementations of the critical flow. Test fixtures may use synthetic data, but the demo flow must use the real backend path.

## 5. Workflow and error handling

- Keep functions focused and side effects visible.
- Validate all external and model-generated inputs at the receiving boundary.
- Do not silently swallow errors, return “clean” after a failed scan, or continue after a security-critical check fails.
- If file parsing, Gemma, secret scanning, residual-risk review, approval verification, or provider validation fails, stop the outbound flow and show a safe, actionable error.
- Do not expose stack traces, file paths, document contents, secrets, prompt contents, or internal provider errors to the UI.
- Log only minimized operational metadata as allowed by `SECURITY.md`.

## 6. Testing and security invariants

Tests should use synthetic documents and fake provider responses. Cover at least:

- Successful end-to-end flow from text or text-based PDF through approval and answer.
- High-risk secret blocking, including when Gemma recommends keeping the secret.
- Unknown tool names and invalid tool arguments being rejected.
- Prompt-injection text inside a document not changing policy or triggering tools beyond the allowlist.
- No external call before approval; edits invalidate prior approval; cancellation sends nothing.
- The exact approved payload is the payload delivered to the provider.
- Parser limits and failures, Gemma/provider timeouts, and cleanup on success and failure.
- Placeholder mappings remain local and are cleared with the session.
- Model/provider output is displayed as text, not executable markup.

Use the formatter, linter, type checker, test runner, and build commands configured in the repository. This workspace currently contains the PRD and project guidance but no application package configuration, so command names are intentionally not fabricated here. When the app is scaffolded, record the real commands in the repository and update this section.

## 7. AI coding agent workflow

Before a non-trivial change:

1. Read `PrivacyPal_PRD.md`, this guide, and `SECURITY.md`.
2. Inspect the actual code and configuration before choosing a pattern or dependency.
3. Identify the affected flow, privacy boundary, failure behavior, and tests.
4. Keep the change scoped. Ask for a decision when a requirement truly conflicts or a security policy is not defined.

After implementation:

1. Review the diff for accidental changes, secrets, and personal data.
2. Run the relevant tests, lint/type checks, and build that actually exist.
3. Confirm the approval gate, no-send-on-failure behavior, and data cleanup still hold.
4. Update the source documentation when behavior or configuration changes.
5. Report the files changed, validation performed, and any unresolved decision.

Use synthetic values in prompts, screenshots, tests, and demo fixtures. Never put real documents, passwords, API keys, or private data into an AI coding assistant or source-control issue.

## 8. Definition of done

- [ ] The PRD behavior is implemented without inventing a second flow.
- [ ] Backend validation and security rules remain authoritative.
- [ ] Errors, loading states, and security failures are handled safely.
- [ ] Relevant tests pass, including the security invariants above.
- [ ] Configured formatting, linting, type checks, and build pass.
- [ ] No source documents, secrets, prompts, or mappings are written to logs or unintended storage.
- [ ] Documentation reflects the implementation and its limitations.
