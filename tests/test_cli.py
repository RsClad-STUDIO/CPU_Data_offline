import sys
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import io

from cpu_data import cli, updater


class CLITests(unittest.TestCase):
    def test_conflicting_update_modes_are_rejected(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "--fast", "--update"]):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 2)

    def test_update_failure_returns_nonzero_exit(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "--update"]), \
             patch.object(cli, "configure_database"), \
             patch.object(updater, "run_update", side_effect=RuntimeError("source unavailable")):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 1)

    def test_explicit_update_subcommand_supports_mode(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "update", "--mode", "full"]), \
             patch.object(cli, "configure_database"), \
             patch.object(updater, "run_update") as run_update:
            cli.main()
        run_update.assert_called_once_with(fast=False)

    def test_missing_database_does_not_trigger_automatic_download(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "cpu.db"
            with patch.object(cli.database_store, "DB_PATH", missing), \
                 patch.object(updater, "run_update") as run_update, \
                 patch("sys.stdout", new_callable=io.StringIO):
                self.assertFalse(cli.ensure_db())
            run_update.assert_not_called()

    def test_help_exits_successfully(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "--help"]):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
