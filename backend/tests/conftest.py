from __future__ import annotations

import pytest

from app.conversation_store import ConversationStore
from app.main import app


@pytest.fixture(autouse=True)
def isolated_conversation_database(tmp_path, monkeypatch):
    """Keep API tests isolated from the real per-user history database."""
    store = ConversationStore(tmp_path / "test-history.sqlite3")
    monkeypatch.setattr(app.state, "conversation_store", store)
    return store
