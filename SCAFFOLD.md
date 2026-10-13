# Application scaffold

This repository currently contains product documentation and the initial folder layout. Implement modules according to the root `ARCHITECTURE.md`, `DATABASE.md`, `SECURITY.md`, `design.md`, `CODE_STYLE.md`, and `TESTING.md` documents. No runtime code or dependency configuration is defined yet.

```text
backend/app/       FastAPI application layers and adapters
backend/tests/     Unit/integration tests and synthetic fixtures
frontend/src/      React/Vite client, components, and features
frontend/tests/    Component and browser tests
```

The MVP uses in-memory session state, local extraction/OCR and Gemma, and a server-side answer-provider adapter behind explicit approval. Do not introduce a persistent database or use real documents or credentials in tests.
