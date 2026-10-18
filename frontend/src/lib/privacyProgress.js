import { processingCopy } from './deployment.js';

const STAGES = [
  { id: 'read', title: 'Read document' },
  { id: 'sensitive', title: 'Find sensitive details' },
  { id: 'relevant', title: 'Select relevant content' },
  { id: 'residual', title: 'Check remaining clues' },
];

function pageText(count) {
  return `${count} ${count === 1 ? 'page' : 'pages'}`;
}

/** Derive progress only from confirmed upload and backend workflow data. */
export function getPrivacyProgress({
  uploadStatus = 'empty',
  uploadResult = null,
  uploadError = null,
  questionStatus = 'idle',
  questionError = null,
  workflowResponse = null,
} = {}) {
  const stages = STAGES.map(stage => ({ ...stage, status: 'pending', detail: 'Not started' }));

  if (uploadStatus === 'uploaded' && uploadResult) {
    stages[0].status = 'completed';
    stages[0].detail = Number.isInteger(uploadResult.page_count)
      ? `Extracted ${pageText(uploadResult.page_count)} locally.`
      : 'Confirmed by the local service.';
  } else if (uploadStatus === 'uploading') {
    stages[0].status = 'in-progress';
    stages[0].detail = 'Uploading to the local service.';
  } else if (['upload-error', 'cancelled', 'unavailable'].includes(uploadStatus)) {
    stages[0].status = 'failed';
    stages[0].detail = uploadError?.message || 'Upload did not complete.';
  } else if (uploadStatus === 'selected') {
    stages[0].detail = 'Selected in this browser; upload is not confirmed.';
  }

  if (workflowResponse) {
    const findings = Array.isArray(workflowResponse.findings) ? workflowResponse.findings : [];
    const pagesUsed = Array.isArray(workflowResponse.pages_used) ? workflowResponse.pages_used : [];
    const residual = workflowResponse.residual_review || {};
    const reasons = Array.isArray(residual.reasons) ? residual.reasons : [];

    const checkedDraft = workflowResponse.local_checks?.sensitive === 'completed' && workflowResponse.local_checks?.relevant === 'completed';
    if (workflowResponse.review_complete || checkedDraft) {
      stages[1].status = 'completed';
      stages[1].detail = `${findings.length} ${findings.length === 1 ? 'finding' : 'findings'} returned by the local review.`;
      stages[2].status = 'completed';
      stages[2].detail = pagesUsed.length
        ? `Draft uses relevant content from ${pageText(pagesUsed.length)}.`
        : 'The local review reported no relevant source pages.';
      if (workflowResponse.local_checks?.residual === 'failed') {
        stages[3].status = 'failed';
        stages[3].detail = reasons[0] || 'The remaining-clue review did not complete.';
      } else if (residual.status === 'blocked') {
        stages[3].status = 'blocked';
        stages[3].detail = reasons[0] || 'A high-risk issue blocks approval.';
      } else if (residual.status === 'needs_review' && !workflowResponse.acknowledged) {
        stages[3].status = 'needs-review';
        stages[3].detail = reasons[0] || 'Review the remaining privacy warnings.';
      } else if (residual.status === 'needs_review') {
        stages[3].status = 'completed';
        stages[3].detail = 'You acknowledged the remaining review warnings.';
      } else {
        stages[3].status = 'completed';
        stages[3].detail = reasons[0] || 'The local review found no remaining clues.';
      }
    } else {
      stages[1].status = 'failed';
      stages[1].detail = 'A required local privacy check did not complete.';
      stages[2].status = 'failed';
      stages[2].detail = 'A minimized request is not ready for approval.';
      stages[3].status = 'failed';
      stages[3].detail = reasons[0] || 'The remaining-clue review is incomplete.';
    }
  } else if (questionStatus === 'processing') {
    stages[1].status = 'in-progress';
    stages[1].detail = 'Checking for sensitive details locally.';
    stages[2].detail = 'Waiting for the local review.';
    stages[3].detail = 'Waiting for the local review.';
  } else if (['processing-error', 'cancelled', 'unavailable'].includes(questionStatus)) {
    stages[1].status = 'failed';
    stages[1].detail = questionError?.message || 'Local analysis did not return a review.';
    stages[2].detail = 'No minimized request was returned.';
    stages[3].detail = 'No remaining-clue review was returned.';
    if (questionError?.localChecks) {
      for (const [index, key] of [[1, 'sensitive'], [2, 'relevant'], [3, 'residual']]) {
        const status = questionError.localChecks[key];
        if (!['completed', 'failed', 'pending'].includes(status)) continue;
        stages[index].status = status;
        stages[index].detail = status === 'completed'
          ? 'This local check completed before a later step failed.'
          : status === 'failed' ? questionError.message : 'Waiting for a successful local review.';
      }
    }
  }

  return stages.map(stage => ({ ...stage, title: processingCopy(stage.title), detail: processingCopy(stage.detail) }));
}
