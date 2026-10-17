"""Local SQLite persistence for user-visible conversation history only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.privacy.pipeline import scan_sensitive_data

RETENTION_DAYS = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ConversationStore:
    """Parameterized SQLite repository; never accepts workflow/document payloads."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path).expanduser().resolve()
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt" and (
            not parent_existed or self.path.parent.name.casefold() == "privacypal"
        ):
            self.path.parent.chmod(0o700)
        self.initialize()
        self.prune_expired()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT,
                    workflow_id TEXT NOT NULL,
                    UNIQUE(conversation_id, workflow_id, role)
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_updated
                    ON conversations(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                    ON messages(conversation_id, created_at, message_id);
                """
            )
        if os.name != "nt":
            self.path.chmod(0o600)

    def prune_expired(self, now: datetime | None = None) -> int:
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="microseconds")
        with self._connection() as db:
            # Retention is an absolute limit for each stored message. A recent
            # message must not extend the lifetime of older conversation data.
            db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
            cursor = db.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,))
            return cursor.rowcount

    def create(self) -> dict[str, str]:
        self.prune_expired()
        now = _now()
        conversation_id = str(uuid4())
        with self._connection() as db:
            db.execute(
                "INSERT INTO conversations(conversation_id, created_at, updated_at) VALUES (?, ?, ?)",
                (conversation_id, now, now),
            )
        return {"conversation_id": conversation_id, "created_at": now, "updated_at": now}

    def exists(self, conversation_id: str) -> bool:
        self.prune_expired()
        with self._connection() as db:
            return db.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone() is not None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, str | None]]:
        self.prune_expired()
        with self._connection() as db:
            rows = db.execute(
                """SELECT c.conversation_id, c.created_at, c.updated_at,
                          (SELECT substr(m.content, 1, 120) FROM messages m
                           WHERE m.conversation_id = c.conversation_id AND m.role = 'user'
                           ORDER BY m.created_at, m.message_id LIMIT 1) AS preview
                   FROM conversations c ORDER BY c.updated_at DESC, c.conversation_id
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, conversation_id: str) -> dict[str, object] | None:
        self.prune_expired()
        with self._connection() as db:
            conversation = db.execute(
                "SELECT conversation_id, created_at, updated_at FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                return None
            messages = db.execute(
                """SELECT message_id, role, content, created_at, status
                   FROM messages WHERE conversation_id = ?
                   ORDER BY created_at, message_id""",
                (conversation_id,),
            ).fetchall()
        result: dict[str, object] = dict(conversation)
        result["messages"] = [dict(row) for row in messages]
        return result

    def save_answer_pair(
        self, conversation_id: str, workflow_id: str, question: str, answer: str
    ) -> bool:
        """Atomically store a successful turn once; no drafts/findings enter this API."""
        # Avoid retaining known high-risk credentials even when the locally
        # approved draft was sanitized separately from the original question.
        try:
            if any(
                finding.action == "block"
                for value in (question, answer)
                for finding in scan_sensitive_data(value).findings
            ):
                return False
        except (TypeError, ValueError):
            return False
        self.prune_expired()
        now = _now()
        answer_at = (datetime.now(timezone.utc) + timedelta(microseconds=1)).isoformat(timespec="microseconds")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
            if exists is None:
                db.rollback()
                return False
            existing = db.execute(
                "SELECT 1 FROM messages WHERE conversation_id = ? AND workflow_id = ? LIMIT 1",
                (conversation_id, workflow_id),
            ).fetchone()
            if existing:
                db.rollback()
                return False
            db.execute(
                "INSERT INTO messages(message_id, conversation_id, role, content, created_at, status, workflow_id) VALUES (?, ?, 'user', ?, ?, 'complete', ?)",
                (str(uuid4()), conversation_id, question, now, workflow_id),
            )
            db.execute(
                "INSERT INTO messages(message_id, conversation_id, role, content, created_at, status, workflow_id) VALUES (?, ?, 'assistant', ?, ?, 'complete', ?)",
                (str(uuid4()), conversation_id, answer, answer_at, workflow_id),
            )
            db.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (answer_at, conversation_id),
            )
            db.commit()
            return True

    def delete(self, conversation_id: str) -> bool:
        self.prune_expired()
        with self._connection() as db:
            cursor = db.execute(
                "DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,)
            )
            return cursor.rowcount > 0
