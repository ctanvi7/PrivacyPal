from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.extraction.document_service import ExtractedDocument, PageText
from app.main import Session, app, sessions
from app.model.ollama_adapter import ModelError
from app.privacy.pipeline import ResidualReview
from app.provider.answer_provider import ProviderError


ORIGIN = {"Origin": "http://127.0.0.1:5173"}
SOURCE_TEXT = "Synthetic monthly report: rent is 1200 and utilities are 180."


def _tool(name: str, arguments: dict | None = None) -> dict:
    return {"function": {"name": name, "arguments": arguments or {}}}


async def _fake_local_workflow(_self, context, registry):
    calls = [
        _tool("inspect_document", {"terms": ["rent"]}),
        _tool("detect_sensitive_data"),
        _tool("select_relevant_content"),
        _tool("propose_sanitized_request"),
        _tool("review_residual_risk", {"risk_categories": []}),
    ]
    for call in calls:
        registry.execute(call, context)
    return context


async def _fake_edited_review(_self, _question: str, _draft: str):
    return ()


class FakeProvider:
    answer_text = "Synthetic provider answer"
    failure: Exception | None = None
    calls: list[str] = []

    def __init__(self, **_kwargs):
        pass

    async def send(self, approved):
        self.calls.append(approved.content)
        if self.failure:
            raise self.failure
        return self.answer_text


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    sessions.items.clear()
    FakeProvider.calls = []
    FakeProvider.failure = None
    FakeProvider.answer_text = "Synthetic provider answer"
    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", _fake_local_workflow)
    monkeypatch.setattr(main.OllamaAnalyzer, "review_edited_draft", _fake_edited_review)
    monkeypatch.setattr(main, "OpenAICompatibleProvider", FakeProvider)
    monkeypatch.setattr(
        main,
        "settings",
        replace(
            main.settings,
            answer_provider_name="Test Provider",
            answer_provider_url="https://example.test/v1/chat/completions",
            answer_provider_model="test-model",
            answer_provider_api_key="test-only-key",
        ),
    )
    with TestClient(app) as test_client:
        yield test_client
    sessions.items.clear()


def _session_and_draft(
    client: TestClient,
    source_text: str = SOURCE_TEXT,
    question: str = "What are the monthly costs?",
) -> tuple[str, dict]:
    session_response = client.post("/api/v1/sessions", headers=ORIGIN)
    session_data = session_response.json()
    session_id = session_data["session_id"]
    sessions.items[session_id] = Session(
        document_id="synthetic-document",
        document=ExtractedDocument((PageText(1, source_text),), "pdf"),
        touched_at=time.monotonic(),
        conversation_id=session_data["conversation_id"],
    )
    response = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        headers=ORIGIN,
        json={"document_id": "synthetic-document", "question": question},
    )
    assert response.status_code == 200, response.text
    return session_id, response.json()


def test_unapproved_and_cancelled_workflow_never_calls_provider(client: TestClient):
    session_id, review = _session_and_draft(client)
    cancelled = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/cancel",
        headers=ORIGIN,
    )
    assert cancelled.status_code == 200
    approve = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert approve.status_code == 404
    assert FakeProvider.calls == []


def test_approval_sends_exact_current_draft_once_and_persists_answer(client: TestClient):
    session_id, review = _session_and_draft(client)
    expected = "Summarize the monthly costs without identifying the source."
    edited = client.patch(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/draft",
        headers=ORIGIN,
        json={"version": review["version"], "draft": expected},
    )
    assert edited.status_code == 200
    assert edited.json()["draft"] == expected
    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": edited.json()["version"]},
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "Synthetic provider answer"
    assert response.json()["history_saved"] is True
    assert FakeProvider.calls == [expected]
    active_session = sessions.items[session_id]
    assert active_session.document is None
    assert active_session.document_id is None
    assert active_session.workflow.question == ""
    assert active_session.workflow.draft == ""

    replay = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert replay.status_code == 409
    assert FakeProvider.calls == [expected]
    history = client.get(
        f"/api/v1/conversations/{sessions.items[session_id].conversation_id}", headers=ORIGIN
    ).json()
    assert [message["role"] for message in history["messages"]] == ["user", "assistant"]


