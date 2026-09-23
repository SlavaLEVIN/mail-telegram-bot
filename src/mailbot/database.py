from pathlib import Path

import aiosqlite

from mailbot.models import Classification, MailMessage, StoredMessage


SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    account_id TEXT PRIMARY KEY,
    uidvalidity TEXT NOT NULL,
    last_uid INTEGER NOT NULL,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    account_id TEXT NOT NULL,
    account_email TEXT NOT NULL,
    uidvalidity TEXT NOT NULL,
    uid INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TEXT NOT NULL,
    category TEXT NOT NULL,
    importance INTEGER NOT NULL,
    summary TEXT NOT NULL,
    classifier_source TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, uidvalidity, uid)
);

CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages(received_at);
CREATE INDEX IF NOT EXISTS idx_messages_importance ON messages(importance DESC);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self._path = path
        self._connection: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self._path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("База данных не открыта")
        return self._connection

    async def get_sync_state(self, account_id: str) -> tuple[str, int] | None:
        cursor = await self.connection.execute(
            "SELECT uidvalidity, last_uid FROM sync_state WHERE account_id = ?",
            (account_id,),
        )
        row = await cursor.fetchone()
        return (row["uidvalidity"], row["last_uid"]) if row else None

    async def set_sync_state(self, account_id: str, uidvalidity: str, last_uid: int) -> None:
        await self.connection.execute(
            """
            INSERT INTO sync_state(account_id, uidvalidity, last_uid, last_error, updated_at)
            VALUES (?, ?, ?, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(account_id) DO UPDATE SET
                uidvalidity = excluded.uidvalidity,
                last_uid = excluded.last_uid,
                last_error = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (account_id, uidvalidity, last_uid),
        )
        await self.connection.commit()

    async def set_sync_error(self, account_id: str, error: str) -> None:
        state = await self.get_sync_state(account_id)
        uidvalidity, last_uid = state or ("unknown", 0)
        await self.connection.execute(
            """
            INSERT INTO sync_state(account_id, uidvalidity, last_uid, last_error, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(account_id) DO UPDATE SET
                last_error = excluded.last_error,
                updated_at = CURRENT_TIMESTAMP
            """,
            (account_id, uidvalidity, last_uid, error[:500]),
        )
        await self.connection.commit()

    async def add_message(self, message: MailMessage, result: Classification) -> bool:
        cursor = await self.connection.execute(
            """
            INSERT OR IGNORE INTO messages(
                account_id, account_email, uidvalidity, uid, message_id, sender,
                subject, received_at, category, importance, summary, classifier_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.account_id,
                message.account_email,
                message.uidvalidity,
                message.uid,
                message.message_id,
                message.sender,
                message.subject,
                message.received_at.isoformat(),
                result.category,
                result.importance,
                result.summary,
                result.source,
            ),
        )
        await self.connection.commit()
        return cursor.rowcount == 1

    async def mark_notified(self, account_id: str, uidvalidity: str, uid: int) -> None:
        await self.connection.execute(
            "UPDATE messages SET notified = 1 WHERE account_id = ? AND uidvalidity = ? AND uid = ?",
            (account_id, uidvalidity, uid),
        )
        await self.connection.commit()

    async def is_notified(self, account_id: str, uidvalidity: str, uid: int) -> bool:
        cursor = await self.connection.execute(
            "SELECT notified FROM messages WHERE account_id = ? AND uidvalidity = ? AND uid = ?",
            (account_id, uidvalidity, uid),
        )
        row = await cursor.fetchone()
        return bool(row and row["notified"])

    async def get_message_id(self, account_id: str, uidvalidity: str, uid: int) -> int | None:
        cursor = await self.connection.execute(
            "SELECT rowid AS id FROM messages WHERE account_id = ? AND uidvalidity = ? AND uid = ?",
            (account_id, uidvalidity, uid),
        )
        row = await cursor.fetchone()
        return int(row["id"]) if row else None

    @staticmethod
    def _stored_message(row: aiosqlite.Row) -> StoredMessage:
        from datetime import datetime

        def clean(value: str) -> str:
            return " ".join(value.replace("\xa0", " ").split())

        return StoredMessage(
            id=row["id"],
            account_id=row["account_id"],
            account_email=row["account_email"],
            sender=clean(row["sender"]),
            subject=clean(row["subject"]),
            received_at=datetime.fromisoformat(row["received_at"]),
            category=row["category"],
            importance=row["importance"],
            summary=clean(row["summary"]),
        )

    async def list_messages(
        self,
        since_iso: str,
        limit: int = 6,
        offset: int = 0,
        category: str | None = None,
        minimum_importance: int | None = None,
    ) -> tuple[list[StoredMessage], int]:
        filters = ["received_at >= ?"]
        parameters: list[object] = [since_iso]
        if category:
            filters.append("category = ?")
            parameters.append(category)
        if minimum_importance is not None:
            filters.append("importance >= ?")
            parameters.append(minimum_importance)
        where = " AND ".join(filters)

        count_cursor = await self.connection.execute(
            f"SELECT COUNT(*) AS total FROM messages WHERE {where}",
            parameters,
        )
        count_row = await count_cursor.fetchone()

        cursor = await self.connection.execute(
            f"""
            SELECT rowid AS id, account_id, account_email, sender, subject,
                   received_at, category, importance, summary
            FROM messages
            WHERE {where}
            ORDER BY importance DESC, received_at DESC
            LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        )
        rows = await cursor.fetchall()
        return [self._stored_message(row) for row in rows], int(count_row["total"])

    async def recent_messages(self, since_iso: str, limit: int = 100) -> list[StoredMessage]:
        messages, _ = await self.list_messages(since_iso, limit=limit)
        return messages

    async def get_message(self, message_id: int) -> StoredMessage | None:
        cursor = await self.connection.execute(
            """
            SELECT rowid AS id, account_id, account_email, sender, subject,
                   received_at, category, importance, summary
            FROM messages WHERE rowid = ?
            """,
            (message_id,),
        )
        row = await cursor.fetchone()
        return self._stored_message(row) if row else None

    async def set_category(self, message_id: int, category: str) -> None:
        await self.connection.execute(
            "UPDATE messages SET category = ?, classifier_source = 'user' WHERE rowid = ?",
            (category, message_id),
        )
        await self.connection.commit()

    async def set_importance(self, message_id: int, importance: int) -> None:
        await self.connection.execute(
            "UPDATE messages SET importance = ?, classifier_source = 'user' WHERE rowid = ?",
            (max(0, min(100, importance)), message_id),
        )
        await self.connection.commit()

    async def sync_status(self) -> list[dict[str, object]]:
        cursor = await self.connection.execute(
            "SELECT account_id, last_uid, last_error, updated_at FROM sync_state ORDER BY account_id"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_app_state(self, key: str) -> str | None:
        cursor = await self.connection.execute("SELECT value FROM app_state WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_app_state(self, key: str, value: str) -> None:
        await self.connection.execute(
            "INSERT INTO app_state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.connection.commit()
