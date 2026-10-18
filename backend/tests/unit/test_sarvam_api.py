"""Language and speech must compose with the existing approval/session gates."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.privacy.pipeline import ResidualReview
from app.provider.answer_provider import ProviderError

ORIGIN = {'Origin': 'http://127.0.0.1:5173'}
ANSWER = 'The monthly costs are 1200.'


async def analyze(_self, context, registry):
    for name, args in [('inspect_document', {'terms': ['costs']}), ('detect_sensitive_data', {}),
                       ('select_relevant_content', {}), ('propose_sanitized_request', {}),
                       ('review_residual_risk', {'risk_categories': []})]:
        registry.execute({'function': {'name': name, 'arguments': args}}, context)
    return context


@pytest.fixture
def feature(monkeypatch):
    calls = []
    class Sarvam:
        answer = ANSWER
        fail = False
        translated = 'मासिक खर्च 1200 है।'
        def __init__(self, *_args): pass
        async def chat(self, **kwargs):
            calls.append(('chat', kwargs))
            if self.fail: raise ProviderError('Fixture failure')
            return self.answer
        async def translate(self, text, **kwargs):
            calls.append(('translate', text, kwargs))
            return self.translated
        async def transcribe(self, audio, **kwargs):
            calls.append(('transcribe', audio, kwargs))
            return 'What are the monthly costs?'
        async def synthesize(self, text, **kwargs):
            calls.append(('synthesize', text, kwargs))
            return 'UklGRgAAAABXQVZF'
    monkeypatch.setattr(main, 'settings', replace(main.settings, sarvam_api_key='fixture-only-key'))
    monkeypatch.setattr(main, 'SarvamClient', Sarvam)
    monkeypatch.setattr(main.OllamaAnalyzer, 'run_privacy_workflow', analyze)
    async def edit(*_args): return ()
    monkeypatch.setattr(main.OllamaAnalyzer, 'review_edited_draft', edit)
    main.sessions.items.clear()
    with TestClient(main.app) as client:
        yield client, calls, Sarvam
    main.sessions.items.clear()


def review(feature):
    client, _, _ = feature
    session = client.post('/api/v1/sessions', headers=ORIGIN).json()
    sid = session['session_id']
    document = client.post(f'/api/v1/sessions/{sid}/documents', headers=ORIGIN,
                           json={'pasted_text': 'Monthly costs are 1200. Contact demo.person@example.test.'}).json()
    response = client.post(f'/api/v1/sessions/{sid}/questions', headers=ORIGIN,
                           json={'document_id': document['document_id'], 'question': 'What are the monthly costs?', 'provider_id': 'sarvam'})
    assert response.status_code == 200
    return sid, response.json(), f"/api/v1/sessions/{sid}/workflows/{response.json()['workflow_id']}"


def test_selected_provider_is_bound_to_review_and_only_approved_payload_is_sent(feature):
    client, calls, _ = feature
    sid, result, url = review(feature)
    assert result['provider']['id'] == 'sarvam' and calls == []
    approved = client.post(url + '/approve', headers=ORIGIN, json={'version': 1, 'provider_id': 'default'})
    assert approved.status_code == 200
    assert approved.json()['provider']['id'] == 'sarvam'
    assert calls == [('chat', {'model': 'sarvam-105b', 'content': result['draft']})]
    assert 'demo.person@example.test' not in result['draft']
    assert client.post(url + '/approve', headers=ORIGIN, json={'version': 1}).status_code == 409
    assert main.sessions.items[sid].document is None
    assert main.sessions.items[sid].answer_digest
    assert approved.json()['history_saved'] is True


@pytest.mark.parametrize('mode', ['withheld', 'failure'])
def test_sarvam_failure_or_unsafe_answer_is_not_saved_or_retried(feature, mode):
    client, calls, sarvam = feature
    sid, _, url = review(feature)
    if mode == 'withheld': sarvam.answer = 'API key: SYNTHETIC_PRIVATE_SECRET_12345'
    else: sarvam.fail = True
    assert client.post(url + '/approve', headers=ORIGIN, json={'version': 1}).status_code == 502
    assert client.post(url + '/approve', headers=ORIGIN, json={'version': 1}).status_code == 409
    assert len(calls) == 1
    assert main.sessions.items[sid].answer_digest is None
    cid = main.sessions.items[sid].conversation_id
    assert client.get(f'/api/v1/conversations/{cid}').json()['messages'] == []


def test_draft_translation_is_preview_then_requires_recheck_and_fresh_approval(feature):
    client, calls, _ = feature
    _, result, url = review(feature)
    body = {'consent': True, 'version': 1, 'source_language': 'en-IN', 'target_language': 'hi-IN'}
    translated = client.post(url + '/translate-draft', headers=ORIGIN, json=body)
    assert translated.status_code == 200
    assert calls[0][0:2] == ('translate', result['draft'])
    assert all(call[0] != 'chat' for call in calls)
    text = translated.json()['translated_text']
    edited = client.patch(url + '/draft', headers=ORIGIN, json={'version': 1, 'draft': text})
    assert edited.status_code == 200 and edited.json()['version'] == 2
    assert client.post(url + '/approve', headers=ORIGIN, json={'version': 1}).status_code == 409
    assert all(call[0] != 'chat' for call in calls)


@pytest.mark.parametrize('problem', ['no-consent', 'stale', 'blocked', 'warning', 'identity', 'secret', 'language'])
def test_invalid_draft_translation_never_calls_sarvam(feature, problem):
    client, calls, _ = feature
    sid, _, url = review(feature)
    workflow = main.sessions.items[sid].workflow
    body = {'consent': True, 'version': 1, 'source_language': 'en-IN', 'target_language': 'hi-IN'}
    if problem == 'no-consent': body['consent'] = False
    elif problem == 'stale': body['version'] = 2
    elif problem == 'blocked': workflow.review_complete = False
    elif problem == 'warning': workflow.residual = ResidualReview('needs_review', (), ('Check context.',))
    elif problem == 'identity': workflow.draft += ' Contact demo.person@example.test.'
    elif problem == 'secret': workflow.draft += ' API key: SYNTHETIC_PRIVATE_SECRET_12345'
    elif problem == 'language': body['target_language'] = 'xx-XX'
    assert client.post(url + '/translate-draft', headers=ORIGIN, json=body).status_code in {403, 409, 422}
    assert calls == []


def test_clear_during_translation_prevents_stale_preview_and_blocks_concurrent_approval(feature, monkeypatch):
    client, calls, sarvam = feature
    sid, _, url = review(feature)
    started, release = Event(), Event()
    async def waiting(*_args, **_kwargs):
        calls.append(('translate',))
        started.set()
        await asyncio.to_thread(release.wait, 5)
        return 'मासिक खर्च 1200 है।'
    monkeypatch.setattr(sarvam, 'translate', waiting)
    body = {'consent': True, 'version': 1, 'source_language': 'en-IN', 'target_language': 'hi-IN'}
    with ThreadPoolExecutor(max_workers=1) as pool:
        translating = pool.submit(client.post, url + '/translate-draft', headers=ORIGIN, json=body)
        assert started.wait(3)
        assert client.post(url + '/approve', headers=ORIGIN, json={'version': 1}).status_code == 409
        assert client.patch(url + '/draft', headers=ORIGIN, json={'version': 1, 'draft': 'Changed draft.'}).status_code == 409
        assert client.post(f'/api/v1/sessions/{sid}/clear', headers=ORIGIN).status_code == 200
        release.set()
        assert translating.result(timeout=5).status_code == 409
    assert all(call[0] != 'chat' for call in calls)


@pytest.mark.parametrize('route,extra', [('translate-answer', {'source_language': 'en-IN', 'target_language': 'hi-IN'}), ('speech/synthesize', {'language': 'hi-IN'})])
def test_answer_services_require_exact_displayed_answer_and_consent(feature, route, extra):
    client, calls, _ = feature
    sid, _, url = review(feature)
    assert client.post(url + '/approve', headers=ORIGIN, json={'version': 1}).status_code == 200
    endpoint = f'/api/v1/sessions/{sid}/{route}'
    for text, consent in [(ANSWER, False), ('Unapproved source text.', True)]:
        response = client.post(endpoint, headers=ORIGIN, json={'text': text, 'consent': consent, **extra})
        assert response.status_code in {403, 409}
    assert len(calls) == 1
    assert client.post(endpoint, headers=ORIGIN, json={'text': ANSWER, 'consent': True, **extra}).status_code == 200
    assert calls[-1][1] == ANSWER
    client.post(f'/api/v1/sessions/{sid}/clear', headers=ORIGIN)
    assert client.post(endpoint, headers=ORIGIN, json={'text': ANSWER, 'consent': True, **extra}).status_code == 404


def test_transcription_needs_consent_and_never_submits_a_question(feature, monkeypatch):
    client, calls, _ = feature
    sid = client.post('/api/v1/sessions', headers=ORIGIN).json()['session_id']
    url = f'/api/v1/sessions/{sid}/speech/transcribe'
    file = {'file': ('private-filename.wav', b'fixture audio', 'audio/wav')}
    assert client.post(url, headers=ORIGIN, data={'consent': 'false'}, files=file).status_code == 403
    assert calls == []
    result = client.post(url, headers=ORIGIN, data={'consent': 'true'}, files=file)
    assert result.status_code == 200 and result.json()['review_required'] is True
    assert main.sessions.items[sid].workflow is None
    assert calls[0][2]['filename'] == 'speech.wav'
    monkeypatch.setattr(main, 'MAX_AUDIO_BYTES', 4)
    assert client.post(url, headers=ORIGIN, data={'consent': 'true'}, files=file).status_code == 413
    assert len(calls) == 1


def test_unconfigured_sarvam_not_advertised_and_credentials_never_returned(feature, monkeypatch):
    client, _, _ = feature
    providers = client.get('/api/v1/providers').json()
    assert any(item['id'] == 'sarvam' for item in providers['items'])
    assert 'fixture-only-key' not in str(providers)
    monkeypatch.setattr(main, 'settings', replace(main.settings, sarvam_api_key=''))
    assert all(item['id'] != 'sarvam' for item in client.get('/api/v1/providers').json()['items'])