def test_stale_draft_version_cannot_be_approved(client: TestClient):
    session_id, review = _session_and_draft(client)
    edited = client.patch(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/draft",
        headers=ORIGIN,
        json={"version": review["version"], "draft": "A safe revised monthly cost summary."},
    )
    assert edited.status_code == 200
    stale = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert stale.status_code == 409
    assert FakeProvider.calls == []


def test_high_risk_secret_blocks_approval_and_never_reaches_provider(client: TestClient):
    session_id, review = _session_and_draft(client)
    secret = "synthetic-api-key-DO_NOT_SEND-12345"
    edited = client.patch(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/draft",
        headers=ORIGIN,
        json={
            "version": review["version"],
            "draft": f"Safe monthly summary. API key: {secret}",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["residual_review"]["status"] == "blocked"

    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": edited.json()["version"]},
    )
    assert response.status_code == 409
    assert secret not in response.text
    assert FakeProvider.calls == []
    conversation_id = sessions.items[session_id].conversation_id
    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN).json()
    assert history["messages"] == []


def test_document_analysis_rejects_detected_high_risk_secret_safely(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    secret = "synthetic-api-key-DO_NOT_SEND-12345"

    async def reject_detected_secret(_self, context, registry):
        # Run the real deterministic detector against synthetic document text.
        registry.execute(_tool("detect_sensitive_data"), context)
        assert context.scan is not None
        assert any(
            item.category == "credential" and item.action == "block"
            for item in context.scan.findings
        )
        raise ModelError("A high-risk value was detected during local analysis.")

    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", reject_detected_secret)
    session_response = client.post("/api/v1/sessions", headers=ORIGIN)
    session_data = session_response.json()
    session_id = session_data["session_id"]
    sessions.items[session_id] = Session(
        document_id="synthetic-document",
        document=ExtractedDocument((PageText(1, f"Monthly report. API key: {secret}"),), "pdf"),
        touched_at=time.monotonic(),
        conversation_id=session_data["conversation_id"],
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        headers=ORIGIN,
        json={"document_id": "synthetic-document", "question": "Summarize this report."},
    )

    assert response.status_code == 503
    assert secret not in response.text
    assert "No request was sent externally." in response.text
    assert FakeProvider.calls == []
    conversation_id = session_data["conversation_id"]
    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN)
    assert history.status_code == 200
    assert history.json()["messages"] == []


def test_incomplete_review_cannot_be_approved(client: TestClient):
    session_id, review = _session_and_draft(client)
    workflow = sessions.items[session_id].workflow
    workflow.review_complete = False
    workflow.residual = ResidualReview("blocked", (), ("Synthetic blocked review.",))
    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert response.status_code == 409
    assert FakeProvider.calls == []


def test_provider_failure_consumes_approval_without_retry(client: TestClient):
    FakeProvider.failure = ProviderError("synthetic private provider response")
    session_id, review = _session_and_draft(client)
    path = f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve"
    response = client.post(path, headers=ORIGIN, json={"version": review["version"]})
    retry = client.post(path, headers=ORIGIN, json={"version": review["version"]})

    assert response.status_code == 502
    assert "synthetic private provider response" not in response.text
    assert retry.status_code == 409
    assert len(FakeProvider.calls) == 1
    assert sessions.items[session_id].document is None
    conversation_id = sessions.items[session_id].conversation_id
    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN).json()
    assert history["messages"] == []


def test_high_risk_provider_answer_is_withheld_and_not_persisted(client: TestClient):
    secret = "synthetic-api-key-DO_NOT_SEND-12345"
    FakeProvider.answer_text = f"The document contains API key: {secret}"
    session_id, review = _session_and_draft(client)

    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    retry = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )

    assert response.status_code == 502
    assert secret not in response.text
    assert retry.status_code == 409
    assert FakeProvider.calls == [review["draft"]]
    conversation_id = sessions.items[session_id].conversation_id
    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN).json()
    assert history["messages"] == []


def test_missing_provider_configuration_blocks_approval(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, answer_provider_url="", answer_provider_model="", answer_provider_api_key=""),
    )
    session_id, review = _session_and_draft(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert response.status_code == 503
    assert FakeProvider.calls == []
