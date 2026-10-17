import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../../src/lib/apiClient.js';
import {
  createPrivacyReviewController,
  normalizePrivacyReview,
  PrivacyReviewDataError,
} from '../../src/lib/privacyReview.js';

const rawBackendReview = { backendSpecific: { prompt: 'masked' } };
const adaptReview = raw => ({
  originalRequestText: `Question mapped from ${raw.backendSpecific.prompt}`,
  proposedOutgoingText: 'Use a masked account number.',
  exactOutgoingText: 'Use a masked account number.',
  recommendations: [{ action: 'mask', item: 'Account number', replacement: '[ACCOUNT]', reason: 'Not needed to answer.' }],
  riskFlags: [{ label: 'Residual identifier', description: 'Review the wording.', level: 'warning' }],
});

function loadForEditing(options = {}) {
  const controller = createPrivacyReviewController({ adaptBackendReview: adaptReview, ...options });
  controller.load(rawBackendReview, { source: 'backend' });
  return controller;
}

test('normalizes backend data only through an explicit adapter', () => {
  const normalized = normalizePrivacyReview(rawBackendReview, adaptReview, { source: 'backend' });
  assert.equal(normalized.originalRequestText, 'Question mapped from masked');
  assert.equal(normalized.proposedOutgoingText, 'Use a masked account number.');
  assert.equal(normalized.exactOutgoingText, normalized.proposedOutgoingText);
  assert.equal(normalized.recommendations[0].action, 'mask');
  assert.equal(normalized.recommendations[0].reason, 'Not needed to answer.');
  assert.equal(normalized.riskFlags[0].level, 'warning');
  assert.equal(normalized.source, 'backend');
  assert.throws(() => normalizePrivacyReview(rawBackendReview, adaptReview), /explicitly identified backend/);
  assert.throws(() => normalizePrivacyReview(rawBackendReview), PrivacyReviewDataError);
});

test('rejects malformed adapter output without fabricating findings', () => {
  assert.throws(
    () => normalizePrivacyReview(rawBackendReview, () => ({ originalRequestText: 'Question' }), { source: 'backend' }),
    /recommendations are malformed/,
  );
  assert.throws(
    () => normalizePrivacyReview(rawBackendReview, () => ({ ...adaptReview(rawBackendReview), recommendations: [{ action: 'delete', item: 'x', reason: 'y' }] }), { source: 'backend' }),
    /recommendations are malformed/,
  );
});

test('supports editing and preserves the exact final outgoing text', () => {
  const controller = loadForEditing();
  assert.equal(controller.getState().status, 'review-ready');
  controller.beginEditing();
  controller.updateOutgoingText('User-edited exact text');
  assert.equal(controller.getState().status, 'editing');
  assert.equal(controller.getState().exactOutgoingText, 'User-edited exact text');
  controller.finishEditing();
  assert.equal(controller.getState().status, 'awaiting-approval');
  assert.equal(controller.getState().exactOutgoingText, 'User-edited exact text');
});

test('allows approval of the unchanged proposal only after review confirmation', async () => {
  let calls = 0;
  const controller = loadForEditing({
    sendApprovedRequest: async payload => { calls += 1; return { sent: payload.exactOutgoingText }; },
  });
  assert.equal(await controller.approve(), null);
  assert.equal(calls, 0);
  controller.confirmReview();
  assert.equal(controller.getState().status, 'awaiting-approval');
  await controller.approve();
  assert.equal(controller.getState().status, 'sent');
  assert.equal(calls, 1);
});

test('requires explicit approval and leaves sending unavailable without a backend contract', async () => {
  let sendCalls = 0;
  const controller = loadForEditing({ sendApprovedRequest: async () => { sendCalls += 1; } });
  assert.equal(await controller.approve(), null);
  assert.equal(sendCalls, 0);
  controller.beginEditing();
  controller.finishEditing();
  const unavailable = createPrivacyReviewController({ adaptBackendReview: adaptReview });
  unavailable.load(rawBackendReview, { source: 'backend' });
  unavailable.beginEditing();
  unavailable.finishEditing();
  await unavailable.approve();
  assert.equal(unavailable.getState().status, 'approval-unavailable');
  assert.equal(unavailable.getState().approvalGranted, false);
  assert.match(unavailable.getState().error.message, /Nothing was sent/);
});

test('sends only after approval, prevents duplicate approvals, and marks confirmed send', async () => {
  let resolveSend;
  let calls = 0;
  let receivedPayload;
  const controller = loadForEditing({
    adaptBackendReview: adaptReview,
    sendApprovedRequest: payload => {
      calls += 1;
      receivedPayload = payload;
      return new Promise(resolve => { resolveSend = resolve; });
    },
  });
  controller.beginEditing();
  controller.updateOutgoingText('Exact approved wording');
  controller.finishEditing();
  assert.equal(calls, 0);
  const first = controller.approve();
  const duplicate = controller.approve();
  assert.equal(first, duplicate);
  assert.equal(controller.getState().approvalGranted, true);
  await Promise.resolve();
  assert.equal(calls, 1);
  assert.equal(controller.getState().status, 'sending');
  assert.equal(receivedPayload.exactOutgoingText, 'Exact approved wording');
  resolveSend({ accepted: true });
  await first;
  assert.equal(controller.getState().status, 'sent');
  assert.equal(controller.getState().result.accepted, true);
  await controller.approve();
  assert.equal(calls, 1);
});

test('returns a recoverable failure to editing and requires approval again', async () => {
  let calls = 0;
  const controller = loadForEditing({
    adaptBackendReview: adaptReview,
    sendApprovedRequest: async () => {
      calls += 1;
      if (calls === 1) throw new ApiError('Safe temporary error.', { code: 'http_error', status: 503, retryable: true });
      return { accepted: true };
    },
  });
  controller.beginEditing();
  controller.finishEditing();
  await controller.approve();
  assert.equal(controller.getState().status, 'send-error');
  assert.equal(controller.getState().approvalGranted, false);
  assert.equal(await controller.approve(), null, 'send errors cannot be blindly replayed');
  controller.returnToEditing();
  assert.equal(controller.getState().status, 'editing');
  controller.updateOutgoingText('Reviewed after error');
  controller.finishEditing();
  await controller.approve();
  assert.equal(controller.getState().status, 'sent');
  assert.equal(calls, 2);
});

test('keeps illustrative data outside the backend review model', () => {
  const demoData = { illustrative: true, proposedOutgoingText: 'Sample only' };
  const controller = createPrivacyReviewController();
  controller.load(demoData, { source: 'demo' });
  assert.equal(controller.getState().status, 'review-error');
  assert.equal(controller.getState().review, null);
  assert.equal(controller.getState().error.code, 'invalid_review');
});
