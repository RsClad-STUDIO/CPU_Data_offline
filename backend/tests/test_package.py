"""Smoke tests for the src-layout backend package and console adapters."""
import unittest
from pathlib import Path

from cpu_data import cli
from cpu_data.application import update
from cpu_data.infrastructure import database


class PackageLayoutTests(unittest.TestCase):
    def test_package_is_loaded_from_backend_src(self):
        package_root = Path(__file__).resolve().parents[1] / "src" / "cpu_data"
        self.assertEqual(Path(cli.__file__).resolve().parent, package_root.resolve())

    def test_cli_entry_point_is_importable(self):
        self.assertTrue(callable(cli.main))

    def test_update_entry_point_is_importable(self):
        self.assertTrue(callable(update.main))

    def test_database_path_is_user_data_file(self):
        self.assertEqual(Path(database.DB_PATH).name, "cpu.db")


if __name__ == "__main__":
    unittest.main()
