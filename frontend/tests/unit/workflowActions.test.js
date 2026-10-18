import assert from 'node:assert/strict';
import test from 'node:test';
import { createPrivacyPalApi } from '../../src/lib/privacyPalApi.js';
import { getPrivacyProgress } from '../../src/lib/privacyProgress.js';
import { getWorkflowStatus, performWorkflowAction } from '../../src/lib/workflowActions.js';

function review(overrides = {}) {
  return {
    workflow_id: 'workflow-1', version: 2, question: 'What are the costs?',
    draft: 'Exact reviewed sanitized draft.', review_complete: true,
    acknowledged: true, send_state: 'review',
    findings: [{ category: 'Personal detail', action: 'mask' }], pages_used: [2],
    residual_review: { status: 'needs_review', findings: [], reasons: ['Warning acknowledged.'] },
    provider: { name: 'Mock provider', configured: true, endpoint: 'https://example.test/v1' },
    ...overrides,
  };
}

function progress(workflowResponse) {
  return getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult: { page_count: 2 }, workflowResponse });
}

function stateHarness(initial) {
  const state = { workflow: initial, busy: false, error: '', updates: [] };
  const callbacks = {
    setWorkflow(update) {
      state.workflow = typeof update === 'function' ? update(state.workflow) : update;
      state.updates.push(state.workflow);
    },
    setBusy(value) { state.busy = value; },
    setError(value) { state.error = value; },
  };
  return {
    state,
    run: (action, approval = true) => performWorkflowAction({
      workflow: state.workflow, busy: state.busy, sessionId: 'session-1', action, approval, ...callbacks,
    }),
  };
}

test('partial approval receipt preserves every completed review step through sending and answer delivery', async () => {
  const initial = review();
  const { state, run } = stateHarness(initial);
  const calls = [];
  let deliver;
  const api = createPrivacyPalApi({ client: { request(path, options) {
    calls.push({ path, options });
    return new Promise(resolve => { deliver = resolve; });
  } } });
  const action = (sid, id, version) => api.approveWorkflow(sid, id, version);
  assert.equal(calls.length, 0);
  const pending = run(action);
  assert.equal(state.workflow.send_state, 'sending');
  assert.match(getWorkflowStatus(state.workflow).label, /Sending/);
  assert.equal(await run(action), null, 'busy approval cannot send a second request');
  deliver({
    workflow_id: initial.workflow_id, version: initial.version, answer: 'Synthetic answer.',
    provider: initial.provider, pages_used: [2], send_state: 'sent',
  }); // Actual backend receipt omits draft, findings, residual_review and review_complete.
  await pending;
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, 'api/v1/sessions/session-1/workflows/workflow-1/approve');
  assert.deepEqual(calls[0].options.body, { version: initial.version, restore_placeholders: false });
  assert.equal(state.workflow.answer, 'Synthetic answer.');
  assert.equal(state.workflow.send_state, 'sent');
  assert.equal(state.workflow.draft, initial.draft);
  assert.equal(state.workflow.findings, initial.findings);
  assert.equal(state.workflow.residual_review, initial.residual_review);
  assert.equal(state.workflow.acknowledged, true);
  for (const update of state.updates) assert.deepEqual(progress(update), progress(initial), 'no transient loss of local checks');
  assert.equal(getWorkflowStatus(state.workflow).label, 'Sent — answer received');
  assert.equal(state.busy, false);
  assert.equal(state.error, '');
  assert.equal(await run(action), null, 'a consumed approval cannot be replayed');
  assert.equal(calls.length, 1);
});

test('provider failure preserves local results and reports only delivery failure without retry', async () => {
  const initial = review();
  const { state, run } = stateHarness(initial);
  let calls = 0;
  const action = async () => { calls += 1; throw new Error('The provider failed. Delivery may have occurred.'); };
  assert.equal(await run(action), null);
  assert.equal(state.workflow.send_state, 'delivery_unknown');
  assert.equal(state.workflow.answer, null);
  assert.equal(state.workflow.draft, initial.draft);
  assert.equal(state.workflow.residual_review, initial.residual_review);
  assert.equal(state.workflow.acknowledged, true);
  for (const update of state.updates) assert.deepEqual(progress(update), progress(initial));
  assert.equal(getWorkflowStatus(state.workflow).label, 'Provider delivery failed');
  assert.match(getWorkflowStatus(state.workflow).detail, /cannot be retried/);
  assert.match(state.error, /provider failed/);
  assert.equal(state.busy, false);
  await run(action);
  assert.equal(calls, 1);
});

test('edited drafts use the new full review instead of retaining previous passing checks', async () => {
  const { state, run } = stateHarness(review());
  const edited = review({ version: 3, draft: 'Edited draft', review_complete: false, acknowledged: false,
    residual_review: { status: 'blocked', reasons: ['High-risk value.'] } });
  await run(async () => edited, false);
  assert.equal(state.workflow, edited);
  assert.deepEqual(progress(state.workflow).map(step => step.status), ['completed', 'failed', 'failed', 'failed']);
  assert.equal(getWorkflowStatus(state.workflow).label, 'blocked');
});

test('review action failure leaves the existing review and delivery status unchanged', async () => {
  const initial = review();
  const { state, run } = stateHarness(initial);
  await run(async () => { throw new Error('Edit failed.'); }, false);
  assert.equal(state.workflow, initial);
  assert.equal(state.error, 'Edit failed.');
  assert.equal(state.busy, false);
});

test('withheld provider answer preserves privacy review, hides the answer, and cannot be replayed', async () => {
  const initial = review();
  const { state, run } = stateHarness(initial);
  let calls = 0;
  const api = createPrivacyPalApi({ client: { async request() {
    calls += 1;
    const error = new Error('The provider answer was withheld because its personal details could not be verified.');
    error.code = 'ANSWER_WITHHELD';
    throw error;
  } } });
  const action = (sid, id, version) => api.approveWorkflow(sid, id, version);
  await run(action);
  assert.equal(state.workflow.send_state, 'answer_withheld');
  assert.equal(state.workflow.answer, null);
  assert.equal(state.workflow.review_complete, true);
  assert.deepEqual(progress(state.workflow), progress(initial));
  assert.equal(getWorkflowStatus(state.workflow).label, 'Answer withheld');
  assert.match(state.error, /could not be verified/);
  await run(action);
  assert.equal(calls, 1);
});
