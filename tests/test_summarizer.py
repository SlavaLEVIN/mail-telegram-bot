import json
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from mailbot.models import Classification, MailMessage
from mailbot.summarizer import SummaryService, fallback_summary, sanitize_for_summary


def message(subject: str, body: str) -> MailMessage:
    return MailMessage(
        account_id="test",
        account_email="owner@example.com",
        uidvalidity="1",
        uid=1,
        message_id="id",
        sender="Teacher <teacher@example.com>",
        subject=subject,
        received_at=datetime.now(UTC),
        body=body,
        headers={},
    )


class SanitizerTests(unittest.TestCase):
    def test_removes_private_data_but_keeps_deadline(self) -> None:
        value = sanitize_for_summary(
            "Встреча 25.09.2026 в 17:00. Код подтверждения: 654321. "
            "Пишите student@example.com, +7 999 123-45-67. https://example.com/private"
        )
        self.assertIn("25.09.2026", value)
        self.assertIn("17:00", value)
        self.assertNotIn("654321", value)
        self.assertNotIn("student@example.com", value)
        self.assertNotIn("999 123", value)
        self.assertNotIn("example.com", value)

    def test_local_summary_prefers_action_and_time(self) -> None:
        mail = message(
            "Встреча по проекту",
            "Здравствуйте. Нужно прийти завтра в 17:00 в аудиторию 305. С уважением, преподаватель.",
        )
        result = fallback_summary(mail, Classification("event", 78, mail.subject, "rules"))
        self.assertIn("17:00", result)
        self.assertIn("аудиторию 305", result)


class BazaarLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_is_sanitized_and_paid_fallback_is_disabled(self) -> None:
        class FakeResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            def raise_for_status(self) -> None:
                return None

            async def json(self) -> dict:
                return {"choices": [{"message": {"content": "Встреча завтра в 17:00."}}]}

        class FakeSession:
            def __init__(self) -> None:
                self.payload = None
                self.headers = None

            def post(self, _url, *, json, headers):
                self.payload = json
                self.headers = headers
                return FakeResponse()

            async def close(self) -> None:
                return None

        service = SummaryService("bazaarlink", "test-key", "https://api.example/v1", "auto:free", 10, 2000, None)
        fake = FakeSession()
        service._session = fake
        mail = message(
            "Встреча для student@example.com",
            "Встреча 25.09.2026 в 17:00. Код подтверждения: 654321. https://example.com/a",
        )

        result = await service.summarize(mail, Classification("event", 78, mail.subject, "rules"))

        sent = json.dumps(fake.payload, ensure_ascii=False)
        self.assertEqual(result, "Встреча завтра в 17:00.")
        self.assertEqual(fake.headers["X-Free-Fallback"], "false")
        self.assertNotIn("student@example.com", sent)
        self.assertNotIn("654321", sent)
        self.assertNotIn("example.com/a", sent)
        self.assertIn("25.09.2026", sent)

    async def test_sensitive_mail_never_calls_external_api(self) -> None:
        service = SummaryService("bazaarlink", "test-key", "https://api.example/v1", "auto:free", 10, 2000, None)
        result = await service.summarize(
            message("Код", "Код подтверждения: 654321"),
            Classification("code", 98, "Получен одноразовый код. Сам код скрыт.", "rules"),
        )
        self.assertEqual(result, "Получен одноразовый код. Сам код скрыт.")
        self.assertIsNone(service._session)


if __name__ == "__main__":
    unittest.main()
