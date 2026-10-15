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

## Runtime AI requirement

The pitch flow must use live Gemma tool calls and a real configured answer-model API, with no canned responses or silent mock fallback. Mocks may be used in tests only and must be explicit test configuration; missing or failed runtime configuration must produce a visible error, not substitute a mock.
