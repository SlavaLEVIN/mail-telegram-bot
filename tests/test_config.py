import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from mailbot.config import load_accounts


class AccountConfigTests(unittest.TestCase):
    def test_example_contains_expected_accounts(self) -> None:
        project = Path(__file__).parents[1]
        variables = {
            **{f"MAILRU_{index:02d}_PASSWORD": "secret" for index in range(1, 11)},
            **{f"GMAIL_{index:02d}_PASSWORD": "secret" for index in range(1, 6)},
        }
        with patch.dict(os.environ, variables, clear=False):
            accounts = load_accounts(project / "config" / "accounts.toml.example")

        self.assertEqual(len(accounts), 15)
        self.assertEqual(sum(account.provider == "mailru" for account in accounts), 10)
        self.assertEqual(sum(account.provider == "gmail" for account in accounts), 5)


if __name__ == "__main__":
    unittest.main()

