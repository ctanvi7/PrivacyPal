import { ApiError, createApiClient } from './apiClient.js';

function invalidResponse(message) {
  return new ApiError(message, { code: 'invalid_response', retryable: false });
}

function requireObject(value, message) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalidResponse(message);
  return value;
}

function requireText(value, message) {
  if (typeof value !== 'string' || !value.trim()) throw invalidResponse(message);
  return value;
}

/** Validates and preserves the confirmed session-create response. */
export function mapSessionResponse(value) {
  const response = requireObject(value, 'The local service returned an invalid session response.');
  requireText(response.session_id, 'The local service returned an invalid session response.');
  if (!Number.isInteger(response.expires_in_seconds) || response.expires_in_seconds <= 0) {
    throw invalidResponse('The local service returned an invalid session response.');
  }
  if (response.conversation_id !== undefined) requireText(response.conversation_id, 'The local service returned an invalid session response.');
  return Object.freeze({ ...response });
}

function mapConversationSummary(value) {
  const item = requireObject(value, 'The local service returned invalid conversation history.');
  requireText(item.conversation_id, 'The local service returned invalid conversation history.');
  requireText(item.created_at, 'The local service returned invalid conversation history.');
  requireText(item.updated_at, 'The local service returned invalid conversation history.');
  if (item.preview !== null && typeof item.preview !== 'string') throw invalidResponse('The local service returned invalid conversation history.');
  return Object.freeze({ ...item });
}

export function mapConversationList(value) {
  const response = requireObject(value, 'The local service returned invalid conversation history.');
  if (!Array.isArray(response.items) || !Number.isInteger(response.limit) || !Number.isInteger(response.offset)) {
    throw invalidResponse('The local service returned invalid conversation history.');
  }
  return Object.freeze({ ...response, items: response.items.map(mapConversationSummary) });
}

export function mapConversationDetail(value) {
  const response = requireObject(value, 'The local service returned an invalid conversation.');
  requireText(response.conversation_id, 'The local service returned an invalid conversation.');
  requireText(response.created_at, 'The local service returned an invalid conversation.');
  requireText(response.updated_at, 'The local service returned an invalid conversation.');
  if (!Array.isArray(response.messages)) throw invalidResponse('The local service returned an invalid conversation.');
  const messages = response.messages.map(message => {
    requireObject(message, 'The local service returned an invalid conversation message.');
    requireText(message.message_id, 'The local service returned an invalid conversation message.');
    if (!['user', 'assistant'].includes(message.role) || typeof message.content !== 'string' ||
        typeof message.created_at !== 'string' || (message.status !== null && typeof message.status !== 'string')) {
      throw invalidResponse('The local service returned an invalid conversation message.');
    }
    return Object.freeze({ ...message });
  }).sort((left, right) => {
    const difference = Date.parse(left.created_at) - Date.parse(right.created_at);
    return Number.isFinite(difference) && difference !== 0 ? difference : left.message_id.localeCompare(right.message_id);
  });
  return Object.freeze({ ...response, messages });
}

/** Validates and preserves the actual upload response; no local selection is treated as success. */
export function mapDocumentResponse(value) {
  const response = requireObject(value, 'The local service returned an invalid document response.');
  requireText(response.document_id, 'The local service returned an invalid document response.');
  requireText(response.source_type, 'The local service returned an invalid document response.');
  requireText(response.status, 'The local service returned an invalid document response.');
  if (!Number.isInteger(response.page_count) || !Number.isInteger(response.character_count)) {
    throw invalidResponse('The local service returned an invalid document response.');
  }
  return Object.freeze({ ...response });
}

/**
 * Explicit adapter for POST /api/v1/sessions/{id}/questions. It retains every
 * backend field without inventing review findings, risk levels, or defaults.
 */
export function mapWorkflowResponse(value) {
  const response = requireObject(value, 'The local service returned an invalid privacy analysis response.');
  requireText(response.workflow_id, 'The local service returned an invalid privacy analysis response.');
  requireText(response.question, 'The local service returned an invalid privacy analysis response.');
  requireText(response.draft, 'The local service returned an invalid privacy analysis response.');
  requireText(response.send_state, 'The local service returned an invalid privacy analysis response.');
  if (!Number.isInteger(response.version) || !Array.isArray(response.findings) ||
      !response.residual_review || typeof response.residual_review !== 'object' || Array.isArray(response.residual_review) ||
      typeof response.review_complete !== 'boolean' || typeof response.acknowledged !== 'boolean' ||
      !response.provider || typeof response.provider !== 'object' || Array.isArray(response.provider) ||
      !Array.isArray(response.pages_used) ||
      typeof response.residual_review.status !== 'string' ||
      !Array.isArray(response.residual_review.findings) || !Array.isArray(response.residual_review.reasons)) {
    throw invalidResponse('The local service returned an invalid privacy analysis response.');
  }
  return Object.freeze({ ...response });
}

