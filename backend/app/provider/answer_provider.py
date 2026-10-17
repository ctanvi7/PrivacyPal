"""Single-send OpenAI-compatible adapter that accepts only an approved draft."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

MAX_PROVIDER_REQUEST_CHARS = 8_000
MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024
MAX_PROVIDER_ANSWER_CHARS = 8_000


class ProviderError(RuntimeError):
    """Safe provider failure; request and response bodies are never included."""


@dataclass(frozen=True)
class ApprovedRequest:
    workflow_id: str
    version: int
    provider_name: str
    provider_url: str
    content: str = field(repr=False)


class OpenAICompatibleProvider:
    """Send only the exact server-approved sanitized content, with no retry."""

    def __init__(self, *, url: str, model: str, api_key: str, timeout_seconds: float = 30.0) -> None:
        self.url = url
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def send(self, approved: ApprovedRequest) -> str:
        if not isinstance(approved, ApprovedRequest):
            raise ProviderError("Only a server-approved request can be sent.")
        if not approved.content.strip() or len(approved.content) > MAX_PROVIDER_REQUEST_CHARS:
            raise ProviderError("The approved request is empty or exceeds the provider limit.")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": approved.content}],
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds), follow_redirects=False) as client:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise ProviderError("The answer provider returned an oversized response.")
                response.raise_for_status()
                data = response.json()
            answer = data["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_PROVIDER_ANSWER_CHARS:
                raise ProviderError("The answer provider returned no usable answer.")
            return answer.strip()
        except ProviderError:
            raise
        except Exception as exc:
            # Never include the exception text: HTTP clients can include URLs or bodies.
            raise ProviderError("The answer provider failed. Delivery may have occurred; do not retry this approval.") from exc
