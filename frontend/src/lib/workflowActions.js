import { processingCopy } from './deployment.js';

/** Apply full review responses or partial approval receipts without losing checks. */
export async function performWorkflowAction({
  workflow, sessionId, busy, action, approval = false,
  setWorkflow, setBusy, setError,
}) {
  if (!workflow || busy || !sessionId) return null;
  if (approval && workflow.send_state !== 'review') return null;
  setBusy(true);
  setError('');
  if (approval) setWorkflow(current => ({ ...current, send_state: 'sending' }));
  try {
    const next = await action(sessionId, workflow.workflow_id, workflow.version);
    if (next) setWorkflow(current => approval ? { ...current, ...next } : next);
    return next;
  } catch (error) {
    setError(error?.message || 'The review action could not be completed safely.');
    if (approval) setWorkflow(current => ({
      ...current, answer: null,
      send_state: error?.code === 'ANSWER_WITHHELD' ? 'answer_withheld' : 'delivery_unknown',
    }));
    return null;
  } finally {
    setBusy(false);
  }
}

/** Delivery status never changes the results of the completed local review. */
function workflowStatus(response) {
  switch (response.send_state) {
    case 'sending':
      return { label: 'Sending approved request', detail: 'Local privacy checks are complete. Waiting for the answer provider.' };
    case 'sent':
      return { label: 'Sent — answer received', detail: 'The approved request was sent and the answer is shown below.' };
    case 'delivery_unknown':
      return { label: 'Provider delivery failed', detail: 'Local privacy check results are preserved. Delivery may have occurred; this approval cannot be retried.' };
    case 'answer_withheld':
      return { label: 'Answer withheld', detail: 'The provider returned personal-looking details that could not be verified against the approved request. The answer was withheld; local review results are preserved. This approval cannot be retried.' };
    case 'cancelled':
      return { label: 'Cancelled', detail: 'This review was cancelled. No answer request was sent.' };
    default:
      return {
        label: response.residual_review?.status === 'ready_for_user_review' ? 'Ready for review'
          : response.residual_review?.status === 'needs_review' ? 'Needs review'
            : response.residual_review?.status || 'Review pending',
        detail: response.residual_review?.status === 'blocked' ? 'Identifying details still need attention. Edit the request and recheck, or cancel. Nothing has been sent.'
          : response.review_complete ? 'Check the exact request before it is sent to the answer provider.'
          : 'Privacy checks are incomplete; approval is unavailable.',
      };
  }
}

export function getWorkflowStatus(response) {
  const result = workflowStatus(response);
  return { ...result, detail: processingCopy(result.detail) };
}
