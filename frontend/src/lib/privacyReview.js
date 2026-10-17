import { ApiError } from './apiClient.js';

const BACKEND_ACTIONS = new Set(['keep', 'mask', 'replace', 'omit', 'block']);

/**
 * The confirmed backend currently returns question/draft/findings and a
 * residual_review object. It does not return keep decisions, replacement
 * values, or a separate risk-flag schema; this adapter displays only supplied
 * values and does not infer missing classifications.
 */
export function adaptBackendWorkflow(response) {
  if (!response || typeof response !== 'object' || Array.isArray(response) ||
      typeof response.question !== 'string' || typeof response.draft !== 'string' ||
      !Array.isArray(response.findings) || !response.residual_review ||
      !Array.isArray(response.residual_review.findings) || !Array.isArray(response.residual_review.reasons)) {
    throw new TypeError('The backend workflow response is malformed.');
  }
  const recommendations = response.findings.map(item => {
    if (!item || typeof item !== 'object' || !BACKEND_ACTIONS.has(item.action) ||
        typeof item.category !== 'string' || typeof item.reason !== 'string') {
      throw new TypeError('A backend finding is malformed.');
    }
    return { action: item.action, item: item.category, reason: item.reason };
  });
  const riskFlags = [
    ...response.residual_review.findings.map(item => {
      if (!item || typeof item !== 'object' || typeof item.category !== 'string' || typeof item.reason !== 'string') {
        throw new TypeError('A backend residual finding is malformed.');
      }
      return { label: item.category, description: item.reason };
    }),
    ...response.residual_review.reasons.map(reason => {
      if (typeof reason !== 'string') throw new TypeError('A backend risk reason is malformed.');
      return { label: reason };
    }),
  ];
  return {
    originalRequestText: response.question,
    proposedOutgoingText: response.draft,
    exactOutgoingText: response.draft,
    recommendations,
    riskFlags,
  };
}

export class PrivacyReviewDataError extends Error {
  constructor(message) { super(message); this.name = 'PrivacyReviewDataError'; }
}

function initialState() {
  return { status: 'empty', review: null, backendResponse: null, exactOutgoingText: '', approvalGranted: false, result: null, error: null };
}

function safeError(error, fallback) {
  if (error instanceof ApiError) return { code: error.code, message: error.message, retryable: error.retryable };
  return { code: 'workflow_error', message: fallback, retryable: false };
}

function reviewStatus(response) {
  if (!response.review_complete || response.residual_review.status === 'blocked') return 'review-blocked';
  return 'review-ready';
}

