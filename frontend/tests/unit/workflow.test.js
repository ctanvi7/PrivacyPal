import assert from 'node:assert/strict';
import test from 'node:test';
import { createInitialWorkflowState, workflowReducer } from '../../src/lib/workflow.js';

function transition(state, type, payload = {}) {
  return workflowReducer(state, { type, ...payload });
}

function readyState() {
  let state = transition(createInitialWorkflowState(), 'DOCUMENT_SELECTED', { document: { name: 'pay.pdf' } });
  state = transition(state, 'UPLOAD_STARTED');
  return transition(state, 'UPLOAD_SUCCEEDED');
}

test('models document selection, upload, question processing, review, edit, approval, and answer', () => {
  let state = createInitialWorkflowState();
  assert.equal(state.status, 'empty');
  state = transition(state, 'DOCUMENT_SELECTED', { document: { name: 'pay.pdf' } });
  assert.equal(state.status, 'document-selected');
  state = transition(state, 'UPLOAD_STARTED');
  assert.equal(state.status, 'uploading');
  state = transition(state, 'UPLOAD_SUCCEEDED');
  assert.equal(state.status, 'uploaded-ready');
  state = transition(state, 'QUESTION_SUBMITTED', { question: '  Review income  ' });
  assert.equal(state.status, 'processing');
  assert.equal(state.question, 'Review income');
  const review = { findings: [{ action: 'mask', reason: 'Identifier' }] };
  state = transition(state, 'REVIEW_READY', { review, proposedRequest: 'Masked request' });
  assert.equal(state.status, 'review-ready');
  assert.equal(state.review, review);
  assert.equal(state.proposedRequest, 'Masked request');
  state = transition(state, 'EDITING_STARTED');
  assert.equal(state.status, 'editing');
  state = transition(state, 'REQUEST_EDITED', { request: 'Final edited request' });
  assert.equal(state.finalOutgoingText, 'Final edited request');
  state = transition(state, 'EDITING_FINISHED');
  assert.equal(state.status, 'awaiting-approval');
  assert.equal(state.editedRequest, 'Final edited request');
  const blockedSend = transition(state, 'APPROVAL_STARTED');
  assert.equal(blockedSend, state, 'sending cannot start before explicit approval');
  state = transition(state, 'USER_APPROVED');
  assert.equal(state.status, 'approved');
  assert.equal(state.approvalGranted, true);
  state = transition(state, 'APPROVAL_STARTED');
  assert.equal(state.status, 'sending');
  state = transition(state, 'APPROVAL_SENT');
  assert.equal(state.status, 'sent');
  const answer = { text: 'Answer', citations: [{ page: 2 }] };
  state = transition(state, 'ANSWER_RECEIVED', { answer });
  assert.equal(state.status, 'answered');
  assert.equal(state.answer, answer);
});

test('keeps invalid or out-of-order events from advancing the workflow', () => {
  const empty = createInitialWorkflowState();
  assert.equal(transition(empty, 'UPLOAD_STARTED'), empty);
  const ready = readyState();
  assert.equal(transition(ready, 'QUESTION_SUBMITTED', { question: '  ' }), ready);
  assert.equal(transition(ready, 'ANSWER_RECEIVED', { answer: 'fake' }), ready);
});

test('recovers from upload, processing, approval, and network errors', () => {
  const failure = { message: 'Unavailable' };
  let state = transition(createInitialWorkflowState(), 'DOCUMENT_SELECTED', { document: { name: 'pay.pdf' } });
  state = transition(state, 'UPLOAD_STARTED');
  state = transition(state, 'UPLOAD_FAILED', { error: failure });
  assert.equal(state.status, 'upload-error');
  assert.equal(transition(state, 'RETRY').status, 'document-selected');

  state = transition(readyState(), 'QUESTION_SUBMITTED', { question: 'Question' });
  state = transition(state, 'PROCESSING_FAILED', { error: failure });
  assert.equal(state.status, 'processing-error');
  assert.equal(transition(state, 'RETRY').status, 'uploaded-ready');

  state = transition(readyState(), 'QUESTION_SUBMITTED', { question: 'Question' });
  state = transition(state, 'REVIEW_READY', { review: {}, proposedRequest: 'Draft' });
  state = transition(state, 'EDITING_STARTED');
  state = transition(state, 'REQUEST_EDITED', { request: 'Edited' });
  state = transition(state, 'EDITING_FINISHED');
  state = transition(state, 'USER_APPROVED');
  state = transition(state, 'APPROVAL_STARTED');
  state = transition(state, 'APPROVAL_FAILED', { error: failure });
  assert.equal(state.status, 'approval-error');
  assert.equal(transition(state, 'RETRY').status, 'awaiting-approval');

  state = transition(readyState(), 'QUESTION_SUBMITTED', { question: 'Question' });
  state = transition(state, 'NETWORK_FAILED', { error: failure });
  assert.equal(state.status, 'network-error');
  assert.equal(transition(state, 'RETRY').status, 'processing');

  state = transition(readyState(), 'QUESTION_SUBMITTED', { question: 'Question' });
  state = transition(state, 'REVIEW_READY', { review: {}, proposedRequest: 'Draft' });
  state = transition(state, 'EDITING_STARTED');
  state = transition(state, 'EDITING_FINISHED');
  state = transition(state, 'USER_APPROVED');
  state = transition(state, 'APPROVAL_STARTED');
  state = transition(state, 'NETWORK_FAILED', { error: failure });
  assert.equal(transition(state, 'RETRY').status, 'approval-error', 'ambiguous sending requires review, not automatic resend');
});

test('reset clears document and workflow data', () => {
  const selected = transition(createInitialWorkflowState(), 'DOCUMENT_SELECTED', { document: { name: 'pay.pdf' } });
  assert.deepEqual(transition(selected, 'RESET'), createInitialWorkflowState());
});
