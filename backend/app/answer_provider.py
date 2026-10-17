"""Server-side answer-provider boundary for explicitly approved text only."""

from __future__ import annotations

from typing import Protocol


class AnswerProvider(Protocol):
    """Provider interface that accepts only the approved outbound text."""

    async def answer(self, approved_text: str) -> str:
        """Return an answer for the supplied approved text."""


class AnswerProviderError(RuntimeError):
    """Safe provider failure with delivery certainty for retry decisions."""

    def __init__(self, *, delivery_unknown: bool = False) -> None:
        super().__init__("The answer provider could not complete the request.")
        self.delivery_unknown = delivery_unknown


class AnswerProviderNotConfigured(RuntimeError):
    """Raised until a concrete provider and server-side credentials are configured."""


def require_provider_configuration(provider_name: str | None, api_key: str | None) -> None:
    """Fail closed if provider selection or its environment credential is absent."""

    if not provider_name or not api_key:
        raise AnswerProviderNotConfigured
