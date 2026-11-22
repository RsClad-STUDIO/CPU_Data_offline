import sys
import unittest
from unittest.mock import patch

from cpu_data import cli, updater


class CLITests(unittest.TestCase):
    def test_conflicting_update_modes_are_rejected(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "--fast", "--update"]):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 2)

    def test_update_failure_returns_nonzero_exit(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "--update"]), \
             patch.object(updater, "run_update", side_effect=RuntimeError("source unavailable")):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 1)

    def test_help_exits_successfully(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "--help"]):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
