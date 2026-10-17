import assert from 'node:assert/strict';
import test from 'node:test';
import {
  ApiError,
  createApiClient,
  DEFAULT_API_BASE_URL,
  WORKFLOW_API_CONTRACT,
} from '../../src/lib/apiClient.js';

test('uses the configured base URL and JSON-encodes request bodies', async () => {
  let requestedUrl;
  let requestedOptions;
  const client = createApiClient({
    baseUrl: 'http://localhost:8123/',
    fetchImpl: async (url, options) => {
      requestedUrl = url;
      requestedOptions = options;
      return new Response(JSON.stringify({ accepted: true }), {
        headers: { 'content-type': 'application/json' },
      });
    },
  });

  assert.deepEqual(await client.request('/api/example', { method: 'POST', body: { question: 'Hi' } }), { accepted: true });
  assert.equal(client.baseUrl, 'http://localhost:8123/');
  assert.equal(requestedUrl.href, 'http://localhost:8123/api/example');
  assert.equal(requestedOptions.headers.get('accept'), 'application/json');
  assert.equal(requestedOptions.headers.get('content-type'), 'application/json');
  assert.equal(requestedOptions.body, JSON.stringify({ question: 'Hi' }));
});

test('returns successful non-JSON responses as text and handles empty responses', async () => {
  const client = createApiClient({ fetchImpl: async () => new Response('ready', { status: 200 }) });
  assert.equal(await client.request('health'), 'ready');

  const emptyClient = createApiClient({ fetchImpl: async () => new Response(null, { status: 204 }) });
  assert.equal(await emptyClient.request('health'), null);
});

test('maps HTTP errors to safe messages without exposing the response body', async () => {
  const client = createApiClient({
    fetchImpl: async () => new Response(JSON.stringify({ detail: 'sensitive internal detail' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    }),
  });
  await assert.rejects(client.request('status'), error => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, 'http_error');
    assert.equal(error.status, 503);
    assert.equal(error.retryable, true);
    assert.doesNotMatch(error.message, /sensitive internal detail/);
    return true;
  });

  const nonJsonClient = createApiClient({
    fetchImpl: async () => new Response('private proxy response', { status: 502, statusText: 'Bad Gateway' }),
  });
  await assert.rejects(nonJsonClient.request('status'), error => {
    assert.equal(error.code, 'http_error');
    assert.equal(error.status, 502);
    assert.doesNotMatch(error.message, /private proxy response/);
    return true;
  });
});

test('maps network failures and malformed JSON to safe API errors', async () => {
  const offlineClient = createApiClient({ fetchImpl: async () => { throw new TypeError('private socket detail'); } });
  await assert.rejects(offlineClient.request('status'), error => error.code === 'network_error' && !/private socket detail/.test(error.message));

  const malformedClient = createApiClient({
    fetchImpl: async () => new Response('{broken', { headers: { 'content-type': 'application/json' } }),
  });
  await assert.rejects(malformedClient.request('status'), error => error.code === 'invalid_response');
});

test('supports caller cancellation and request timeouts', async () => {
  const controller = new AbortController();
  controller.abort();
  const cancelledClient = createApiClient({ fetchImpl: async (_url, { signal }) => {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    return new Response('unexpected');
  } });
  await assert.rejects(cancelledClient.request('status', { signal: controller.signal }), error => error.code === 'cancelled');

  const timeoutClient = createApiClient({
    timeoutMs: 5,
    fetchImpl: (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }),
  });
  await assert.rejects(timeoutClient.request('status'), error => error.code === 'timeout' && error.retryable);
});

test('does not allow requests to escape the configured origin', async () => {
  const client = createApiClient({ fetchImpl: async () => new Response('unexpected') });
  assert.equal(DEFAULT_API_BASE_URL, 'http://127.0.0.1:8000');
  await assert.rejects(client.request('https://example.com/private'), TypeError);
  assert.equal(WORKFLOW_API_CONTRACT.implemented, true);
  assert.deepEqual(WORKFLOW_API_CONTRACT.pending, ['draft editing', 'acknowledgement', 'approval and answer delivery']);
});
