import asyncio

from app.model.ollama_adapter import OllamaAnalyzer
from app.tools.registry import ToolContext, ToolRegistry, privacy_workflow_complete


def native_call(name, arguments=None):
    return {"type": "function", "function": {"name": name, "arguments": arguments or {}}}


def test_ollama_adapter_drives_all_privacy_tools_in_order():
    analyzer = OllamaAnalyzer("http://127.0.0.1:11434", "gemma4:e4b")
    expected = [
        native_call("inspect_document", {"terms": ["salary"]}),
        native_call("detect_sensitive_data"),
        native_call("select_relevant_content"),
        native_call("propose_sanitized_request"),
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
    assert [item[0][0]["role"] for item in calls_seen] == ["system"] * 5
    assert all(len(item[1]) == 5 for item in calls_seen)
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
