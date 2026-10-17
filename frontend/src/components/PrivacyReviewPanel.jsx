const STATUS_LABELS = {
  'review-ready': 'Review the proposed text and recommendations.',
  editing: 'Editing the exact outgoing text.',
  'awaiting-approval': 'The final text is ready. Approve explicitly to send it.',
  approved: 'Approval recorded; preparing the approved submission.',
  sending: 'Submitting the explicitly approved text.',
  sent: 'The backend confirmed the approved request was submitted.',
  'approval-unavailable': 'Sending is unavailable. Nothing was sent.',
  'send-error': 'Submission failed. Review the final text before trying again.',
};

function BackendAnalysis({ response }) {
  const residual = response.residual_review;
  const residualFindings = Array.isArray(residual.findings) ? residual.findings : [];
  return <section className="review-card glass-panel" aria-labelledby="backend-review-title">
    <div className="review-top"><span className="review-lock" aria-hidden="true">✓</span><div className="review-title"><h2 id="backend-review-title">Local privacy review</h2><p>{response.review_complete ? 'The backend returned this local review. Nothing has been sent to an answer provider.' : 'The backend returned an incomplete review. Nothing has been sent to an answer provider.'}</p></div></div>
    <section aria-labelledby="backend-question-title"><h3 id="backend-question-title">Your question</h3><p>{response.question}</p></section>
    <section aria-labelledby="backend-draft-title"><h3 id="backend-draft-title">Proposed request · not sent</h3><pre className="request-preview">{response.draft}</pre></section>
    <section aria-labelledby="backend-findings-title"><h3 id="backend-findings-title">Privacy findings returned by the backend</h3>
      {response.findings.length ? <ul>{response.findings.map((finding, index) => <li key={finding.finding_id || index}>
        <strong>{finding.category || 'Finding'}</strong>{finding.action && <> · {finding.action}</>}{finding.reason && <p>{finding.reason}</p>}
      </li>)}</ul> : <p>The backend returned no findings.</p>}
    </section>
    <section aria-labelledby="backend-residual-title"><h3 id="backend-residual-title">Remaining review</h3><p>Status returned: {residual.status || 'unspecified'}</p>
      {residualFindings.length > 0 && <ul>{residualFindings.map((finding, index) => <li key={finding.finding_id || index}>{finding.category || 'Finding'}{finding.action && <> · {finding.action}</>}{finding.reason && <p>{finding.reason}</p>}</li>)}</ul>}
      {Array.isArray(residual.reasons) && residual.reasons.length > 0 && <ul>{residual.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}
    </section>
    <p className="review-footnote">Workflow {response.workflow_id} · version {response.version} · pages used: {response.pages_used.length ? response.pages_used.join(', ') : 'none reported'} · state: {response.send_state} · acknowledged: {response.acknowledged ? 'yes' : 'no'} · provider: {response.provider.name || 'not supplied'} ({response.provider.configured ? 'configured' : 'not configured'})</p>
  </section>;
}

export default function PrivacyReviewPanel({ state, controller, workflowResponse }) {
  if (workflowResponse) return <BackendAnalysis response={workflowResponse}/>;
  const review = state.review;
  if (!review || review.source !== 'backend') return null;
  const editing = state.status === 'editing';

  return <section className="review-card glass-panel" aria-labelledby="backend-review-title">
    <div className="review-top">
      <span className="review-lock" aria-hidden="true"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/></svg></span>
      <div className="review-title">
        <h2 id="backend-review-title">Review before sending</h2>
        <p>{STATUS_LABELS[state.status] || 'Review the backend-provided request.'}</p>
      </div>
    </div>

    <section aria-labelledby="review-original-title">
      <h3 id="review-original-title">Original question or request</h3>
      <p>{review.originalRequestText}</p>
    </section>
    <section aria-labelledby="review-proposal-title">
      <h3 id="review-proposal-title">Proposed outgoing text</h3>
      <p>{review.proposedOutgoingText}</p>
    </section>

    <section aria-labelledby="review-recommendations-title">
      <h3 id="review-recommendations-title">Privacy recommendations</h3>
      {review.recommendations.length ? <ul>
        {review.recommendations.map((item, index) => <li key={`${item.action}-${item.item}-${index}`}>
          <strong>{item.action.toUpperCase()}</strong> {item.item}
          {item.replacement != null && <> → {item.replacement}</>}
          <p>{item.reason}</p>
        </li>)}
      </ul> : <p>No recommendations were supplied by the backend.</p>}
    </section>

    <section aria-labelledby="review-risks-title">
      <h3 id="review-risks-title">Remaining risk flags</h3>
      {review.riskFlags.length ? <ul>
        {review.riskFlags.map((flag, index) => <li key={`${flag.label}-${index}`}>
          <strong>{flag.label}</strong>{flag.level && <> · {flag.level}</>}
          {flag.description && <p>{flag.description}</p>}
        </li>)}
      </ul> : <p>No risk flags were supplied by the backend.</p>}
    </section>

    <section aria-labelledby="review-final-text-title">
      <h3 id="review-final-text-title">Exact text after edits</h3>
      <label className="visually-hidden" htmlFor="backend-final-request">Final outgoing request</label>
      <textarea
        id="backend-final-request"
        className="request-preview"
        value={state.exactOutgoingText}
        readOnly={!editing}
        onChange={event => controller.updateOutgoingText(event.target.value)}
      />
    </section>

    {state.error && <p className="notice" role="alert">{state.error.message}</p>}
    <div className="review-actions">
      {state.status === 'review-ready' && <>
        <button className="edit-button" type="button" onClick={() => controller.beginEditing()}>Edit request</button>
        <button className="approve-button" type="button" onClick={() => controller.confirmReview()}>Continue to approval</button>
      </>}
      {editing && <button className="edit-button" type="button" onClick={() => controller.finishEditing()}>Show final text for approval</button>}
      {state.status === 'awaiting-approval' && <>
        <button className="edit-button" type="button" onClick={() => controller.beginEditing()}>Edit request</button>
        <button className="approve-button" type="button" disabled={!controller.canSend} onClick={() => controller.approve()}>Approve exact text &amp; send</button>
      </>}
      {state.status === 'awaiting-approval' && !controller.canSend && <p className="review-footnote">Sending is unavailable until the backend approval contract is connected. Nothing will be sent.</p>}
      {['approval-unavailable', 'send-error'].includes(state.status) && <button className="edit-button" type="button" onClick={() => controller.returnToEditing()}>Return to editing</button>}
    </div>
  </section>;
}
