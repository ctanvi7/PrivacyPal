const STATUS_LABELS = {
  'review-ready': 'Review the backend-provided text and recommendations.',
  'review-blocked': 'The backend review is incomplete or blocked. Approval is unavailable.',
  editing: 'Edit the exact outgoing request. Saving changes reruns backend privacy checks.',
  'saving-edit': 'Saving your edit and rerunning backend privacy checks…',
  'awaiting-acknowledgement': 'The backend reported remaining review warnings. Acknowledge them before approval.',
  acknowledging: 'Recording your acknowledgement with the backend…',
  'awaiting-approval': 'Confirm the exact text below before it is sent to the configured provider.',
  sending: 'The backend is processing your explicit approval. Do not retry this request.',
  sent: 'The backend returned an answer for the approved request.',
  'send-error': 'The approval result failed or is uncertain. Do not retry this workflow.',
  'review-error': 'This workflow could not be updated. Start a new review before approval.',
};

export default function PrivacyReviewPanel({ state, controller, onRestart }) {
  if (!state?.review || !state.backendResponse) return null;
  const response = state.backendResponse;
  const editing = state.status === 'editing';
  const busy = ['saving-edit', 'acknowledging', 'sending'].includes(state.status);
  const canEdit = ['review-ready', 'review-blocked', 'awaiting-acknowledgement', 'awaiting-approval'].includes(state.status);
  const canContinue = state.status === 'review-ready';
  const canAcknowledge = state.status === 'awaiting-acknowledgement';
  const awaitingApproval = state.status === 'awaiting-approval';

  return <section className="review-card glass-panel" aria-labelledby="backend-review-title" aria-busy={busy}>
    <div className="review-top"><span className="review-lock" aria-hidden="true">✓</span><div className="review-title"><h2 id="backend-review-title">Local privacy review</h2><p>{STATUS_LABELS[state.status] || 'Review the backend-provided request.'}</p></div></div>
    <section aria-labelledby="backend-question-title"><h3 id="backend-question-title">Your question</h3><p>{state.review.originalRequestText}</p></section>
    <section aria-labelledby="backend-findings-title"><h3 id="backend-findings-title">Privacy recommendations returned by the backend</h3>
      {state.review.recommendations.length ? <ul>{state.review.recommendations.map((item, index) => <li key={`${item.action}-${item.item}-${index}`}>
        <strong>{item.action.toUpperCase()}</strong> {item.item}<p>{item.reason}</p>
      </li>)}</ul> : <p>The backend returned no privacy findings.</p>}
    </section>
    <section aria-labelledby="backend-risk-title"><h3 id="backend-risk-title">Remaining risk review</h3><p>Backend status: <strong>{response.residual_review.status}</strong></p>
      {state.review.riskFlags.length ? <ul>{state.review.riskFlags.map((flag, index) => <li key={`${flag.label}-${index}`}>
        <strong>{flag.label}</strong>{flag.description && <p>{flag.description}</p>}
      </li>)}</ul> : <p>The backend returned no remaining risk flags.</p>}
    </section>
    <section aria-labelledby="backend-proposed-title"><h3 id="backend-proposed-title">Proposed outgoing request</h3><pre className="request-preview">{state.review.proposedOutgoingText}</pre></section>
    <section aria-labelledby="review-final-text-title"><h3 id="review-final-text-title">Exact text to be sent</h3>
      <label className="visually-hidden" htmlFor="backend-final-request">Exact final outgoing request</label>
      <textarea id="backend-final-request" className="request-preview" value={state.exactOutgoingText} readOnly={!editing} onChange={event => controller.updateOutgoingText(event.target.value)} />
    </section>

    <p className="review-footnote">Workflow {response.workflow_id} · version {response.version} · pages used: {response.pages_used.length ? response.pages_used.join(', ') : 'none reported'} · provider: {response.provider.name || 'not supplied'} ({response.provider.configured ? 'configured' : 'not configured'})</p>
    {state.error && <p className="notice" role="alert">{state.error.message}</p>}
    <div className="review-actions">
      {canEdit && !editing && <button className="edit-button" type="button" disabled={busy} onClick={() => controller.beginEditing()}>Edit request</button>}
      {editing && <button className="edit-button" type="button" disabled={busy} onClick={() => void controller.finishEditing()}>Save and recheck request</button>}
      {canContinue && <button className="approve-button" type="button" disabled={!response.review_complete || response.residual_review.status === 'blocked'} onClick={() => controller.confirmReview()}>Continue to approval</button>}
      {canAcknowledge && <button className="approve-button" type="button" disabled={busy} onClick={() => void controller.acknowledge()}>Acknowledge warnings</button>}
      {awaitingApproval && <button className="approve-button" type="button" disabled={!controller.canApprove || busy} onClick={() => void controller.approve()}>Approve exact text &amp; send</button>}
      {awaitingApproval && !response.provider.configured && <p className="review-footnote">The backend has no configured answer provider. Nothing can be sent until it is configured.</p>}
      {state.status === 'review-blocked' && <p className="review-footnote">Approval is blocked by the backend review. Edit the request to run checks again.</p>}
      {state.status === 'send-error' && <p className="review-footnote">This approval cannot be retried. Check provider delivery status before starting a new request.</p>}
      {['review-error', 'send-error'].includes(state.status) && <button className="edit-button" type="button" onClick={onRestart}>Start a new review</button>}
    </div>
  </section>;
}
