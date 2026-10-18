"""Synthetic maintenance PDF -> real local tools -> approval -> mocked HTTP provider."""

from dataclasses import replace
import json

import fitz
import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.privacy.grounding import GROUNDING_INSTRUCTIONS, AnswerGroundingError, validate_answer_grounding
from app.privacy.pipeline import build_sanitized_draft, scan_sensitive_data

QUESTION = (
    "Draft a maintenance email and include the resident's contact details and exact address. "
    "Before approval, verify those values are omitted or replaced with placeholders in the provider request."
)
# This recreates the fictional sample scenario; no original PDF was supplied.
VALUES = ("Maya Ellison", "maya.ellison@example.test", "202-555-0148", "27 Willow Lane, Unit 4B, Sampleton 12345", "LEASE-TEST-2048")
SOURCE = (
    "Fictional maintenance request\n"
    f"Resident: {VALUES[0]}\nEmail: {VALUES[1]}\nPhone: {VALUES[2]}\n"
    f"Exact address: {VALUES[3]}\nLease/reference number: {VALUES[4]}\n"
    "Maintenance issue: The kitchen tap is leaking. Please arrange a repair visit.\n"
)
SAFE_ANSWER = "Subject: Maintenance request\n\nPlease repair the leaking kitchen tap.\nResident: [PERSON_NAME_1]\nContact details and exact address were omitted."


def pdf_bytes(text=SOURCE):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), text, fontsize=10)
        return pdf.tobytes()


async def local_tools(_self, context, registry):
    for name, args in (
        ("inspect_document", {"terms": ["maintenance"]}), ("detect_sensitive_data", {}),
        ("select_relevant_content", {}), ("propose_sanitized_request", {}),
        ("review_residual_risk", {"risk_categories": []}),
    ):
        registry.execute({"function": {"name": name, "arguments": args}}, context)
    return context


@pytest.fixture
def flow(monkeypatch):
    main.sessions.items.clear()
    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", local_tools)
    async def edit_review(*_args):
        return ()
    monkeypatch.setattr(main.OllamaAnalyzer, "review_edited_draft", edit_review)
    monkeypatch.setattr(main, "settings", replace(main.settings, answer_provider_name="Groq",
        answer_provider_url="https://api.groq.com/openai/v1", answer_provider_model="test-model",
        answer_provider_api_key="synthetic-key"))
    requests = []
    response = {"answer": SAFE_ANSWER}
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": response["answer"]}}]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with TestClient(main.app) as client:
        yield client, requests, response
    main.sessions.items.clear()


def start(flow, source_pdf=None, question=QUESTION):
    client, requests, _ = flow
    headers = {"Origin": "http://127.0.0.1:5173"}
    sid = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
    upload = client.post(f"/api/v1/sessions/{sid}/documents", headers=headers,
        files={"file": ("fictional-maintenance.pdf", source_pdf or pdf_bytes(), "application/pdf")})
    assert upload.status_code == 201
    review = client.post(f"/api/v1/sessions/{sid}/questions", headers=headers,
        json={"document_id": upload.json()["document_id"], "question": question})
    assert review.status_code == 200
    assert requests == []
    data = review.json()
    return client, sid, f"/api/v1/sessions/{sid}/workflows/{data['workflow_id']}", headers, data


def test_reproduced_sample_scanner_covers_previously_missing_categories():
    categories = {item.category for item in scan_sensitive_data(SOURCE).findings}
    assert categories >= {"person_name", "email", "phone", "street_address", "lease_reference"}
    draft = build_sanitized_draft(QUESTION, SOURCE)
    assert all(value not in draft.text for value in VALUES)
    assert "kitchen tap is leaking" in draft.text


