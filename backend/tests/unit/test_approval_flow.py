from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.main as main


ORIGIN = {"Origin": "http://127.0.0.1:5173"}


async def fake_local_workflow(self, context, registry):
    calls = [
        {"function": {"name": "inspect_document", "arguments": {"terms": ["salary"]}}},
        {"function": {"name": "detect_sensitive_data", "arguments": {}}},
        {"function": {"name": "select_relevant_content", "arguments": {}}},
        {"function": {"name": "propose_sanitized_request", "arguments": {}}},
        {"function": {"name": "review_residual_risk", "arguments": {"risk_categories": []}}},
    ]
    for call in calls:
        registry.execute(call, context)
    return context


@pytest.fixture
def client(monkeypatch):
    main.sessions.items.clear()
    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", fake_local_workflow)
    with TestClient(main.app) as test_client:
        yield test_client
    main.sessions.items.clear()


def test_provider_failure_consumes_approval_without_retry(client, monkeypatch):
    sent = []

    class FailingProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            sent.append(approved)
            raise main.ProviderError()

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FailingProvider)
    monkeypatch.setattr(main, "settings", replace(
        main.settings,
        answer_provider_name="Test Provider",
        answer_provider_url="https://example.test/v1/chat/completions",
        answer_provider_model="test-model",
        answer_provider_api_key="test-key-not-a-real-credential",
    ))
    main.sessions.items.clear()

    session_id = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    document = client.post(
        f"/api/v1/sessions/{session_id}/documents",
        headers=ORIGIN,
        json={"pasted_text": "Synthetic salary is 80000 annually."},
    ).json()
    review = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        headers=ORIGIN,
        json={"document_id": document["document_id"], "question": "What is the salary?"},
    ).json()

    approval_url = f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve"
    approval = {"version": review["version"], "restore_placeholders": False}
    failed = client.post(approval_url, headers=ORIGIN, json=approval)
    replay = client.post(approval_url, headers=ORIGIN, json=approval)

    assert failed.status_code == 502
    assert replay.status_code == 409
    assert len(sent) == 1
    main.sessions.items.clear()
