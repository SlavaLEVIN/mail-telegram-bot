import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from mailbot.mail_client import _decode_header


class HeaderTests(unittest.TestCase):
    def test_folding_and_non_breaking_spaces_are_removed(self) -> None:
        value = _decode_header("OAuth application has been added to your\n\t\xa0account")
        self.assertEqual(value, "OAuth application has been added to your account")


if __name__ == "__main__":
    unittest.main()
