import assert from 'node:assert/strict';
import test from 'node:test';
import { createPrivacyPalApi, mapProviderList } from '../../src/lib/privacyPalApi.js';

const workflow = { workflow_id: 'w-1', version: 1, question: 'Question?', draft: 'Reviewed draft.', findings: [],
  residual_review: { status: 'ready_for_user_review', findings: [], reasons: [] }, review_complete: true,
  acknowledged: false, send_state: 'review', provider: { id: 'sarvam', configured: true }, pages_used: [1] };

test('provider discovery retains only configured backend choices and question binds the selected provider', async () => {
  let call;
  const api = createPrivacyPalApi({ client: { request: async (...args) => { call = args; return workflow; } } });
  await api.submitQuestion('s-1', 'd-1', 'Question?', { providerId: 'sarvam' });
  assert.deepEqual(call[1].body, { document_id: 'd-1', question: 'Question?', provider_id: 'sarvam' });
  assert.equal(mapProviderList({ items: [{ id: 'sarvam', name: 'Sarvam AI', configured: true }] }).items[0].id, 'sarvam');
  assert.throws(() => mapProviderList({ items: [{ id: 'sarvam', name: 'Sarvam AI', configured: false }] }));
});

test('translation carries explicit consent and version and rejects mismatched previews', async () => {
  let call;
  let result = { workflow_id: 'w/1', version: 2, translated_text: 'अनुवाद', target_language: 'hi-IN' };
  const api = createPrivacyPalApi({ client: { request: async (...args) => { call = args; return result; } } });
  await api.translateDraft('s/1', 'w/1', 2, 'en-IN', 'hi-IN');
  assert.equal(call[0], 'api/v1/sessions/s%2F1/workflows/w%2F1/translate-draft');
  assert.deepEqual(call[1].body, { version: 2, source_language: 'en-IN', target_language: 'hi-IN', consent: true });
  result = { ...result, version: 1 };
  await assert.rejects(api.translateDraft('s/1', 'w/1', 2, 'en-IN', 'hi-IN'), error => error.code === 'invalid_response');
});

test('transcription uploads one audio file and consent without submitting any question', async () => {
  const calls = [];
  const api = createPrivacyPalApi({ client: { request: async (...args) => { calls.push(args); return { transcript: 'Reviewed voice question?', review_required: true }; } } });
  const audio = new File(['synthetic audio'], 'voice.wav', { type: 'audio/wav' });
  const result = await api.transcribeAudio('s-1', audio);
  assert.equal(result.transcript, 'Reviewed voice question?');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'api/v1/sessions/s-1/speech/transcribe');
  assert.equal(calls[0][1].body.get('consent'), 'true');
  assert.equal(calls[0][1].body.get('file').name, 'voice.wav');
  assert.equal(calls[0][1].headers, undefined);
});

test('answer services send the displayed answer only with separate consent', async () => {
  const calls = [];
  const api = createPrivacyPalApi({ client: { request: async (...args) => {
    calls.push(args);
    return args[0].endsWith('/speech/synthesize') ? { audio_base64: 'UklGRgAAAABXQVZF', content_type: 'audio/wav' } : { translated_text: 'अनुवाद', target_language: 'hi-IN' };
  } } });
  await api.translateAnswer('s-1', 'Displayed answer.', 'en-IN', 'hi-IN');
  await api.synthesizeSpeech('s-1', 'Displayed answer.', 'hi-IN');
  for (const [, options] of calls) { assert.equal(options.body.consent, true); assert.equal(options.body.text, 'Displayed answer.'); }
  assert.deepEqual(calls[1][1].body, { consent: true, text: 'Displayed answer.', language: 'hi-IN' });
});

test('invalid speech/transcription data cannot become playable audio or an auto-submitted question', async () => {
  const api = createPrivacyPalApi({ client: { request: async () => ({ transcript: 'Question?', audio_base64: 'x', content_type: 'text/html' }) } });
  await assert.rejects(api.synthesizeSpeech('s-1', 'Answer.', 'hi-IN'), error => error.code === 'invalid_response');
  await assert.rejects(api.transcribeAudio('s-1', new File(['voice'], 'voice.wav')), error => error.code === 'invalid_response');
});
