import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import db


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


    def test_backup_and_integrity_check(self):
        db.upsert_cpu({"name": "Test CPU", "passmark_score": 1234})
        backup_path = self.db_path.parent / "backup.db"
        self.assertEqual(db.backup_database(backup_path), backup_path.resolve())
        valid, result = db.verify_database()
        self.assertTrue(valid)
        self.assertEqual(result, "ok")
        with closing(sqlite3.connect(backup_path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cpus").fetchone()[0], 1)
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


if __name__ == "__main__":
    unittest.main()
