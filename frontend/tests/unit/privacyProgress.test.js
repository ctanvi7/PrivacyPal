import assert from 'node:assert/strict';
import test from 'node:test';
import { getPrivacyProgress } from '../../src/lib/privacyProgress.js';
import { createApiClient } from '../../src/lib/apiClient.js';
import { createQuestionController } from '../../src/lib/questionController.js';

const titles = ['Read document', 'Find sensitive details', 'Select relevant content', 'Check remaining clues'];
const uploadResult = { page_count: 2, character_count: 240 };
const completeReview = {
  review_complete: true, acknowledged: false, send_state: 'review',
  findings: [{ category: 'Personal detail' }], pages_used: [1],
  residual_review: { status: 'clear', reasons: [] },
};

test('shows real privacy review stages pending before work begins', () => {
  const stages = getPrivacyProgress();
  assert.deepEqual(stages.map(stage => stage.title), titles);
  assert.deepEqual(stages.map(stage => stage.status), ['pending', 'pending', 'pending', 'pending']);
});

test('marks document reading only after backend upload confirmation', () => {
  assert.equal(getPrivacyProgress({ uploadStatus: 'uploading' })[0].status, 'in-progress');
  assert.equal(getPrivacyProgress({ uploadStatus: 'selected' })[0].status, 'pending');
  const uploaded = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult });
  assert.equal(uploaded[0].status, 'completed');
  assert.match(uploaded[0].detail, /2 pages/);
  assert.equal(getPrivacyProgress({ uploadStatus: 'upload-error' })[0].status, 'failed');
});

test('reflects processing and backend local-review results without implying approval', () => {
  const processing = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, questionStatus: 'processing' });
  assert.equal(processing[0].status, 'completed');
  assert.equal(processing[1].status, 'in-progress');
  const review = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, questionStatus: 'review-ready', workflowResponse: completeReview });
  assert.deepEqual(review.map(stage => stage.status), ['completed', 'completed', 'completed', 'completed']);
  assert.match(review[1].detail, /1 finding/);
  assert.match(review[2].detail, /1 page/);
});

test('shows warning, blocked, and incomplete local-review states', () => {
  assert.equal(getPrivacyProgress({ uploadStatus: 'cancelled' })[0].status, 'failed');
  assert.equal(getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, questionStatus: 'processing-error' })[1].status, 'failed');
  const warning = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, workflowResponse: { ...completeReview, residual_review: { status: 'needs_review', reasons: ['Check this clue.'] } } });
  assert.equal(warning[3].status, 'needs-review');
  const blocked = getPrivacyProgress({ workflowResponse: { ...completeReview, residual_review: { status: 'blocked', reasons: ['Blocked.'] } } });
  assert.equal(blocked[3].status, 'blocked');
  const incomplete = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, workflowResponse: { ...completeReview, review_complete: false } });
  assert.equal(incomplete[1].status, 'failed');
  assert.equal(incomplete[2].status, 'failed');
  assert.equal(incomplete[3].status, 'failed');
});

test('blocked final check preserves confirmed detection and relevance results', () => {
  const stages = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, workflowResponse: {
    ...completeReview, review_complete: false,
    local_checks: { sensitive: 'completed', relevant: 'completed', residual: 'blocked' },
    residual_review: { status: 'blocked', reasons: ['Identifying details need redaction.'] },
  } });
  assert.deepEqual(stages.map(stage => stage.status), ['completed', 'completed', 'completed', 'blocked']);
  assert.match(stages[1].detail, /1 finding/);
  assert.match(stages[3].detail, /need redaction/);
});

test('failed contextual review does not turn completed detection into a failed scan', () => {
  const stages = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, workflowResponse: {
    ...completeReview, review_complete: false,
    local_checks: { sensitive: 'completed', relevant: 'completed', residual: 'failed' },
    residual_review: { status: 'needs_review', reasons: ['Contextual review did not complete.'] },
  } });
  assert.deepEqual(stages.map(stage => stage.status), ['completed', 'completed', 'completed', 'failed']);
});

test('initial review errors preserve completed checks and identify the actual failed step', () => {
  for (const [localChecks, expected] of [
    [{ sensitive: 'failed', relevant: 'pending', residual: 'pending' }, ['completed', 'failed', 'pending', 'pending']],
    [{ sensitive: 'completed', relevant: 'failed', residual: 'pending' }, ['completed', 'completed', 'failed', 'pending']],
    [{ sensitive: 'completed', relevant: 'completed', residual: 'failed' }, ['completed', 'completed', 'completed', 'failed']],
  ]) {
    const stages = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, questionStatus: 'processing-error',
      questionError: { message: 'Local review could not complete.', localChecks } });
    assert.deepEqual(stages.map(stage => stage.status), expected);
    assert.ok(stages.every(stage => !stage.detail.includes('0 findings')));
    assert.equal(stages.find(stage => stage.status === 'failed').detail, 'Local review could not complete.');
  }
});

test('failed native review progress survives HTTP parsing and question-controller state', async () => {
  const api = createApiClient({ fetchImpl: async () => new Response(JSON.stringify({ error: {
    code: 'LOCAL_ANALYSIS_FAILED', message: 'Remaining-clue review could not complete.', retryable: true,
    local_checks: { sensitive: 'completed', relevant: 'completed', residual: 'failed', unexpected: 'ignored' },
  } }), { status: 503, headers: { 'Content-Type': 'application/json' } }) });
  const controller = createQuestionController({ submitQuestion: () => api.request('/api/v1/sessions/test/questions') });
  await controller.submit({ question: 'Draft maintenance email.', session: { session_id: 'test' },
    uploadedSessionId: 'test', uploadedDocument: { document_id: 'doc' } });
  const state = controller.getState();
  assert.equal(state.status, 'processing-error');
  assert.equal(state.result, null); // A failed response never becomes an approvable review.
  assert.deepEqual(state.error.localChecks, { sensitive: 'completed', relevant: 'completed', residual: 'failed' });
  const stages = getPrivacyProgress({ uploadStatus: 'uploaded', uploadResult, questionStatus: state.status, questionError: state.error });
  assert.deepEqual(stages.map(stage => stage.status), ['completed', 'completed', 'completed', 'failed']);
});
