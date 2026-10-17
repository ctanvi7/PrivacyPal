import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../../src/lib/apiClient.js';
import { createQuestionController } from '../../src/lib/questionController.js';

const session = { session_id: 'session-1' };
const uploadedSessionId = session.session_id;
const uploadedDocument = { document_id: 'confirmed-document' };

test('rejects empty questions and requires a server-confirmed uploaded document', async () => {
  let calls = 0;
  const controller = createQuestionController({ submitQuestion: async () => { calls += 1; } });
  await controller.submit({ question: '   ', uploadedDocument });
  assert.equal(controller.getState().status, 'validation-error');
  assert.equal(controller.getState().error.code, 'empty_question');
  await controller.submit({ question: 'Summarize this', uploadedDocument: null, session, uploadedSessionId });
  assert.equal(controller.getState().status, 'blocked');
  assert.equal(controller.getState().error.code, 'upload_required');
  await controller.submit({ question: 'Summarize this', uploadedDocument });
  assert.equal(controller.getState().status, 'blocked');
  await controller.submit({ question: 'Summarize this', uploadedDocument, session, uploadedSessionId: 'different-session' });
  assert.equal(controller.getState().status, 'blocked');
  assert.equal(calls, 0);
});

test('submits a valid question only with an uploaded document', async () => {
  let received;
  const reviewResponse = { backendPayload: true };
  const controller = createQuestionController({
    submitQuestion: async (question, document, context) => {
      received = { question, document, session: context.session };
      return reviewResponse;
    },
  });
  controller.setQuestion('  What is the total?  ');
  await controller.submit({ uploadedDocument, session, uploadedSessionId });
  assert.deepEqual(received, { question: 'What is the total?', document: uploadedDocument, session });
  assert.equal(controller.getState().status, 'review-ready');
  assert.equal(controller.getState().result, reviewResponse);
});

test('prevents duplicate question submissions while one request is pending', async () => {
  let resolveRequest;
  let calls = 0;
  const controller = createQuestionController({
    submitQuestion: () => {
      calls += 1;
      return new Promise(resolve => { resolveRequest = resolve; });
    },
  });
  const first = controller.submit({ question: 'Question', uploadedDocument, session, uploadedSessionId });
  const second = controller.submit({ question: 'Question', uploadedDocument, session, uploadedSessionId });
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(calls, 1);
  resolveRequest({ requestId: 'mock-review' });
  await first;
  assert.equal(controller.getState().status, 'review-ready');
});

test('cancels processing and supports retry after a recoverable error', async () => {
  const cancelled = createQuestionController({
    submitQuestion: (_question, _document, { signal }) => new Promise((_resolve, reject) => {
      const abort = () => reject(new DOMException('Aborted', 'AbortError'));
      if (signal.aborted) abort();
      else signal.addEventListener('abort', abort, { once: true });
    }),
  });
  const pending = cancelled.submit({ question: 'Question', uploadedDocument, session, uploadedSessionId });
  cancelled.cancel();
  await pending;
  assert.equal(cancelled.getState().status, 'cancelled');

  let attempts = 0;
  const retryable = createQuestionController({
    submitQuestion: async () => {
      attempts += 1;
      if (attempts === 1) throw new ApiError('Service unavailable.', { code: 'network_error', retryable: true });
      return { review: 'mocked response' };
    },
  });
  await retryable.submit({ question: 'Question', uploadedDocument, session, uploadedSessionId });
  assert.equal(retryable.getState().status, 'processing-error');
  await retryable.retry({ uploadedDocument, session, uploadedSessionId });
  assert.equal(attempts, 2);
  assert.equal(retryable.getState().status, 'review-ready');
});

test('does not submit when analysis integration is absent', async () => {
  const controller = createQuestionController();
  await controller.submit({ question: 'Question', uploadedDocument, session, uploadedSessionId });
  assert.equal(controller.getState().status, 'unavailable');
  assert.equal(controller.getState().result, null);
  assert.equal(controller.getState().error.code, 'integration_unavailable');
});
