import unittest
from pathlib import Path

import db
import updater
import cpu_lookup
from cpu_data import database, updater as packaged_updater, cli
from cpu_data.cli import main as cli_main


class PackageCompatibilityTests(unittest.TestCase):
    def test_legacy_module_names_are_true_module_aliases(self):
        self.assertIs(db, database)
        self.assertIs(updater, packaged_updater)

    def test_default_database_path_uses_user_data_directory(self):
        self.assertEqual(Path(database.DB_PATH).name, "cpu.db")
        self.assertNotEqual(Path(database.DB_PATH).parent, Path(__file__).resolve().parents[1] / "data")

    def test_cli_entry_point_is_importable(self):
        self.assertTrue(callable(cli_main))
        self.assertIs(cpu_lookup, cli)
        self.assertIs(cpu_lookup.main, cli_main)

    def test_update_console_entry_point_is_importable(self):
        self.assertTrue(callable(packaged_updater.main))


if __name__ == "__main__":
    unittest.main()
