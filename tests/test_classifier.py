import os
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from mailbot.classifier import RuleClassifier, sanitize_for_ai
from mailbot.models import MailMessage


def message(subject: str, body: str, headers: dict[str, str] | None = None) -> MailMessage:
    return MailMessage(
        account_id="test",
        account_email="test@example.com",
        uidvalidity="1",
        uid=1,
        message_id="id",
        sender="Sender <sender@example.com>",
        subject=subject,
        received_at=datetime.now(UTC),
        body=body,
        headers=headers or {},
    )


class SanitizerTests(unittest.TestCase):
    def test_removes_codes_urls_and_secret_lines(self) -> None:
        value = sanitize_for_ai("Код: 123456\nPassword: hunter2\nhttps://example.com/reset?t=abc")
        self.assertNotIn("123456", value)
        self.assertNotIn("hunter2", value)
        self.assertNotIn("example.com", value)


class RuleClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = RuleClassifier((), ())

    def test_detects_one_time_code(self) -> None:
        result = self.classifier.classify(message("Код подтверждения", "Ваш код подтверждения: 654321"))
        self.assertEqual(result.category, "code")
        self.assertGreaterEqual(result.importance, 90)
        self.assertNotIn("654321", result.summary)

    def test_newsletter_header_has_low_priority(self) -> None:
        result = self.classifier.classify(
            message("Новая коллекция", "Посмотрите наши товары", {"list-unsubscribe": "<url>"})
        )
        self.assertEqual(result.category, "newsletter")
        self.assertLess(result.importance, 20)

    def test_study_message_is_important(self) -> None:
        result = self.classifier.classify(message("Лабораторная работа", "Дедлайн перенесён на пятницу"))
        self.assertEqual(result.category, "deadline")
        self.assertGreaterEqual(result.importance, 70)

    def test_meeting_is_an_important_event(self) -> None:
        result = self.classifier.classify(message("Встреча завтра в 17:00", "Встреча завтра в 17:00 в Москве"))
        self.assertEqual(result.category, "event")
        self.assertGreaterEqual(result.importance, 70)

    def test_github_oauth_change_is_security(self) -> None:
        result = self.classifier.classify(
            message("[GitHub] A third-party OAuth application has been added to your account", "Review access")
        )
        self.assertEqual(result.category, "security")
        self.assertGreaterEqual(result.importance, 90)

    def test_work_content_beats_newsletter_header(self) -> None:
        result = self.classifier.classify(
            message(
                "Data Science Bootcamp / Результаты отбора",
                "Результаты отбора на стажировку",
                {"list-unsubscribe": "<url>"},
            )
        )
        self.assertEqual(result.category, "work")
        self.assertGreaterEqual(result.importance, 70)


if __name__ == "__main__":
    unittest.main()
