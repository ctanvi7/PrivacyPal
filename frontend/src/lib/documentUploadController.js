import { ApiError } from './apiClient.js';
import { getDocumentValidationError } from './documentValidation.js';

const NO_UPLOAD_HANDLER_MESSAGE = 'Backend upload is not configured. The document remains selected only in this browser.';
const GENERIC_UPLOAD_ERROR = 'The document could not be uploaded. Please try again.';

function initialState() {
  return {
    status: 'empty',
    selectedFile: null,
    session: null,
    uploadedDocument: null,
    uploadedSessionId: null,
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
 * Coordinates validated selection, session creation, and server-confirmed upload.
 */
export function createDocumentUploadController({
  createSession,
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
      session: state.session,
      uploadedDocument: null,
      uploadedSessionId: null,
      error: null,
    });
  }

  function reset() {
    stopActive();
    return publish(initialState());
  }

  function forgetDocument() {
    stopActive();
    return publish({ ...initialState(), session: state.session });
  }

  function cancel() {
    if (!active) return state;
    stopActive();
    return publish({
      ...state,
      status: state.selectedFile ? 'cancelled' : 'empty',
      uploadedDocument: null,
      uploadedSessionId: null,
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
    if (typeof createSession !== 'function' || typeof uploadDocument !== 'function') {
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

    const selectedFile = state.selectedFile;
    let session = state.session;
    publish({ ...state, status: 'uploading', uploadedDocument: null, uploadedSessionId: null, error: null });
    const operation = {
      controller,
      timer,
      promise: null,
    };
    operation.promise = Promise.resolve()
      .then(() => {
        if (currentSequence !== sequence || controller.signal.aborted) return null;
        return (async () => {
          if (!session) {
            session = await createSession({ signal: controller.signal });
            if (currentSequence !== sequence || controller.signal.aborted) return null;
            if (!session || typeof session.session_id !== 'string' || !session.session_id) {
              throw new ApiError('The local service returned an invalid session response.', { code: 'invalid_response' });
            }
            publish({ ...state, session, status: 'uploading', error: null });
          }
          const document = await uploadDocument(session.session_id, selectedFile, { signal: controller.signal });
          if (!document || typeof document.document_id !== 'string' || !document.document_id) {
            throw new ApiError('The local service did not confirm the uploaded document.', { code: 'invalid_response' });
          }
          return document;
        })();
      })
      .then(uploadedDocument => {
        if (currentSequence !== sequence || controller.signal.aborted) return null;
        publish({ ...state, session, status: 'uploaded', uploadedDocument, uploadedSessionId: session.session_id, error: null });
        return uploadedDocument;
      })
      .catch(error => {
        if (currentSequence !== sequence) return null;
        if (timedOut) {
          publish({
            ...state,
            status: 'upload-error',
            uploadedDocument: null,
            uploadedSessionId: null,
            error: { code: 'timeout', message: 'Upload timed out. Check your connection and try again.', retryable: true },
          });
        } else if (controller.signal.aborted || error?.name === 'AbortError') {
          publish({
            ...state,
            status: 'cancelled',
            uploadedDocument: null,
            uploadedSessionId: null,
            error: { code: 'cancelled', message: 'Upload cancelled. You can retry when ready.', retryable: true },
          });
        } else {
          publish({ ...state, status: 'upload-error', uploadedDocument: null, uploadedSessionId: null, error: safeUploadError(error) });
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
    forgetDocument,
  });
}
