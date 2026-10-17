import { ApiError } from './apiClient.js';

const EMPTY_QUESTION = 'Enter a question about your document.';
const UPLOAD_REQUIRED = 'Upload the selected document successfully before asking a question.';
const UNAVAILABLE = 'Question analysis is unavailable until the backend integration is configured.';
const GENERIC_FAILURE = 'The question could not be submitted. Please try again.';

function initialState() {
  return { status: 'idle', question: '', result: null, error: null };
}

function safeError(error) {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message, retryable: error.retryable };
  }
  return { code: 'processing_error', message: GENERIC_FAILURE, retryable: true };
}

/**
 * Question submission boundary. The injected submit function owns the actual
 * backend contract; this controller only checks readiness and manages UI state.
 */
export function createQuestionController({ submitQuestion, timeoutMs = 60_000 } = {}) {
  let state = initialState();
  let active = null;
  let sequence = 0;
  const listeners = new Set();

  function publish(next) {
    state = next;
    for (const listener of listeners) listener(state);
    return state;
  }

  function stopActive() {
    if (!active) return;
    sequence += 1;
    active.controller.abort();
    if (active.timer) clearTimeout(active.timer);
    active = null;
  }

  function setQuestion(question) {
    const nextQuestion = typeof question === 'string' ? question : '';
    if (state.status === 'processing') return state;
    return publish({ ...state, status: 'idle', question: nextQuestion, result: null, error: null });
  }

  function reset() {
    stopActive();
    return publish(initialState());
  }

  function cancel() {
    if (!active) return state;
    stopActive();
    return publish({ ...state, status: 'cancelled', error: { code: 'cancelled', message: 'Question submission cancelled.', retryable: true } });
  }

  function submit({ question = state.question, uploadedDocument } = {}) {
    if (active) return active.promise;
    const normalizedQuestion = typeof question === 'string' ? question.trim() : '';
    if (!normalizedQuestion) {
      return Promise.resolve(publish({ ...state, question: typeof question === 'string' ? question : '', status: 'validation-error', result: null, error: { code: 'empty_question', message: EMPTY_QUESTION, retryable: false } }));
    }
    if (!uploadedDocument) {
      return Promise.resolve(publish({ ...state, question: normalizedQuestion, status: 'blocked', result: null, error: { code: 'upload_required', message: UPLOAD_REQUIRED, retryable: false } }));
    }
    if (typeof submitQuestion !== 'function') {
      return Promise.resolve(publish({ ...state, question: normalizedQuestion, status: 'unavailable', result: null, error: { code: 'integration_unavailable', message: UNAVAILABLE, retryable: false } }));
    }
    if (state.status === 'review-ready') return Promise.resolve(state.result);

    const currentSequence = ++sequence;
    const controller = new AbortController();
    let timedOut = false;
    const timer = timeoutMs > 0 ? setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs) : null;
    publish({ ...state, status: 'processing', question: normalizedQuestion, result: null, error: null });

    const operation = { controller, timer, promise: null };
    operation.promise = Promise.resolve()
      .then(() => {
        if (currentSequence !== sequence || controller.signal.aborted) return null;
        return submitQuestion(normalizedQuestion, uploadedDocument, { signal: controller.signal });
      })
      .then(result => {
        if (currentSequence !== sequence || controller.signal.aborted) return null;
        publish({ ...state, status: 'review-ready', result, error: null });
        return result;
      })
      .catch(error => {
        if (currentSequence !== sequence) return null;
        const failure = timedOut
          ? { code: 'timeout', message: 'Question processing timed out. You can try again.', retryable: true }
          : controller.signal.aborted || error?.name === 'AbortError'
            ? { code: 'cancelled', message: 'Question submission cancelled.', retryable: true }
            : safeError(error);
        publish({ ...state, status: failure.code === 'cancelled' ? 'cancelled' : 'processing-error', error: failure });
        return null;
      })
      .finally(() => {
        if (timer) clearTimeout(timer);
        if (active === operation) active = null;
      });
    active = operation;
    return operation.promise;
  }

  function retry({ uploadedDocument } = {}) {
    if (!state.error?.retryable) return Promise.resolve(state);
    return submit({ question: state.question, uploadedDocument });
  }

  return Object.freeze({
    getState: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    setQuestion,
    submit,
    retry,
    cancel,
    reset,
  });
}