/** Coordinates backend edits, acknowledgement, and explicit single-use approval. */
export function createPrivacyReviewController({
  updateDraft,
  acknowledgeReview,
  sendApprovedRequest,
  adaptBackendReview = adaptBackendWorkflow,
} = {}) {
  let state = initialState();
  let active = null;
  let sequence = 0;
  const listeners = new Set();

  function publish(next) {
    state = next;
    for (const listener of listeners) listener(state);
    return state;
  }

  function load(raw, { source } = {}) {
    if (source !== 'backend') {
      return publish({ ...initialState(), status: 'review-error', error: { code: 'invalid_review', message: 'Only a confirmed backend response can become a real privacy review.', retryable: false } });
    }
    try {
      const review = adaptBackendReview(raw);
      if (!raw || raw.send_state !== 'review' || !Number.isInteger(raw.version) || typeof raw.workflow_id !== 'string') {
        throw new TypeError('Invalid active workflow state.');
      }
      return publish({ ...initialState(), status: reviewStatus(raw), review, backendResponse: raw, exactOutgoingText: review.exactOutgoingText });
    } catch {
      return publish({ ...initialState(), status: 'review-error', error: { code: 'invalid_review', message: 'The backend privacy review could not be interpreted. Nothing was sent.', retryable: false } });
    }
  }

  function beginEditing() {
    if (!['review-ready', 'review-blocked', 'awaiting-approval', 'awaiting-acknowledgement'].includes(state.status)) return state;
    return publish({ ...state, status: 'editing', approvalGranted: false, error: null });
  }

  function updateOutgoingText(text) {
    if (state.status !== 'editing' || typeof text !== 'string') return state;
    return publish({ ...state, exactOutgoingText: text, approvalGranted: false, error: null });
  }

  function finishEditing() {
    if (active) return active.promise;
    if (state.status !== 'editing') return Promise.resolve(state);
    const response = state.backendResponse;
    const draft = state.exactOutgoingText.trim();
    if (!draft) return Promise.resolve(publish({ ...state, error: { code: 'empty_outgoing_text', message: 'The final request must contain text before it can be reviewed.', retryable: false } }));
    if (draft === response.draft) return Promise.resolve(publish({ ...state, status: state.backendResponse.acknowledged ? 'awaiting-approval' : reviewStatus(response), error: null }));
    if (typeof updateDraft !== 'function') return Promise.resolve(publish({ ...state, status: 'review-error', error: { code: 'edit_unavailable', message: 'Request editing is unavailable. Nothing was sent.', retryable: false } }));

    const op = { sequence: ++sequence, controller: new AbortController(), promise: null };
    active = op;
    publish({ ...state, status: 'saving-edit', approvalGranted: false, error: null });
    op.promise = Promise.resolve()
      .then(() => updateDraft({ workflowId: response.workflow_id, version: response.version, draft }, { signal: op.controller.signal }))
      .then(updated => {
        if (active !== op || op.controller.signal.aborted) return null;
        return load(updated, { source: 'backend' });
      })
      .catch(error => {
        if (active !== op || op.controller.signal.aborted) return null;
        return publish({ ...state, status: 'review-error', approvalGranted: false, error: safeError(error, 'The edited request could not be revalidated. Start a new review before approval.') });
      })
      .finally(() => { if (active === op) active = null; });
    return op.promise;
  }

  function confirmReview() {
    if (state.status !== 'review-ready') return state;
    if (state.backendResponse.residual_review.status === 'needs_review' && !state.backendResponse.acknowledged) {
      return publish({ ...state, status: 'awaiting-acknowledgement', approvalGranted: false, error: null });
    }
    return publish({ ...state, status: 'awaiting-approval', approvalGranted: false, error: null });
  }

  function acknowledge() {
    if (active) return active.promise;
    if (state.status !== 'awaiting-acknowledgement' || typeof acknowledgeReview !== 'function') return Promise.resolve(state);
    const response = state.backendResponse;
    const op = { controller: new AbortController(), promise: null };
    active = op;
    publish({ ...state, status: 'acknowledging', approvalGranted: false, error: null });
    op.promise = Promise.resolve()
      .then(() => acknowledgeReview({ workflowId: response.workflow_id, version: response.version }, { signal: op.controller.signal }))
      .then(updated => {
        if (active !== op || op.controller.signal.aborted) return null;
        const loaded = load(updated, { source: 'backend' });
        if (loaded.status === 'review-ready' && updated.acknowledged) return publish({ ...state, status: 'awaiting-approval' });
        return loaded;
      })
      .catch(error => {
        if (active !== op || op.controller.signal.aborted) return null;
        return publish({ ...state, status: 'review-error', approvalGranted: false, error: safeError(error, 'The review could not be acknowledged. Start a new review before approval.') });
      })
      .finally(() => { if (active === op) active = null; });
    return op.promise;
  }

  function approve() {
    if (active) return active.promise;
    if (state.status === 'sent') return Promise.resolve(state.result);
    if (state.status !== 'awaiting-approval') return Promise.resolve(null);
    const response = state.backendResponse;
    if (!response.review_complete || response.residual_review.status === 'blocked' || response.send_state !== 'review' ||
        (response.residual_review.status === 'needs_review' && !response.acknowledged) ||
        state.exactOutgoingText.trim() !== response.draft || !response.provider?.configured) {
      return Promise.resolve(publish({ ...state, status: 'review-blocked', approvalGranted: false, error: { code: 'review_not_current', message: 'The current backend review does not approve this exact text. Edit and recheck it before sending.', retryable: false } }));
    }
    if (typeof sendApprovedRequest !== 'function') {
      return Promise.resolve(publish({ ...state, status: 'approval-unavailable', error: { code: 'approval_unavailable', message: 'Sending is unavailable. Nothing was sent.', retryable: false } }));
    }

    const op = { controller: new AbortController(), promise: null };
    active = op;
    publish({ ...state, status: 'sending', approvalGranted: true, error: null });
    op.promise = Promise.resolve()
      .then(() => sendApprovedRequest({ workflowId: response.workflow_id, version: response.version, exactOutgoingText: response.draft }, { signal: op.controller.signal }))
      .then(result => {
        if (active !== op || op.controller.signal.aborted) return null;
        return publish({ ...state, status: 'sent', approvalGranted: true, result, error: null });
      })
      .catch(error => {
        if (active !== op || op.controller.signal.aborted) return null;
        return publish({ ...state, status: 'send-error', approvalGranted: false, error: safeError(error, 'The approval result is unknown or failed. Do not retry this workflow; start a new review if needed.') });
      })
      .finally(() => { if (active === op) active = null; });
    return op.promise;
  }

  function reset() {
    sequence += 1;
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
    acknowledge,
    approve,
    reset,
    get canApprove() {
      const response = state.backendResponse;
      return state.status === 'awaiting-approval' && !!response?.review_complete &&
        response?.residual_review?.status !== 'blocked' && response?.send_state === 'review' &&
        (response?.residual_review?.status !== 'needs_review' || response?.acknowledged === true) &&
        state.exactOutgoingText.trim() === response?.draft && response?.provider?.configured === true &&
        typeof sendApprovedRequest === 'function';
    },
  });
}
