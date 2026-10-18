import { CLOUD_HOSTED } from './deployment.js';

const SUPPORTED_MIME_TYPES = new Set([
  'application/pdf',
  'image/png',
  'image/jpeg',
  'image/webp',
]);

const SUPPORTED_EXTENSIONS = new Set(['pdf', 'png', 'jpg', 'jpeg', 'webp']);

export const UNSUPPORTED_DOCUMENT_MESSAGE =
  'Unsupported file. Choose a PDF, PNG, JPEG, or WebP image.';

/**
 * Returns a user-facing validation message, or null for an accepted file.
 * A missing candidate represents a cancelled file picker and is not an error.
 */
export function getDocumentValidationError(file) {
  if (!file) return null;
  if (CLOUD_HOSTED && file.size > 4 * 1024 * 1024) return 'AWS demo uploads are limited to 4 MiB.';

  const name = typeof file.name === 'string' ? file.name : '';
  const extension = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
  const mimeType = typeof file.type === 'string' ? file.type.toLowerCase() : '';

  if (SUPPORTED_MIME_TYPES.has(mimeType) || SUPPORTED_EXTENSIONS.has(extension)) {
    return null;
  }

  return UNSUPPORTED_DOCUMENT_MESSAGE;
}
