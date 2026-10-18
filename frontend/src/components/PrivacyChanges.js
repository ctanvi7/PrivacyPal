import { createElement as h } from 'react';
import { processingCopy } from '../lib/deployment.js';

const label = value => value.replaceAll('_', ' ').replace(/^./, char => char.toUpperCase());
const actions = { mask: 'Masked', omit: 'Removed', block: 'Blocked' };

function findingList(findings) {
  return h('ul', { className: 'privacy-change-list' }, findings.map((finding, index) => {
    const token = finding.replacement_token || finding.placeholder;
    return h('li', { key: finding.finding_id || index },
      h('div', { className: 'privacy-change-heading' },
        h('strong', null, typeof finding.category === 'string' ? label(finding.category) : 'Category not provided'),
        h('span', { className: 'change-action' }, typeof finding.action === 'string' ? actions[finding.action] || label(finding.action) : 'Action not provided')),
      typeof finding.reason === 'string' && h('p', null, finding.reason),
      typeof token === 'string' && token && h('p', { className: 'replacement-token' }, 'Replacement: ', h('code', null, token)));
  }));
}

export default function PrivacyChanges({ response }) {
  const findings = Array.isArray(response.findings) ? response.findings : [];
  const residual = response.residual_review || {};
  const remaining = Array.isArray(residual.findings) ? residual.findings : [];
  const reasons = Array.isArray(residual.reasons) ? residual.reasons : [];
  return h('section', { className: 'finding-list privacy-changes', 'aria-label': 'Privacy changes' },
    h('h3', null, 'Privacy changes'),
    h('p', { className: 'privacy-changes-intro' }, processingCopy('Reported by the local review. Detection may miss sensitive details.')),
    findings.length ? findingList(findings) : h('p', null, processingCopy('No findings were returned by the local review.')),
    remaining.length > 0 && h('div', { className: 'remaining-findings' }, h('h4', null, 'Remaining findings'), findingList(remaining)),
    reasons.length > 0 && h('div', { className: 'review-notes', 'data-warning': residual.status === 'needs_review' || residual.status === 'blocked' },
      h('h4', null, residual.status === 'needs_review' || residual.status === 'blocked' ? 'Contextual warnings' : 'Review notes'),
      h('ul', null, reasons.map((reason, index) => h('li', { key: index }, reason)))));
}
