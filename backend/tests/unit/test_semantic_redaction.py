"""Gemma proposes source values; backend validation owns all redaction and sending."""

import asyncio
from dataclasses import replace
import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.model.ollama_adapter as adapter
from app.privacy.pipeline import PrivacyCheckError
from app.privacy.semantic import validated_findings
from app.tools.registry import ToolContext, ToolRegistry

VALUES = {
    "person_name": "Morgan Rivers", "email": "morgan.rivers@example.test", "phone": "202-555-0186",
    "street_address": "Flat 9, 32 Oak Court, Sampleton", "lease_reference": "SYN-LEASE-2042",
}
CANDIDATES = [{"category": category, "value": value} for category, value in VALUES.items()]
# Mirrors table extraction: labels and values are separate lines, without colons.
SOURCE = "Fictional maintenance request\n" + "\n".join(f"{key}\n{value}" for key, value in VALUES.items()) + (
    "\nMaintenance request from Morgan Rivers about a leaking kitchen tap. "
    "Contact morgan.rivers@example.test at Flat 9, 32 Oak Court, Sampleton for maintenance. "
    "The maintenance reference is SYN-LEASE-2042."
)
QUESTION = "Draft a maintenance email and include the resident's contact details and exact address"
STAGES = ["detect_sensitive_data", "review_residual_risk"]


