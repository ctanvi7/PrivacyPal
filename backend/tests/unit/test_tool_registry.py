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


@pytest.mark.parametrize(
    "call",
    [
        {"function": {"name": "run_shell", "arguments": {}}},
        tool_call("inspect_document", {"terms": [], "session_id": "outside"}),
        tool_call("detect_sensitive_data", {"text": "unbounded model input"}),
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