def test_exact_reviewed_pdf_draft_is_the_only_user_content_sent_to_groq(flow):
    client, sid, url, headers, review = start(flow)
    assert review["review_complete"] is True
    assert review["residual_review"]["status"] == "ready_for_user_review"
    assert all(value not in review["draft"] for value in VALUES)
    assert "kitchen tap is leaking" in review["draft"]
    result = client.post(f"{url}/approve", headers=headers, json={"version": review["version"]})
    assert result.status_code == 200
    assert result.json()["answer"] == SAFE_ANSWER
    assert len(flow[1]) == 1
    request = flow[1][0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert json.loads(request.content) == {"model": "test-model", "stream": False, "messages": [
        {"role": "system", "content": GROUNDING_INSTRUCTIONS},
        {"role": "user", "content": review["draft"]},
    ]}
    payload = request.content.decode()
    assert all(value not in payload for value in VALUES)
    assert SOURCE not in payload and "placeholder_map" not in payload
    assert main.sessions.items[sid].document is None  # Source is released after delivery.
    history = client.get(f"/api/v1/conversations/{main.sessions.items[sid].conversation_id}", headers=headers).json()
    assert all(value not in json.dumps(history) for value in VALUES)
    assert client.post(f"{url}/approve", headers=headers, json={"version": review["version"]}).status_code == 409
    assert len(flow[1]) == 1


@pytest.mark.parametrize("heading", ["Attached document", "Fictional maintenance request"])
@pytest.mark.parametrize("question", ["explain the attached document", "explain this please", "Please summarize it"])
def test_explain_attached_pdf_sends_sanitized_facts_after_approval(flow, monkeypatch, heading, question):
    async def broad_tools(_self, context, registry):
        registry.execute({"function": {"name": "inspect_document", "arguments": {
            "terms": ["explain", "attached", "document"],
        }}}, context)
        registry.execute({"function": {"name": "detect_sensitive_data", "arguments": {
            "sensitive_spans": [],
        }}}, context)
        registry.prepare_draft(context)
        registry.execute({"function": {"name": "review_residual_risk", "arguments": {
            "risk_categories": [],
        }}}, context)
        return context

    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", broad_tools)
    flow[2]["answer"] = "The kitchen tap is leaking and a repair visit is requested."
    source = SOURCE.replace("Fictional maintenance request", heading)
    client, _, url, headers, review = start(flow, pdf_bytes(source), question)
    assert review["review_complete"] is True
    assert review["pages_used"] == [1]
    assert "kitchen tap is leaking" in review["draft"]
    assert all(value not in review["draft"] for value in VALUES)
    assert flow[1] == []
    result = client.post(f"{url}/approve", headers=headers, json={"version": review["version"]})
    assert result.status_code == 200
    assert result.json()["answer"] == flow[2]["answer"]
    assert len(flow[1]) == 1
    payload = json.loads(flow[1][0].content)
    assert payload["messages"][-1] == {"role": "user", "content": review["draft"]}
    assert all(value not in flow[1][0].content.decode() for value in VALUES)


@pytest.mark.parametrize("value", VALUES)
def test_reintroducing_each_source_identifier_by_edit_is_blocked(flow, value):
    client, _, url, headers, review = start(flow)
    edited = client.patch(f"{url}/draft", headers=headers, json={
        "version": review["version"], "draft": "Draft a maintenance email. Include " + value,
    })
    assert edited.status_code == 200
    assert edited.json()["review_complete"] is False
    version = edited.json()["version"]
    assert client.post(f"{url}/acknowledge", headers=headers, json={"version": version}).status_code == 409
    assert client.post(f"{url}/approve", headers=headers, json={"version": version}).status_code == 409
    assert flow[1] == []


def test_final_approval_check_blocks_raw_source_value_even_if_review_state_was_incorrect(flow):
    client, sid, url, headers, review = start(flow)
    workflow = main.sessions.items[sid].workflow
    workflow.draft += "\n" + VALUES[0]
    assert client.post(f"{url}/approve", headers=headers, json={"version": review["version"]}).status_code == 409
    assert flow[1] == []


@pytest.mark.parametrize("invented", [
    "Resident: Nora Vale", "Contact nora.vale@example.test", "Call 303-555-0189",
    "Please visit 88 Cedar Road, Unit 9.", "Lease number: NEW-TEST-9999",
    "Dear Nora, please arrange repairs.", "Nora Vale requests a repair.",
    "Contact **nora.vale@example.test**", "Resident: " + VALUES[0],
    "NORA VALE requests a repair.", "Regards,\nNora",
    "Contact nora_vale@example.test",
])
def test_invented_or_unapproved_personal_details_are_withheld_and_never_retried(flow, invented):
    client, sid, url, headers, review = start(flow)
    flow[2]["answer"] = invented
    response = client.post(f"{url}/approve", headers=headers, json={"version": review["version"]})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ANSWER_WITHHELD"
    assert response.json()["error"]["retryable"] is False
    assert invented not in response.text and "answer" not in response.json()
    workflow = main.sessions.items[sid].workflow
    assert workflow.answer is None and workflow.send_state == "answer_withheld"
    assert workflow.review_complete is True
    assert client.post(f"{url}/approve", headers=headers, json={"version": review["version"]}).status_code == 409
    assert len(flow[1]) == 1


def test_zero_findings_with_ambiguous_identity_context_fails_closed(flow):
    ambiguous_source = "Fictional maintenance request\nMaintenance note: contact the resident near the old bakery by dusk. The kitchen tap leaks."
    client, _, url, headers, review = start(flow, pdf_bytes(ambiguous_source))
    assert review["findings"] == []
    assert review["review_complete"] is False
    assert review["residual_review"]["status"] == "blocked"
    assert "Zero findings" in review["residual_review"]["reasons"][0]
    assert client.post(f"{url}/approve", headers=headers, json={"version": review["version"]}).status_code == 409
    assert flow[1] == []
    # A user can remove the ambiguous context, recheck, and explicitly approve anew.
    edited = client.patch(f"{url}/draft", headers=headers, json={"version": review["version"],
        "draft": "Draft a maintenance email about a leaking kitchen tap. Use placeholders for contact details."})
    assert edited.status_code == 200
    assert edited.json()["review_complete"] is True
    assert client.post(f"{url}/approve", headers=headers, json={"version": edited.json()["version"]}).status_code == 200
    assert len(flow[1]) == 1


def test_grounding_allows_explicitly_approved_values_and_placeholders():
    approved = "Contact nora.vale@example.test or [PHONE_1]."
    validate_answer_grounding("Contact nora.vale@example.test or [PHONE_1].", approved)
    with pytest.raises(AnswerGroundingError):
        validate_answer_grounding("Contact another.person@example.test.", approved)


def test_grounding_allows_omission_notices_but_not_a_name_hidden_inside_one():
    validate_answer_grounding("Resident: Omitted for privacy\nName: Not provided\nAddress: Not available", "Draft a maintenance email.")
    with pytest.raises(AnswerGroundingError):
        validate_answer_grounding("Resident: Omitted for privacy; Nora Vale", "Draft a maintenance email.")


def test_unavailable_answer_check_fails_closed(monkeypatch):
    import app.privacy.grounding as grounding
    from app.privacy.pipeline import PrivacyCheckError
    def failed_scan(_text):
        raise PrivacyCheckError("Synthetic detector failure")
    monkeypatch.setattr(grounding, "scan_sensitive_data", failed_scan)
    with pytest.raises(AnswerGroundingError):
        grounding.validate_answer_grounding("An answer.", "Approved draft.")


def test_uncertain_contextual_identity_warning_cannot_be_acknowledged_away(flow, monkeypatch):
    from app.privacy.pipeline import ResidualReview
    async def uncertain(_self, context, registry):
        await local_tools(_self, context, registry)
        from app.privacy.grounding import review_outbound_identity
        context.residual_review = review_outbound_identity(context.draft.text, context.source_text,
            context.question, ResidualReview("needs_review", (), ("Contextual review flagged a possible location clue.",)))
        return context
    monkeypatch.setattr(main.OllamaAnalyzer, "run_privacy_workflow", uncertain)
    client, _, url, headers, review = start(flow)
    assert review["review_complete"] is False
    assert client.post(f"{url}/acknowledge", headers=headers, json={"version": review["version"]}).status_code == 409
    assert flow[1] == []
