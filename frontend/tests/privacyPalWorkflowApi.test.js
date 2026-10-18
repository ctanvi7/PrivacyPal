import assert from 'node:assert/strict';
import test from 'node:test';
import { createPrivacyPalApi } from '../src/lib/privacyPalApi.js';

function workflowResponse(overrides = {}) {
  return {
    workflow_id: 'workflow/1',
    version: 2,
    question: 'What does this clause mean?',
    draft: 'Question: What does this clause mean?',
    findings: [],
    residual_review: { status: 'ready_for_user_review', findings: [], reasons: [] },
    review_complete: true,
    acknowledged: false,
    send_state: 'review',
    provider: { name: 'Provider', endpoint: 'https://provider.invalid/chat/completions', configured: true },
    pages_used: [2],
    ...overrides,
  };
}

test('workflow actions call the existing backend routes with their versioned payloads', async () => {
  const calls = [];
  const api = createPrivacyPalApi({
    client: {
      async request(path, options) {
        calls.push({ path, options });
        if (path.endsWith('/approve')) {
          return { workflow_id: 'workflow/1', version: 2, answer: 'A plain-language explanation.', provider: { name: 'Provider', configured: true }, pages_used: [2], send_state: 'sent' };
        }
        if (path.endsWith('/cancel')) return { status: 'cancelled' };
        return workflowResponse({ acknowledged: path.endsWith('/acknowledge') });
      },
    },
  });

  const edited = await api.editWorkflowDraft('session/1', 'workflow/1', 1, 'An edited question');
  const acknowledged = await api.acknowledgeWorkflow('session/1', 'workflow/1', 2);
  const approved = await api.approveWorkflow('session/1', 'workflow/1', 2);
  const cancelled = await api.cancelWorkflow('session/1', 'workflow/1');

  assert.equal(edited.draft, 'Question: What does this clause mean?');
  assert.equal(acknowledged.acknowledged, true);
  assert.equal(approved.answer, 'A plain-language explanation.');
  assert.equal(cancelled.status, 'cancelled');
  assert.deepEqual(calls.map(({ path, options }) => [path, options.method]), [
    ['api/v1/sessions/session%2F1/workflows/workflow%2F1/draft', 'PATCH'],
    ['api/v1/sessions/session%2F1/workflows/workflow%2F1/acknowledge', 'POST'],
    ['api/v1/sessions/session%2F1/workflows/workflow%2F1/approve', 'POST'],
    ['api/v1/sessions/session%2F1/workflows/workflow%2F1/cancel', 'POST'],
  ]);
  assert.deepEqual(calls[0].options.body, { version: 1, draft: 'An edited question' });
  assert.deepEqual(calls[1].options.body, { version: 2 });
  assert.deepEqual(calls[2].options.body, { version: 2, restore_placeholders: false });
  assert.equal('body' in calls[3].options, false);
});