@pytest.fixture
def client_and_requests(monkeypatch):
    main.sessions.items.clear()
    requests = []
    control = {"candidates": CANDIDATES, "risk_categories": [], "final_spans": [], "recheck_spans": []}
    real_client = httpx.AsyncClient
    def handler(request):
        payload = json.loads(request.content)
        requests.append((str(request.url), payload))
        if str(request.url).endswith('/chat/completions'):
            return httpx.Response(200, json={"choices": [{"message": {"content": "Please arrange repair of the leaking kitchen tap. Contact [PERSON_NAME_1]."}}]})
        index = sum(url.endswith('/api/chat') for url, _ in requests) - 1
        stage = STAGES[min(index, 1)]
        if stage == "detect_sensitive_data":
            assert [t['function']['name'] for t in payload['tools']] == [stage]
            assert payload['messages'][1]['content'] == f"Question: {QUESTION}\n\nSource:\n{SOURCE}"
            args = {"terms": ["maintenance"], "sensitive_spans": control["candidates"]}
        elif stage == "review_residual_risk":
            final_messages = json.dumps(payload["messages"])
            assert SOURCE not in final_messages
            pending = control['final_spans'] if index == 1 else control['recheck_spans']
            pending_values = {item['value'] for item in pending}
            assert all(value not in final_messages for value in VALUES.values() if value not in pending_values)
            assert len(payload["messages"]) == 2
            args = {"risk_categories": control["risk_categories"], "sensitive_spans": pending}
        else:
            args = {"terms": ["maintenance"]} if stage == 'inspect_document' else {}
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
            "tool_calls": [{"function": {"name": stage, "arguments": args}}]}})
    monkeypatch.setattr(adapter.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(main, "settings", replace(main.settings, answer_provider_name='Groq',
        answer_provider_url='https://api.groq.com/openai/v1', answer_provider_model='test-model', answer_provider_api_key='synthetic-key'))
    with TestClient(main.app) as client:
        yield client, requests, control
    main.sessions.items.clear()


def start(client):
    headers = {"Origin": "http://127.0.0.1:5173"}
    sid = client.post('/api/v1/sessions', headers=headers).json()['session_id']
    doc = client.post(f'/api/v1/sessions/{sid}/documents', headers=headers, json={'pasted_text': SOURCE}).json()
    result = client.post(f'/api/v1/sessions/{sid}/questions', headers=headers, json={'document_id': doc['document_id'], 'question': QUESTION})
    return sid, headers, result


def test_gemma_detects_unlabeled_values_backend_redacts_and_sends_only_approved_text(client_and_requests):
    client, requests, _ = client_and_requests
    sid, headers, result = start(client)
    assert result.status_code == 200
    review = result.json()
    assert review['review_complete'] is True
    assert review['local_checks']['sensitive'] == 'completed'
    assert all(value not in review['draft'] for value in VALUES.values())
    assert {f['category'] for f in review['findings']} >= {'person_name', 'email', 'street_address', 'lease_reference'}
    assert 'leaking kitchen tap' in review['draft']
    assert len(requests) == 2
    assert all(url.endswith('/api/chat') for url, _ in requests)
    response = client.post(f"/api/v1/sessions/{sid}/workflows/{review['workflow_id']}/approve", headers=headers, json={'version':review['version']})
    assert response.status_code == 200
    assert len(requests) == 3
    payload = requests[-1][1]
    assert payload['messages'][1] == {'role':'user', 'content':review['draft']}
    assert all(value not in json.dumps(payload) for value in VALUES.values())
    assert SOURCE not in json.dumps(payload)
    assert 'semantic_values' not in json.dumps(review) and 'placeholder_map' not in json.dumps(review)


@pytest.mark.parametrize('bad', [
    [{'category':'person_name','value':'Not In This Source'}],
    [{'category':'unknown','value':'Morgan Rivers'}],
    [{'category':'person_name','value':'Morgan Rivers','action':'keep'}],
    [{'category':'person_name','value':'[PERSON_NAME_1]'}],
])
def test_invalid_model_detections_fail_closed_without_provider_call(client_and_requests, bad, caplog):
    client, requests, control = client_and_requests
    control['candidates'] = bad
    sid, headers, result = start(client)
    assert result.status_code == 503
    assert main.sessions.items[sid].workflow is None
    assert len(requests) == 1
    assert 'Not In This Source' not in result.text + caplog.text


def test_actual_residual_risk_stays_blocked_with_completed_prior_checks(client_and_requests):
    client, requests, control = client_and_requests
    control['risk_categories'] = ['location']
    sid, headers, result = start(client)
    review = result.json()
    assert result.status_code == 200 and review['review_complete'] is False
    assert review['residual_review']['status'] == 'blocked'
    assert review['local_checks'] == {'sensitive':'completed','relevant':'completed','residual':'blocked'}
    url = f"/api/v1/sessions/{sid}/workflows/{review['workflow_id']}"
    assert client.post(f'{url}/approve', headers=headers, json={'version':1}).status_code == 409
    assert all(url.endswith('/api/chat') for url, _ in requests)


@pytest.mark.parametrize('bad', [
    {'category': 'person_name', 'value': 'Not In This Source'},
    {'category': 'email', 'value': '[EMAIL_1]'},
])
def test_invalid_final_review_never_creates_an_approvable_workflow(client_and_requests, bad):
    client, requests, control = client_and_requests
    control['final_spans'] = [bad]
    sid, headers, result = start(client)
    assert result.status_code == 503
    assert result.json()['error']['local_checks'] == {'sensitive': 'completed', 'relevant': 'completed', 'residual': 'failed'}
    assert main.sessions.items[sid].workflow is None
    assert client.post(f'/api/v1/sessions/{sid}/workflows/failed/approve', headers=headers, json={'version': 1}).status_code == 404
    assert len(requests) == 2 and all(url.endswith('/api/chat') for url, _ in requests)


def test_remaining_gemma_detection_is_redacted_and_rechecked_once_before_review(client_and_requests):
    client, requests, control = client_and_requests
    control['candidates'] = [item for item in CANDIDATES if item['category'] != 'person_name']
    control['final_spans'] = [{'category':'person_name','value':VALUES['person_name']}]
    sid, headers, result = start(client)
    assert result.status_code == 200
    review = result.json()
    assert review['review_complete'] is True
    assert VALUES['person_name'] not in review['draft']
    assert len(requests) == 3 and all(url.endswith('/api/chat') for url, _ in requests)
    assert 'person_name' in {f['category'] for f in review['findings']}
    assert main.sessions.items[sid].workflow.send_state == 'review'


def test_unresolved_second_review_stays_blocked_and_does_not_loop(client_and_requests):
    client, requests, control = client_and_requests
    control['candidates'] = [item for item in CANDIDATES if item['category'] != 'person_name']
    control['final_spans'] = [{'category':'person_name','value':VALUES['person_name']}]
    control['risk_categories'] = ['location']
    _, _, result = start(client)
    assert result.status_code == 200
    assert result.json()['review_complete'] is False
    assert result.json()['residual_review']['status'] == 'blocked'
    assert len(requests) == 3


def test_semantic_findings_require_exact_source_evidence_and_support_pdf_whitespace():
    result = validated_findings('Name\nMorgan\nRivers', [{'category':'person_name','value':'Morgan Rivers'}])
    assert len(result) == 1 and result[0]._value == 'Morgan\nRivers'
    assert 'Morgan' not in repr(result[0])


def test_multiline_identifier_is_masked_before_relevance_can_split_it():
    from app.privacy.pipeline import build_sanitized_draft
    source = 'Maintenance resident Morgan\nRivers needs a kitchen tap repair.\nAddress\nFlat 9,\n32 Oak Court,\nSampleton\nMaintenance reference SYN-LEASE-2042.'
    findings = validated_findings(source, [
        {'category':'person_name','value':'Morgan Rivers'},
        {'category':'street_address','value':'Flat 9, 32 Oak Court, Sampleton'},
    ])
    draft = build_sanitized_draft(QUESTION, source, additional_findings=findings)
    assert 'Morgan' not in draft.text and 'Rivers' not in draft.text
    assert 'Flat 9' not in draft.text and '32 Oak' not in draft.text
    assert '[PERSON_NAME_' in draft.text
    assert len(set(draft.placeholder_map.values())) == len(draft.placeholder_map)


def test_truncated_native_response_is_not_accepted(monkeypatch):
    real_client = httpx.AsyncClient
    def handler(request):
        return httpx.Response(200, json={'done':True,'done_reason':'length','message':{'tool_calls':[]}})
    monkeypatch.setattr(adapter.httpx,'AsyncClient',lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(adapter.ModelError):
        asyncio.run(adapter.OllamaAnalyzer('http://127.0.0.1:11434','gemma4:e4b')._chat([], []))
