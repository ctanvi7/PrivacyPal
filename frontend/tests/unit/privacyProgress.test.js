import assert from 'node:assert/strict';
import test from 'node:test';
import { getPrivacyProgress } from '../../src/lib/privacyProgress.js';

const titles = ['Document upload', 'Local privacy analysis', 'Review and approval', 'Answer returned'];
const completeReview = { review_complete: true, acknowledged: false, send_state: 'review' };

test('shows all real workflow stages as pending before work begins', () => {
  const stages = getPrivacyProgress();
  assert.deepEqual(stages.map(stage => stage.title), titles);
  assert.deepEqual(stages.map(stage => stage.status), ['pending', 'pending', 'pending', 'pending']);
  assert.match(stages[3].detail, /no answer has been returned/i);
});

test('marks upload as in progress and only completes after backend confirmation', () => {
  assert.equal(getPrivacyProgress({ uploadStatus: 'uploading' })[0].status, 'in-progress');
  assert.equal(getPrivacyProgress({ uploadStatus: 'selected' })[0].status, 'pending');
  assert.equal(getPrivacyProgress({ uploadStatus: 'uploaded' })[0].status, 'completed');
  assert.equal(getPrivacyProgress({ uploadStatus: 'upload-error' })[0].status, 'failed');
});

test('reflects processing and the real local-review response without implying approval or an answer', () => {
  const processing = getPrivacyProgress({ uploadStatus: 'uploaded', questionStatus: 'processing' });
  assert.equal(processing[0].status, 'completed');
  assert.equal(processing[1].status, 'in-progress');

  const review = getPrivacyProgress({ uploadStatus: 'uploaded', questionStatus: 'review-ready', workflowResponse: completeReview });
  assert.deepEqual(review.map(stage => stage.status), ['completed', 'completed', 'in-progress', 'pending']);
  assert.match(review[2].detail, /approve explicitly before sending/i);
  assert.match(review[3].detail, /no answer has been returned/i);
});

test('shows failed uploads, failed analysis, and backend-incomplete reviews accurately', () => {
  assert.equal(getPrivacyProgress({ uploadStatus: 'cancelled' })[0].status, 'failed');
  assert.equal(getPrivacyProgress({ uploadStatus: 'uploaded', questionStatus: 'processing-error' })[1].status, 'failed');
  const incomplete = getPrivacyProgress({ uploadStatus: 'uploaded', workflowResponse: { review_complete: false } });
  assert.equal(incomplete[1].status, 'failed');
  assert.equal(incomplete[2].status, 'failed');
  assert.equal(incomplete[3].status, 'pending');
});

test('keeps illustrative preview steps pending and explicitly says no real workflow ran', () => {
  const stages = getPrivacyProgress({ uploadStatus: 'uploaded', workflowResponse: completeReview, illustrativePreview: true });
  assert.ok(stages.every(stage => stage.status === 'pending'));
  assert.match(stages[0].detail, /no upload occurred/i);
  assert.match(stages[1].detail, /no analysis occurred/i);
});
