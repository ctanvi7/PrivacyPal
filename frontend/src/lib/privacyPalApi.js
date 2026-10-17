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
  return Object.freeze({ ...response });
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
      !Array.isArray(response.pages_used)) {
    throw invalidResponse('The local service returned an invalid privacy analysis response.');
  }
  return Object.freeze({ ...response });
}

/** Contract-specific session, PDF upload, and local-analysis API. */
export function createPrivacyPalApi({ client = createApiClient() } = {}) {
  return Object.freeze({
    async createSession({ signal } = {}) {
      return mapSessionResponse(await client.request('api/v1/sessions', { method: 'POST', signal }));
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
  });
}

export const privacyPalApi = createPrivacyPalApi();
