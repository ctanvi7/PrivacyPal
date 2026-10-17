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
