import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cpu_data import database_location as location


def make_database(path: Path, rows=("Intel Core i7-13700K",)):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("CREATE TABLE cpus (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO meta VALUES ('schema_version', '2')")
            conn.executemany("INSERT INTO cpus(name) VALUES (?)", [(name,) for name in rows])


class DatabaseLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.new_dir = self.root / "new"
        self.old_dir = self.root / "old"
        self.new_db = self.new_dir / "cpu.db"
        self.old_db = self.old_dir / "cpu.db"
        self.settings_file = self.root / "config" / "settings.json"
        self.settings = SimpleNamespace(db_path=self.new_db)
        self.patches = [
            patch.object(location, "SETTINGS", self.settings),
            patch.object(location, "SETTINGS_FILE", self.settings_file),
            patch.object(location, "LEGACY_DB_PATH", self.old_db),
            patch.dict("os.environ", {}, clear=False),
        ]
        for item in self.patches:
            item.start()
        self.env_patch = patch.dict("os.environ", {"CPU_DATA_HOME": ""})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_migration_uses_sqlite_backup_and_preserves_source(self):
        make_database(self.old_db)
        result = location.migrate_database(self.old_db, self.new_db)
        self.assertEqual(result, self.new_db.resolve())
        self.assertTrue(self.old_db.exists())
        self.assertEqual(location._validate_database(self.new_db), (2, 1))

    def test_migration_refuses_to_overwrite_destination(self):
        make_database(self.old_db)
        make_database(self.new_db, ("Existing destination",))
        with self.assertRaises(FileExistsError):
            location.migrate_database(self.old_db, self.new_db)
        self.assertEqual(location._validate_database(self.new_db), (2, 1))

    def test_declining_migration_selects_and_persists_legacy_path(self):
        make_database(self.old_db)
        with patch("builtins.input", return_value="2"):
            selected = location.resolve_database_path(interactive=True)
        self.assertEqual(selected, self.old_db.resolve())
        saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["database_path"], str(self.old_db.resolve()))

    def test_accepting_migration_copies_and_selects_new_path(self):
        make_database(self.old_db)
        with patch("builtins.input", return_value="1"):
            selected = location.resolve_database_path(interactive=True)
        self.assertEqual(selected, self.new_db.resolve())
        self.assertTrue(self.old_db.exists())
        self.assertEqual(location._validate_database(self.new_db), (2, 1))

    def test_both_databases_require_an_explicit_choice(self):
        make_database(self.old_db)
        make_database(self.new_db, ("New CPU",))
        with patch("builtins.input", return_value="2"):
            selected = location.resolve_database_path(interactive=True)
        self.assertEqual(selected, self.old_db.resolve())

    def test_noninteractive_legacy_selection_fails_without_modifying_databases(self):
        make_database(self.old_db)
        with self.assertRaises(location.DatabaseSelectionRequired):
            location.resolve_database_path(interactive=False)
        self.assertTrue(self.old_db.exists())
        self.assertFalse(self.new_db.exists())

    def test_cpu_data_home_overrides_cli_and_saved_locations(self):
        custom = self.root / "explicit"
        with patch.dict("os.environ", {"CPU_DATA_HOME": str(self.root / "environment")}):
            selected = location.resolve_database_path(str(custom), interactive=False)
        self.assertEqual(selected, (self.root / "environment" / "cpu.db").resolve())
        self.assertFalse(self.settings_file.exists())

    def test_future_schema_is_rejected_without_creating_destination(self):
        make_database(self.old_db)
        with closing(sqlite3.connect(self.old_db)) as conn:
            with conn:
                conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        with self.assertRaises(RuntimeError):
            location.migrate_database(self.old_db, self.new_db)
        self.assertTrue(self.old_db.exists())
        self.assertFalse(self.new_db.exists())

    def test_explicit_directory_is_persisted(self):
        custom = self.root / "custom"
        selected = location.resolve_database_path(str(custom), interactive=False)
        self.assertEqual(selected, (custom / "cpu.db").resolve())
        saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["database_path"], str(selected))


if __name__ == "__main__":
    unittest.main()
