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

test('attaches session creation to the selected conversation without changing the route', async () => {
  let call;
  const api = createPrivacyPalApi({ client: { request: async (...args) => { call = args; return { session_id: 's-1', conversation_id: 'c-1', expires_in_seconds: 1800 }; } } });
  const session = await api.createSession({ conversationId: 'c-1' });
  assert.equal(call[0], 'api/v1/sessions');
  assert.deepEqual(call[1].body, { conversation_id: 'c-1' });
  assert.equal(session.conversation_id, 'c-1');
  const mismatched = createPrivacyPalApi({ client: { request: async () => ({ session_id: 's-2', conversation_id: 'other', expires_in_seconds: 1800 }) } });
  await assert.rejects(mismatched.createSession({ conversationId: 'c-1' }), error => error.code === 'invalid_response');
});

test('connects conversation create, paginated list, detail, and confirmed delete routes', async () => {
  const calls = [];
  const api = createPrivacyPalApi({ client: { request: async (...args) => {
    calls.push(args);
    if (args[0] === 'api/v1/conversations' || args[0].includes('?')) return args[1].method === 'POST'
      ? { conversation_id: 'c-1', created_at: 'today', updated_at: 'today' }
      : { items: [{ conversation_id: 'c-1', created_at: 'today', updated_at: 'today', preview: 'Question' }], limit: 25, offset: 50 };
    if (args[1].method === 'DELETE') return { status: 'deleted' };
    return { conversation_id: 'c-1', created_at: 'today', updated_at: 'today', messages: [
      { message_id: 'm2', role: 'assistant', content: 'Answer', created_at: '2026-10-17T10:02:00Z', status: 'complete' },
      { message_id: 'm1', role: 'user', content: 'Question', created_at: '2026-10-17T10:01:00Z', status: 'complete' },
    ] };
  } } });
  assert.equal((await api.createConversation()).conversation_id, 'c-1');
  assert.equal((await api.listConversations({ limit: 25, offset: 50 })).items[0].preview, 'Question');
  const detail = await api.getConversation('c/1');
  assert.equal(calls[2][0], 'api/v1/conversations/c%2F1');
  assert.deepEqual(detail.messages.map(message => message.role), ['user', 'assistant']);
  assert.deepEqual(await api.deleteConversation('c-1'), { status: 'deleted' });
  assert.equal(calls[1][0], 'api/v1/conversations?limit=25&offset=50');
  assert.equal(calls[3][1].method, 'DELETE');
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

test('edits the active draft with the backend workflow route and current version', async () => {
  let call;
  const api = createPrivacyPalApi({ client: { request: async (...args) => { call = args; return {
    workflow_id: 'w-1', version: 2, question: 'Question?', draft: 'Edited exact text', findings: [],
    residual_review: { status: 'ready_for_user_review', findings: [], reasons: [] }, review_complete: true,
    acknowledged: false, send_state: 'review', provider: { name: 'Provider', configured: true }, pages_used: [2],
  }; } } });
  const controller = new AbortController();
  const result = await api.updateDraft('s/1', 'w/1', 1, 'Edited exact text', { signal: controller.signal });
  assert.equal(call[0], 'api/v1/sessions/s%2F1/workflows/w%2F1/draft');
  assert.equal(call[1].method, 'PATCH');
  assert.deepEqual(call[1].body, { version: 1, draft: 'Edited exact text' });
  assert.equal(call[1].signal, controller.signal);
  assert.equal(result.version, 2);
  assert.equal(result.draft, 'Edited exact text');
});

test('acknowledges the current backend workflow version', async () => {
  let call;
  const api = createPrivacyPalApi({ client: { request: async (...args) => { call = args; return {
    workflow_id: 'w-1', version: 1, question: 'Question?', draft: 'Safe text', findings: [],
    residual_review: { status: 'needs_review', findings: [], reasons: ['Check contextual risk.'] }, review_complete: true,
    acknowledged: true, send_state: 'review', provider: { name: 'Provider', configured: true }, pages_used: [],
  }; } } });
  const result = await api.acknowledgeReview('s-1', 'w-1', 1);
  assert.equal(call[0], 'api/v1/sessions/s-1/workflows/w-1/acknowledge');
  assert.equal(call[1].method, 'POST');
  assert.deepEqual(call[1].body, { version: 1 });
  assert.equal(result.acknowledged, true);
});

test('approves only the workflow version and maps the confirmed answer response', async () => {
  let call;
  const api = createPrivacyPalApi({ client: { request: async (...args) => { call = args; return {
    workflow_id: 'w-1', version: 3, answer: 'Actual backend answer', send_state: 'sent',
    provider: { name: 'Provider' }, pages_used: [1, 3], history_saved: true,
  }; } } });
  const result = await api.approveWorkflow('s-1', 'w-1', 3);
  assert.equal(call[0], 'api/v1/sessions/s-1/workflows/w-1/approve');
  assert.equal(call[1].method, 'POST');
  assert.deepEqual(call[1].body, { version: 3 });
  assert.equal(result.answer, 'Actual backend answer');
  assert.deepEqual(result.pages_used, [1, 3]);
  const malformed = createPrivacyPalApi({ client: { request: async () => ({ workflow_id: 'w-1', version: 3, answer: 'answer' }) } });
  await assert.rejects(malformed.approveWorkflow('s-1', 'w-1', 3), error => error.code === 'invalid_response');
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
