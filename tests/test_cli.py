import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
             patch.object(cli, "configure_database"), \
             patch.object(cli, "_run_update_in_adapter", side_effect=RuntimeError("source unavailable")):
            self.assertEqual(cli.main(), 1)

    def test_explicit_update_subcommand_supports_mode(self):
        result = SimpleNamespace(
            mode="full", status="completed", total=10, processed=10,
            succeeded=8, not_found=2, database_count=10,
        )
        with patch.object(sys, "argv", ["cpu_lookup.py", "update", "--mode", "full"]), \
             patch.object(cli, "configure_database"), \
             patch.object(cli, "_run_update_in_adapter", return_value=(result, 0)) as run_update, \
             patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(), 0)
        run_update.assert_called_once_with(fast=False)

    def test_missing_database_does_not_trigger_automatic_download(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "cpu.db"
            with patch.object(cli.database_store, "DB_PATH", missing), \
                 patch.object(cli, "_run_update_in_adapter") as run_update, \
                 patch("sys.stdout", new_callable=io.StringIO):
                self.assertFalse(cli.ensure_db())
            run_update.assert_not_called()

    def test_help_exits_successfully(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "--help"]):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)

    def test_search_json_uses_application_query_service(self):
        row = {"id": 1, "name": "Intel Core i7-13700K", "passmark_score": 46600}
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpu.db"
            db_path.touch()
            with patch.object(sys, "argv", ["cpu_lookup.py", "search", "13700K", "--format", "json"]), \
                 patch.object(cli, "configure_database"), \
                 patch.object(cli.database_store, "DB_PATH", db_path), \
                 patch.object(cli.queries, "search_cpus", return_value=[row]) as search, \
                 patch("sys.stdout", output):
                code = cli.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["items"][0]["name"], row["name"])
        search.assert_called_once_with("13700K", limit=20)

    def test_show_json_returns_not_found_envelope(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpu.db"
            db_path.touch()
            with patch.object(sys, "argv", ["cpu_lookup.py", "show", "missing", "--format", "json"]), \
                 patch.object(cli, "configure_database"), \
                 patch.object(cli.database_store, "DB_PATH", db_path), \
                 patch.object(cli.queries, "get_cpu_by_name", return_value=None), \
                 patch.object(cli.queries, "search_cpus", return_value=[]), \
                 patch("sys.stdout", output):
                code = cli.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_stats_json_returns_database_metadata(self):
        output = io.StringIO()
        stats = {"database_path": "cpu.db", "database_exists": True, "cpu_count": 3}
        with patch.object(sys, "argv", ["cpu_lookup.py", "stats", "--format", "json"]), \
             patch.object(cli, "configure_database"), \
             patch.object(cli.queries, "get_database_stats", return_value=stats), \
             patch("sys.stdout", output):
            code = cli.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"], stats)

    def test_db_verify_json_reports_integrity(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["cpu_lookup.py", "db", "verify", "--format", "json"]), \
             patch.object(cli, "configure_database"), \
             patch.object(cli.queries, "verify_database", return_value=(True, "ok")), \
             patch("sys.stdout", output):
            code = cli.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["data"]["valid"])

    def test_db_backup_json_returns_path(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "backup.db"
            with patch.object(sys, "argv", ["cpu_lookup.py", "db", "backup", str(destination), "--format", "json"]), \
                 patch.object(cli, "configure_database"), \
                 patch.object(cli.queries, "backup_database", return_value=destination), \
                 patch("sys.stdout", output):
                code = cli.main()
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["backup_path"], str(destination))

    def test_legacy_query_remains_interactive_search(self):
        with patch.object(sys, "argv", ["cpu_lookup.py", "i7-13700K"]), \
             patch.object(cli, "configure_database"), \
             patch.object(cli, "ensure_db", return_value=True), \
             patch.object(cli, "search_loop") as search_loop:
            self.assertEqual(cli.main(), 0)
        search_loop.assert_called_once_with(initial_query="i7-13700K")


if __name__ == "__main__":
    unittest.main()
