# PrivacyPal frontend

Run the current React frontend from PowerShell:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

The initial screen is a genuine empty chat. Select **Rent affordability** in the sidebar to open the clearly labeled illustrative preview. The preview uses synthetic values only; its edit and approval controls do not send data. Selecting a file keeps it in the browser and shows a pending state.

## Backend integration status

The `backend/app` directories currently contain placeholders only. There is no implemented API, so the frontend cannot upload or analyze documents, prepare a real privacy review, or request an answer. The API route outline in the root `ARCHITECTURE.md` is a design contract, not a running service or a complete request/response schema. The current UI therefore keeps file selection local and question submission fail-closed with a connection-pending message. Sample conversation data remains explicitly illustrative.

## API transport and workflow model

`src/lib/apiClient.js` provides a transport-only Fetch client with JSON and text response handling, safe HTTP/network error messages, cancellation, and a configurable timeout. It does not define or call upload, analysis, review, edit, approval, or answer routes. Its default base URL is `http://127.0.0.1:8000`; set `VITE_PRIVACYPAL_API_BASE_URL` in the Vite environment to use another local backend URL. Vite environment values are included at build time, so this variable must contain only a non-secret API URL. The UI does not call this transport until the backend contract is confirmed.

`src/lib/workflow.js` defines the frontend workflow transitions and recoverable upload, processing, approval, and network error states. At present the UI uses it to track validated document selection; later processing states are modelled and tested but are not presented as completed backend work.

`src/lib/documentUploadController.js` owns local selected-file state separately from `uploadedDocument`, which is populated only when an injected uploader resolves after server confirmation. It handles validation, duplicate-submit prevention, cancellation, timeout, retry, reset, and safe errors. The UI currently uses its selection/reset behavior only. There is intentionally no uploader configured, so the app does not send the file or show a false upload success. When the backend contract is ready, implement a small contract-specific `uploadDocument(file, { signal })` adapter and inject it into this controller; do not add route or multipart assumptions to the controller itself. Progress is not shown because no confirmed progress contract exists.

`src/lib/questionController.js` requires a server-confirmed `uploadedDocument` before it invokes an injected analysis function. It validates empty questions, blocks duplicate in-flight submissions, and tracks processing, cancellation, unavailable, and recoverable error states. The UI has no analysis callback configured, so selected local files cannot trigger real analysis.

`src/lib/privacyReview.js` documents the canonical review model and requires an explicit adapter from the eventual backend schema. The adapter maps original request text, proposed and exact outgoing text, keep/mask/replace recommendations with reasons, and opaque backend-supplied risk flags. A caller must explicitly identify the input as backend-originated; the illustrative sidebar conversation does not pass through this path. `src/components/PrivacyReviewPanel.jsx` presents only a normalized backend review, displays the exact editable outgoing text, and keeps approval separate from editing. The controller requires a separate explicit approval action before calling an injected sender, suppresses duplicate sends, and returns failures to editing without automatically retrying. No review adapter or approval sender is currently configured; the send button stays disabled.

## Tests

Run the dependency-free frontend unit tests with:

```powershell
cd frontend
npm.cmd test
```

## Backend contract needed to enable workflow calls

Before connecting real workflow requests, document and implement:

- Session creation, session cookie and CSRF behavior, expiry, and clear semantics.
- Upload field names, accepted content, size/page limits, and response schema.
- Question submission payload, processing status/polling behavior, and response schema.
- Review finding fields, keep/mask/replace decisions, reasons, risk flags, and the exact proposed outbound request.
- Request edit payload and the revalidation/version behavior after edits.
- Approval payload and server-side approval conditions, plus final answer and citation/reference schema.
- Structured error codes, safe user-facing messages, retryability, and CORS/allowed-origin configuration.

The route outline in the root `ARCHITECTURE.md` is a guide for those contracts, not evidence that any route is currently available.
