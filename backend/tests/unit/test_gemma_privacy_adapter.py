import asyncio
import logging

import pytest
import app.model.ollama_adapter as adapter_module
from app.model.ollama_adapter import ModelBusyError, ModelError, OllamaAnalyzer
from app.tools.registry import ToolContext, ToolRegistry, privacy_workflow_complete


def native_call(name, arguments=None):
    if name == "detect_sensitive_data" and arguments is None:
        arguments = {"terms": ["payment"], "sensitive_spans": []}
    return {"type": "function", "function": {"name": name, "arguments": arguments or {}}}


def test_overlapping_workflows_fail_fast_and_cancellation_releases_capacity():
    async def scenario():
        entered = asyncio.Event()
        first = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
        second = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
        async def blocking_chat(*_args):
            entered.set()
            await asyncio.Event().wait()
        second_calls = []
        async def ready_chat(*_args):
            second_calls.append(True)
            return {"message": {"tool_calls": [native_call("review_residual_risk", {"risk_categories": []})]}}
        first._chat = blocking_chat
        second._chat = ready_chat
        context = ToolContext("synthetic-session", "synthetic-workflow", "Explain this please", ({"page": 1, "text": "The tap leaks."},))
        task = asyncio.create_task(first.run_privacy_workflow(context, ToolRegistry()))
        await entered.wait()
        try:
            with pytest.raises(ModelBusyError):
                await second.review_edited_draft("Explain this", "The tap leaks.")
            assert second_calls == []
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert await second.review_edited_draft("Explain this", "The tap leaks.") == ()
        assert len(second_calls) == 1
    asyncio.run(scenario())


def test_ollama_adapter_drives_all_privacy_tools_in_order():
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
    expected = [
        native_call("detect_sensitive_data", {"terms": ["salary"], "sensitive_spans": []}),
        native_call("review_residual_risk", {"risk_categories": []}),
    ]
    calls_seen = []

    async def fake_chat(messages, tools=None):
        calls_seen.append((messages, tools))
        return {"message": {"content": "", "tool_calls": [expected[len(calls_seen) - 1]]}}

    analyzer._chat = fake_chat
    context = ToolContext(
        session_id="session-test",
        workflow_id="workflow-test",
        question="What is the salary?",
        document_pages=({"page": 1, "text": "Salary is 80000 annually. The office is in Paris."},),
    )
    result = asyncio.run(analyzer.run_privacy_workflow(context, ToolRegistry()))

    assert result is context
    assert [item[0][0]["role"] for item in calls_seen] == ["system"] * 2
    assert [len(item[1]) for item in calls_seen] == [1, 1]
    assert context.executed_tools == [
        "inspect_document",
        "detect_sensitive_data",
        "select_relevant_content",
        "propose_sanitized_request",
        "review_residual_risk",
    ]
    assert privacy_workflow_complete(context)


def test_edited_draft_review_uses_a_native_allowlisted_risk_tool():
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
    calls = []

    async def fake_chat(messages, tools=None):
        calls.append((messages, tools))
        return {"message": {"tool_calls": [native_call("review_residual_risk", {"risk_categories": ["unique_fact"]})]}}

    analyzer._chat = fake_chat
    categories = asyncio.run(analyzer.review_edited_draft("What happened?", "A private one-off event occurred."))

    assert categories == ("unique_fact",)
    assert len(calls) == 1
    assert calls[0][1][0]["function"]["name"] == "review_residual_risk"


def test_residual_review_receives_only_exact_draft_without_original_question():
    draft = "Question: Draft an email.\nRelevant context: Contact [PERSON_NAME_1] at [EMAIL_2]."
    messages = OllamaAnalyzer._residual_messages("Contact SYNTHETIC_ORIGINAL_PERSON", draft)
    assert messages[1]["role"] == "user"
    assert f"<request>\n{draft}\n</request>" in messages[1]["content"]
    assert "SYNTHETIC_ORIGINAL_PERSON" not in str(messages)
    assert "NEVER include them in sensitive_spans" in messages[0]["content"]


def test_tool_calls_disable_thinking_and_use_a_small_output_budget(monkeypatch):
    requests = []

    class FakeResponse:
        content = b'{"message":{"tool_calls":[]}}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"tool_calls": [], "thinking": "SYNTHETIC_PRIVATE_REASONING"}}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, json):
            requests.append(json)
            return FakeResponse()

    monkeypatch.setattr(adapter_module.httpx, "AsyncClient", FakeClient)
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")

    asyncio.run(analyzer._chat([{"role": "user", "content": "test"}], [{"type": "function"}]))
    asyncio.run(analyzer._chat([{"role": "user", "content": "test"}]))
    result = asyncio.run(analyzer._chat([{"role": "user", "content": "test"}], [
        {"type": "function", "function": {"name": "review_residual_risk"}},
    ]))

    assert requests[0]["think"] is False
    assert requests[0]["options"] == {"num_predict": 128, "temperature": 0}
    assert "think" not in requests[1]
    assert requests[1]["options"] == {"num_predict": 1_024}
    assert requests[2]["think"] is True
    assert requests[2]["options"] == {"num_predict": adapter_module.RESIDUAL_MAX_PREDICT, "temperature": 0}
    assert all(request["keep_alive"] == 900 for request in requests)
    assert "thinking" not in result["message"]


