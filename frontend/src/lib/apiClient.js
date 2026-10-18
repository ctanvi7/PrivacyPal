import { CLOUD_HOSTED, processingCopy } from './deployment.js';

export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';
export const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

export const WORKFLOW_API_CONTRACT = Object.freeze({
  implemented: true,
  connected: Object.freeze([
    'session creation', 'document upload', 'local question analysis', 'draft editing',
    'warning acknowledgement', 'review cancellation', 'approval and answer delivery',
  ]),
  pending: Object.freeze([]),
});

export class ApiError extends Error {
  constructor(message, { code = 'api_error', status = 0, retryable = false, localChecks = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.retryable = retryable;
    this.localChecks = localChecks;
  }
}

function getConfiguredBaseUrl() {
  const configured = import.meta.env?.VITE_PRIVACYPAL_API_BASE_URL;
  if (configured) return configured;
  if (CLOUD_HOSTED && typeof window !== 'undefined') return window.location.origin;

  // Keep the API and UI on the same loopback hostname. This preserves the
  // session cookie's same-site behavior when Vite is opened as localhost.
  if (typeof window !== 'undefined' && window.location?.hostname === 'localhost') {
    return 'http://localhost:8000';
  }
  return DEFAULT_API_BASE_URL;
}

function messageForStatus(status) {
  if (status === 400 || status === 422) return 'The server could not accept this request. Check the information and try again.';
  if (status === 401 || status === 403) return 'The session is no longer authorized. Start a new session and try again.';
  if (status === 404) return 'The requested item is no longer available. Refresh and try again.';
  if (status === 409) return 'The workflow changed before this action completed. Refresh its status and try again.';
  if (status === 413) return 'The selected document is too large to process.';
  if (status === 415) return 'This document type is not supported by the server.';
  if (status === 429) return 'The service is busy. Wait a moment and try again.';
  if (status >= 500) return 'The local service could not complete the request. Try again later.';
  return 'The request could not be completed.';
}

function safeBackendMessage(message) {
  if (typeof message !== 'string') return null;
  const candidate = message.trim();
  if (!candidate || candidate.length > 240 || /[\r\n]|traceback|stack trace|authorization:|bearer\s|api[_ -]?key|-----BEGIN|provider response| at [\w.$]+\s*\(/i.test(candidate)) return null;
  return processingCopy(candidate);
}

async function readResponse(response) {
  if (response.status === 204) return null;

  const text = await response.text();
  if (!text) return null;

  const contentType = response.headers?.get?.('content-type') || '';
  if (!/\bjson\b/i.test(contentType)) return text;

  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError('The local service returned an unreadable response.', {
      code: 'invalid_response',
      status: response.status,
      retryable: response.status >= 500,
    });
  }
}

function isFormData(value) {
  return typeof FormData !== 'undefined' && value instanceof FormData;
}

function isBlob(value) {
  return typeof Blob !== 'undefined' && value instanceof Blob;
}

/**
 * Creates the shared transport client used by the explicit frontend API adapter.
 */
export function createApiClient({
  baseUrl = getConfiguredBaseUrl(),
  fetchImpl = globalThis.fetch,
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
} = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new TypeError('A Fetch API implementation is required.');
  }

  const normalizedBaseUrl = `${baseUrl.replace(/\/+$/, '')}/`;

  async function request(path, { method = 'GET', headers = {}, body, signal, timeoutMs: requestTimeout = timeoutMs } = {}) {
    if (typeof path !== 'string' || !path || path.startsWith('//')) {
      throw new TypeError('API paths must be non-empty relative paths.');
    }

    const url = new URL(path.replace(/^\/+/, ''), normalizedBaseUrl);
    if (url.origin !== new URL(normalizedBaseUrl).origin) {
      throw new TypeError('API requests must stay on the configured origin.');
    }

    const controller = new AbortController();
    let timedOut = false;
    const abortFromCaller = () => controller.abort();
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener('abort', abortFromCaller, { once: true });

    const timer = requestTimeout > 0
      ? setTimeout(() => { timedOut = true; controller.abort(); }, requestTimeout)
      : null;

    const requestHeaders = new Headers(headers);
    requestHeaders.set('Accept', 'application/json');
    let requestBody = body;
    if (body !== undefined && typeof body !== 'string' && !isFormData(body) && !isBlob(body)) {
      requestHeaders.set('Content-Type', 'application/json');
      requestBody = JSON.stringify(body);
    }

    try {
      const response = await fetchImpl(url, {
        method,
        headers: requestHeaders,
        body: requestBody,
        signal: controller.signal,
        credentials: 'include',
      });
      const data = await readResponse(response);
      if (!response.ok) {
        const apiError = data && typeof data === 'object' && !Array.isArray(data) ? data.error : null;
        const safeMessage = safeBackendMessage(apiError?.message) || messageForStatus(response.status);
        throw new ApiError(safeMessage, {
          localChecks: ['LOCAL_ANALYSIS_FAILED', 'MODEL_BUSY'].includes(apiError?.code) ? safeLocalChecks(apiError.local_checks) : null,
          code: typeof apiError?.code === 'string' ? apiError.code : 'http_error',
          status: response.status,
          retryable: typeof apiError?.retryable === 'boolean'
            ? apiError.retryable
            : response.status === 408 || response.status === 429 || response.status >= 500,
        });
      }
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (timedOut) {
        throw new ApiError('The request timed out. Please try again.', { code: 'timeout', retryable: true });
      }
      if (signal?.aborted) {
        throw new ApiError('The request was cancelled.', { code: 'cancelled', retryable: false });
      }
      throw new ApiError(processingCopy('The local service could not be reached. Check that it is running and try again.'), {
        code: 'network_error',
        retryable: true,
      });
    } finally {
      if (timer) clearTimeout(timer);
      signal?.removeEventListener('abort', abortFromCaller);
    }
  }

  return Object.freeze({ baseUrl: normalizedBaseUrl, request });
}

function safeLocalChecks(value) {
  if (!value || typeof value !== 'object') return null;
  const result = {};
  for (const key of ['sensitive', 'relevant', 'residual']) {
    if (!['completed', 'failed', 'pending'].includes(value[key])) return null;
    result[key] = value[key];
  }
  return result;
}
