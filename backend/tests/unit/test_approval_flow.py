from __future__ import annotations

from dataclasses import dataclass
import time

import pytest
from fastapi.testclient import TestClient

from app.extraction.document_service import ExtractedDocument, PageText
from app.main import Session, app, sessions
from app.model.ollama_adapter import Analysis

ORIGIN = "http://127.0.0.1:5173"
SOURCE_TEXT = "Private original document text which must never reach the provider."


@dataclass
class FakeProvider:
    answer_text: str = "Synthetic provider answer"
    failure: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[str] = []

    async def answer(self, approved_text: str) -> str:
        self.calls.append(approved_text)
        if self.failure is not None:
            raise self.failure
        return self.answer_text


class FakeAnalyzer:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def analyze(self, _question: str, _pages: list[dict[str, object]]) -> Analysis:
        return Analysis(answer="The synthetic monthly total is 1200.", pages_used=(1,))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sessions.items.clear()
    app.state.answer_provider = None
    monkeypatch.setattr("app.main.OllamaAnalyzer", FakeAnalyzer)
    with TestClient(app) as test_client:
        yield test_client
    sessions.items.clear()
    app.state.answer_provider = None


def _headers() -> dict[str, str]:
    return {"Origin": ORIGIN}


def _session_and_draft(client: TestClient) -> tuple[str, dict[str, object]]:
    session_response = client.post("/api/v1/sessions", headers=_headers())
    session_id = session_response.json()["session_id"]
    sessions.items[session_id] = Session(
        document_id="synthetic-document",
        document=ExtractedDocument((PageText(1, SOURCE_TEXT),), "pdf"),
        touched_at=time.monotonic(),
    )
    draft_response = client.post(
        f"/api/v1/sessions/{session_id}/requests",
        headers=_headers(),
        json={"document_id": "synthetic-document", "question": "What is the monthly total?"},
    )
    assert draft_response.status_code == 201
    return session_id, draft_response.json()


def test_unapproved_and_cancelled_request_never_calls_provider(client: TestClient) -> None:
    provider = FakeProvider()
    app.state.answer_provider = provider
    session_id, draft = _session_and_draft(client)

    cancel_response = client.post(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}/cancel",
        headers=_headers(),
    )
    assert cancel_response.status_code == 200
    approve_response = client.post(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}/approve",
        headers=_headers(),
        json={"draft_version": 1, "approved": True},
    )

    assert approve_response.status_code == 409
    assert provider.calls == []


def test_approval_sends_only_exact_approved_text(client: TestClient) -> None:
    provider = FakeProvider()
    app.state.answer_provider = provider
    session_id, draft = _session_and_draft(client)
    edit_text = "Summarize the monthly costs without identifying the source."
    edited = client.patch(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}",
        headers=_headers(),
        json={"expected_draft_version": 1, "proposed_request": edit_text},
    )
    assert edited.status_code == 200

    response = client.post(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}/approve",
        headers=_headers(),
        json={"draft_version": 2, "approved": True},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Synthetic provider answer"
    assert provider.calls == [edit_text]
    assert SOURCE_TEXT not in provider.calls[0]
    changed_after_approval = client.patch(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}",
        headers=_headers(),
        json={"expected_draft_version": 2, "proposed_request": "Changed after approval."},
    )
    assert changed_after_approval.status_code == 409
    assert provider.calls == [edit_text]


def test_stale_approval_version_does_not_call_provider(client: TestClient) -> None:
    provider = FakeProvider()
    app.state.answer_provider = provider
    session_id, draft = _session_and_draft(client)
    client.patch(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}",
        headers=_headers(),
        json={"expected_draft_version": 1, "proposed_request": "A revised safe summary."},
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}/approve",
        headers=_headers(),
        json={"draft_version": 1, "approved": True},
    )

    assert response.status_code == 409
    assert provider.calls == []


def test_high_risk_secret_fails_review_and_never_calls_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider()
    app.state.answer_provider = provider

    class SecretAnalyzer(FakeAnalyzer):
        async def analyze(self, _question: str, _pages: list[dict[str, object]]) -> Analysis:
            return Analysis(answer="The document includes api_key=synthetic-secret-value", pages_used=(1,))

    monkeypatch.setattr("app.main.OllamaAnalyzer", SecretAnalyzer)
    session_response = client.post("/api/v1/sessions", headers=_headers())
    session_id = session_response.json()["session_id"]
    sessions.items[session_id] = Session(
        document_id="synthetic-document",
        document=ExtractedDocument((PageText(1, SOURCE_TEXT),), "pdf"),
        touched_at=time.monotonic(),
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/requests",
        headers=_headers(),
        json={"document_id": "synthetic-document", "question": "What is the total?"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PRIVACY_CHECK_FAILED"
    assert "synthetic-secret-value" not in response.text
    assert provider.calls == []


def test_provider_failure_is_safe_and_not_retried(client: TestClient) -> None:
    from app.answer_provider import AnswerProviderError

    provider = FakeProvider(failure=AnswerProviderError())
    app.state.answer_provider = provider
    session_id, draft = _session_and_draft(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}/approve",
        headers=_headers(),
        json={"draft_version": 1, "approved": True},
    )
    retry = client.post(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}/approve",
        headers=_headers(),
        json={"draft_version": 1, "approved": True},
    )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "ANSWER_PROVIDER_FAILED",
            "message": "The answer provider could not complete the request.",
        }
    }
    assert "synthetic provider failure" not in response.text
    assert retry.status_code == 409
    assert len(provider.calls) == 1


def test_missing_provider_configuration_fails_without_sending(client: TestClient) -> None:
    session_id, draft = _session_and_draft(client)

    response = client.post(
        f"/api/v1/sessions/{session_id}/requests/{draft['request_id']}/approve",
        headers=_headers(),
        json={"draft_version": 1, "approved": True},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ANSWER_PROVIDER_NOT_CONFIGURED"
    assert response.json()["error"]["message"] == (
        "Select an answer provider and configure its server-side credentials before approval."
    )
