import { ApiError } from './apiClient.js';

function initialState() {
  return { status: 'loading', items: [], selectedId: null, detail: null, detailStatus: 'empty', error: null, detailError: null, deletingId: null, creating: false, offset: 0, hasMore: false };
}

function safeMessage(error, fallback) {
  return error instanceof ApiError && typeof error.message === 'string' ? error.message : fallback;
}

/** Local-calendar grouping for backend ISO timestamps; older items remain visible under Older. */
export function groupConversationsByLocalDate(items, now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const cutoff = new Date(today);
  cutoff.setDate(cutoff.getDate() - 7);
  const groups = { today: [], previous7Days: [], older: [] };
  for (const item of items) {
    const parsed = new Date(item.updated_at);
    if (Number.isNaN(parsed.getTime())) {
      groups.older.push(item);
      continue;
    }
    const localDate = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
    if (localDate.getTime() === today.getTime()) groups.today.push(item);
    else if (localDate < today && localDate >= cutoff) groups.previous7Days.push(item);
    else groups.older.push(item);
  }
  return groups;
}

/** Owns list/detail request sequencing so late history responses cannot change current selection. */
export function createConversationHistoryController({ api, pageSize = 100 } = {}) {
  if (!api) throw new TypeError('A conversation history API is required.');
  let state = initialState();
  let listSequence = 0;
  let detailSequence = 0;
  let selectionEpoch = 0;
  let createOperation = null;
  let deleteOperations = new Map();
  let listOperations = new Map();
  const listeners = new Set();

  function publish(next) {
    state = next;
    listeners.forEach(listener => listener(state));
    return state;
  }

  function load({ append = false } = {}) {
    const offset = append ? state.offset : 0;
    if (listOperations.has(offset)) return listOperations.get(offset);
    const requestId = ++listSequence;
    // Advancing this request sequence would invalidate another distinct page, so a
    // page request only supersedes the same offset after it has settled.
    const effectiveRequestId = requestId;
    publish({ ...state, status: state.items.length ? state.status : 'loading', error: null });
    const operation = (async () => {
      try {
        const response = await api.listConversations({ limit: pageSize, offset });
        if (effectiveRequestId !== listSequence) return state;
        const items = append ? [...state.items, ...response.items] : response.items;
        return publish({ ...state, status: 'ready', items, offset: response.offset + response.items.length,
          hasMore: response.items.length === response.limit, error: null });
      } catch (error) {
        if (effectiveRequestId !== listSequence) return state;
        return publish({ ...state, status: 'error', error: safeMessage(error, 'Conversation history could not be loaded.') });
      }
    })();
    listOperations.set(offset, operation);
    operation.finally(() => { if (listOperations.get(offset) === operation) listOperations.delete(offset); });
    return operation;
  }

  async function open(conversationId) {
    const requestId = ++detailSequence;
    selectionEpoch += 1;
    publish({ ...state, selectedId: conversationId, detail: null, detailStatus: 'loading', detailError: null });
    try {
      const detail = await api.getConversation(conversationId);
      if (requestId !== detailSequence || state.selectedId !== conversationId) return state;
      return publish({ ...state, selectedId: conversationId, detail, detailStatus: 'ready', detailError: null });
    } catch (error) {
      if (requestId !== detailSequence || state.selectedId !== conversationId) return state;
      const notFound = error?.status === 404;
      const next = publish({ ...state, detail: null, detailStatus: 'error', detailError: safeMessage(error, 'This conversation could not be loaded.') });
      if (notFound) void load();
      return next;
    }
  }

  function clearSelection() {
    detailSequence += 1;
    selectionEpoch += 1;
    return publish({ ...state, selectedId: null, detail: null, detailStatus: 'empty', detailError: null });
  }

  function create() {
    if (createOperation) return createOperation;
    const createEpoch = selectionEpoch;
    const operation = Promise.resolve().then(() => api.createConversation()).then(created => {
      listSequence += 1;
      listOperations.clear();
      const item = { ...created, preview: null };
      const items = [item, ...state.items.filter(existing => existing.conversation_id !== created.conversation_id)];
      const shouldSelect = selectionEpoch === createEpoch;
      if (shouldSelect) { selectionEpoch += 1; detailSequence += 1; }
      publish({ ...state, status: 'ready', items,
        selectedId: shouldSelect ? created.conversation_id : state.selectedId,
        detail: shouldSelect ? { ...created, messages: [] } : state.detail,
        detailStatus: shouldSelect ? 'ready' : state.detailStatus, detailError: shouldSelect ? null : state.detailError, creating: false });
      if (typeof api.listConversations === 'function') void load();
      return created;
    }).catch(error => {
      publish({ ...state, creating: false, error: safeMessage(error, 'A new conversation could not be created.') });
      throw error;
    }).finally(() => { createOperation = null; });
    createOperation = operation;
    publish({ ...state, creating: true, error: null });
    return operation;
  }

  function remove(conversationId) {
    if (deleteOperations.has(conversationId)) return deleteOperations.get(conversationId);
    publish({ ...state, deletingId: conversationId, error: null });
    const operation = Promise.resolve().then(() => api.deleteConversation(conversationId)).then(() => {
      listSequence += 1;
      listOperations.clear();
      const wasSelected = state.selectedId === conversationId;
      if (wasSelected) { detailSequence += 1; selectionEpoch += 1; }
      publish({ ...state, items: state.items.filter(item => item.conversation_id !== conversationId),
        selectedId: wasSelected ? null : state.selectedId, detail: wasSelected ? null : state.detail,
        detailStatus: wasSelected ? 'empty' : state.detailStatus, deletingId: null, error: null });
      return true;
    }).catch(error => {
      publish({ ...state, deletingId: null, error: safeMessage(error, 'The conversation could not be deleted.') });
      if (error?.status === 404) void load();
      return false;
    }).finally(() => deleteOperations.delete(conversationId));
    deleteOperations.set(conversationId, operation);
    return operation;
  }

  async function refreshAfterAnswer(conversationId, result) {
    const refreshSelectionEpoch = selectionEpoch;
    await load();
    if (result?.history_saved !== true) return false;
    // A completed answer may arrive while the user is viewing another saved
    // conversation. Refresh the list, but never change their current selection.
    if (conversationId && selectionEpoch === refreshSelectionEpoch &&
        (!state.selectedId || state.selectedId === conversationId)) await open(conversationId);
    return true;
  }

  return Object.freeze({
    getState: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    load,
    loadMore: () => state.hasMore ? load({ append: true }) : Promise.resolve(state),
    open,
    clearSelection,
    create,
    remove,
    refresh: () => load(),
    refreshAfterAnswer,
  });
}
