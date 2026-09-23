import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from mailbot.database import Database
from mailbot.models import Classification, MailMessage


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        await self.database.open()

    async def asyncTearDown(self) -> None:
        await self.database.close()
        self.temp_dir.cleanup()

    async def test_message_is_deduplicated_and_notification_is_tracked(self) -> None:
        message = MailMessage(
            account_id="gmail-01",
            account_email="user@gmail.com",
            uidvalidity="42",
            uid=7,
            message_id="message-id",
            sender="sender@example.com",
            subject="Test",
            received_at=datetime.now(UTC),
            body="Body",
            headers={},
        )
        result = Classification("personal", 80, "Summary", "rules")

        self.assertTrue(await self.database.add_message(message, result))
        self.assertFalse(await self.database.add_message(message, result))
        self.assertFalse(await self.database.is_notified("gmail-01", "42", 7))

        await self.database.mark_notified("gmail-01", "42", 7)
        self.assertTrue(await self.database.is_notified("gmail-01", "42", 7))

        message_id = await self.database.get_message_id("gmail-01", "42", 7)
        self.assertIsNotNone(message_id)
        await self.database.set_category(message_id, "work")
        await self.database.set_importance(message_id, 90)
        stored = await self.database.get_message(message_id)
        self.assertEqual(stored.category, "work")
        self.assertEqual(stored.importance, 90)


if __name__ == "__main__":
    unittest.main()
