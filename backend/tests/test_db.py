import sqlite3
import shutil
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

from cpu_data.infrastructure import database as db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "cpu.db"
        self.original_path = db.DB_PATH
        db.DB_PATH = str(self.db_path)
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_upsert_updates_score_and_preserves_details(self):
        db.upsert_many([{"name": "Intel Core i7-13700K", "brand": "Intel",
                         "cores": "16", "threads": "24", "passmark_score": 44000}])
        db.upsert_many([{"name": "intel core i7-13700k", "brand": "Intel",
                         "passmark_score": 46000}])
        rows = db.search_cpus("13700K")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cores"], "16")
        self.assertEqual(rows[0]["threads"], "24")
        self.assertEqual(rows[0]["passmark_score"], 46000)

    def test_empty_batch(self):
        db.upsert_many([])
        self.assertEqual(db.count_cpus(), 0)

    def test_empty_name_is_rejected(self):
        with self.assertRaises(ValueError):
            db.upsert_cpu({"name": " "})

    def test_search_escapes_like_wildcards(self):
        db.upsert_many([{"name": "Intel Core i7-13700K"}])
        self.assertEqual(db.search_cpus("%"), [])

    def test_legacy_duplicates_are_merged_and_archived(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DROP TABLE cpus")
            conn.execute("""CREATE TABLE cpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                brand TEXT, family TEXT, cores TEXT, threads TEXT,
                base_clock TEXT, boost_clock TEXT, tdp TEXT, socket TEXT,
                process TEXT, memory_support TEXT, igpu TEXT,
                passmark_score INTEGER, source_url TEXT, updated_at TEXT)""")
            cols = ("name,brand,family,cores,threads,base_clock,boost_clock,tdp,"
                    "socket,process,memory_support,igpu,passmark_score,source_url,updated_at")
            sql = f"INSERT INTO cpus ({cols}) VALUES ({','.join('?' for _ in range(15))})"
            conn.execute(sql, ("Intel Core i7-13700K","Intel",None,"16","24",None,None,
                               "125 W","LGA1700",None,None,"UHD 770",44000,"nano","2026-01-01"))
            conn.execute(sql, ("intel core i7-13700k","Intel",None,None,None,"3.4 GHz",
                               "5.4 GHz",None,None,"10 nm",None,None,46000,"passmark","2026-02-01"))

        db.init_db()
        self.assertEqual(db.count_cpus(), 1)
        row = db.search_cpus("13700K")[0]
        self.assertEqual(row["cores"], "16")
        self.assertEqual(row["base_clock"], "3.4 GHz")
        self.assertEqual(row["process"], "10 nm")
        self.assertEqual(row["passmark_score"], 46000)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cpus_duplicate_archive").fetchone()[0], 1)

        db.init_db()
        self.assertEqual(db.count_cpus(), 1)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cpus_duplicate_archive").fetchone()[0], 1)

    def test_metadata_round_trip(self):
        db.set_meta("last_updated", "2026-11-23")
        self.assertEqual(db.get_meta("last_updated"), "2026-11-23")


    def test_verify_missing_database_does_not_create_file(self):
        self.db_path.unlink()
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "database_not_found")
        self.assertFalse(self.db_path.exists())

    def test_verify_rejects_empty_database_file_without_modifying_it(self):
        self.db_path.unlink()
        self.db_path.touch()
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "schema_missing")
        self.assertEqual(self.db_path.stat().st_size, 0)

    def test_db_exists_handles_empty_database_without_creating_tables(self):
        self.db_path.unlink()
        self.db_path.touch()
        self.assertFalse(db.db_exists())
        self.assertEqual(self.db_path.stat().st_size, 0)

    def test_backup_and_integrity_check(self):
        db.upsert_cpu({"name": "Test CPU", "passmark_score": 1234})
        backup_path = self.db_path.parent / "backup.db"
        self.assertEqual(db.backup_database(backup_path), backup_path.resolve())
        valid, result = db.verify_database()
        self.assertTrue(valid)
        self.assertEqual(result, "ok")
        with closing(sqlite3.connect(backup_path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cpus").fetchone()[0], 1)

        # Exercise the documented file-copy restore procedure on a separate DB.
        restored_path = self.db_path.parent / "restored.db"
        shutil.copy2(backup_path, restored_path)
        with closing(sqlite3.connect(restored_path)) as restored, restored:
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM cpus").fetchone()[0], 1)

        with self.assertRaises(FileExistsError):
            db.backup_database(backup_path)

    def test_legacy_database_is_backed_up_before_migration(self):
        self.db_path.unlink()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("""
                CREATE TABLE cpus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    brand TEXT, family TEXT, cores TEXT, threads TEXT,
                    base_clock TEXT, boost_clock TEXT, tdp TEXT, socket TEXT,
                    process TEXT, memory_support TEXT, igpu TEXT,
                    passmark_score INTEGER, source_url TEXT, updated_at TEXT
                )
            """)
            conn.execute(
                "INSERT INTO cpus(name, brand, passmark_score) VALUES(?,?,?)",
                ("Intel Core i5-12400", "Intel", 18000),
            )

        db.init_db()
        backups = list(self.db_path.parent.glob("cpu.db.pre-v2-*.bak"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cpus").fetchone()[0], 1)
        self.assertEqual(db.get_meta("last_migration_backup"), str(backups[0].resolve()))
        self.assertEqual(db.count_cpus(), 1)


    def test_migration_aborts_when_backup_fails(self):
        self.db_path.unlink()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "CREATE TABLE cpus (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO cpus(name) VALUES(?)", ("Preserve me",))

        with patch.object(db, "backup_database", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                db.init_db()

        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(cpus)")}
            self.assertNotIn("name_key", columns)
            self.assertEqual(
                conn.execute("SELECT name FROM cpus").fetchone()[0],
                "Preserve me",
            )


    def test_future_schema_version_is_rejected_without_migration(self):
        self.db_path.unlink()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', '3')"
            )
        with self.assertRaises(RuntimeError):
            db.init_db()
        backups = list(self.db_path.parent.glob("cpu.db.pre-v2-*.bak"))
        self.assertEqual(backups, [])


    def test_verify_rejects_missing_required_cpu_column(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DROP TABLE cpus")
            conn.execute(
                "CREATE TABLE cpus (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "name_key TEXT, passmark_score INTEGER)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX ux_cpus_name_key ON cpus(name_key)"
            )
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "schema_invalid")

    def test_verify_rejects_missing_schema_version(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DELETE FROM meta WHERE key = 'schema_version'")
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "schema_version_missing")

    def test_verify_rejects_invalid_schema_version(self):
        db.set_meta("schema_version", "not-a-number")
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "schema_version_invalid")

    def test_verify_rejects_unsupported_schema_version(self):
        db.set_meta("schema_version", str(db.SCHEMA_VERSION + 1))
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "schema_version_unsupported")

    def test_verify_rejects_missing_name_key_unique_index(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DROP INDEX ux_cpus_name_key")
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "schema_unique_index_missing")

    def test_verify_rejects_null_name_key(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO cpus(name, name_key) VALUES(?, NULL)",
                ("Invalid CPU",),
            )
        valid, result = db.verify_database()
        self.assertFalse(valid)
        self.assertEqual(result, "schema_name_key_invalid")

    def test_verify_is_read_only(self):
        db.upsert_cpu({"name": "Read-only verification CPU"})
        before = self.db_path.read_bytes()
        valid, result = db.verify_database()
        after = self.db_path.read_bytes()
        self.assertTrue(valid, result)
        self.assertEqual(before, after)


    def test_read_operations_do_not_create_missing_database(self):
        self.db_path.unlink()
        with self.assertRaises(FileNotFoundError):
            db.search_cpus("13700K")
        with self.assertRaises(FileNotFoundError):
            db.get_cpu_by_id(1)
        with self.assertRaises(FileNotFoundError):
            db.get_meta("schema_version")
        with self.assertRaises(FileNotFoundError):
            db.count_cpus()
        self.assertFalse(self.db_path.exists())

    def test_current_schema_initialization_does_not_rewrite_cpu_rows(self):
        db.upsert_many([
            {"name": "CPU A"},
            {"name": "CPU B"},
        ])
        statements = []
        original_get_connection = db.get_connection

        def traced_connection():
            connection = original_get_connection()
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(db, "get_connection", side_effect=traced_connection):
            db.init_db()

        cpu_name_key_updates = [
            sql for sql in statements
            if sql.lstrip().upper().startswith("UPDATE CPUS SET NAME_KEY")
        ]
        self.assertEqual(cpu_name_key_updates, [])

    def test_backup_failure_cleans_temporary_file_and_keeps_target_absent(self):
        destination = self.db_path.parent / "failed-backup.db"
        with patch.object(db, "_backup_to_path", side_effect=OSError("simulated disk error")):
            with self.assertRaisesRegex(OSError, "simulated disk error"):
                db.backup_database(destination)
        self.assertFalse(destination.exists())
        self.assertEqual(
            list(self.db_path.parent.glob(".failed-backup.db.*.tmp")),
            [],
        )

    def test_backup_does_not_overwrite_destination_created_during_backup(self):
        destination = self.db_path.parent / "racing-backup.db"

        def create_racing_target(_temporary, target):
            target.write_text("keep existing file", encoding="utf-8")
            raise FileExistsError(target)

        with patch.object(db.os, "link", side_effect=create_racing_target):
            with self.assertRaises(FileExistsError):
                db.backup_database(destination)
        self.assertEqual(destination.read_text(encoding="utf-8"), "keep existing file")
        self.assertEqual(
            list(self.db_path.parent.glob(".racing-backup.db.*.tmp")),
            [],
        )


if __name__ == "__main__":
    unittest.main()
