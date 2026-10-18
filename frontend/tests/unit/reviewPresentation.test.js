import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import SafeMarkdown from '../../src/components/SafeMarkdown.js';
import PrivacyChanges from '../../src/components/PrivacyChanges.js';
import ReviewTimeline from '../../src/components/ReviewTimeline.js';

// Synthetic fixtures only, never added to the application or sent to a provider.
const review = {
  workflow_id: 'synthetic', version: 2, question: 'A synthetic question',
  draft: 'Exact reviewed text.\nKeep whitespace and [EMAIL_1] unchanged.',
  review_complete: true, acknowledged: true, send_state: 'review', pages_used: [1],
  findings: [{ finding_id: 'f1', category: 'email_address', action: 'mask', reason: 'Contact detail.' }],
  residual_review: { status: 'needs_review', findings: [], reasons: ['A distinctive fact remains.'] },
  provider: { configured: true, name: 'Synthetic provider' },
};
let server;
let PrivacyReviewPanel;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  PrivacyReviewPanel = (await server.ssrLoadModule('/src/components/PrivacyReviewPanel.jsx')).default;
});
after(async () => { await server?.close(); });

test('answer Markdown renders headings, paragraphs, emphasis, ordered and unordered lists', () => {
  const html = renderToStaticMarkup(h(SafeMarkdown, null, '# Overview\n\nA **clear** answer.\n\n- First item\n- Second item\n\n1. Check costs\n2. Review terms'));
  assert.match(html, /<h3>Overview<\/h3>/);
  assert.match(html, /<p>A <strong>clear<\/strong> answer\.<\/p>/);
  assert.match(html, /<ul><li>First item<\/li><li>Second item<\/li><\/ul>/);
  assert.match(html, /<ol start="1"><li>Check costs<\/li><li>Review terms<\/li><\/ol>/);
  assert.doesNotMatch(html, /\*\*clear\*\*|# Overview/);
});

test('untrusted answer HTML is escaped and provider images and links cannot execute or fetch', () => {
  const html = renderToStaticMarkup(h(SafeMarkdown, null,
    '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[click](javascript:alert) ![remote image](https://example.test/tracker.png)\n\n```html\n<iframe src="https://example.test"></iframe>\n```'));
  assert.doesNotMatch(html, /<script|<img|<iframe|href=|<a\b/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /<pre><code>&lt;iframe/);
  assert.match(html, /remote image/);
});

test('privacy changes use only returned categories, actions, reasons and optional replacement tokens', () => {
  const html = renderToStaticMarkup(h(PrivacyChanges, { response: review }));
  assert.match(html, /Privacy changes/);
  assert.match(html, /Email address/);
  assert.match(html, /Masked/);
  assert.match(html, /Contact detail/);
  assert.match(html, /Contextual warnings/);
  assert.match(html, /A distinctive fact remains/);
  assert.doesNotMatch(html, /Replacement:|EMAIL_1/); // Never infer a mapping from the draft.
  const withToken = renderToStaticMarkup(h(PrivacyChanges, { response: {
    ...review, findings: [{ category: 'email_address', action: 'mask', replacement_token: '[EMAIL_1]' },
      { category: 'credential', action: 'omit' }, { category: 'secret', action: 'block' }],
  } }));
  assert.match(withToken, /Replacement: <code>\[EMAIL_1\]<\/code>/);
  assert.match(withToken, /Removed/);
  assert.match(withToken, /Blocked/);
});

test('no findings still shows contextual warnings and remaining findings without claiming safety', () => {
  const html = renderToStaticMarkup(h(PrivacyChanges, { response: {
    ...review, findings: [], residual_review: { ...review.residual_review,
      findings: [{ category: 'unique_fact', action: 'block', reason: 'Review this clue.' }] },
  } }));
  assert.match(html, /No findings were returned/);
  assert.match(html, /Detection may miss sensitive details/);
  assert.match(html, /A distinctive fact remains/);
  assert.match(html, /Remaining findings/);
  assert.match(html, /Unique fact/);
});

test('timeline labels completed, warning, failed and pending checks independently of color', () => {
  const props = { uploadStatus: 'uploaded', uploadResult: { page_count: 1 }, workflowResponse: review };
  const complete = renderToStaticMarkup(h(ReviewTimeline, props));
  assert.equal((complete.match(/>Completed<\/span>/g) || []).length, 4);
  assert.match(complete, /✓/);
  const warning = renderToStaticMarkup(h(ReviewTimeline, { ...props, workflowResponse: { ...review, acknowledged: false } }));
  assert.match(warning, />Needs review<\/span>/);
  assert.match(warning, /needs-review" aria-hidden="true">!/);
  const failed = renderToStaticMarkup(h(ReviewTimeline, { ...props, workflowResponse: { ...review, review_complete: false } }));
  assert.match(failed, />Failed<\/span>/);
  assert.match(failed, /×/);
  assert.match(renderToStaticMarkup(h(ReviewTimeline)), />Pending<\/span>/);
});

test('preview remains exact and open before approval, collapses beneath the formatted answer after sending', () => {
  let approvals = 0;
  const props = { response: review, onApprove: () => { approvals += 1; } };
  const ready = renderToStaticMarkup(h(PrivacyReviewPanel, props));
  assert.match(ready, /<details class="request-disclosure" open="">/);
  assert.match(ready, /Exact request to be sent/);
  assert.ok(ready.includes(review.draft));
  assert.match(ready, /role="region" aria-label="Exact sanitized request"/);
  const answered = renderToStaticMarkup(h(PrivacyReviewPanel, { ...props, response: {
    ...review, send_state: 'sent', answer: '# Your answer\n\n- A useful point',
  } }));
  assert.match(answered, /<details class="request-disclosure">/);
  assert.ok(answered.indexOf('aria-label="Provider answer"') < answered.indexOf('request-disclosure'));
  assert.match(answered, /<h3>Your answer<\/h3>/);
  assert.match(answered, /<ul><li>A useful point<\/li><\/ul>/);
  assert.ok(answered.includes(review.draft));
  assert.equal(approvals, 0, 'presentation must never submit a request');
});

test('provider failure preserves completed review data and blocked reviews never enable approval', () => {
  const failed = renderToStaticMarkup(h(PrivacyReviewPanel, { response: { ...review, send_state: 'delivery_unknown' }, error: 'Provider failed.' }));
  assert.match(failed, /Provider delivery failed/);
  assert.match(failed, /Local privacy check results are preserved/);
  assert.ok(failed.includes(review.draft));
  for (const response of [
    { ...review, review_complete: false },
    { ...review, acknowledged: false },
    { ...review, provider: { configured: false } },
    { ...review, residual_review: { status: 'blocked' } },
  ]) {
    const html = renderToStaticMarkup(h(PrivacyReviewPanel, { response }));
    assert.match(html, /class="approve-button" type="button" disabled=""/);
  }
});

test('unverified personal details are withheld instead of rendered as document facts', () => {
  const response = { ...review, send_state: 'answer_withheld', answer: 'Invented Resident: Nora Vale' };
  const html = renderToStaticMarkup(h(PrivacyReviewPanel, { response,
    error: 'The provider answer was withheld because its personal details could not be verified.' }));
  assert.match(html, /Answer withheld/);
  assert.match(html, /could not be verified/);
  assert.doesNotMatch(html, /Nora Vale|aria-label="Provider answer"/);
  assert.match(html, /class="approve-button" type="button" disabled=""/);
  const timeline = renderToStaticMarkup(h(ReviewTimeline, { uploadStatus: 'uploaded', uploadResult: { page_count: 1 }, workflowResponse: response }));
  assert.equal((timeline.match(/>Completed<\/span>/g) || []).length, 4);
});
