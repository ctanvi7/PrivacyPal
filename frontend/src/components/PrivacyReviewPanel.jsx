import { useState } from 'react';
import { getWorkflowStatus } from '../lib/workflowActions.js';
import DraftTranslation from './DraftTranslation.jsx';
import SafeMarkdown from './SafeMarkdown.js';

function Icon({ name }) {
  const paths = {
    lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/></>,
    send: <><path d="m21 3-7.5 18-3.8-7.7L2 9.5 21 3Z"/><path d="m9.7 13.3 5-5"/></>,
    edit: <><path d="m15 5 4 4M4 20l4.3-.9L19 8.4a2.8 2.8 0 0 0-4-4L4.3 15.1 4 20Z"/></>,
  };
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export default function PrivacyReviewPanel({ response, busy = false, error = '', onEdit, onAcknowledge, onApprove, onCancel, sarvamAvailable = false, onTranslate, onUseTranslation }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(response.draft);
  const residual = response.residual_review || {};
  const providerConfigured = response.provider?.configured === true;
  const residualReviewable = ['ready_for_user_review', 'needs_review'].includes(residual.status);
  const needsWarningAck = residual.status === 'needs_review' && !response.acknowledged;
  const canApprove = providerConfigured && response.review_complete && residualReviewable && !needsWarningAck && response.send_state === 'review' && !busy;
  const disabledReason = !providerConfigured
    ? 'Approval is unavailable because the answer provider is not configured.'
    : residual.status === 'blocked' ? 'Approval is blocked until identifying details are removed or replaced and the request is rechecked.'
      : !response.review_complete ? 'Approval is unavailable until all privacy checks are complete.'
        : !residualReviewable ? 'Approval is unavailable because the remaining-clue check is incomplete.'
        : needsWarningAck ? 'Review and acknowledge the remaining privacy warning before approval.'
          : response.send_state !== 'review' ? `Approval is unavailable while this review is ${response.send_state}.` : '';
  const answer = response.send_state === 'answer_withheld' ? null : response.answer;
  const status = getWorkflowStatus(response);

  async function saveDraft() {
    const updated = await onEdit(draft);
    if (updated) { setDraft(updated.draft); setEditing(false); }
  }

  return <section className="review-card glass-panel" aria-labelledby="review-title">
    <div className="review-top"><span className="review-lock"><Icon name="lock"/></span><div className="review-title"><h2 id="review-title">{response.send_state === 'sent' ? 'Answer received' : response.send_state === 'answer_withheld' ? 'Answer withheld' : response.send_state === 'delivery_unknown' ? 'Answer provider failed' : 'Review before sending'}</h2><p>{status.detail}</p></div><span className={`risk-pill state-${residual.status || 'pending'}`}><i/>{status.label}</span></div>
    <p className="provider-line">{providerConfigured ? `Answer provider: ${response.provider.name}` : `Answer provider ${response.provider?.name || ''} is not configured`}{response.provider?.endpoint && <small> · {response.provider.endpoint}</small>}</p>
    {error && <p className="notice" role="alert">{error}</p>}
    {answer && <section className="answer-result" aria-label="Provider answer" aria-live="polite"><div className="answer-label">Answer</div><SafeMarkdown>{answer}</SafeMarkdown><small>{response.provider?.name || 'Provider'}{Array.isArray(response.pages_used) && response.pages_used.length ? ` · pages ${response.pages_used.join(', ')}` : ''}</small></section>}
    <details className="request-disclosure" open={!answer || editing}>
      <summary><span>Exact request to be sent</span><small>Version {response.version}</small></summary>
      <p className="request-caption">Inspect the exact text {answer ? 'approved for this answer' : 'before approving'}. The original document is not attached.</p>
      {editing ? <><label className="visually-hidden" htmlFor="sanitized-request">Exact sanitized request</label><textarea id="sanitized-request" className="request-preview request-editor" value={draft} readOnly={busy} onChange={event => setDraft(event.target.value)} /></>
        : <div className="request-preview" role="region" aria-label="Exact sanitized request" tabIndex={0}>{response.draft}</div>}
    </details>
    {sarvamAvailable && !editing && response.send_state === 'review' && <DraftTranslation response={response} busy={busy} onTranslate={onTranslate} onUseTranslation={onUseTranslation}/>}
    <div className="review-actions">
      {editing ? <><button className="approve-button" type="button" onClick={saveDraft} disabled={busy || !draft.trim()}>{busy ? 'Checking…' : 'Save and recheck'}</button><button className="edit-button" type="button" onClick={() => { setDraft(response.draft); setEditing(false); }} disabled={busy}>Discard edits</button></>
        : <><button className="approve-button" type="button" onClick={onApprove} disabled={!canApprove}><Icon name="send"/>{busy ? 'Working…' : response.send_state === 'sent' ? 'Answer received' : response.send_state === 'answer_withheld' ? 'Answer withheld' : response.send_state === 'delivery_unknown' ? 'Provider delivery failed' : 'Approve & get answer'}</button><button className="edit-button" type="button" onClick={() => { setDraft(response.draft); setEditing(true); }} disabled={busy || !!answer || response.send_state !== 'review'}><Icon name="edit"/>Edit request</button></>}
    </div>
    {!editing && <p className={`review-footnote ${canApprove ? 'approval-ready' : ''}`}><span className="info-icon">i</span>{canApprove ? 'Only this exact text will be sent after your approval.' : disabledReason || 'The request has already been submitted.'}</p>}
    {needsWarningAck && <button className="acknowledge-button" type="button" onClick={onAcknowledge} disabled={busy}>I reviewed the remaining warning</button>}
    {!answer && response.send_state === 'review' && <button className="cancel-review" type="button" onClick={onCancel} disabled={busy}>Cancel review</button>}
  </section>;
}
