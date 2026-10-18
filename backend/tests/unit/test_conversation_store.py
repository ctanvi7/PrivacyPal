from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.conversation_store import ConversationStore


def test_store_persists_across_repository_instances_and_orders_messages(tmp_path):
    path = tmp_path / "nested" / "history.sqlite3"
    first = ConversationStore(path)
    conversation = first.create()
    assert first.save_answer_pair(
        conversation["conversation_id"], "workflow-1", "Question one", "Answer one"
    )

    second = ConversationStore(path)
    loaded = second.get(conversation["conversation_id"])
    assert loaded is not None
    assert [message["role"] for message in loaded["messages"]] == ["user", "assistant"]
    assert [message["content"] for message in loaded["messages"]] == ["Question one", "Answer one"]


def test_pair_write_is_idempotent_and_conversations_are_isolated(tmp_path):
    store = ConversationStore(tmp_path / "history.sqlite3")
    first = store.create()["conversation_id"]
    second = store.create()["conversation_id"]
    assert store.save_answer_pair(first, "workflow-1", "Q", "A")
    assert not store.save_answer_pair(first, "workflow-1", "Q", "A")
    assert store.get(second)["messages"] == []


def test_retention_prunes_expired_conversation_and_messages(tmp_path):
    store = ConversationStore(tmp_path / "history.sqlite3")
    conversation_id = store.create()["conversation_id"]
    store.save_answer_pair(conversation_id, "workflow-1", "Q", "A")
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="microseconds")
    import sqlite3

    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE conversations SET updated_at = ? WHERE conversation_id = ?", (old, conversation_id))
    assert store.prune_expired() == 1
    assert store.get(conversation_id) is None


def test_recent_conversation_activity_does_not_extend_old_message_retention(tmp_path):
    store = ConversationStore(tmp_path / "history.sqlite3")
    conversation_id = store.create()["conversation_id"]
    store.save_answer_pair(conversation_id, "workflow-old", "Old question", "Old answer")
    store.save_answer_pair(conversation_id, "workflow-new", "New question", "New answer")
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(timespec="microseconds")
    import sqlite3

    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE messages SET created_at = ? WHERE conversation_id = ? AND workflow_id = ?",
            (old, conversation_id, "workflow-old"),
        )
        db.execute(
            "UPDATE messages SET created_at = ? WHERE conversation_id = ? AND workflow_id = ? AND role = 'assistant'",
            ((datetime.fromisoformat(old) + timedelta(microseconds=1)).isoformat(timespec="microseconds"), conversation_id, "workflow-old"),
        )

    loaded = store.get(conversation_id)
    assert loaded is not None
    assert [message["content"] for message in loaded["messages"]] == ["New question", "New answer"]


def test_high_risk_credentials_are_not_persisted(tmp_path):
    store = ConversationStore(tmp_path / "history.sqlite3")
    conversation_id = store.create()["conversation_id"]
    secret = "synthetic-api-key-DO_NOT_STORE-12345"

    assert not store.save_answer_pair(
        conversation_id, "workflow-1", f"What is API key: {secret}?", "Safe answer"
    )
    assert store.get(conversation_id)["messages"] == []

    assert not store.save_answer_pair(
        conversation_id, "workflow-2", "Safe question", f"API key: {secret}"
    )
    assert store.get(conversation_id)["messages"] == []


def test_pair_write_rolls_back_atomically_when_second_insert_fails(tmp_path):
    import sqlite3

    store = ConversationStore(tmp_path / "history.sqlite3")
    conversation_id = store.create()["conversation_id"]
    with sqlite3.connect(store.path) as db:
        db.execute(
            """CREATE TRIGGER reject_assistant BEFORE INSERT ON messages
               WHEN NEW.role = 'assistant' BEGIN SELECT RAISE(ABORT, 'synthetic'); END"""
        )

    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        store.save_answer_pair(conversation_id, "workflow-1", "Question", "Answer")
    assert store.get(conversation_id)["messages"] == []


def test_delete_cascades_messages(tmp_path):
    store = ConversationStore(tmp_path / "history.sqlite3")
    conversation_id = store.create()["conversation_id"]
    store.save_answer_pair(conversation_id, "workflow-1", "Q", "A")
    assert store.delete(conversation_id)
    assert store.get(conversation_id) is None
