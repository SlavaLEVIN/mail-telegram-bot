import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from mailbot.bot import parse_digest_time


class ScheduleTests(unittest.TestCase):
    def test_normalizes_exact_time(self) -> None:
        self.assertEqual(parse_digest_time("8:05"), "08:05")

    def test_rejects_invalid_time(self) -> None:
        for value in ("24:00", "12:60", "утром", "12"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_digest_time(value)


if __name__ == "__main__":
    unittest.main()
