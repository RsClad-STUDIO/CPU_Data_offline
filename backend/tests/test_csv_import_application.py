import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cpu_data.application.csv_import import preview_csv_import
from cpu_data.infrastructure import database


class CSVImportApplicationTests(unittest.TestCase):
    def _create_database(self, path, names):
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE cpus (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO cpus(name) VALUES (?)",
                [(name,) for name in names],
            )

    def test_preview_uses_existing_database_read_only_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._create_database(db_path, ["Intel Core i7-13700K"])
            before = hashlib.sha256(db_path.read_bytes()).hexdigest()

            with patch.object(database, "DB_PATH", db_path):
                preview = preview_csv_import(
                    b"CPU Name,Brand\n"
                    b"Intel Core i7-13700K,Intel\n"
                    b"AMD Ryzen 7 7800X3D,AMD\n",
                    source_name="vendor-catalog",
                    retrieved_at="2026-11-24",
                    profile="vendor-csv-v1",
                )

            after = hashlib.sha256(db_path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(
                [row.status for row in preview.rows],
                ["update", "new"],
            )
            self.assertEqual(preview.source, "vendor-catalog")
            self.assertEqual(preview.retrieved_at, "2026-11-24")
            self.assertEqual(preview.profile, "vendor-csv-v1")
            self.assertEqual(
                preview.sha256,
                hashlib.sha256(
                    b"CPU Name,Brand\n"
                    b"Intel Core i7-13700K,Intel\n"
                    b"AMD Ryzen 7 7800X3D,AMD\n"
                ).hexdigest(),
            )

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.db"
            with patch.object(database, "DB_PATH", missing):
                with self.assertRaises(FileNotFoundError):
                    preview_csv_import(b"CPU Name\nIntel Core i7\n")
            self.assertFalse(missing.exists())

    def test_existing_database_without_cpu_table_fails_without_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "empty.db"
            sqlite3.connect(db_path).close()
            before = db_path.read_bytes()
            with patch.object(database, "DB_PATH", db_path):
                with self.assertRaises(sqlite3.OperationalError):
                    preview_csv_import(b"CPU Name\nIntel Core i7\n")
            self.assertEqual(db_path.read_bytes(), before)

    def test_database_connection_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._create_database(db_path, ["Intel Core i7-13700K"])
            with patch.object(database, "DB_PATH", db_path):
                connection = database.get_readonly_connection()
                try:
                    with self.assertRaises(sqlite3.OperationalError):
                        connection.execute(
                            "INSERT INTO cpus(name) VALUES ('AMD Ryzen 7')"
                        )
                finally:
                    connection.close()


if __name__ == "__main__":
    unittest.main()