def test_runtime_metrics_log_only_valid_counters_without_model_content(monkeypatch, caplog):
    import httpx

    requests = []
    def handler(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "done": True, "message": {"content": "SYNTHETIC_PRIVATE_RESPONSE", "thinking": "PRIVATE_REASONING"},
            "total_duration": 2_000_000_000, "load_duration": 10_000_000,
            "prompt_eval_duration": 500_000_000, "eval_duration": 1_490_000_000,
            "prompt_eval_count": 100, "eval_count": 20,
        })
    real_client = httpx.AsyncClient
    monkeypatch.setattr(adapter_module.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b", keep_alive_seconds=600)
    with caplog.at_level(logging.INFO, logger="app.model.ollama_adapter"):
        result = asyncio.run(analyzer._chat([{"role": "user", "content": "PRIVATE_PROMPT"}]))
    assert requests[0]["keep_alive"] == 600
    assert "total_ms=2000 load_ms=10 prompt_ms=500 generation_ms=1490" in caplog.text
    assert "prompt_tokens=100 output_tokens=20" in caplog.text
    assert not any(value in caplog.text for value in ("SYNTHETIC_PRIVATE_RESPONSE", "PRIVATE_REASONING", "PRIVATE_PROMPT"))
    assert "thinking" not in result["message"]


def test_failed_tool_stage_logs_only_safe_stage_and_exception_type(caplog):
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
    expected = [
        native_call("detect_sensitive_data"),
    ]
    calls_seen = []

    async def fake_chat(_messages, tools=None):
        assert tools is not None
        calls_seen.append(True)
        return {"message": {"tool_calls": [expected[len(calls_seen) - 1]]}}

    analyzer._chat = fake_chat
    context = ToolContext(
        session_id="session-test",
        workflow_id="workflow-test",
        question="When does the contract start?",
        document_pages=({"page": 1, "text": "Payment receipt SENSITIVE_SYNTHETIC_VALUE."},),
    )

    with caplog.at_level(logging.WARNING, logger="app.model.ollama_adapter"):
        with pytest.raises(ModelError):
            asyncio.run(analyzer.run_privacy_workflow(context, ToolRegistry()))

    assert "stage=prepare_draft exception_type=ToolValidationError" in caplog.text
    assert "SENSITIVE_SYNTHETIC_VALUE" not in caplog.text


def test_successful_native_review_does_not_classify_a_receipt_heading_as_a_person():
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
    calls = iter([
        native_call("detect_sensitive_data"),
        native_call("review_residual_risk", {"risk_categories": []}),
    ])
    async def fake_chat(_messages, _tools=None):
        return {"done": True, "done_reason": "stop", "message": {"tool_calls": [next(calls)]}}
    analyzer._chat = fake_chat
    context = ToolContext("synthetic-session", "synthetic-workflow", "Explain the attached document.", (
        {"page": 1, "text": "PrivacyPal Synthetic Payment Receipt\nReceipt number: SYN-2026-001\nAmount paid: 100.00 USD\nStatus: Payment received\nReference: DEMO-ONLY-12345"},
    ))
    asyncio.run(analyzer.run_privacy_workflow(context, ToolRegistry()))
    assert privacy_workflow_complete(context)
    assert len(context.executed_tools) == 5
    assert context.residual_review.status == "ready_for_user_review"


def test_document_word_does_not_exempt_an_explicitly_labeled_person():
    from app.privacy.grounding import AnswerGroundingError, review_outbound_identity, validate_answer_grounding
    from app.privacy.pipeline import ResidualReview
    source = "Resident: Maya Receipt\nMaintenance is scheduled for Tuesday."
    result = review_outbound_identity("Resident: Maya Receipt", source, "Draft a maintenance email.",
        ResidualReview("ready_for_user_review", (), ()))
    assert result.status == "blocked"
    with pytest.raises(AnswerGroundingError):
        validate_answer_grounding("Resident: Maya Receipt", "Draft a maintenance email.")


@pytest.mark.parametrize("bad_response", [
    {"message": {"content": "A clean-looking prose answer is not a tool call."}},
    {"message": {"tool_calls": []}},
    {"message": {"tool_calls": [native_call("detect_sensitive_data", {"unexpected": True})]}},
    {"message": {"tool_calls": [native_call("detect_sensitive_data", {})]}},
])
def test_failed_detection_response_stops_before_clean_review(bad_response, caplog):
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
    responses = iter([
        bad_response,
    ])
    async def fake_chat(_messages, _tools=None):
        return next(responses)
    analyzer._chat = fake_chat
    context = ToolContext("synthetic-session", "synthetic-workflow", "Explain the attached document.", (
        {"page": 1, "text": "Payment receipt. SENSITIVE_SYNTHETIC_VALUE"},
    ))
    with caplog.at_level(logging.WARNING, logger="app.model.ollama_adapter"):
        with pytest.raises(ModelError):
            asyncio.run(analyzer.run_privacy_workflow(context, ToolRegistry()))
    assert context.executed_tools == []
    assert context.scan is None and context.draft is None and context.residual_review is None
    assert not privacy_workflow_complete(context)
    assert "stage=detect_sensitive_data" in caplog.text
    assert "SENSITIVE_SYNTHETIC_VALUE" not in caplog.text
