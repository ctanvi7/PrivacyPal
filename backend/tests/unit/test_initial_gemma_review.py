"""Initial review uses the real adapter/registry with native Ollama HTTP fixtures."""

import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.model.ollama_adapter as adapter

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
STAGES = ["detect_sensitive_data", "review_residual_risk"]


@pytest.mark.parametrize("failure", [None, "missing_call", "invalid_arguments", "timeout", "placeholder_residual"])
def test_initial_question_review_success_and_fail_closed_native_failures(monkeypatch, caplog, failure):
    main.sessions.items.clear()
    outbound = Mock(side_effect=AssertionError("Provider must not be constructed before approval"))
    monkeypatch.setattr(main, "OpenAICompatibleProvider", outbound)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        assert str(request.url).endswith("/api/chat")
        assert payload["model"] == main.settings.gemma_model
        stage = STAGES[len(requests)]
        assert payload["stream"] is False
        assert payload["think"] is (stage == "review_residual_risk")
        assert payload["options"]["num_predict"] == (adapter.RESIDUAL_MAX_PREDICT if stage == "review_residual_risk" else adapter.DETECTION_MAX_PREDICT if stage == "detect_sensitive_data" else adapter.TOOL_CALL_MAX_PREDICT)
        assert [tool["function"]["name"] for tool in payload["tools"]] == [stage]
        requests.append(stage)
        if stage == "detect_sensitive_data" and failure and failure != "placeholder_residual":
            if failure == "timeout":
                raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_REASONING", request=request)
            if failure == "missing_call":
                return httpx.Response(200, json={"message": {"content": "SYNTHETIC_PRIVATE_REASONING"}})
            arguments = {"unexpected": "SYNTHETIC_PRIVATE_REASONING"}
        else:
            arguments = {"risk_categories": []}
            if stage == "detect_sensitive_data":
                arguments = {"terms": ["attached", "document"], "sensitive_spans": []}
        if stage == "review_residual_risk" and failure == "placeholder_residual":
            arguments = {"risk_categories": [], "sensitive_spans": [{"category": "email", "value": "[EMAIL_1]"}]}
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": "", "tool_calls": [{"function": {"name": stage, "arguments": arguments}}],
        }})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(adapter.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    try:
        with TestClient(main.app) as client:
            sid = client.post("/api/v1/sessions", headers=ORIGIN).json()["session_id"]
            uploaded = client.post(f"/api/v1/sessions/{sid}/documents", headers=ORIGIN, json={"pasted_text":
                "PrivacyPal Synthetic Payment Receipt\nAmount paid: 100 USD\nStatus: Payment received\nContact fixture@example.test"})
            response = client.post(f"/api/v1/sessions/{sid}/questions", headers=ORIGIN,
                json={"document_id": uploaded.json()["document_id"], "question": "Explain the attached document."})
            if failure is None:
                assert response.status_code == 200
                review = response.json()
                assert review["review_complete"] is True
                assert review["residual_review"]["status"] == "ready_for_user_review"
                assert review["send_state"] == "review"
                assert review["findings"]  # Real detection ran; no fabricated zero-findings fallback.
                assert "fixture@example.test" not in review["draft"]
                assert "Amount paid: 100 USD" in review["draft"]
                assert review["pages_used"] == [1]
                assert requests == STAGES
            else:
                assert response.status_code == 503
                assert "findings" not in response.json()
                assert main.sessions.items[sid].workflow is None
                assert client.post(f"/api/v1/sessions/{sid}/workflows/uncreated/approve", headers=ORIGIN,
                    json={"version": 1}).status_code == 404
                if failure == "placeholder_residual":
                    assert requests == STAGES
                    assert response.json()["error"]["local_checks"] == {"sensitive": "completed", "relevant": "completed", "residual": "failed"}
                    assert "stage=review_residual_risk" in caplog.text
                else:
                    assert requests == STAGES[:1]
                    assert response.json()["error"]["local_checks"] == {"sensitive": "failed", "relevant": "pending", "residual": "pending"}
                    assert "stage=detect_sensitive_data" in caplog.text
                assert "SYNTHETIC_PRIVATE_REASONING" not in caplog.text + response.text
            outbound.assert_not_called()
    finally:
        main.sessions.items.clear()
