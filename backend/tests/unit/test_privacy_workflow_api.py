from dataclasses import replace
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from app.privacy.grounding import GROUNDING_INSTRUCTIONS
import httpx
import json
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


def test_model_busy_returns_pending_review_without_creating_a_draft(client, monkeypatch):
    from app.model.ollama_adapter import ModelBusyError
    async def busy(*_args):
        raise ModelBusyError("Synthetic occupied model")
    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", busy)
    sid = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    document = client.post(f"/api/v1/sessions/{sid}/documents", headers=ORIGIN, json={"pasted_text": SAMPLE}).json()
    result = client.post(f"/api/v1/sessions/{sid}/questions", headers=ORIGIN,
        json={"document_id": document["document_id"], "question": "Explain this please"})
    assert result.status_code == 429
    error = result.json()["error"]
    assert error["code"] == "MODEL_BUSY" and error["retryable"] is True
    assert set(error["local_checks"].values()) == {"pending"}
    assert main.sessions.items[sid].workflow is None
    assert main.sessions.items[sid].analysis_id is None


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


def test_session_cookie_rejects_another_session_id(client):
    first = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    second = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]

    rejected = client.post(
        f"/api/v1/sessions/{first}/clear",
        headers=ORIGIN,
    )

    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "SESSION_OWNERSHIP_REQUIRED"
    assert first in main.sessions.items
    assert second in main.sessions.items


def test_clear_session_removes_all_state_and_expires_ownership_cookie(client):
    session_id, _review = start_workflow(client)
    session = main.sessions.items[session_id]

    response = client.post(f"/api/v1/sessions/{session_id}/clear", headers=ORIGIN)

    assert response.status_code == 200
    assert response.json() == {"status": "cleared"}
    assert session.document is None and session.workflow is None
    assert session_id not in main.sessions.items
    assert client.cookies.get(main.SESSION_COOKIE) is None


def test_document_removal_invalidates_active_workflow(client):
    session_id, review = start_workflow(client)
    session = main.sessions.items[session_id]
    document_id = session.document_id

    response = client.delete(f"/api/v1/sessions/{session_id}/documents/{document_id}", headers=ORIGIN)
    stale_edit = client.patch(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/draft",
        headers=ORIGIN,
        json={"version": review["version"], "draft": "Updated safe summary."},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "removed"}
    assert session.document is None and session.document_id is None and session.workflow is None
    assert stale_edit.status_code == 404


def test_expired_session_is_removed_and_rejected(client):
    session_id, _review = start_workflow(client)
    session = main.sessions.items[session_id]
    session.touched_at = time.monotonic() - main.sessions.idle_seconds - 1

    response = client.post(f"/api/v1/sessions/{session_id}/clear", headers=ORIGIN)

    assert response.status_code == 404
    assert session_id not in main.sessions.items
    assert session.status == "expired"
    assert session.document is None and session.workflow is None


def test_edit_during_provider_call_is_rejected_and_replay_sends_once(client, monkeypatch):
    started, release = Event(), Event()
    calls = []

    class WaitingProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            calls.append(approved.content)
            started.set()
            await asyncio.to_thread(release.wait, 5)
            return "Answer"

    monkeypatch.setattr(main, "OpenAICompatibleProvider", WaitingProvider)
    session_id, review = start_workflow(client)
    url = f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        approval = pool.submit(client.post, f"{url}/approve", headers=ORIGIN, json={"version": review["version"]})
        assert started.wait(3)
        edit = client.patch(f"{url}/draft", headers=ORIGIN, json={"version": review["version"], "draft": "New safe draft."})
        assert edit.status_code == 409
        replay = client.post(f"{url}/approve", headers=ORIGIN, json={"version": review["version"]})
        assert replay.status_code == 409
        release.set()
        assert approval.result(timeout=5).status_code == 200

    assert len(calls) == 1


def test_clear_while_local_analysis_is_running_prevents_workflow_recreation(client, monkeypatch):
    started, release = Event(), Event()

    async def waiting_analysis(_self, context, registry):
        started.set()
        await asyncio.to_thread(release.wait, 5)
        return await fake_local_workflow(_self, context, registry)

    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", waiting_analysis)
    session_id = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    document = client.post(
        f"/api/v1/sessions/{session_id}/documents",
        headers=ORIGIN,
        json={"pasted_text": SAMPLE},
    ).json()
    with ThreadPoolExecutor(max_workers=1) as pool:
        analysis = pool.submit(
            client.post,
            f"/api/v1/sessions/{session_id}/questions",
            headers=ORIGIN,
            json={"document_id": document["document_id"], "question": "What is the salary?"},
        )
        assert started.wait(3)
        cleared = client.post(f"/api/v1/sessions/{session_id}/clear", headers=ORIGIN)
        release.set()
        result = analysis.result(timeout=5)

    assert cleared.status_code == 200
    assert result.status_code == 409
    assert session_id not in main.sessions.items


def test_rejects_duplicate_question_while_local_analysis_is_in_flight(client, monkeypatch):
    started, release = Event(), Event()
    calls = []

    async def waiting_analysis(_self, context, registry):
        calls.append(context.workflow_id)
        if len(calls) == 1:
            started.set()
            await asyncio.to_thread(release.wait, 5)
        return await fake_local_workflow(_self, context, registry)

    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", waiting_analysis)
    session_id = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    document = client.post(
        f"/api/v1/sessions/{session_id}/documents",
        headers=ORIGIN,
        json={"pasted_text": SAMPLE},
    ).json()
    question_url = f"/api/v1/sessions/{session_id}/questions"
    payload = {"document_id": document["document_id"], "question": "What is the salary?"}

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, question_url, headers=ORIGIN, json=payload)
        assert started.wait(3)
        duplicate = client.post(question_url, headers=ORIGIN, json=payload)
        assert duplicate.status_code == 409
        assert "already running" in duplicate.json()["error"]["message"]
        release.set()
        assert first.result(timeout=5).status_code == 200

    retry = client.post(question_url, headers=ORIGIN, json=payload)
    assert retry.status_code == 200
    assert len(calls) == 2


