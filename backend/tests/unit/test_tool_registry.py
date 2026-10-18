import pytest

from app.tools.registry import (
    ToolContext,
    ToolRegistry,
    ToolValidationError,
    ollama_tool_definitions,
    privacy_workflow_ready,
    validate_tool_call,
    validate_tool_sequence,
)


def tool_call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


def test_native_tool_definitions_include_only_five_allowlisted_tools():
    definitions = ollama_tool_definitions()

    assert [item["function"]["name"] for item in definitions] == [
        "inspect_document",
        "detect_sensitive_data",
        "select_relevant_content",
        "propose_sanitized_request",
        "review_residual_risk",
    ]


def test_one_native_call_can_request_bound_inspection_and_verified_detection():
    context = ToolContext("session", "workflow", "Explain maintenance.", (
        {"page": 1, "text": "Maintenance for Maya Ellison: the tap leaks."},
    ))
    registry = ToolRegistry()
    call = tool_call("detect_sensitive_data", {"terms": ["maintenance"], "sensitive_spans": [
        {"category": "person_name", "value": "Maya Ellison"},
    ]})
    registry.execute(call, context)
    assert context.executed_tools == ["inspect_document", "detect_sensitive_data"]
    assert context.inspected_pages == (1,)
    assert context.semantic_detection_complete
    registry.prepare_draft(context)
    assert "Maya Ellison" not in context.draft.text
    with pytest.raises(ToolValidationError):
        registry.execute(call, context)
    assert not privacy_workflow_ready(context)  # Separate native audit remains required.


@pytest.mark.parametrize("terms", [[], [""], ["x"] * 9, "maintenance"])
def test_combined_call_rejects_invalid_search_terms_before_any_operation(terms):
    context = ToolContext("session", "workflow", "Explain maintenance.", (
        {"page": 1, "text": "The tap leaks."},
    ))
    with pytest.raises(ToolValidationError):
        ToolRegistry().execute(tool_call("detect_sensitive_data", {"terms": terms, "sensitive_spans": []}), context)
    assert context.executed_tools == []
    assert context.scan is None


@pytest.mark.parametrize(
    "call",
    [
        {"function": {"name": "run_shell", "arguments": {}}},
        tool_call("inspect_document", {"terms": [], "session_id": "outside"}),
        tool_call("detect_sensitive_data", {"text": "unbounded model input"}),
        tool_call("detect_sensitive_data", {"terms": ["maintenance"]}),
        tool_call("review_residual_risk", {"risk_categories": ["email"], "draft": "raw secret"}),
    ],
)
def test_unknown_or_extra_tool_fields_are_rejected(call):
    with pytest.raises(ToolValidationError):
        validate_tool_call(call)


def test_tool_arguments_must_be_valid_and_bounded():
    with pytest.raises(ToolValidationError):
        validate_tool_call(tool_call("inspect_document", {"terms": [""]}))
    with pytest.raises(ToolValidationError):
        validate_tool_call(tool_call("inspect_document", "x" * 2_001))


def test_tool_sequences_reject_duplicates_and_wrong_order():
    with pytest.raises(ToolValidationError):
        validate_tool_sequence([
            tool_call("detect_sensitive_data", {}),
            tool_call("inspect_document", {"terms": ["meeting"]}),
        ])
    with pytest.raises(ToolValidationError):
        validate_tool_sequence([
            tool_call("inspect_document", {"terms": ["meeting"]}),
            tool_call("inspect_document", {"terms": ["meeting"]}),
        ])


def test_registry_runs_bound_privacy_workflow_and_keeps_mapping_out_of_results():
    context = ToolContext(
        session_id="synthetic-session",
        workflow_id="synthetic-workflow",
        question="When does the meeting start?",
        document_pages=(
            {"page": 1, "text": "The meeting starts at 3 PM; contact demo.person@example.test for details."},
        ),
    )
    registry = ToolRegistry()
    calls = [
        tool_call("inspect_document", {"terms": ["meeting"]}),
        tool_call("detect_sensitive_data", {}),
        tool_call("select_relevant_content", {}),
        tool_call("propose_sanitized_request", {}),
        tool_call("review_residual_risk", {"risk_categories": []}),
    ]

    results = [registry.execute(call, context) for call in calls]

    # The source and selected passages go only to local Gemma; the sanitized
    # draft returned for review must not expose the original address.
    assert "demo.person@example.test" not in str(results[3])
    assert "[EMAIL_1]" in results[3]["text"]
    assert privacy_workflow_ready(context)


def test_deterministic_preparation_requires_validated_detection_and_is_not_repeatable():
    context = ToolContext("synthetic-session", "synthetic-workflow", "When is maintenance?", (
        {"page": 1, "text": "Maintenance is on Tuesday. Contact fixture@example.test."},
    ))
    registry = ToolRegistry()
    with pytest.raises(ToolValidationError):
        registry.prepare_draft(context)
    registry.execute(tool_call("inspect_document", {"terms": ["maintenance"]}), context)
    with pytest.raises(ToolValidationError):
        registry.prepare_draft(context)
    registry.execute(tool_call("detect_sensitive_data", {"sensitive_spans": []}), context)
    registry.prepare_draft(context)
    assert context.draft is not None and context.selected.status == "selected"
    assert not privacy_workflow_ready(context)  # Native final review is still mandatory.
    with pytest.raises(ToolValidationError):
        registry.prepare_draft(context)


def test_selected_pages_follow_redacted_content_even_without_search_matches():
    context = ToolContext("session", "workflow", "Explain the attached document.", (
        {"page": 1, "text": "Resident: Maya\nEllison\nThe kitchen tap is leaking."},
        {"page": 2, "text": "Repairs are scheduled for Tuesday."},
        {"page": 3, "text": "x" * 8_000},
    ))
    registry = ToolRegistry()
    registry.execute(tool_call("inspect_document", {"terms": ["attached", "document"]}), context)
    assert context.inspected_pages == ()
    registry.execute(tool_call("detect_sensitive_data", {"sensitive_spans": [
        {"category": "person_name", "value": "Maya\nEllison"},
    ]}), context)
    registry.prepare_draft(context)
    assert context.selected_pages == (1, 2)
    assert "Maya" not in context.draft.text and "Ellison" not in context.draft.text
    assert "kitchen tap is leaking" in context.draft.text
    assert "Repairs are scheduled for Tuesday" in context.draft.text
    assert "source_spans" not in context.draft.public_view()


def test_pages_with_only_omitted_content_are_not_reported_as_used():
    context = ToolContext("session", "workflow", "Explain the attached document.", (
        {"page": 1, "text": "api_key=SYNTHETIC_SECRET"},
        {"page": 2, "text": "The kitchen tap is leaking."},
    ))
    registry = ToolRegistry()
    registry.execute(tool_call("inspect_document", {"terms": ["document"]}), context)
    registry.execute(tool_call("detect_sensitive_data", {"sensitive_spans": []}), context)
    registry.prepare_draft(context)
    assert context.selected_pages == (2,)
    assert "SYNTHETIC_SECRET" not in context.draft.text
