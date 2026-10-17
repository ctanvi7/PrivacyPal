import { ApiError } from './apiClient.js';
import { getDocumentValidationError } from './documentValidation.js';

const NO_UPLOAD_HANDLER_MESSAGE = 'Backend upload is not configured. The document remains selected only in this browser.';
const GENERIC_UPLOAD_ERROR = 'The document could not be uploaded. Please try again.';

function initialState() {
  return {
    status: 'empty',
    selectedFile: null,
    uploadedDocument: null,
    error: null,
  };
}

function safeUploadError(error) {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message, retryable: error.retryable };
  }
  return { code: 'upload_error', message: GENERIC_UPLOAD_ERROR, retryable: true };
}

/**
 * Coordinates local selection and an injected, contract-specific uploader.
 * No endpoint or request payload is assumed here. The uploader must resolve
 * only after the backend confirms the uploaded document.
 */
export function createDocumentUploadController({
  uploadDocument,
  validate = getDocumentValidationError,
  timeoutMs = 30_000,
} = {}) {
  let state = initialState();
  let sequence = 0;
  let active = null;
  const listeners = new Set();

  function publish(nextState) {
    state = nextState;
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

  function select(file) {
    if (!file) return state;
    const validationError = validate(file);
    if (validationError) {
      return publish({
        ...state,
        error: { code: 'unsupported_file', message: validationError, retryable: false },
      });
    }

    stopActive();
    return publish({
      status: 'selected',
      selectedFile: file,
      uploadedDocument: null,
      error: null,
    });
  }

  function reset() {
    stopActive();
    return publish(initialState());
  }

  function cancel() {
    if (!active) return state;
    stopActive();
    return publish({
      ...state,
      status: state.selectedFile ? 'cancelled' : 'empty',
      uploadedDocument: null,
      error: { code: 'cancelled', message: 'Upload cancelled. You can retry when ready.', retryable: true },
    });
  }

  function upload() {
    if (active) return active.promise;
    if (!state.selectedFile) {
      return Promise.resolve(publish({
        ...state,
        error: { code: 'no_document', message: 'Choose a supported document before uploading.', retryable: false },
      }));
    }
    if (state.status === 'uploaded') return Promise.resolve(state.uploadedDocument);
    if (typeof uploadDocument !== 'function') {
      publish({
        ...state,
        status: 'unavailable',
        uploadedDocument: null,
        error: { code: 'integration_unavailable', message: NO_UPLOAD_HANDLER_MESSAGE, retryable: false },
      });
      return Promise.resolve(null);
    }

    const currentSequence = ++sequence;
    const controller = new AbortController();
    let timedOut = false;
    const timer = timeoutMs > 0
      ? setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs)
      : null;

    publish({ ...state, status: 'uploading', uploadedDocument: null, error: null });
    const operation = {
      controller,
      timer,
      promise: null,
    };
    operation.promise = Promise.resolve()
      .then(() => {
        if (currentSequence !== sequence || controller.signal.aborted) return null;
        return uploadDocument(state.selectedFile, { signal: controller.signal });
      })
      .then(uploadedDocument => {
        if (currentSequence !== sequence || controller.signal.aborted) return null;
        publish({ ...state, status: 'uploaded', uploadedDocument, error: null });
        return uploadedDocument;
      })
      .catch(error => {
        if (currentSequence !== sequence) return null;
        if (timedOut) {
          publish({
            ...state,
            status: 'upload-error',
            uploadedDocument: null,
            error: { code: 'timeout', message: 'Upload timed out. Check your connection and try again.', retryable: true },
          });
        } else if (controller.signal.aborted || error?.name === 'AbortError') {
          publish({
            ...state,
            status: 'cancelled',
            uploadedDocument: null,
            error: { code: 'cancelled', message: 'Upload cancelled. You can retry when ready.', retryable: true },
          });
        } else {
          publish({ ...state, status: 'upload-error', uploadedDocument: null, error: safeUploadError(error) });
        }
        return null;
      })
      .finally(() => {
        if (timer) clearTimeout(timer);
        if (active === operation) active = null;
      });

    active = operation;
    return operation.promise;
  }

  return Object.freeze({
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    select,
    upload,
    retry: upload,
    cancel,
    reset,
  });
}
