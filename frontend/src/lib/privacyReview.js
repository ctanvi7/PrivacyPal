import { ApiError } from './apiClient.js';

/**
 * Canonical review shape produced by an explicit backend adapter:
 * {
 *   originalRequestText: string,
 *   proposedOutgoingText: string,
 *   exactOutgoingText: string,
 *   recommendations: [{ action: 'keep'|'mask'|'replace', item: string,
 *     replacement?: string|null, reason: string }],
 *   riskFlags: [{ label: string, description?: string, level?: string }]
 * }
 * `level` is opaque backend-supplied text: this model defines no risk scale.
 * The adapter maps the backend schema into this canonical shape. The caller
 * must explicitly identify the raw value as backend-originated; demo objects
 * are not passed through this real-review normalization path.
 */
export class PrivacyReviewDataError extends Error {
  constructor(message) { super(message); this.name = 'PrivacyReviewDataError'; }
}

function requiredText(value, field) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new PrivacyReviewDataError(`Privacy review is missing valid ${field}.`);
  }
  return value;
}

export function normalizePrivacyReview(raw, adaptBackendReview, { source } = {}) {
  if (source !== 'backend') {
    throw new PrivacyReviewDataError('Only an explicitly identified backend response can become a real privacy review.');
  }
  if (typeof adaptBackendReview !== 'function') {
    throw new PrivacyReviewDataError('A backend-specific review adapter is required.');
  }
  let canonical;
  try {
    canonical = adaptBackendReview(raw);
  } catch {
    throw new PrivacyReviewDataError('The backend privacy review could not be interpreted.');
  }
  if (!canonical || typeof canonical !== 'object' || Array.isArray(canonical)) {
    throw new PrivacyReviewDataError('The backend privacy review could not be interpreted.');
  }

  const recommendations = canonical.recommendations;
  if (!Array.isArray(recommendations) || recommendations.some(item =>
    !item || !['keep', 'mask', 'replace'].includes(item.action) ||
    typeof item.item !== 'string' || !item.item.trim() || typeof item.reason !== 'string' || !item.reason.trim() ||
    (item.replacement !== undefined && item.replacement !== null && typeof item.replacement !== 'string')
  )) {
    throw new PrivacyReviewDataError('The backend privacy recommendations are malformed.');
  }
  const riskFlags = canonical.riskFlags;
  if (!Array.isArray(riskFlags) || riskFlags.some(flag =>
    !flag || typeof flag.label !== 'string' || !flag.label.trim() ||
    (flag.description !== undefined && typeof flag.description !== 'string') ||
    (flag.level !== undefined && typeof flag.level !== 'string')
  )) {
    throw new PrivacyReviewDataError('The backend risk flags are malformed.');
  }

  return Object.freeze({
    originalRequestText: requiredText(canonical.originalRequestText, 'original request'),
    proposedOutgoingText: requiredText(canonical.proposedOutgoingText, 'proposed outgoing text'),
    exactOutgoingText: requiredText(canonical.exactOutgoingText, 'exact outgoing text'),
    recommendations: Object.freeze(recommendations.map(item => Object.freeze({ ...item }))),
    riskFlags: Object.freeze(riskFlags.map(flag => Object.freeze({ ...flag }))),
    source: 'backend',
  });
}

function initialState() {
  return { status: 'empty', review: null, exactOutgoingText: '', approvalGranted: false, result: null, error: null };
}

function safeSendError(error) {
  if (error instanceof ApiError) return { code: error.code, message: error.message, retryable: error.retryable };
  return { code: 'send_error', message: 'The approved request could not be submitted. Review its status before trying again.', retryable: false };
}

/**
 * Manages editing and explicit approval. `sendApprovedRequest` is a
 * contract-specific adapter supplied only after the backend approval contract
 * exists. The callback receives the normalized review and exact edited text.
 */
export function createPrivacyReviewController({ sendApprovedRequest, adaptBackendReview } = {}) {
  let state = initialState();
  let active = null;
  const listeners = new Set();

  function publish(next) {
    state = next;
    for (const listener of listeners) listener(state);
    return state;
  }

  function load(raw, { source } = {}) {
    try {
      const review = normalizePrivacyReview(raw, adaptBackendReview, { source });
      return publish({ status: 'review-ready', review, exactOutgoingText: review.exactOutgoingText, approvalGranted: false, result: null, error: null });
    } catch (error) {
      return publish({ ...initialState(), status: 'review-error', error: { code: 'invalid_review', message: error.message, retryable: false } });
    }
  }

  function beginEditing() {
    if (!['review-ready', 'awaiting-approval', 'approval-unavailable', 'send-error'].includes(state.status)) return state;
    return publish({ ...state, status: 'editing', approvalGranted: false, error: null });
  }

  function updateOutgoingText(text) {
    if (state.status !== 'editing' || typeof text !== 'string') return state;
    return publish({ ...state, exactOutgoingText: text, error: null });
  }

  function finishEditing() {
    if (state.status !== 'editing') return state;
    return publish({ ...state, status: 'awaiting-approval', approvalGranted: false, error: null });
  }

  function confirmReview() {
    if (state.status !== 'review-ready') return state;
    return publish({ ...state, status: 'awaiting-approval', approvalGranted: false, error: null });
  }

  function approve() {
    if (active) return active.promise;
    if (state.status === 'sent') return Promise.resolve(state.result);
    if (state.status !== 'awaiting-approval') return Promise.resolve(null);
    if (!state.exactOutgoingText.trim()) {
      publish({ ...state, error: { code: 'empty_outgoing_text', message: 'The final request must contain text before approval.', retryable: false } });
      return Promise.resolve(null);
    }
    if (typeof sendApprovedRequest !== 'function') {
      publish({ ...state, status: 'approval-unavailable', approvalGranted: false, error: { code: 'approval_unavailable', message: 'Sending is unavailable until the backend approval contract is connected. Nothing was sent.', retryable: false } });
      return Promise.resolve(null);
    }

    const controller = new AbortController();
    const payload = { review: state.review, exactOutgoingText: state.exactOutgoingText };
    publish({ ...state, status: 'approved', approvalGranted: true, error: null });
    const operation = { controller, promise: null };
    operation.promise = Promise.resolve()
      .then(() => {
        if (active !== operation || controller.signal.aborted) return null;
        publish({ ...state, status: 'sending', approvalGranted: true, error: null });
        return sendApprovedRequest(payload, { signal: controller.signal });
      })
      .then(result => {
        if (active !== operation || controller.signal.aborted) return null;
        publish({ ...state, status: 'sent', approvalGranted: true, result, error: null });
        return result;
      })
      .catch(error => {
        if (active !== operation) return null;
        publish({ ...state, status: 'send-error', approvalGranted: false, error: safeSendError(error) });
        return null;
      })
      .finally(() => { if (active === operation) active = null; });
    active = operation;
    return operation.promise;
  }

  function returnToEditing() {
    if (!['send-error', 'approval-unavailable'].includes(state.status)) return state;
    return publish({ ...state, status: 'editing', approvalGranted: false, error: null });
  }

  function reset() {
    if (active) active.controller.abort();
    active = null;
    return publish(initialState());
  }

  return Object.freeze({
    getState: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    load,
    beginEditing,
    updateOutgoingText,
    finishEditing,
    confirmReview,
    approve,
    returnToEditing,
    reset,
    canSend: typeof sendApprovedRequest === 'function',
  });
}