/** Validates the confirmed response from the workflow approval endpoint. */
export function mapApprovalResponse(value) {
  const response = requireObject(value, 'The local service returned an invalid answer response.');
  requireText(response.workflow_id, 'The local service returned an invalid answer response.');
  requireText(response.answer, 'The local service returned an invalid answer response.');
  if (!Number.isInteger(response.version) || response.send_state !== 'sent' ||
      !Array.isArray(response.pages_used) || typeof response.history_saved !== 'boolean') {
    throw invalidResponse('The local service returned an invalid answer response.');
  }
  return Object.freeze({ ...response });
}

/** Contract-specific session, PDF upload, and local-analysis API. */
export function createPrivacyPalApi({ client = createApiClient() } = {}) {
  return Object.freeze({
    async createSession({ signal, conversationId } = {}) {
      const result = await client.request('api/v1/sessions', {
        method: 'POST', signal,
        ...(conversationId ? { body: { conversation_id: conversationId } } : {}),
      });
      const session = mapSessionResponse(result);
      if (conversationId && session.conversation_id !== conversationId) {
        throw invalidResponse('The local service attached the session to a different conversation.');
      }
      return session;
    },
    async uploadDocument(sessionId, file, { signal } = {}) {
      requireText(sessionId, 'A session is required before uploading a document.');
      if (!file) throw new TypeError('A selected file is required.');
      const form = new FormData();
      form.append('file', file, file.name);
      const result = await client.request(`api/v1/sessions/${encodeURIComponent(sessionId)}/documents`, {
        method: 'POST', body: form, signal,
      });
      return mapDocumentResponse(result);
    },
    async submitQuestion(sessionId, documentId, question, { signal } = {}) {
      requireText(sessionId, 'An active session is required before asking a question.');
      requireText(documentId, 'A server-confirmed document is required before asking a question.');
      requireText(question, 'Enter a question about your document.');
      const result = await client.request(`api/v1/sessions/${encodeURIComponent(sessionId)}/questions`, {
        method: 'POST',
        body: { document_id: documentId, question },
        signal,
        timeoutMs: 130_000,
      });
      return mapWorkflowResponse(result);
    },
    async updateDraft(sessionId, workflowId, version, draft, { signal } = {}) {
      requireText(sessionId, 'An active session is required to edit this request.');
      requireText(workflowId, 'An active workflow is required to edit this request.');
      if (!Number.isInteger(version) || version < 1) throw invalidResponse('The workflow version is invalid.');
      requireText(draft, 'The edited request cannot be empty.');
      const result = await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/draft`,
        { method: 'PATCH', body: { version, draft }, signal, timeoutMs: 130_000 },
      );
      return mapWorkflowResponse(result);
    },
    async acknowledgeReview(sessionId, workflowId, version, { signal } = {}) {
      requireText(sessionId, 'An active session is required to acknowledge this review.');
      requireText(workflowId, 'An active workflow is required to acknowledge this review.');
      if (!Number.isInteger(version) || version < 1) throw invalidResponse('The workflow version is invalid.');
      const result = await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/acknowledge`,
        { method: 'POST', body: { version }, signal },
      );
      return mapWorkflowResponse(result);
    },
    async approveWorkflow(sessionId, workflowId, version, { signal } = {}) {
      requireText(sessionId, 'An active session is required to approve this request.');
      requireText(workflowId, 'An active workflow is required to approve this request.');
      if (!Number.isInteger(version) || version < 1) throw invalidResponse('The workflow version is invalid.');
      const result = await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/approve`,
        { method: 'POST', body: { version }, signal, timeoutMs: 40_000 },
      );
      return mapApprovalResponse(result);
    },
    async createConversation({ signal } = {}) {
      const result = requireObject(await client.request('api/v1/conversations', { method: 'POST', signal }), 'The local service returned an invalid conversation.');
      requireText(result.conversation_id, 'The local service returned an invalid conversation.');
      return Object.freeze({ ...result });
    },
    async listConversations({ limit = 50, offset = 0, signal } = {}) {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      return mapConversationList(await client.request(`api/v1/conversations?${params}`, { signal }));
    },
    async getConversation(conversationId, { signal } = {}) {
      requireText(conversationId, 'A conversation is required.');
      return mapConversationDetail(await client.request(`api/v1/conversations/${encodeURIComponent(conversationId)}`, { signal }));
    },
    async deleteConversation(conversationId, { signal } = {}) {
      requireText(conversationId, 'A conversation is required.');
      const result = requireObject(await client.request(`api/v1/conversations/${encodeURIComponent(conversationId)}`, { method: 'DELETE', signal }), 'The local service returned an invalid deletion response.');
      if (result.status !== 'deleted') throw invalidResponse('The local service did not confirm conversation deletion.');
      return result;
    },
  });
}

export const privacyPalApi = createPrivacyPalApi();
