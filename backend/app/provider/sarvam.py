"""Server-side Sarvam API adapter. Never logs text, audio, or credentials."""

from __future__ import annotations

import re

import httpx

from app.provider.answer_provider import ProviderError

SARVAM_BASE_URL = "https://api.sarvam.ai"
MAX_TRANSLATION_CHARS = 2_000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 30
MAX_TTS_CHARS = 2_500
MAX_TEXT_RESPONSE_BYTES = 64 * 1024
MAX_TTS_RESPONSE_BYTES = 16 * 1024 * 1024
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9_]{0,40}_\d+\]")


def _protect_placeholders(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}
    for index, marker in enumerate(PLACEHOLDER.findall(text), start=1):
        sentinel = f"PRIVACYPALMASKTOKEN{index:04d}END"
        replacements[sentinel] = marker
        text = text.replace(marker, sentinel, 1)
    return text, replacements


def _restore_placeholders(text: str, replacements: dict[str, str]) -> str:
    for sentinel in replacements:
        if text.count(sentinel) != 1:
            raise ProviderError("Translation did not preserve every masked placeholder.")
    if PLACEHOLDER.search(text):
        # Any remaining marker was introduced or duplicated by the translation service.
        raise ProviderError("Translation changed a masked placeholder.")
    for sentinel, marker in replacements.items():
        text = text.replace(sentinel, marker)
    return text


class SarvamClient:
    def __init__(self, api_key: str, timeout_seconds: float = 45.0) -> None:
        if not api_key:
            raise ProviderError("Sarvam is not configured.")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"api-subscription-key": self._api_key}

    async def chat(self, *, model: str, content: str) -> str:
        if not content.strip() or len(content) > 8_000:
            raise ProviderError("The approved request is empty or exceeds the provider limit.")
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                response = await client.post(
                    f"{SARVAM_BASE_URL}/v1/chat/completions",
                    headers=self._headers(),
                    json={"model": model, "messages": [{"role": "user", "content": content}], "stream": False},
                )
                if len(response.content) > MAX_TEXT_RESPONSE_BYTES:
                    raise ProviderError("Sarvam returned an oversized response.")
                response.raise_for_status()
                data = response.json()
            answer = data["choices"][0]["message"]["content"]
            if not isinstance(answer, str) or not answer.strip() or len(answer) > 8_000:
                raise ProviderError("Sarvam returned no usable answer.")
            return answer.strip()
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("Sarvam failed. Delivery may have occurred; do not retry this approval.") from exc

    async def translate(self, text: str, *, source_language: str, target_language: str, model: str) -> str:
        if not text.strip() or len(text) > MAX_TRANSLATION_CHARS:
            raise ProviderError("Translation text must contain 1 to 2,000 characters.")
        protected, replacements = _protect_placeholders(text)
        source = protected
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                response = await client.post(
                    f"{SARVAM_BASE_URL}/translate",
                    headers=self._headers(),
                    json={"input": source, "source_language_code": source_language, "target_language_code": target_language, "model": model},
                )
                if len(response.content) > MAX_TEXT_RESPONSE_BYTES:
                    raise ProviderError("Sarvam returned an oversized response.")
                response.raise_for_status()
                result = response.json()
            translated = result.get("translated_text")
            if not isinstance(translated, str) or not translated.strip():
                raise ProviderError("Sarvam returned no usable translation.")
            if len(translated) > 8_000:
                raise ProviderError("Sarvam returned an oversized translation.")
            return _restore_placeholders(translated, replacements)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("Sarvam translation failed. No provider fallback was attempted.") from exc

    async def transcribe(self, audio: bytes, *, filename: str, content_type: str) -> str:
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ProviderError("Choose an audio file up to 10 MiB.")
        allowed = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/aac", "audio/flac", "audio/ogg", "audio/opus", "audio/webm", "audio/aiff", "audio/x-aiff", "audio/mp4", "audio/x-m4a", "video/mp4", "audio/amr", "audio/x-ms-wma", "audio/pcm"}
        if content_type.lower().split(";")[0].strip() not in allowed:
            raise ProviderError("Use a WAV, MP3, AAC, FLAC, or OGG audio file.")
        try:
            async with httpx.AsyncClient(timeout=max(self._timeout, 75.0), follow_redirects=False) as client:
                response = await client.post(
                    f"{SARVAM_BASE_URL}/speech-to-text",
                    headers=self._headers(),
                    data={"model": "saaras:v4"},
                    files={"file": (filename[:128], audio, content_type)},
                )
                if len(response.content) > MAX_TEXT_RESPONSE_BYTES:
                    raise ProviderError("Sarvam returned an oversized transcription response.")
                response.raise_for_status()
                result = response.json()
            transcript = result.get("transcript")
            if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 2_000:
                raise ProviderError("Sarvam returned no usable transcript.")
            return transcript.strip()
        except ProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {400, 422}:
                message = "Sarvam rejected this audio. Try a short, clear recording in a supported format such as WAV, MP3, or WebM."
            elif status in {401, 403}:
                message = "Sarvam rejected the API key or this account does not have speech transcription access. Check the key and Sarvam account."
            elif status == 429:
                message = "Sarvam speech transcription is rate-limited or out of quota. Check the Sarvam account and try again later."
            elif status >= 500:
                message = "Sarvam speech transcription is temporarily unavailable. Try again later."
            else:
                message = f"Sarvam could not transcribe this audio (HTTP {status}). No other provider was contacted."
            raise ProviderError(message) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("Sarvam speech transcription timed out. Try a shorter recording and try again.") from exc
        except Exception as exc:
            raise ProviderError("Speech transcription failed. Check the backend connection to Sarvam and try again. No other provider was contacted.") from exc

    async def synthesize(self, text: str, *, language: str, model: str) -> str:
        if not text.strip() or len(text) > MAX_TTS_CHARS:
            raise ProviderError("Text-to-speech supports 1 to 2,500 characters.")
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                response = await client.post(
                    f"{SARVAM_BASE_URL}/text-to-speech",
                    headers={**self._headers(), "Content-Type": "application/json"},
                    json={"text": text, "language_code": language, "model": model},
                )
                if len(response.content) > MAX_TTS_RESPONSE_BYTES:
                    raise ProviderError("Sarvam returned oversized speech audio.")
                response.raise_for_status()
                result = response.json()
            audios = result.get("audios")
            if not isinstance(audios, list) or not audios or not isinstance(audios[0], str):
                raise ProviderError("Sarvam returned no usable speech audio.")
            return audios[0]
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("Speech generation failed. No provider fallback was attempted.") from exc
