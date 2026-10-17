import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError, createApiClient } from '../../src/lib/apiClient.js';
import { createPrivacyPalApi, mapWorkflowResponse } from '../../src/lib/privacyPalApi.js';

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } });
}

test('creates a session with the confirmed route and validates its response', async () => {
  let request;
  const api = createPrivacyPalApi({ client: { request: async (...args) => { request = args; return { session_id: 's-1', expires_in_seconds: 1800 }; } } });
  assert.deepEqual(await api.createSession(), { session_id: 's-1', expires_in_seconds: 1800 });
  assert.deepEqual(request.slice(0, 2), ['api/v1/sessions', { method: 'POST', signal: undefined }]);
  const malformed = createPrivacyPalApi({ client: { request: async () => ({ session_id: '' }) } });
  await assert.rejects(malformed.createSession(), error => error instanceof ApiError && error.code === 'invalid_response');
});

test('uploads one multipart file field without setting Content-Type manually', async () => {
  let call;
  const api = createPrivacyPalApi({ client: { request: async (...args) => {
    call = args;
    return { document_id: 'd-1', source_type: 'pdf', status: 'ready', page_count: 1, character_count: 120, extracted_character_count: 120 };
  } } });
  const file = new File(['%PDF-1.4'], 'pay.pdf', { type: 'application/pdf' });
  const response = await api.uploadDocument('s/one', file);
  assert.equal(call[0], 'api/v1/sessions/s%2Fone/documents');
  assert.equal(call[1].method, 'POST');
  assert.equal(call[1].body instanceof FormData, true);
  assert.deepEqual([...call[1].body.keys()], ['file']);
  assert.equal(call[1].body.get('file').name, 'pay.pdf');
  assert.equal('headers' in call[1] && new Headers(call[1].headers).has('content-type'), false);
  assert.equal(response.document_id, 'd-1');
  const missingId = createPrivacyPalApi({ client: { request: async () => ({ source_type: 'pdf', status: 'ready', page_count: 1, character_count: 10 }) } });
  await assert.rejects(missingId.uploadDocument('s-1', file), error => error.code === 'invalid_response');
});

test('submits question JSON to the session route and preserves actual workflow fields', async () => {
  let call;
  const backendResponse = {
    workflow_id: 'w-1', version: 1, question: 'What total?', draft: 'Summarize the total.',
    findings: [{ finding_id: 'f-1', category: 'email', action: 'mask', reason: 'Identifier' }],
    residual_review: { status: 'ready_for_user_review', findings: [], reasons: [] },
    review_complete: true, acknowledged: false, send_state: 'review',
    provider: { name: 'local provider label', configured: false }, pages_used: [1], backend_extra: 'kept',
  };
  const api = createPrivacyPalApi({ client: { request: async (...args) => { call = args; return backendResponse; } } });
  const response = await api.submitQuestion('s-1', 'd-1', 'What total?');
  assert.equal(call[0], 'api/v1/sessions/s-1/questions');
  assert.equal(call[1].method, 'POST');
  assert.deepEqual(call[1].body, { document_id: 'd-1', question: 'What total?' });
  assert.deepEqual(response, backendResponse);
  assert.equal(response.findings[0].reason, 'Identifier');
  assert.equal(response.backend_extra, 'kept');
});

test('rejects malformed workflow responses without filling missing findings', () => {
  assert.throws(() => mapWorkflowResponse({ workflow_id: 'w', version: 1, question: 'q', draft: 'd' }), error => error.code === 'invalid_response');
});

test('shows safe backend API errors and network errors without leaking raw bodies', async () => {
  const errorClient = createApiClient({ fetchImpl: async () => jsonResponse({ error: { code: 'FILE_TOO_LARGE', message: 'The upload exceeds the limit.', retryable: false } }, 413) });
  await assert.rejects(errorClient.request('upload'), error => error.code === 'FILE_TOO_LARGE' && error.message === 'The upload exceeds the limit.' && !error.retryable);
  const hostileClient = createApiClient({ fetchImpl: async () => jsonResponse({ error: { code: 'FAIL', message: 'Traceback private stack data', retryable: false } }, 500) });
  await assert.rejects(hostileClient.request('analysis'), error => !/Traceback/.test(error.message));
  const networkClient = createApiClient({ fetchImpl: async () => { throw new TypeError('socket secret'); } });
  await assert.rejects(networkClient.request('analysis'), error => error.code === 'network_error' && !/socket secret/.test(error.message));
});

test('passes cancellation signals through API operations', async () => {
  let options;
  const api = createPrivacyPalApi({ client: { request: async (_path, requestOptions) => { options = requestOptions; throw new ApiError('Cancelled.', { code: 'cancelled' }); } } });
  const controller = new AbortController();
  await assert.rejects(api.createSession({ signal: controller.signal }), error => error.code === 'cancelled');
  assert.equal(options.signal, controller.signal);
});
