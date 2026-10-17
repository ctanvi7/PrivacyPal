const STAGES = [
  { id: 'upload', title: 'Document upload' },
  { id: 'analysis', title: 'Local privacy analysis' },
  { id: 'review', title: 'Review and approval' },
  { id: 'answer', title: 'Answer returned' },
];

/** Derive visible progress only from confirmed frontend/backend state. */
export function getPrivacyProgress({
  uploadStatus = 'empty',
  questionStatus = 'idle',
  workflowResponse = null,
  reviewStatus = 'empty',
  answerReturned = false,
  illustrativePreview = false,
} = {}) {
  const stages = STAGES.map(stage => ({ ...stage, status: 'pending', detail: 'Not started' }));

  if (illustrativePreview) {
    stages[0].detail = 'Illustrative preview only; no upload occurred.';
    stages[1].detail = 'Illustrative preview only; no analysis occurred.';
    stages[2].detail = 'Approval is not connected; sample controls send nothing.';
    stages[3].detail = 'No answer was requested or returned.';
    return stages;
  }

  if (uploadStatus === 'uploaded') {
    stages[0].status = 'completed';
    stages[0].detail = 'Confirmed by the local service.';
  } else if (uploadStatus === 'uploading') {
    stages[0].status = 'in-progress';
    stages[0].detail = 'Uploading to the local service.';
  } else if (['upload-error', 'cancelled', 'unavailable'].includes(uploadStatus)) {
    stages[0].status = 'failed';
    stages[0].detail = 'Upload did not complete.';
  } else if (uploadStatus === 'selected') {
    stages[0].detail = 'Selected locally; upload has not been confirmed.';
  }

  if (workflowResponse) {
    if (workflowResponse.review_complete === true) {
      stages[1].status = 'completed';
      stages[1].detail = 'Backend returned a complete local review.';
      stages[2].status = ['sending', 'acknowledging', 'saving-edit'].includes(reviewStatus) ? 'in-progress' :
        ['review-blocked', 'review-error', 'send-error'].includes(reviewStatus) ? 'failed' :
          ['sent'].includes(reviewStatus) ? 'completed' : 'in-progress';
      stages[2].detail = reviewStatus === 'sent' ? 'Backend confirmed approval and submission.' :
        reviewStatus === 'sending' ? 'Submitting the explicitly approved request.' :
          reviewStatus === 'send-error' ? 'Approval result failed or is uncertain; do not retry this workflow.' :
            'Review the exact text and approve explicitly before sending.';
    } else {
      stages[1].status = 'failed';
      stages[1].detail = 'Backend returned an incomplete local review.';
      stages[2].status = 'failed';
      stages[2].detail = 'Approval is unavailable because the review is incomplete.';
    }
  } else if (questionStatus === 'processing') {
    stages[1].status = 'in-progress';
    stages[1].detail = 'Processing with the local backend.';
  } else if (['processing-error', 'cancelled', 'unavailable'].includes(questionStatus)) {
    stages[1].status = 'failed';
    stages[1].detail = 'Local analysis did not return a review.';
  }

  if (questionStatus === 'review-ready' && !workflowResponse) {
    stages[1].status = 'failed';
    stages[1].detail = 'No valid backend review is available.';
  }

  if (answerReturned) {
    stages[2].status = 'completed';
    stages[3].status = 'completed';
    stages[3].detail = 'Answer returned by the backend.';
  } else if (reviewStatus === 'sending') {
    stages[3].status = 'in-progress';
    stages[3].detail = 'Waiting for the backend response to the approved request.';
  } else if (reviewStatus === 'send-error') {
    stages[3].status = 'failed';
    stages[3].detail = 'No answer was confirmed; delivery may be uncertain.';
  } else {
    stages[3].detail = 'No answer has been returned.';
  }
  return stages;
}

