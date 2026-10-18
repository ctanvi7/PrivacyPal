import pytest

from app.privacy.pipeline import (
    PrivacyCheckError,
    build_sanitized_draft,
    review_residual_risk,
    scan_sensitive_data,
    select_relevant_content,
)


def test_detector_finds_and_hides_common_synthetic_identifiers():
    text = (
        "Contact demo.person@example.test or call 555-010-1234. "
        "Member ID: MEM-0042. SSN 123-45-6789. password=TEST_SECRET_DO_NOT_SEND_123"
    )

    result = scan_sensitive_data(text)

    assert {finding.category for finding in result.findings} >= {
        "email",
        "phone",
        "account_identifier",
        "government_id",
        "credential",
    }
    public_text = repr(result.public_view())
    assert "demo.person@example.test" not in public_text
    assert "TEST_SECRET_DO_NOT_SEND_123" not in public_text
    assert "123-45-6789" not in public_text


def test_valid_payment_card_pattern_is_high_risk():
    result = scan_sensitive_data("Synthetic card: 4111 1111 1111 1111")

    assert any(finding.category == "payment_card" and finding.action == "block" for finding in result.findings)


def test_minimization_masks_pii_and_keeps_placeholder_mapping_private():
    source = (
        "The project meeting starts at 3 PM; contact demo.person@example.test for details. "
        "Unrelated note: the office printer is out of paper."
    )

    draft = build_sanitized_draft("When does the project meeting start?", source)

    assert "project meeting starts at 3 PM" in draft.text
    assert "office printer" not in draft.text
    assert "demo.person@example.test" not in draft.text
    assert draft.placeholder_map
    assert "demo.person@example.test" not in repr(draft)
    assert "placeholder_map" not in draft.public_view()


def test_broad_document_summary_uses_bounded_complete_sentences():
    source = "Payment received for the synthetic receipt. Contact demo.person@example.test for support."

    selected = select_relevant_content("Explain the attached document.", source)
    draft = build_sanitized_draft("Explain the attached document.", source)

    assert selected.status == "selected"
    assert selected.text == source
    assert "demo.person@example.test" not in draft.text
    assert "[EMAIL_1]" in draft.text


@pytest.mark.parametrize("question", [
    "explain this please", "Can you explain this?", "Please summarise it briefly",
    "Describe it in simple terms", "Please summarize", "Explain the pdf",
    "Explain it simply", "What is this about?",
])
def test_generic_requests_use_bound_document_and_still_mask_identifiers(question):
    source = "The kitchen tap is leaking. Contact demo.person@example.test for repairs."
    selected = select_relevant_content(question, source)
    draft = build_sanitized_draft(question, source)
    assert selected.text == source
    assert "kitchen tap is leaking" in draft.text
    assert "demo.person@example.test" not in draft.text
    assert "[EMAIL_1]" in draft.text
    assert draft.source_spans


def test_explanation_with_a_topic_does_not_expand_to_the_whole_document():
    source = "Rent is due each month. The kitchen tap is leaking."
    selected = select_relevant_content("Explain this rent charge please", source)
    assert selected.text == "Rent is due each month."
    assert select_relevant_content("Explain quantum mechanics please", source).status == "no_relevant_content"


def test_native_search_terms_bridge_synonyms_without_including_unrelated_sentences():
    source = "Total due: 2500. Contact billing@example.test for questions. The office closes at noon."
    selected = select_relevant_content("How much do I owe?", source, search_terms=("total due",))
    draft = build_sanitized_draft("How much do I owe?", source, search_terms=("total due",))
    assert selected.text == "Total due: 2500."
    assert "Total due: 2500" in draft.text
    assert "office closes" not in draft.text and "billing@example.test" not in draft.text
    assert select_relevant_content("How much do I owe?", source, search_terms=("invented absent phrase",)).status == "no_relevant_content"


@pytest.mark.parametrize("terms", [("",), ("x" * 101,), ("due",) * 9, ["due"]])
def test_relevance_rejects_invalid_model_search_terms(terms):
    with pytest.raises(PrivacyCheckError):
        select_relevant_content("How much do I owe?", "Total due: 2500.", search_terms=terms)


def test_overview_includes_facts_even_when_only_heading_matches_question():
    source = "Attached document\nThe kitchen tap is leaking.\nContact demo.person@example.test for repairs."
    draft = build_sanitized_draft("Explain the attached document.", source)
    assert "kitchen tap is leaking" in draft.text
    assert "demo.person@example.test" not in draft.text
    assert "[EMAIL_1]" in draft.text


def test_overview_skips_oversized_sentence_without_cutting_it():
    source = "x" * 200 + "\nThe tap leaks.\nRepair is pending."
    selected = select_relevant_content("Summarize the document.", source, max_chars=33)
    assert selected.text == "The tap leaks. Repair is pending."
    assert len(selected.text) <= 33


@pytest.mark.parametrize("source", ["", "unrelated information", "x" * 8_000])
def test_unusable_context_cannot_create_question_only_draft(source):
    with pytest.raises(PrivacyCheckError):
        build_sanitized_draft("When is maintenance scheduled?", source)


def test_redaction_cannot_leave_an_empty_context_or_exceed_draft_limit():
    with pytest.raises(PrivacyCheckError):
        build_sanitized_draft("Explain the attached document.", "api_key=SYNTHETIC_SECRET")
    question = "Explain the attached document."
    source = "Email: a@b.co"
    limit = len(f"Question: {question}\n\nRelevant context:\n{source}")
    with pytest.raises(PrivacyCheckError):
        build_sanitized_draft(question, source, max_chars=limit)


def test_high_risk_secret_is_omitted_even_if_keep_is_suggested():
    question = "What is the deployment API key?"
    source = "The deployment API key=TEST_SECRET_DO_NOT_SEND_123 is configured for the meeting."
    selected = select_relevant_content(question, source)
    raw = f"Question: {question}\n\nRelevant context:\n{selected.text}"
    finding = next(item for item in scan_sensitive_data(raw).findings if item.action == "block")

    draft = build_sanitized_draft(question, source, actions={finding.finding_id: "keep"})

    assert "TEST_SECRET_DO_NOT_SEND_123" not in draft.text
    assert "TEST_SECRET_DO_NOT_SEND_123" not in repr(draft.placeholder_map)


def test_unknown_finding_action_fails_closed():
    with pytest.raises(PrivacyCheckError):
        build_sanitized_draft(
            "When is the meeting?",
            "The meeting starts at noon.",
            actions={"finding-from-another-request": "mask"},
        )


def test_residual_review_requires_contextual_completion_and_blocks_secrets():
    incomplete = review_residual_risk("The meeting starts at noon.")
    blocked = review_residual_risk(
        "API key=TEST_SECRET_DO_NOT_SEND_123",
        contextual_review_complete=True,
    )
    completed = review_residual_risk(
        "The meeting starts at noon.",
        contextual_review_complete=True,
    )

    assert incomplete.status == "needs_review"
    assert blocked.status == "blocked"
    assert completed.status == "ready_for_user_review"
    assert "guaranteed" not in " ".join(completed.reasons).lower()


def test_scan_rejects_oversized_input():
    with pytest.raises(PrivacyCheckError):
        scan_sensitive_data("x" * 25_001)
