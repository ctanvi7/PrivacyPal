export function createInitialWorkflowState() {
  return {
    status: 'empty',
    document: null,
    question: '',
    review: null,
    proposedRequest: '',
    editedRequest: null,
    finalOutgoingText: null,
    approvalGranted: false,
    answer: null,
    error: null,
    resumeStatus: null,
  };
}

function withError(state, status, error, resumeStatus = null) {
  return { ...state, status, error, resumeStatus };
}

export function workflowReducer(state, event) {
  switch (event.type) {
    case 'RESET':
      return createInitialWorkflowState();
    case 'DOCUMENT_SELECTED':
      return {
        ...createInitialWorkflowState(),
        status: 'document-selected',
        document: event.document,
      };
    case 'UPLOAD_STARTED':
      if (!['document-selected', 'upload-error'].includes(state.status) || !state.document) return state;
      return { ...state, status: 'uploading', error: null, resumeStatus: null };
    case 'UPLOAD_SUCCEEDED':
      if (state.status !== 'uploading') return state;
      return { ...state, status: 'uploaded-ready', error: null, resumeStatus: null };
    case 'UPLOAD_FAILED':
      if (state.status !== 'uploading') return state;
      return withError(state, 'upload-error', event.error);
    case 'QUESTION_SUBMITTED':
      if (state.status !== 'uploaded-ready' || !event.question?.trim()) return state;
      return {
        ...state,
        status: 'processing',
        question: event.question.trim(),
        review: null,
        proposedRequest: '',
        editedRequest: null,
        finalOutgoingText: null,
        approvalGranted: false,
        answer: null,
        error: null,
        resumeStatus: null,
      };
    case 'REVIEW_READY':
      if (state.status !== 'processing') return state;
      return {
        ...state,
        status: 'review-ready',
        review: event.review,
        proposedRequest: event.proposedRequest,
        finalOutgoingText: event.proposedRequest,
        editedRequest: null,
        approvalGranted: false,
        error: null,
      };
    case 'REQUEST_EDITED':
      if (state.status !== 'editing' || typeof event.request !== 'string') return state;
      return { ...state, editedRequest: event.request, finalOutgoingText: event.request, error: null };
    case 'EDITING_STARTED':
      if (!['review-ready', 'awaiting-approval', 'approval-error'].includes(state.status)) return state;
      return { ...state, status: 'editing', approvalGranted: false, error: null };
    case 'EDITING_FINISHED':
      if (state.status !== 'editing') return state;
      return { ...state, status: 'awaiting-approval', approvalGranted: false, error: null };
    case 'USER_APPROVED':
      if (state.status !== 'awaiting-approval' || !state.finalOutgoingText?.trim()) return state;
      return { ...state, status: 'approved', approvalGranted: true, error: null };
    case 'APPROVAL_STARTED':
      if (state.status !== 'approved' || !state.approvalGranted) return state;
      return { ...state, status: 'sending', error: null, resumeStatus: null };
    case 'APPROVAL_SENT':
      if (state.status !== 'sending') return state;
      return { ...state, status: 'sent', error: null, resumeStatus: null };
    case 'ANSWER_RECEIVED':
      if (state.status !== 'sent') return state;
      return { ...state, status: 'answered', answer: event.answer, error: null, resumeStatus: null };
    case 'PROCESSING_FAILED':
      if (state.status !== 'processing') return state;
      return withError(state, 'processing-error', event.error);
    case 'APPROVAL_FAILED':
      if (state.status !== 'sending') return state;
      return { ...withError(state, 'approval-error', event.error), approvalGranted: false };
    case 'NETWORK_FAILED':
      if (!['uploading', 'processing', 'sending'].includes(state.status)) return state;
      return { ...withError(state, 'network-error', event.error, state.status), approvalGranted: false };
    case 'RETRY':
      if (state.status === 'upload-error') return { ...state, status: 'document-selected', error: null };
      if (state.status === 'processing-error') return { ...state, status: 'uploaded-ready', error: null };
      if (state.status === 'approval-error') {
        return { ...state, status: state.editedRequest === null ? 'review-ready' : 'awaiting-approval', error: null };
      }
      if (state.status === 'network-error') {
        if (state.resumeStatus === 'sending') return { ...state, status: 'approval-error', resumeStatus: null, approvalGranted: false };
        return { ...state, status: state.resumeStatus || 'empty', error: null, resumeStatus: null };
      }
      return state;
    default:
      return state;
  }
}
