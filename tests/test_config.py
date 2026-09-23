import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from mailbot.config import load_accounts


class AccountConfigTests(unittest.TestCase):
    def test_example_contains_one_mailru_account(self) -> None:
        project = Path(__file__).parents[1]
        variables = {"MAILRU_01_PASSWORD": "secret"}
        with patch.dict(os.environ, variables, clear=False):
            accounts = load_accounts(project / "config" / "accounts.toml.example")

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].provider, "mailru")


if __name__ == "__main__":
    unittest.main()
