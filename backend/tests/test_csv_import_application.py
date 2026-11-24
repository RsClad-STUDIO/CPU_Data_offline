import hashlib
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cpu_data.application.csv_import import apply_csv_import, preview_csv_import
from cpu_data.infrastructure import database


class CSVImportApplicationTests(unittest.TestCase):
    def _create_database(self, path, names):
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE cpus (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO cpus(name) VALUES (?)",
                [(name,) for name in names],
            )
            connection.commit()
        finally:
            connection.close()

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
            self.assertEqual(preview.source_name, "vendor-catalog")
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

    def _initialize_database(self, path, records=()):
        with patch.object(database, "DB_PATH", str(path)):
            database.init_db()
            if records:
                database.upsert_many(list(records))

    def _preview(self, path, csv_bytes):
        with patch.object(database, "DB_PATH", path):
            return preview_csv_import(csv_bytes)

    def test_apply_adds_new_cpu_updates_existing_and_explicitly_clears_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._initialize_database(db_path, [{
                "name": "Intel Core i7-13700K",
                "brand": "Intel",
                "cores": "16",
                "threads": "24",
                "passmark_score": 40000,
            }])
            preview = self._preview(
                db_path,
                b"CPU Name,Brand,Cores,Threads,PassMark Score\n"
                b"Intel Core i7-13700K,,__CLEAR__,32,45000\n"
                b"AMD Ryzen 7 7800X3D,AMD,8,16,30000\n",
            )

            result = apply_csv_import(preview, database_path=db_path)

            self.assertEqual((result.inserted, result.updated, result.unchanged), (1, 1, 0))
            with closing(sqlite3.connect(db_path)) as connection, connection:
                rows = {
                    row[0]: row[1:]
                    for row in connection.execute(
                        "SELECT name, brand, cores, threads, passmark_score FROM cpus"
                    )
                }
            self.assertEqual(
                rows["Intel Core i7-13700K"],
                ("Intel", None, "32", 45000),
            )
            self.assertEqual(
                rows["AMD Ryzen 7 7800X3D"],
                ("AMD", "8", "16", 30000),
            )

    def test_batch_failure_rolls_back_prior_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._initialize_database(db_path, [{
                "name": "CPU A",
                "brand": "Original A",
            }])
            preview = self._preview(
                db_path,
                b"CPU Name,Brand\nCPU A,Changed A\nCPU B,Vendor B\n",
            )
            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.execute("""
                    CREATE TRIGGER reject_cpu_b BEFORE INSERT ON cpus
                    WHEN NEW.name = 'CPU B'
                    BEGIN SELECT RAISE(ABORT, 'simulated insert failure'); END
                """)

            with self.assertRaisesRegex(sqlite3.IntegrityError, "simulated insert failure"):
                apply_csv_import(preview, database_path=db_path)

            with closing(sqlite3.connect(db_path)) as connection, connection:
                rows = connection.execute(
                    "SELECT name, brand FROM cpus ORDER BY name"
                ).fetchall()
                self.assertEqual([tuple(row) for row in rows], [("CPU A", "Original A")])

    def test_reimporting_same_csv_is_idempotent_after_a_fresh_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._initialize_database(db_path)
            csv_bytes = b"CPU Name,Brand,Cores\nCPU A,Vendor A,8\n"

            first_preview = self._preview(db_path, csv_bytes)
            first_result = apply_csv_import(first_preview, database_path=db_path)
            with closing(sqlite3.connect(db_path)) as connection, connection:
                first_updated_at = connection.execute(
                    "SELECT updated_at FROM cpus WHERE name = 'CPU A'"
                ).fetchone()[0]

            second_preview = self._preview(db_path, csv_bytes)
            self.assertEqual(second_preview.rows[0].status, "update")
            second_result = apply_csv_import(second_preview, database_path=db_path)

            self.assertEqual((first_result.inserted, first_result.updated), (1, 0))
            self.assertEqual(
                (second_result.inserted, second_result.updated, second_result.unchanged),
                (0, 0, 1),
            )
            with closing(sqlite3.connect(db_path)) as connection, connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM cpus").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT updated_at FROM cpus WHERE name = 'CPU A'"
                    ).fetchone()[0],
                    first_updated_at,
                )

    def test_invalid_preview_is_rejected_without_database_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._initialize_database(db_path)
            preview = self._preview(
                db_path,
                b"CPU Name,Brand\nCPU A,Vendor A\nCPU A,Vendor B\n",
            )
            before = hashlib.sha256(db_path.read_bytes()).hexdigest()

            with self.assertRaisesRegex(ValueError, "ambiguous or invalid"):
                apply_csv_import(preview, database_path=db_path)

            self.assertEqual(
                hashlib.sha256(db_path.read_bytes()).hexdigest(),
                before,
            )

    def test_stale_preview_rolls_back_rows_inserted_earlier_in_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._initialize_database(db_path)
            preview = self._preview(
                db_path,
                b"CPU Name,Brand\nCPU A,Vendor A\nCPU B,Vendor B\n",
            )
            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.execute(
                    "INSERT INTO cpus(name, name_key) VALUES(?, ?)",
                    ("CPU B", "cpu b"),
                )

            with self.assertRaisesRegex(ValueError, "preview is stale"):
                apply_csv_import(preview, database_path=db_path)

            with closing(sqlite3.connect(db_path)) as connection, connection:
                names = [
                    row[0]
                    for row in connection.execute("SELECT name FROM cpus ORDER BY name")
                ]
            self.assertEqual(names, ["CPU B"])

    def test_missing_write_target_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.db"
            from cpu_data.infrastructure.importers.csv_mapper import preview_csv
            preview = preview_csv(b"CPU Name\nCPU A\n")

            with self.assertRaises(FileNotFoundError):
                apply_csv_import(preview, database_path=missing)
            self.assertFalse(missing.exists())

    def test_configured_application_database_is_never_a_write_target(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cpus.db"
            self._initialize_database(db_path)
            from cpu_data.infrastructure.importers.csv_mapper import preview_csv
            preview = preview_csv(b"CPU Name,Brand\nCPU A,Vendor A\n")
            before = hashlib.sha256(db_path.read_bytes()).hexdigest()

            with patch.object(database, "DB_PATH", str(db_path)):
                with self.assertRaisesRegex(ValueError, "configured application database"):
                    apply_csv_import(preview, database_path=db_path)

            self.assertEqual(
                hashlib.sha256(db_path.read_bytes()).hexdigest(),
                before,
            )

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
