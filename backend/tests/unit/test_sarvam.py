"""Sarvam contracts use synthetic content and HTTP mocks only."""
import asyncio
import base64
import io
import json
import wave

import httpx
import pytest

from app.provider.answer_provider import ProviderError
from app.provider.sarvam import SarvamClient, _protect_placeholders, _restore_placeholders
from app.privacy.grounding import GROUNDING_INSTRUCTIONS


def wav_base64():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * 800)
    return base64.b64encode(stream.getvalue()).decode()


@pytest.fixture
def transport(monkeypatch):
    calls = []
    response = {'value': {}}
    def handler(request):
        calls.append(request)
        return httpx.Response(response.get('status', 200), json=response['value'])
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    return calls, response


def test_chat_sends_grounding_and_only_exact_approved_user_content(transport):
    calls, response = transport
    response['value'] = {'choices': [{'message': {'content': 'Monthly costs are 1200.'}}]}
    answer = asyncio.run(SarvamClient('fixture-key').chat(model='sarvam-105b', content='Exact reviewed draft.'))
    assert answer == 'Monthly costs are 1200.'
    assert len(calls) == 1
    assert str(calls[0].url) == 'https://api.sarvam.ai/v1/chat/completions'
    assert calls[0].headers['api-subscription-key'] == 'fixture-key'
    assert json.loads(calls[0].content)['messages'] == [
        {'role': 'system', 'content': GROUNDING_INSTRUCTIONS}, {'role': 'user', 'content': 'Exact reviewed draft.'},
    ]


def test_translation_preserves_repeated_placeholders_and_never_sends_mapping(transport):
    calls, response = transport
    protected, replacements = _protect_placeholders('[EMAIL_1] and [EMAIL_1]')
    response['value'] = {'translated_text': protected}
    result = asyncio.run(SarvamClient('fixture-key').translate('[EMAIL_1] and [EMAIL_1]', source_language='en-IN', target_language='hi-IN', model='sarvam-translate:v1'))
    assert result == '[EMAIL_1] and [EMAIL_1]'
    payload = json.loads(calls[0].content)
    assert payload == {'input': protected, 'source_language_code': 'en-IN', 'target_language_code': 'hi-IN', 'model': 'sarvam-translate:v1'}
    assert 'placeholder_map' not in payload
    for output in ['', protected + ' PRIVACYPALMASKTOKEN9999END', protected + ' [EMAIL_9]', protected + protected]:
        with pytest.raises(ProviderError):
            _restore_placeholders(output, replacements)
    with pytest.raises(ProviderError):
        _protect_placeholders('PRIVACYPALMASKTOKEN0001END [EMAIL_1]')


def test_tts_requests_wav_and_rejects_invalid_audio(transport):
    calls, response = transport
    response['value'] = {'audios': [wav_base64()]}
    result = asyncio.run(SarvamClient('fixture-key').synthesize('Reviewed answer.', language='hi-IN', model='bulbul:v4-flash'))
    assert result == wav_base64()
    assert json.loads(calls[0].content) == {'text': 'Reviewed answer.', 'language_code': 'hi-IN', 'model': 'bulbul:v4-flash', 'output_audio_codec': 'wav'}
    for invalid in ['not base64', base64.b64encode(b'not audio').decode()]:
        response['value'] = {'audios': [invalid]}
        with pytest.raises(ProviderError):
            asyncio.run(SarvamClient('fixture-key').synthesize('Reviewed answer.', language='en-IN', model='bulbul:v4-flash'))


def test_transcription_sends_audio_without_source_filename(transport):
    calls, response = transport
    response['value'] = {'transcript': 'What are the monthly costs?'}
    audio = base64.b64decode(wav_base64())
    assert asyncio.run(SarvamClient('fixture-key').transcribe(audio, filename='speech.wav', content_type='audio/wav')) == 'What are the monthly costs?'
    assert str(calls[0].url) == 'https://api.sarvam.ai/speech-to-text'
    assert b'saaras:v4' in calls[0].content
    assert b'filename="speech.wav"' in calls[0].content


@pytest.mark.parametrize('status', [401, 429, 500])
def test_provider_failures_are_safe_and_not_retried(transport, status):
    calls, response = transport
    response.update(status=status, value={'error': 'fixture-private-provider-detail'})
    with pytest.raises(ProviderError) as error:
        asyncio.run(SarvamClient('fixture-key').chat(model='sarvam-105b', content='Reviewed draft.'))
    assert 'fixture-private-provider-detail' not in str(error.value)
    assert len(calls) == 1


def test_oversized_translation_response_is_rejected(transport):
    _, response = transport
    response['value'] = {'translated_text': 'x' * 70000}
    with pytest.raises(ProviderError, match='oversized'):
        asyncio.run(SarvamClient('fixture-key').translate('Reviewed draft.', source_language='en-IN', target_language='hi-IN', model='sarvam-translate:v1'))
