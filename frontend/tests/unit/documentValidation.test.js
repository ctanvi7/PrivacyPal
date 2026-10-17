import assert from 'node:assert/strict';
import test from 'node:test';
import {
  getDocumentValidationError,
  UNSUPPORTED_DOCUMENT_MESSAGE,
} from '../../src/lib/documentValidation.js';

test('accepts a supported MIME type when the browser provides it', () => {
  assert.equal(
    getDocumentValidationError({ name: 'scan', type: 'image/jpeg' }),
    null,
  );
});

test('accepts supported extensions when MIME type is empty', () => {
  for (const name of ['statement.pdf', 'photo.PNG', 'scan.jpeg', 'image.webp']) {
    assert.equal(getDocumentValidationError({ name, type: '' }), null, name);
  }
});

test('accepts supported file extensions if the browser reports a generic MIME type', () => {
  assert.equal(
    getDocumentValidationError({ name: 'statement.pdf', type: 'application/octet-stream' }),
    null,
  );
});

test('rejects unsupported names and MIME types with the existing message', () => {
  assert.equal(
    getDocumentValidationError({ name: 'notes.txt', type: 'text/plain' }),
    UNSUPPORTED_DOCUMENT_MESSAGE,
  );
  assert.equal(
    getDocumentValidationError({ name: 'unknown', type: '' }),
    UNSUPPORTED_DOCUMENT_MESSAGE,
  );
});

test('does not treat a cancelled file picker as an unsupported file', () => {
  assert.equal(getDocumentValidationError(null), null);
});
