import { ApiError, createApiClient } from './apiClient.js';
import { CLOUD_HOSTED } from './deployment.js';

// Combined inspection/detection, a separate audit, and at most one repair audit.
// CPU-hosted checks allow three 180-second calls plus orchestration time.
// Local checks retain the three 120-second call budget.
export const PRIVACY_ANALYSIS_TIMEOUT_MS = CLOUD_HOSTED ? 600_000 : 390_000;

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

export function mapProviderList(value) {
  const response = requireObject(value, 'The local service returned invalid answer providers.');
  if (!Array.isArray(response.items)) throw invalidResponse('The local service returned invalid answer providers.');
  return Object.freeze({ items: response.items.map(item => {
    requireObject(item, 'The local service returned an invalid answer provider.');
    requireText(item.id, 'The local service returned an invalid answer provider.');
    requireText(item.name, 'The local service returned an invalid answer provider.');
    if (item.configured !== true) throw invalidResponse('The local service returned an unconfigured answer provider.');
    return Object.freeze({ ...item });
  }) });
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

/** Validates the answer returned after a successful, backend-enforced approval. */
export function mapApprovedWorkflowResponse(value) {
  const response = requireObject(value, 'The local service returned an invalid approved response.');
  requireText(response.workflow_id, 'The local service returned an invalid approved response.');
  requireText(response.answer, 'The local service returned an invalid approved response.');
  requireText(response.send_state, 'The local service returned an invalid approved response.');
  if (!Number.isInteger(response.version) || response.send_state !== 'sent' ||
      (response.history_saved !== undefined && typeof response.history_saved !== 'boolean') || !Array.isArray(response.pages_used) ||
      !response.provider || typeof response.provider !== 'object' || Array.isArray(response.provider)) {
    throw invalidResponse('The local service returned an invalid approved response.');
  }
  return Object.freeze({ ...response });
}

export const mapApprovalResponse = mapApprovedWorkflowResponse;

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
    async listProviders({ signal } = {}) {
      return mapProviderList(await client.request('api/v1/providers', { signal }));
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
    async removeDocument(sessionId, documentId, { signal } = {}) {
      requireText(sessionId, 'An active session is required before removing a document.');
      requireText(documentId, 'A document is required before it can be removed.');
      const result = requireObject(await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/documents/${encodeURIComponent(documentId)}`,
        { method: 'DELETE', signal },
      ), 'The local service returned an invalid document removal response.');
      if (result.status !== 'removed') throw invalidResponse('The local service returned an invalid document removal response.');
      return Object.freeze({ ...result });
    },
    async clearSession(sessionId, { signal } = {}) {
      requireText(sessionId, 'An active session is required before starting a new chat.');
      const result = requireObject(await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/clear`,
        { method: 'POST', signal },
      ), 'The local service returned an invalid session clear response.');
      if (result.status !== 'cleared') throw invalidResponse('The local service did not confirm that the session was cleared.');
      return Object.freeze({ ...result });
    },
    async submitQuestion(sessionId, documentId, question, { signal, providerId } = {}) {
      requireText(sessionId, 'An active session is required before asking a question.');
      requireText(documentId, 'A server-confirmed document is required before asking a question.');
      requireText(question, 'Enter a question about your document.');
      const result = await client.request(`api/v1/sessions/${encodeURIComponent(sessionId)}/questions`, {
        method: 'POST',
        body: { document_id: documentId, question, ...(providerId ? { provider_id: providerId } : {}) },
        signal,
        timeoutMs: PRIVACY_ANALYSIS_TIMEOUT_MS,
      });
      return mapWorkflowResponse(result);
    },
    async translateDraft(sessionId, workflowId, version, sourceLanguage, targetLanguage, { signal } = {}) {
      requireText(sessionId, 'An active session is required to translate this request.');
      requireText(workflowId, 'An active workflow is required to translate this request.');
      if (!Number.isInteger(version) || version < 1) throw invalidResponse('The review version is invalid.');
      const result = requireObject(await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/translate-draft`,
        { method: 'POST', body: { version, source_language: sourceLanguage, target_language: targetLanguage, consent: true }, signal, timeoutMs: 60_000 },
      ), 'The local service returned an invalid translation.');
      requireText(result.translated_text, 'The local service returned an invalid translation.');
      requireText(result.target_language, 'The local service returned an invalid translation.');
      if (result.workflow_id !== workflowId || result.version !== version || result.target_language !== targetLanguage) throw invalidResponse('The translation belongs to a different review.');
      return Object.freeze({ ...result });
    },
    async translateAnswer(sessionId, text, sourceLanguage, targetLanguage, { signal } = {}) {
      requireText(sessionId, 'An active session is required for answer translation.');
      requireText(text, 'A displayed answer is required.');
      const result = requireObject(await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/translate-answer`,
        { method: 'POST', body: { text, source_language: sourceLanguage, target_language: targetLanguage, consent: true }, signal, timeoutMs: 60_000 },
      ), 'The local service returned an invalid translation.');
      requireText(result.translated_text, 'The local service returned an invalid translation.');
      return Object.freeze({ ...result });
    },
    async transcribeAudio(sessionId, file, { signal } = {}) {
      requireText(sessionId, 'An active session is required for transcription.');
      if (!file || !file.size) throw new TypeError('A nonempty audio recording is required.');
      const form = new FormData();
      form.append('file', file, file.name);
      form.append('consent', 'true');
      const result = requireObject(await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/speech/transcribe`,
        { method: 'POST', body: form, signal, timeoutMs: 90_000 },
      ), 'The local service returned an invalid transcript.');
      requireText(result.transcript, 'The local service returned an invalid transcript.');
      if (result.review_required !== true || result.transcript.length > 2000) throw invalidResponse('The transcript requires review before use.');
      return Object.freeze({ ...result });
    },
    async synthesizeSpeech(sessionId, text, language, { signal } = {}) {
      requireText(sessionId, 'An active session is required for speech.');
      requireText(text, 'A displayed answer is required.');
      const result = requireObject(await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/speech/synthesize`,
        { method: 'POST', body: { consent: true, text, language }, signal, timeoutMs: 60_000 },
      ), 'The local service returned invalid speech audio.');
      requireText(result.audio_base64, 'The local service returned invalid speech audio.');
      if (result.content_type !== 'audio/wav' || !/^[A-Za-z0-9+/]+={0,2}$/.test(result.audio_base64)) throw invalidResponse('The local service returned invalid speech audio.');
      return Object.freeze({ ...result });
    },
    async editWorkflowDraft(sessionId, workflowId, version, draft, { signal } = {}) {
      requireText(sessionId, 'An active session is required before editing a review.');
      requireText(workflowId, 'An active review is required before editing a draft.');
      if (!Number.isInteger(version) || version < 1) throw new TypeError('A current review version is required.');
      requireText(draft, 'The reviewed request cannot be empty.');
      const result = await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/draft`,
        { method: 'PATCH', body: { version, draft }, signal, timeoutMs: 135_000 },
      );
      return mapWorkflowResponse(result);
    },
    async acknowledgeWorkflow(sessionId, workflowId, version, { signal } = {}) {
      requireText(sessionId, 'An active session is required before acknowledging a review.');
      requireText(workflowId, 'An active review is required before acknowledging it.');
      if (!Number.isInteger(version) || version < 1) throw new TypeError('A current review version is required.');
      const result = await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/acknowledge`,
        { method: 'POST', body: { version }, signal },
      );
      return mapWorkflowResponse(result);
    },
    async approveWorkflow(sessionId, workflowId, version, { signal } = {}) {
      requireText(sessionId, 'An active session is required before approving a review.');
      requireText(workflowId, 'An active review is required before approving it.');
      if (!Number.isInteger(version) || version < 1) throw new TypeError('A current review version is required.');
      const result = await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/approve`,
        { method: 'POST', body: { version, restore_placeholders: false }, signal, timeoutMs: 35_000 },
      );
      return mapApprovedWorkflowResponse(result);
    },
    async cancelWorkflow(sessionId, workflowId, { signal } = {}) {
      requireText(sessionId, 'An active session is required before cancelling a review.');
      requireText(workflowId, 'An active review is required before cancelling it.');
      const result = requireObject(await client.request(
        `api/v1/sessions/${encodeURIComponent(sessionId)}/workflows/${encodeURIComponent(workflowId)}/cancel`,
        { method: 'POST', signal },
      ), 'The local service returned an invalid cancellation response.');
      if (result.status !== 'cancelled') throw invalidResponse('The local service returned an invalid cancellation response.');
      return Object.freeze({ ...result });
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
    async updateDraft(...args) { return this.editWorkflowDraft(...args); },
    async acknowledgeReview(...args) { return this.acknowledgeWorkflow(...args); },
  });
}

export const privacyPalApi = createPrivacyPalApi();
