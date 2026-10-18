"""Approval invariants against the current workflow API with synthetic adapters."""

from dataclasses import dataclass, field, replace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.provider.answer_provider import ProviderError

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
SOURCE_TEXT = "Monthly costs are 1200. Contact alice@example.com. Password: TEST_SECRET_DO_NOT_SEND_12345."


@dataclass
class FakeProvider:
    failure: Exception | None = None
    calls: list[str] = field(default_factory=list)

    async def send(self, approved):
        self.calls.append(approved.content)
        if self.failure is not None:
            raise self.failure
        return "Synthetic provider answer"


async def fake_local_workflow(_self, context, registry):
    for name, arguments in (
        ("inspect_document", {"terms": ["costs"]}),
        ("detect_sensitive_data", {}),
        ("select_relevant_content", {}),
        ("propose_sanitized_request", {}),
        ("review_residual_risk", {"risk_categories": []}),
    ):
        registry.execute({"function": {"name": name, "arguments": arguments}}, context)
    return context


async def fake_edit_review(_self, _question, _draft):
    return ()


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(main, "OpenAICompatibleProvider", lambda **_kwargs: fake)
    return fake


@pytest.fixture
def client(monkeypatch, provider):
    main.sessions.items.clear()
    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", fake_local_workflow)
    monkeypatch.setattr(main.OllamaAnalyzer, "review_edited_draft", fake_edit_review)
    monkeypatch.setattr(main, "settings", replace(
        main.settings, answer_provider_url="https://example.test/v1",
        answer_provider_model="test-model", answer_provider_api_key="synthetic-key",
    ))
    with TestClient(main.app) as test_client:
        yield test_client
    main.sessions.items.clear()


def session_and_draft(client):
    session_id = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    document = client.post(
        f"/api/v1/sessions/{session_id}/documents", headers=ORIGIN,
        json={"pasted_text": SOURCE_TEXT},
    ).json()
    response = client.post(
        f"/api/v1/sessions/{session_id}/questions", headers=ORIGIN,
        json={"document_id": document["document_id"], "question": "What are the monthly costs?"},
    )
    assert response.status_code == 200
    review = response.json()
    return f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}", review


def test_unapproved_and_cancelled_request_never_calls_provider(client, provider):
    url, review = session_and_draft(client)
    assert provider.calls == []
    assert client.post(f"{url}/cancel", headers=ORIGIN).status_code == 200
    response = client.post(f"{url}/approve", headers=ORIGIN, json={"version": review["version"]})
    assert response.status_code == 404
    assert provider.calls == []


def test_approval_sends_only_exact_approved_text(client, provider):
    url, review = session_and_draft(client)
    edit_text = "Summarize the monthly costs without identifying the source."
    edited = client.patch(f"{url}/draft", headers=ORIGIN, json={"version": review["version"], "draft": edit_text})
    assert edited.status_code == 200
    assert provider.calls == []
    version = edited.json()["version"]
    response = client.post(f"{url}/approve", headers=ORIGIN, json={"version": version})
    assert response.status_code == 200
    assert response.json()["answer"] == "Synthetic provider answer"
    assert provider.calls == [edit_text]
    assert SOURCE_TEXT not in provider.calls[0]
    changed = client.patch(f"{url}/draft", headers=ORIGIN, json={"version": version, "draft": "Changed after approval."})
    assert changed.status_code == 409
    assert provider.calls == [edit_text]


def test_stale_approval_version_does_not_call_provider(client, provider):
    url, review = session_and_draft(client)
    edited = client.patch(f"{url}/draft", headers=ORIGIN, json={"version": review["version"], "draft": "A revised safe summary."})
    assert edited.status_code == 200
    response = client.post(f"{url}/approve", headers=ORIGIN, json={"version": review["version"]})
    assert response.status_code == 409
    assert provider.calls == []


def test_high_risk_secret_fails_review_and_never_calls_provider(client, provider):
    url, review = session_and_draft(client)
    edited = client.patch(f"{url}/draft", headers=ORIGIN, json={
        "version": review["version"], "draft": "Password: TEST_SECRET_DO_NOT_SEND_12345.",
    })
    assert edited.status_code == 200
    assert edited.json()["residual_review"]["status"] == "blocked"
    response = client.post(f"{url}/approve", headers=ORIGIN, json={"version": edited.json()["version"]})
    assert response.status_code == 409
    assert "TEST_SECRET_DO_NOT_SEND_12345" not in response.text
    assert provider.calls == []


def test_provider_failure_is_safe_and_not_retried(client, provider):
    provider.failure = ProviderError("synthetic private provider failure")
    url, review = session_and_draft(client)
    response = client.post(f"{url}/approve", headers=ORIGIN, json={"version": review["version"]})
    retry = client.post(f"{url}/approve", headers=ORIGIN, json={"version": review["version"]})
    assert response.status_code == 502
    assert "cannot be retried" in response.text
    assert "synthetic private provider failure" not in response.text
    assert retry.status_code == 409
    assert len(provider.calls) == 1


def test_missing_provider_configuration_fails_without_sending(client, provider, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, answer_provider_api_key=""))
    url, review = session_and_draft(client)
    assert review["provider"]["configured"] is False
    response = client.post(f"{url}/approve", headers=ORIGIN, json={"version": review["version"]})
    assert response.status_code == 503
    assert "Configure the answer provider" in response.text
    assert provider.calls == []
