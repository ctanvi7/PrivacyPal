import assert from 'node:assert/strict';
import test from 'node:test';
import { ApiError } from '../../src/lib/apiClient.js';
import { createDocumentUploadController } from '../../src/lib/documentUploadController.js';

const validFile = { name: 'statement.pdf', type: 'application/pdf', size: 1024 };

test('keeps selection separate until the injected uploader confirms success', async () => {
  const confirmed = { id: 'server-confirmed-document' };
  let receivedFile;
  const controller = createDocumentUploadController({
    uploadDocument: async file => { receivedFile = file; return confirmed; },
  });

  controller.select(validFile);
  assert.equal(controller.getState().status, 'selected');
  assert.equal(controller.getState().selectedFile, validFile);
  assert.equal(controller.getState().uploadedDocument, null);

  const result = await controller.upload();
  assert.equal(receivedFile, validFile);
  assert.equal(result, confirmed);
  assert.equal(controller.getState().status, 'uploaded');
  assert.equal(controller.getState().uploadedDocument, confirmed);
});

test('prevents duplicate uploads and returns the same in-flight operation', async () => {
  let finishUpload;
  let calls = 0;
  const controller = createDocumentUploadController({
    uploadDocument: () => {
      calls += 1;
      return new Promise(resolve => { finishUpload = resolve; });
    },
  });
  controller.select(validFile);

  const first = controller.upload();
  const second = controller.upload();
  assert.equal(first, second);
  assert.equal(calls, 0, 'injected upload starts on the next microtask');
  await Promise.resolve();
  assert.equal(calls, 1);
  finishUpload({ id: 'confirmed' });
  await first;
  assert.equal(controller.getState().status, 'uploaded');
});

test('supports retry after a recoverable server failure', async () => {
  let attempts = 0;
  const controller = createDocumentUploadController({
    uploadDocument: async () => {
      attempts += 1;
      if (attempts === 1) throw new ApiError('Upload failed safely.', { code: 'http_error', status: 503, retryable: true });
      return { id: 'confirmed-after-retry' };
    },
  });
  controller.select(validFile);

  await controller.upload();
  assert.equal(controller.getState().status, 'upload-error');
  assert.equal(controller.getState().uploadedDocument, null);
  assert.equal(controller.getState().error.retryable, true);
  await controller.retry();
  assert.equal(attempts, 2);
  assert.equal(controller.getState().status, 'uploaded');
  assert.equal(controller.getState().uploadedDocument.id, 'confirmed-after-retry');
});

test('retains unsupported-file errors without treating the file as selected or uploaded', () => {
  const controller = createDocumentUploadController();
  const state = controller.select({ name: 'notes.txt', type: 'text/plain' });
  assert.equal(state.status, 'empty');
  assert.equal(state.selectedFile, null);
  assert.equal(state.uploadedDocument, null);
  assert.equal(state.error.code, 'unsupported_file');
});

test('explains that upload is unavailable when no contract-specific uploader is injected', async () => {
  const controller = createDocumentUploadController();
  controller.select(validFile);
  await controller.upload();
  assert.equal(controller.getState().status, 'unavailable');
  assert.equal(controller.getState().selectedFile, validFile);
  assert.equal(controller.getState().uploadedDocument, null);
  assert.equal(controller.getState().error.code, 'integration_unavailable');
});

test('cancels upload and clears selected and server-confirmed state on reset', async () => {
  const controller = createDocumentUploadController({
    uploadDocument: (_file, { signal }) => new Promise((_resolve, reject) => {
      const rejectAbort = () => reject(new DOMException('Aborted', 'AbortError'));
      if (signal.aborted) rejectAbort();
      else signal.addEventListener('abort', rejectAbort, { once: true });
    }),
  });
  controller.select(validFile);
  const pending = controller.upload();
  controller.cancel();
  await pending;
  assert.equal(controller.getState().status, 'cancelled');
  assert.equal(controller.getState().uploadedDocument, null);

  controller.reset();
  assert.equal(controller.getState().status, 'empty');
  assert.equal(controller.getState().selectedFile, null);
  assert.equal(controller.getState().uploadedDocument, null);
});

test('turns timeout into a retryable upload error without claiming success', async () => {
  const controller = createDocumentUploadController({
    timeoutMs: 5,
    uploadDocument: (_file, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }),
  });
  controller.select(validFile);
  await controller.upload();
  assert.equal(controller.getState().status, 'upload-error');
  assert.equal(controller.getState().error.code, 'timeout');
  assert.equal(controller.getState().error.retryable, true);
  assert.equal(controller.getState().uploadedDocument, null);
});
