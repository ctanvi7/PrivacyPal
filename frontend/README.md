# PrivacyPal frontend

Run the React + Vite frontend from PowerShell:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

The empty chat supports selecting a document, uploading it to the local backend, and asking a question after the backend confirms the upload. The sidebar's Rent affordability conversation is illustrative sample data only; its content is never sent to the backend.

## Backend integration

`src/lib/privacyPalApi.js` connects only the implemented backend calls:

- `POST /api/v1/sessions`
- `POST /api/v1/sessions/{session_id}/documents` with one multipart `file` part
- `POST /api/v1/sessions/{session_id}/questions` with `{ document_id, question }`

The browser creates a runtime session before upload. The document is marked uploaded only after the response includes a document ID. Question analysis requires that confirmed document and passes through the actual workflow response. The privacy panel shows the backend's proposed draft, findings, residual review, and metadata as read-only. This question route runs local privacy analysis; it does not send an external answer request.

The API base URL can be set with `VITE_PRIVACYPAL_API_BASE_URL` in the Vite environment. By default, the frontend uses the matching loopback hostname on port 8000 (`localhost` for a `localhost` UI, otherwise `127.0.0.1`) so session cookies remain same-site. Vite variables are public build-time configuration; set only a URL, never credentials. The backend CORS origin defaults to `http://127.0.0.1:5173` (`FRONTEND_ORIGIN`) and accepts its `localhost`/`127.0.0.1` alias on the same port. If those backend settings are changed, configure the frontend URL and allowed origin to match.

Transport errors use backend safe `{ error: { code, message, retryable } }` responses when the message passes a safety check; otherwise a user-safe status message is shown. Network errors, cancellation, timeout, retry, and duplicate-submit states are handled by the shared API client/controllers. Upload progress is shown as an uploading state because the browser Fetch API used here does not report upload progress.

## Tests

```powershell
cd frontend
npm.cmd test
npm.cmd run build
```

## Next integration milestone

The backend also currently implements workflow draft editing, acknowledgement, approval, and answer delivery routes. Those are intentionally not connected by this prompt. They need a separate integration step and tests before the UI offers those operations. The root `docs/API_CONTRACT.md` is still labeled a draft and contains older route examples; use the actual route implementations in `backend/app/main.py` as the source of truth.
