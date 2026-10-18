import { createElement as h } from 'react';
import { getPrivacyProgress } from '../lib/privacyProgress.js';

const states = {
  completed: { label: 'Completed', symbol: '✓' },
  'needs-review': { label: 'Needs review', symbol: '!' },
  failed: { label: 'Failed', symbol: '×' },
  blocked: { label: 'Blocked', symbol: '!' },
  pending: { label: 'Pending', symbol: '○' },
  'in-progress': { label: 'In progress', symbol: '◷' },
};

export default function ReviewTimeline(props) {
  return h('div', { className: 'review-steps', 'aria-label': 'Privacy workflow progress' },
    getPrivacyProgress(props).map(step => {
      const state = states[step.status];
      return h('div', { className: 'timeline-item', 'data-status': step.status, key: step.id },
        h('span', { className: `step-number ${step.status}`, 'aria-hidden': true }, state.symbol),
        h('div', null,
          h('div', { className: 'step-heading' }, h('strong', null, step.title), h('span', { className: 'step-label' }, state.label)),
          h('p', null, step.detail)));
    }));
}
