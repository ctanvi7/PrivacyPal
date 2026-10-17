"""Run a synthetic, local-only Gemma privacy workflow smoke check.

This script uses only the local PrivacyPal API and synthetic fixture content.
It never calls the configured answer provider: it reviews then cancels.
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ORIGIN = "http://127.0.0.1:5173"
SYNTHETIC_TEXT = (
    "Synthetic workshop begins at 10 AM in Lab 4.\n"
    "Registration contact: test.person@example.test.\n"
    "Fixture-only credential: Password=FAKE_NOT_A_REAL_CREDENTIAL_12345.\n"
    "Unrelated note: the demo printer needs paper."
)
QUESTION = "When does the synthetic workshop begin?"
FAKE_EMAIL = "test.person@example.test"
FAKE_SECRET = "FAKE_NOT_A_REAL_CREDENTIAL_12345"


class SmokeCheckError(RuntimeError):
    """A local API or privacy workflow assertion failed."""


def _request(base_url: str, path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Origin": ORIGIN}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        # Gemma may need longer than a normal API request to complete its
        # five-step local tool workflow, especially on first load.
        with urlopen(request, timeout=180) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        # Only surface the status and route, never the response body.
        raise SmokeCheckError(f"Local PrivacyPal API returned HTTP {exc.code} for {path}.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        # Do not print request/response bodies, which could contain test content.
        raise SmokeCheckError(f"Local PrivacyPal API request failed for {path} ({type(exc).__name__}).") from exc
    if not isinstance(result, dict):
        raise SmokeCheckError("Local PrivacyPal API returned an unexpected response.")
    return result


def run(base_url: str) -> None:
    session_id = None
    workflow_id = None
    try:
        health = _request(base_url, "/health")
        if health.get("status") != "ok":
            raise SmokeCheckError("The local API health check did not pass.")

        session = _request(base_url, "/api/v1/sessions", method="POST", payload={})
        session_id = session.get("session_id")
        if not isinstance(session_id, str):
            raise SmokeCheckError("The local API did not create a session.")

        document = _request(
            base_url,
            f"/api/v1/sessions/{session_id}/documents",
            method="POST",
            payload={"pasted_text": SYNTHETIC_TEXT},
        )
        document_id = document.get("document_id")
        if not isinstance(document_id, str):
            raise SmokeCheckError("The local API did not accept the synthetic text fixture.")

        review = _request(
            base_url,
            f"/api/v1/sessions/{session_id}/questions",
            method="POST",
            payload={"document_id": document_id, "question": QUESTION},
        )
        workflow_id = review.get("workflow_id")
        if not isinstance(workflow_id, str):
            raise SmokeCheckError("Gemma did not return a review workflow.")

        draft = review.get("draft")
        residual = review.get("residual_review", {})
        if not isinstance(draft, str) or not draft.strip():
            raise SmokeCheckError("The workflow returned an empty draft.")
        if review.get("review_complete") is not True:
            raise SmokeCheckError("A required local privacy review did not complete.")
        if residual.get("status") not in {"ready_for_user_review", "needs_review"}:
            raise SmokeCheckError("The local residual-risk review did not reach a user-review state.")
        if "10 AM" not in draft or "demo printer" in draft.casefold():
            raise SmokeCheckError("The draft did not keep the relevant fact while excluding unrelated text.")
        if FAKE_EMAIL in draft or FAKE_SECRET in draft:
            raise SmokeCheckError("A synthetic sensitive value remained in the sanitized draft.")

        cancelled = _request(
            base_url,
            f"/api/v1/sessions/{session_id}/workflows/{workflow_id}/cancel",
            method="POST",
            payload={},
        )
        if cancelled.get("status") != "cancelled":
            raise SmokeCheckError("The workflow could not be cancelled cleanly.")

        print("PASS: local API responded and created a session.")
        print("PASS: Gemma completed the local privacy workflow and returned a reviewable draft.")
        print("PASS: the relevant workshop time remained; unrelated and synthetic sensitive values were excluded.")
        print("PASS: the workflow was cancelled without approving or calling an answer provider.")
        print(f"Residual review status: {residual['status']} (review every draft yourself).")
    finally:
        if session_id:
            # Always clear the temporary local session, including on assertion failure.
            try:
                _request(base_url, f"/api/v1/sessions/{session_id}/clear", method="POST", payload={})
            except SmokeCheckError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Local PrivacyPal backend URL")
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path or parsed.query or parsed.fragment:
        print("ERROR: --base-url must be a local HTTP origin such as http://127.0.0.1:8000.", file=sys.stderr)
        return 2
    try:
        run(args.base_url.rstrip("/"))
    except SmokeCheckError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
