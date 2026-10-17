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
      stages[2].status = 'in-progress';
      stages[2].detail = 'Review is ready; approval is not connected in this frontend.';
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

  stages[3].detail = 'Answer delivery is not connected; no answer has been returned.';
  return stages;
}

