from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.tools.registry import ToolRegistry


ORIGIN = {"Origin": "http://127.0.0.1:5173"}
SAMPLE = "Salary is 80000 annually and contact alice@example.com and Password: TEST_SECRET_DO_NOT_SEND_12345."


def tool(name, arguments=None):
    return {"function": {"name": name, "arguments": arguments or {}}}


async def fake_local_workflow(self, context, registry):
    calls = [
        tool("inspect_document", {"terms": ["salary"]}),
        tool("detect_sensitive_data"),
        tool("select_relevant_content"),
        tool("propose_sanitized_request"),
        tool("review_residual_risk", {"risk_categories": []}),
    ]
    for call in calls:
        registry.execute(call, context)
    return context


@pytest.fixture
def client(monkeypatch):
    main.sessions.items.clear()
    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", fake_local_workflow)
    monkeypatch.setattr(main.OllamaAnalyzer, "review_edited_draft", lambda self, question, draft: _async_flags())
    monkeypatch.setattr(main, "settings", replace(
        main.settings,
        answer_provider_name="Test Provider",
        answer_provider_url="https://example.test/v1/chat/completions",
        answer_provider_model="test-model",
        answer_provider_api_key="test-key-not-a-real-credential",
    ))
    with TestClient(main.app) as test_client:
        yield test_client
    main.sessions.items.clear()


async def _async_flags():
    return ("unique_fact",)


def start_workflow(client):
    session_id = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    document = client.post(
        f"/api/v1/sessions/{session_id}/documents",
        headers=ORIGIN,
        json={"pasted_text": SAMPLE},
    ).json()
    review = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        headers=ORIGIN,
        json={"document_id": document["document_id"], "question": "What is the salary?"},
    )
    assert review.status_code == 200, review.text
    return session_id, review.json()


def test_question_only_runs_local_and_provider_receives_exact_approved_sanitized_draft(client, monkeypatch):
    sent = []

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            sent.append(approved)
            return "The salary is 80000 annually."

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FakeProvider)
    session_id, review = start_workflow(client)
    assert sent == []
    assert "TEST_SECRET_DO_NOT_SEND_12345" not in review["draft"]
    assert "alice@example.com" not in review["draft"]
    assert review["provider"]["name"] == "Test Provider"

    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"], "restore_placeholders": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["history_saved"] is True
    assert len(sent) == 1
    assert sent[0].content == review["draft"]
    assert sent[0].provider_name == "Test Provider"
    assert "TEST_SECRET_DO_NOT_SEND_12345" not in sent[0].content
    assert "alice@example.com" not in sent[0].content

    replay = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert replay.status_code == 409
    assert len(sent) == 1
    history = client.get(
        f"/api/v1/conversations/{main.sessions.items[session_id].conversation_id}",
        headers=ORIGIN,
    ).json()
    assert [message["role"] for message in history["messages"]] == ["user", "assistant"]
    assert history["messages"][0]["content"] == "What is the salary?"
    assert history["messages"][1]["content"] == "The salary is 80000 annually."


def test_edit_requires_fresh_review_and_acknowledgement(client, monkeypatch):
    sent = []

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            sent.append(approved)
            return "Answer"

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FakeProvider)
    session_id, review = start_workflow(client)
    edited = client.patch(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/draft",
        headers=ORIGIN,
        json={"version": review["version"], "draft": "A unique contract detail remains in the request."},
    ).json()
    assert edited["version"] == review["version"] + 1
    assert edited["residual_review"]["status"] == "needs_review"
    assert edited["acknowledged"] is False

    stale = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert stale.status_code == 409
    assert sent == []

    acknowledged = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/acknowledge",
        headers=ORIGIN,
        json={"version": edited["version"]},
    ).json()
    assert acknowledged["acknowledged"] is True
    changed_again = client.patch(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/draft",
        headers=ORIGIN,
        json={"version": acknowledged["version"], "draft": "Another revised request."},
    ).json()
    assert changed_again["acknowledged"] is False
    assert changed_again["version"] == acknowledged["version"] + 1


def test_high_risk_value_added_by_edit_is_blocked(client, monkeypatch):
    sent = []

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            sent.append(approved)
            return "Answer"

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FakeProvider)
    session_id, review = start_workflow(client)
    blocked = client.patch(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/draft",
        headers=ORIGIN,
        json={"version": review["version"], "draft": "Useful fact. Password: SECRET_VALUE_12345."},
    ).json()
    assert blocked["residual_review"]["status"] == "blocked"
    assert blocked["review_complete"] is False
    attempted = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": blocked["version"]},
    )
    assert attempted.status_code == 409
    assert sent == []


def test_cancel_discards_workflow_without_provider_call(client):
    session_id, review = start_workflow(client)
    workflow = main.sessions.items[session_id].workflow
    cancelled = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/cancel",
        headers=ORIGIN,
    )
    assert cancelled.status_code == 200
    assert main.sessions.items[session_id].workflow is None
    assert workflow.question == ""
    assert workflow.draft == ""
    assert workflow.placeholder_map == {}
    stale = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert stale.status_code == 404


def test_unconfigured_provider_cannot_be_approved(client, monkeypatch):
    sent = []

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            sent.append(approved)
            return "Answer"

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FakeProvider)
    monkeypatch.setattr(main, "settings", replace(
        main.settings,
        answer_provider_url="",
        answer_provider_model="",
        answer_provider_api_key="",
    ))
    session_id, review = start_workflow(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert response.status_code == 503
    assert sent == []


def test_failed_provider_call_does_not_persist_sensitive_question_or_answer(client, monkeypatch):
    class FailedProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, _approved):
            raise main.ProviderError("synthetic private provider failure")

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FailedProvider)
    session_id, review = start_workflow(client)
    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN,
        json={"version": review["version"]},
    )
    assert response.status_code == 502
    assert "What is the salary?" not in response.text
    conversation_id = main.sessions.items[session_id].conversation_id
    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN).json()
    assert history["messages"] == []
