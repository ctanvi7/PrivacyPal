import assert from 'node:assert/strict';
import test from 'node:test';
import { createConversationHistoryController, groupConversationsByLocalDate } from '../../src/lib/conversationHistory.js';
import { ApiError } from '../../src/lib/apiClient.js';

const item = (id, updated_at = '2026-10-17T08:00:00Z') => ({ conversation_id: id, created_at: updated_at, updated_at, preview: `Question ${id}` });

test('loads saved history and models an empty history without demo entries', async () => {
  const controller = createConversationHistoryController({ api: { listConversations: async () => ({ items: [item('one')], limit: 100, offset: 0 }) } });
  await controller.load();
  assert.equal(controller.getState().status, 'ready');
  assert.deepEqual(controller.getState().items.map(row => row.conversation_id), ['one']);
  const empty = createConversationHistoryController({ api: { listConversations: async () => ({ items: [], limit: 100, offset: 0 }) } });
  await empty.load();
  assert.deepEqual(empty.getState().items, []);
});

test('recovers after a history load failure', async () => {
  let fail = true;
  const controller = createConversationHistoryController({ api: { listConversations: async () => {
    if (fail) throw new ApiError('History unavailable.', { code: 'history_error', status: 503 });
    return { items: [item('ok')], limit: 100, offset: 0 };
  } } });
  await controller.load();
  assert.equal(controller.getState().status, 'error');
  fail = false;
  await controller.refresh();
  assert.equal(controller.getState().items[0].conversation_id, 'ok');
});

test('shares an in-flight list request instead of issuing duplicates', async () => {
  let calls = 0;
  let finish;
  const controller = createConversationHistoryController({ api: { listConversations: () => {
    calls += 1;
    return new Promise(resolve => { finish = resolve; });
  } } });
  const first = controller.load();
  const second = controller.load();
  assert.equal(calls, 1);
  finish({ items: [], limit: 100, offset: 0 });
  await Promise.all([first, second]);
  assert.equal(controller.getState().status, 'ready');
});

test('groups backend timestamps by local calendar date and retains older conversations', () => {
  const now = new Date(2026, 9, 17, 13);
  const atLocalDate = (daysAgo) => new Date(2026, 9, 17 - daysAgo, 12).toISOString();
  const groups = groupConversationsByLocalDate([
    item('today', atLocalDate(0)), item('week', atLocalDate(7)), item('old', atLocalDate(8)),
  ], now);
  assert.deepEqual(groups.today.map(row => row.conversation_id), ['today']);
  assert.deepEqual(groups.previous7Days.map(row => row.conversation_id), ['week']);
  assert.deepEqual(groups.older.map(row => row.conversation_id), ['old']);
});

test('opens messages in backend chronological order and ignores a late response after switching', async () => {
  let resolveFirst;
  const api = { getConversation: id => id === 'first'
    ? new Promise(resolve => { resolveFirst = resolve; })
    : Promise.resolve({ conversation_id: 'second', created_at: '', updated_at: '', messages: [{ message_id: 'm1', role: 'user', content: 'Question', created_at: '1', status: 'complete' }, { message_id: 'm2', role: 'assistant', content: 'Answer', created_at: '2', status: 'complete' }] }) };
  const controller = createConversationHistoryController({ api });
  const first = controller.open('first');
  await controller.open('second');
  assert.equal(controller.getState().detail.messages[0].message_id, 'm1');
  resolveFirst({ conversation_id: 'first', messages: [] });
  await first;
  assert.equal(controller.getState().selectedId, 'second');
  assert.equal(controller.getState().detail.conversation_id, 'second');
});

test('deletes only after backend confirmation and keeps the item on failure', async () => {
  let fail = true;
  const seeded = createConversationHistoryController({ api: {
    listConversations: async () => ({ items: [item('one')], limit: 100, offset: 0 }),
    deleteConversation: async () => { if (fail) throw new ApiError('Delete failed.', { code: 'delete_error', status: 503 }); return { status: 'deleted' }; },
  } });
  await seeded.load();
  assert.equal(await seeded.remove('one'), false);
  assert.equal(seeded.getState().items.length, 1);
  fail = false;
  assert.equal(await seeded.remove('one'), true);
  assert.equal(seeded.getState().items.length, 0);
});

test('clears a selected saved transcript only after confirmed deletion', async () => {
  const controller = createConversationHistoryController({ api: {
    listConversations: async () => ({ items: [item('one')], limit: 100, offset: 0 }),
    getConversation: async () => ({ conversation_id: 'one', created_at: 'x', updated_at: 'x', messages: [] }),
    deleteConversation: async () => ({ status: 'deleted' }),
  } });
  await controller.load();
  await controller.open('one');
  await controller.remove('one');
  assert.equal(controller.getState().selectedId, null);
  assert.equal(controller.getState().detail, null);
  assert.equal(controller.getState().items.length, 0);
});

test('creates a genuine empty conversation without inventing messages', async () => {
  let created = 0;
  const controller = createConversationHistoryController({ api: {
    createConversation: async () => { created += 1; return { conversation_id: 'new', created_at: 'now', updated_at: 'now' }; },
  } });
  const [a, b] = await Promise.all([controller.create(), controller.create()]);
  assert.equal(created, 1);
  assert.equal(a.conversation_id, b.conversation_id);
  assert.equal(controller.getState().detail.messages.length, 0);
});

test('refreshes history after an answer and does not imply saved content when history_saved is false', async () => {
  let lists = 0;
  let details = 0;
  const controller = createConversationHistoryController({ api: {
    listConversations: async () => { lists += 1; return { items: [item('c1')], limit: 100, offset: 0 }; },
    getConversation: async () => { details += 1; return { conversation_id: 'c1', created_at: 'x', updated_at: 'x', messages: [] }; },
  } });
  assert.equal(await controller.refreshAfterAnswer('c1', { history_saved: false }), false);
  assert.equal(lists, 1);
  assert.equal(details, 0);
  assert.equal(controller.getState().detail, null);
  assert.equal(await controller.refreshAfterAnswer('c1', { history_saved: true }), true);
  assert.equal(lists, 2);
  assert.equal(details, 1);
  assert.equal(controller.getState().detail.conversation_id, 'c1');
});

test('answer refresh does not switch away from a conversation selected while the list request is pending', async () => {
  let finishList;
  const controller = createConversationHistoryController({ api: {
    listConversations: () => new Promise(resolve => { finishList = resolve; }),
    getConversation: async id => ({ conversation_id: id, created_at: 'x', updated_at: 'x', messages: [] }),
  } });
  await controller.open('answer-conversation');

  const refresh = controller.refreshAfterAnswer('answer-conversation', { history_saved: true });
  await controller.open('user-selected-conversation');
  finishList({ items: [item('answer-conversation'), item('user-selected-conversation')], limit: 100, offset: 0 });
  await refresh;

  assert.equal(controller.getState().selectedId, 'user-selected-conversation');
  assert.equal(controller.getState().detail.conversation_id, 'user-selected-conversation');
});
