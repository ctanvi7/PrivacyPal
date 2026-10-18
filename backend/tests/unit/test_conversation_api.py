from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.extraction.document_service import ExtractedDocument, PageText
from app.main import PrivacyWorkflow, Session, app, sessions


ORIGIN = {"Origin": "http://127.0.0.1:5173"}


@pytest.fixture
def client():
    sessions.items.clear()
    with TestClient(app) as test_client:
        yield test_client
    sessions.items.clear()


def test_create_list_get_delete_conversation(client: TestClient):
    created = client.post("/api/v1/conversations", headers=ORIGIN)
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]

    listed = client.get("/api/v1/conversations", headers=ORIGIN)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["conversation_id"] == conversation_id
    assert listed.json()["items"][0]["preview"] is None

    loaded = client.get(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN)
    assert loaded.status_code == 200
    assert loaded.json()["messages"] == []

    deleted = client.delete(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN)
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/conversations/{conversation_id}", headers=ORIGIN).status_code == 404


def test_session_creation_accepts_optional_conversation_and_preserves_empty_body(client: TestClient):
    created = client.post("/api/v1/conversations", headers=ORIGIN).json()
    attached = client.post(
        "/api/v1/sessions", headers=ORIGIN, json={"conversation_id": created["conversation_id"]}
    )
    assert attached.status_code == 201
    assert attached.json()["conversation_id"] == created["conversation_id"]
    assert sessions.items[attached.json()["session_id"]].conversation_id == created["conversation_id"]

    empty = client.post("/api/v1/sessions", headers=ORIGIN)
    assert empty.status_code == 201
    assert empty.json()["conversation_id"]


def test_delete_conversation_clears_associated_active_session(client: TestClient):
    session = client.post("/api/v1/sessions", headers=ORIGIN).json()
    session_id = session["session_id"]
    active_session = Session(
        document_id="temporary-document-id",
        document=ExtractedDocument((PageText(1, "temporary extracted text"),), "pdf"),
        workflow=PrivacyWorkflow(
            workflow_id="temporary-workflow-id",
            document_id="temporary-document-id",
            question="temporary sensitive question",
            draft="temporary sanitized draft",
            findings=(),
            placeholder_map={"[PERSON_1]": "temporary name"},
        ),
        touched_at=time.monotonic(),
        conversation_id=session["conversation_id"],
    )
    workflow = active_session.workflow
    sessions.items[session_id] = active_session
    deleted = client.delete(
        f"/api/v1/conversations/{session['conversation_id']}", headers=ORIGIN
    )
    assert deleted.status_code == 200
    assert session_id not in sessions.items
    assert active_session.document is None
    assert active_session.document_id is None
    assert active_session.workflow is None
    assert workflow.question == ""
    assert workflow.draft == ""
    assert workflow.placeholder_map == {}


@pytest.mark.parametrize("operation", ["remove_document", "clear_session"])
def test_session_cleanup_clears_sensitive_content(client: TestClient, operation: str):
    session_data = client.post("/api/v1/sessions", headers=ORIGIN).json()
    session_id = session_data["session_id"]
    workflow = PrivacyWorkflow(
        workflow_id="temporary-workflow-id",
        document_id="temporary-document-id",
        question="synthetic sensitive question",
        draft="synthetic sensitive draft",
        findings=(),
        placeholder_map={"[PERSON_1]": "synthetic private value"},
    )
    active_session = Session(
        document_id="temporary-document-id",
        document=ExtractedDocument((PageText(1, "synthetic extracted text"),), "pdf"),
        workflow=workflow,
        touched_at=time.monotonic(),
        conversation_id=session_data["conversation_id"],
    )
    sessions.items[session_id] = active_session

    if operation == "remove_document":
        response = client.delete(
            f"/api/v1/sessions/{session_id}/documents/temporary-document-id", headers=ORIGIN
        )
    else:
        response = client.post(f"/api/v1/sessions/{session_id}/clear", headers=ORIGIN)

    assert response.status_code == 200
    assert active_session.document is None
    assert active_session.document_id is None
    assert workflow.question == ""
    assert workflow.draft == ""
    assert workflow.placeholder_map == {}
    assert workflow.residual is None
    if operation == "remove_document":
        assert active_session.workflow is None
    else:
        assert session_id not in sessions.items


def test_session_expiry_clears_sensitive_content(client: TestClient):
    session_data = client.post("/api/v1/sessions", headers=ORIGIN).json()
    session_id = session_data["session_id"]
    workflow = PrivacyWorkflow(
        workflow_id="temporary-workflow-id",
        document_id="temporary-document-id",
        question="synthetic sensitive question",
        draft="synthetic sensitive draft",
        findings=(),
        placeholder_map={"[PERSON_1]": "synthetic private value"},
    )
    active_session = Session(
        document_id="temporary-document-id",
        document=ExtractedDocument((PageText(1, "synthetic extracted text"),), "pdf"),
        workflow=workflow,
        touched_at=time.monotonic() - sessions.idle_seconds - 1,
        conversation_id=session_data["conversation_id"],
    )
    sessions.items[session_id] = active_session

    with pytest.raises(HTTPException) as expired:
        sessions.get(session_id)
    assert expired.value.status_code == 404

    assert session_id not in sessions.items
    assert active_session.document is None
    assert active_session.document_id is None
    assert workflow.question == ""
    assert workflow.draft == ""
    assert workflow.placeholder_map == {}


def test_partial_delete_failure_reports_cleared_active_state(client: TestClient, monkeypatch):
    session = client.post("/api/v1/sessions", headers=ORIGIN).json()
    session_id = session["session_id"]

    def fail_delete(_conversation_id):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(app.state.conversation_store, "delete", fail_delete)
    response = client.delete(
        f"/api/v1/conversations/{session['conversation_id']}", headers=ORIGIN
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONVERSATION_CLEANUP_INCOMPLETE"
    assert "synthetic storage failure" not in response.text
    assert session_id not in sessions.items


def test_history_pagination_validation_and_local_origin_protection(client: TestClient):
    invalid = client.get("/api/v1/conversations?limit=101")
    assert invalid.status_code == 422
    forbidden = client.post("/api/v1/conversations", headers={"Origin": "https://example.test"})
    assert forbidden.status_code == 403
