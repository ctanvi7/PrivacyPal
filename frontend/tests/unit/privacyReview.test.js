import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../../src/lib/apiClient.js';
import {
  adaptBackendWorkflow,
  createPrivacyReviewController,
} from '../../src/lib/privacyReview.js';

function workflow(overrides = {}) {
  return {
    workflow_id: 'workflow-1',
    version: 1,
    question: 'What are the monthly costs?',
    draft: 'Summarize monthly costs without identifiers.',
    findings: [{ finding_id: 'f-1', category: 'email', action: 'mask', reason: 'Email is identifying.' }],
    residual_review: { status: 'ready_for_user_review', findings: [], reasons: ['No configured high-risk patterns were detected.'] },
    review_complete: true,
    acknowledged: false,
    send_state: 'review',
    provider: { name: 'Test provider', configured: true },
    pages_used: [1, 3],
    ...overrides,
  };
}

function createController(options = {}) {
  const controller = createPrivacyReviewController(options);
  controller.load(workflow(), { source: 'backend' });
  return controller;
}

test('maps actual backend findings, residual reasons, and text without inventing data', () => {
  const mapped = adaptBackendWorkflow(workflow({
    findings: [
      { category: 'credential', action: 'block', reason: 'A credential-like value must not be sent.' },
      { category: 'email', action: 'mask', reason: 'Email is identifying.' },
    ],
    residual_review: { status: 'needs_review', findings: [{ category: 'unique_fact', action: 'mask', reason: 'Review a unique clue.' }], reasons: ['Contextual review flagged a possible identity clue.'] },
  }));
  assert.deepEqual(mapped.recommendations.map(item => item.action), ['block', 'mask']);
  assert.equal(mapped.recommendations[0].item, 'credential');
  assert.equal(mapped.recommendations[0].reason, 'A credential-like value must not be sent.');
  assert.equal('replacement' in mapped.recommendations[0], false);
  assert.deepEqual(mapped.riskFlags.map(flag => flag.label), ['unique_fact', 'Contextual review flagged a possible identity clue.']);
  assert.equal(mapped.exactOutgoingText, 'Summarize monthly costs without identifiers.');
});

test('requires a backend-marked workflow and does not treat illustrative data as real', () => {
  const controller = createPrivacyReviewController();
  controller.load(workflow(), { source: 'demo' });
  assert.equal(controller.getState().status, 'review-error');
  assert.equal(controller.getState().backendResponse, null);
});

test('editing is sent to the current draft endpoint and refreshed from its response', async () => {
  let received;
  const controller = createController({
    updateDraft: async payload => {
      received = payload;
      return workflow({ version: 2, draft: payload.draft });
    },
  });
  controller.beginEditing();
  controller.updateOutgoingText('Revised exact outgoing request.');
  await controller.finishEditing();
  assert.deepEqual(received, { workflowId: 'workflow-1', version: 1, draft: 'Revised exact outgoing request.' });
  assert.equal(controller.getState().backendResponse.version, 2);
  assert.equal(controller.getState().backendResponse.draft, 'Revised exact outgoing request.');
  assert.equal(controller.getState().exactOutgoingText, 'Revised exact outgoing request.');
  assert.equal(controller.getState().approvalGranted, false);
});

test('requires backend acknowledgement for remaining warnings before approval', async () => {
  let acknowledgePayload;
  let sendCount = 0;
  const controller = createPrivacyReviewController({
    acknowledgeReview: async payload => {
      acknowledgePayload = payload;
      return workflow({
        residual_review: { status: 'needs_review', findings: [], reasons: ['A warning remains.'] },
        acknowledged: true,
      });
    },
    sendApprovedRequest: async () => { sendCount += 1; return { workflow_id: 'workflow-1', version: 1, answer: 'Answer', send_state: 'sent', pages_used: [1], history_saved: true }; },
  });
  controller.load(workflow({
    residual_review: { status: 'needs_review', findings: [], reasons: ['A warning remains.'] },
  }), { source: 'backend' });
  assert.equal(controller.approve() instanceof Promise, true);
  assert.equal(sendCount, 0);
  controller.confirmReview();
  assert.equal(controller.getState().status, 'awaiting-acknowledgement');
  await controller.acknowledge();
  assert.deepEqual(acknowledgePayload, { workflowId: 'workflow-1', version: 1 });
  assert.equal(controller.getState().status, 'awaiting-approval');
  assert.equal(controller.canApprove, true);
});

test('sends only the exact currently approved text, once, and returns the backend answer', async () => {
  let payload;
  let sends = 0;
  const controller = createController({
    sendApprovedRequest: async value => {
      payload = value;
      sends += 1;
      return { workflow_id: value.workflowId, version: value.version, answer: 'Confirmed backend answer', send_state: 'sent', pages_used: [1, 3], history_saved: true };
    },
  });
  assert.equal(await controller.approve(), null);
  assert.equal(sends, 0);
  controller.confirmReview();
  assert.equal(controller.canApprove, true);
  const answer = await controller.approve();
  assert.deepEqual(payload, { workflowId: 'workflow-1', version: 1, exactOutgoingText: 'Summarize monthly costs without identifiers.' });
  assert.equal(answer.result.answer, 'Confirmed backend answer');
  assert.deepEqual(answer.result.pages_used, [1, 3]);
  assert.equal(controller.getState().status, 'sent');
  assert.equal(controller.getState().result.answer, 'Confirmed backend answer');
  await controller.approve();
  assert.equal(sends, 1);
});

test('backend edit conflicts and provider failures cannot be blindly retried', async () => {
  const editFailure = createController({
    updateDraft: async () => { throw new ApiError('The workflow changed. Reload and try again.', { code: 'INVALID_STATE', status: 409 }); },
    sendApprovedRequest: async () => { throw new ApiError('Provider delivery is unknown.', { code: 'PROVIDER_FAILED', status: 502 }); },
  });
  editFailure.beginEditing();
  editFailure.updateOutgoingText('A changed request.');
  await editFailure.finishEditing();
  assert.equal(editFailure.getState().status, 'review-error');
  assert.equal(editFailure.canApprove, false);

  const controller = createController({
    sendApprovedRequest: async () => { throw new ApiError('The provider could not complete the request.', { code: 'PROVIDER_FAILED', status: 502 }); },
  });
  controller.confirmReview();
  await controller.approve();
  assert.equal(controller.getState().status, 'send-error');
  assert.equal(await controller.approve(), null);
  assert.equal(controller.getState().approvalGranted, false);
});

test('blocked or incomplete backend reviews cannot be approved', async () => {
  let sends = 0;
  const controller = createPrivacyReviewController({ sendApprovedRequest: async () => { sends += 1; } });
  controller.load(workflow({
    residual_review: { status: 'blocked', findings: [], reasons: ['High-risk content remains.'] },
  }), { source: 'backend' });
  assert.equal(controller.getState().status, 'review-blocked');
  assert.equal(await controller.approve(), null);
  assert.equal(sends, 0);
});
