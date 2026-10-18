import { useEffect, useState } from 'react';
import { SARVAM_LANGUAGES } from '../lib/sarvam.js';

export default function DraftTranslation({ response, busy, onTranslate, onUseTranslation }) {
  const [source, setSource] = useState('en-IN');
  const [target, setTarget] = useState('hi-IN');
  const [consent, setConsent] = useState(false);
  const [translation, setTranslation] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { setConsent(false); setTranslation(null); setError(''); }, [source, target, response.workflow_id, response.version]);
  const canTranslate = response.review_complete && ['ready_for_user_review', 'needs_review'].includes(response.residual_review?.status)
    && (response.residual_review.status !== 'needs_review' || response.acknowledged) && response.draft.length <= 2000;
  async function translate() {
    if (!consent || busy || !canTranslate) return;
    setConsent(false); setError(''); setTranslation(null);
    try { setTranslation(await onTranslate(source, target)); }
    catch (failure) { setError(failure?.message || 'Translation failed. No fallback provider was used.'); }
  }
  return <section className="sarvam-translation" aria-label="Translate reviewed request">
    <h3>Translate reviewed request</h3>
    <p>Only the exact sanitized request above goes to Sarvam. Translation is a separate external request; using it reruns privacy checks before approval.</p>
    <label>Request source language <select value={source} disabled={busy} onChange={e => setSource(e.target.value)}>{SARVAM_LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>
    <label>Request translation language <select value={target} disabled={busy} onChange={e => setTarget(e.target.value)}>{SARVAM_LANGUAGES.map(([code, name]) => <option key={code} value={code}>{name}</option>)}</select></label>
    <label className="sarvam-consent"><input type="checkbox" checked={consent} disabled={busy || !canTranslate} onChange={e => setConsent(e.target.checked)}/> Send this exact reviewed request to Sarvam for translation.</label>
    <button type="button" className="edit-button" disabled={!consent || busy || !canTranslate} onClick={translate}>{busy ? 'Working…' : 'Translate reviewed request'}</button>
    {!canTranslate && <p>Complete and acknowledge the privacy review first. Translation supports up to 2,000 characters.</p>}
    {error && <p role="alert">{error}</p>}
    {translation && <><label htmlFor="translated-request-preview">Translation preview</label><textarea id="translated-request-preview" className="request-preview" readOnly value={translation.translated_text}/><button type="button" className="edit-button" disabled={busy || translation.version !== response.version} onClick={() => { setTranslation(null); void onUseTranslation(translation.translated_text); }}>Use translation and rerun privacy checks</button></>}
  </section>;
}