def test_clear_during_provider_request_removes_local_state_without_restoring_it(client, monkeypatch):
    started, release = Event(), Event()
    calls = []

    class WaitingProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            calls.append(approved.content)
            started.set()
            await asyncio.to_thread(release.wait, 5)
            return "Answer already in flight"

    monkeypatch.setattr(main, "OpenAICompatibleProvider", WaitingProvider)
    session_id, review = start_workflow(client)
    approval_url = f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve"
    with ThreadPoolExecutor(max_workers=1) as pool:
        approval = pool.submit(client.post, approval_url, headers=ORIGIN, json={"version": review["version"]})
        assert started.wait(3)
        cleared = client.post(f"/api/v1/sessions/{session_id}/clear", headers=ORIGIN)
        release.set()
        approved = approval.result(timeout=5)

    assert cleared.status_code == 200
    assert approved.status_code == 200
    assert len(calls) == 1
    assert session_id not in main.sessions.items
    assert approved.json()["history_saved"] is False
    history = client.get("/api/v1/conversations", headers=ORIGIN).json()
    assert all(item["preview"] is None for item in history["items"])


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


def test_cancel_discards_workflow_without_provider_call(client, monkeypatch):
    sent = []

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            sent.append(approved)
            return "Answer"

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FakeProvider)
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
    assert sent == []


def test_unrelated_question_fails_closed_without_provider_call(client, monkeypatch):
    sent = []

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, approved):
            sent.append(approved)
            return "Answer"

    monkeypatch.setattr(main, "OpenAICompatibleProvider", FakeProvider)
    session_id = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
    document = client.post(
        f"/api/v1/sessions/{session_id}/documents",
        headers=ORIGIN,
        json={"pasted_text": "The garden has three rose bushes and a small fountain."},
    ).json()

    response = client.post(
        f"/api/v1/sessions/{session_id}/questions",
        headers=ORIGIN,
        json={"document_id": document["document_id"], "question": "What is the account balance?"},
    )

    assert response.status_code == 503
    assert "No request was sent externally." in response.json()["error"]["message"]
    assert sent == []


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


def test_loaded_groq_settings_send_exact_reviewed_draft_and_return_answer(client, monkeypatch, tmp_path):
    import app.config as config

    for name in ("ANSWER_PROVIDER_NAME", "ANSWER_PROVIDER_URL", "ANSWER_PROVIDER_MODEL", "ANSWER_PROVIDER_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANSWER_PROVIDER_MODEL=chosen-test-model\nGROQ_API_KEY=synthetic-key\n")
    monkeypatch.setattr(config, "BACKEND_ENV_FILE", env_file)
    monkeypatch.setattr(main, "settings", config.get_settings())
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "A synthetic answer"}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    session_id, review = start_workflow(client)
    assert review["provider"] == {"id": "default", "name": "Groq", "endpoint": config.GROQ_BASE_URL, "configured": True}
    assert "synthetic-key" not in json.dumps(review)
    assert sent == []
    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN, json={"version": review["version"]},
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "A synthetic answer"
    assert response.json()["send_state"] == "sent"
    assert "synthetic-key" not in response.text
    assert len(sent) == 1
    assert str(sent[0].url) == config.GROQ_BASE_URL + "/chat/completions"
    assert json.loads(sent[0].content) == {
        "model": "chosen-test-model", "stream": False,
        "messages": [{"role": "system", "content": GROUNDING_INSTRUCTIONS}, {"role": "user", "content": review["draft"]}],
    }
    assert SAMPLE not in review["draft"]
    assert "TEST_SECRET_DO_NOT_SEND_12345" not in review["draft"]
    assert "alice@example.com" not in review["draft"]


@pytest.mark.parametrize("missing", ["answer_provider_url", "answer_provider_model", "answer_provider_api_key"])
def test_each_missing_provider_setting_disables_approval(client, monkeypatch, missing):
    monkeypatch.setattr(main, "settings", replace(main.settings, **{missing: ""}))
    session_id, review = start_workflow(client)
    assert review["provider"]["configured"] is False
    response = client.post(
        f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve",
        headers=ORIGIN, json={"version": review["version"]},
    )
    assert response.status_code == 503


def test_uncertain_groq_delivery_consumes_approval_and_prevents_resend(client, monkeypatch):
    sent = []

    def handler(request):
        sent.append(request)
        raise httpx.ReadTimeout("synthetic-key private provider details", request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    session_id, review = start_workflow(client)
    url = f"/api/v1/sessions/{session_id}/workflows/{review['workflow_id']}/approve"
    assert sent == []
    response = client.post(url, headers=ORIGIN, json={"version": review["version"]})
    assert response.status_code == 502
    assert "cannot be retried" in response.text
    assert "synthetic-key" not in response.text
    assert "private provider details" not in response.text
    assert main.sessions.items[session_id].workflow.send_state == "delivery_unknown"
    replay = client.post(url, headers=ORIGIN, json={"version": review["version"]})
    assert replay.status_code == 409
    assert len(sent) == 1


def test_failed_provider_call_does_not_persist_sensitive_question_or_answer(client, monkeypatch):
    class FailedProvider:
        def __init__(self, **_kwargs):
            pass

        async def send(self, _approved):
            raise RuntimeError("synthetic private provider failure")

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
