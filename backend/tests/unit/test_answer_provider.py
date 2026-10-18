"""Verify the real adapter over a mock HTTP transport; no external requests."""

import asyncio
import json

import httpx
import pytest
from app.privacy.grounding import GROUNDING_INSTRUCTIONS

from app.provider.answer_provider import ApprovedRequest, OpenAICompatibleProvider, ProviderError


@pytest.mark.parametrize("url", ["https://api.groq.com/openai/v1", "https://api.groq.com/openai/v1/", "https://api.groq.com/openai/v1/chat/completions"])
def test_groq_adapter_sends_only_exact_approved_content(monkeypatch, url):
    requests = []
    approved = ApprovedRequest("synthetic-workflow", 1, "Groq", url, "  Reviewed sanitized draft.\n")

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        assert json.loads(request.content) == {
            "model": "chosen-test-model",
            "messages": [{"role": "system", "content": GROUNDING_INSTRUCTIONS}, {"role": "user", "content": approved.content}],
            "stream": False,
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": "Synthetic answer"}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    provider = OpenAICompatibleProvider(url=url, model="chosen-test-model", api_key="synthetic-key")
    assert requests == []
    assert asyncio.run(provider.send(approved)) == "Synthetic answer"
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "http_error", "invalid_json", "empty_answer", "redirect", "oversized"])
def test_provider_failure_is_safe_and_never_retried(monkeypatch, failure):
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private response synthetic-key", request=request)
        if failure == "http_error":
            return httpx.Response(401, text="private response synthetic-key")
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "https://example.test"})
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * 65537)
        if failure == "empty_answer":
            return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
        return httpx.Response(200, text="private response synthetic-key")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    provider = OpenAICompatibleProvider(url="https://api.groq.com/openai/v1", model="test-model", api_key="synthetic-key")
    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.send(ApprovedRequest("test", 1, "Groq", provider.url, "Synthetic approved draft")))
    assert "synthetic-key" not in str(error.value)
    assert "private response" not in str(error.value)
    assert len(requests) == 1
