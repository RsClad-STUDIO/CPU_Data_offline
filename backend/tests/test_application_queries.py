import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cpu_data.application import queries
from cpu_data.infrastructure import database


class ApplicationQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "missing" / "cpu.db"
        self.patch = patch.object(database, "DB_PATH", self.db_path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def create_database(self):
        database.init_db()
        database.upsert_cpu({
            "name": "Intel Core i7-13700K",
            "brand": "Intel",
            "passmark_score": 46600,
        })

    def test_search_rejects_empty_query(self):
        with self.assertRaises(ValueError):
            queries.search_cpus("  ")

    def test_search_returns_cpu_records(self):
        self.create_database()
        rows = queries.search_cpus("13700K")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Intel Core i7-13700K")

    def test_get_cpu_by_id_and_exact_name(self):
        self.create_database()
        by_id = queries.get_cpu_by_id(1)
        by_name = queries.get_cpu_by_name("intel core i7-13700k")
        self.assertEqual(by_id["name"], "Intel Core i7-13700K")
        self.assertEqual(by_name["name"], "Intel Core i7-13700K")
        self.assertIsNone(queries.get_cpu_by_name("Intel Core i5-13600K"))

    def test_stats_returns_metadata_without_formatting(self):
        self.create_database()
        stats = queries.get_database_stats()
        self.assertTrue(stats["database_exists"])
        self.assertEqual(stats["cpu_count"], 1)
        self.assertEqual(stats["schema_version"], database.SCHEMA_VERSION)
        self.assertIn("database_path", stats)

    def test_verify_missing_database_does_not_create_file(self):
        valid, message = queries.verify_database()
        self.assertFalse(valid)
        self.assertEqual(message, "database_not_found")
        self.assertFalse(self.db_path.exists())

    def test_verify_and_backup_existing_database(self):
        self.create_database()
        valid, message = queries.verify_database()
        self.assertTrue(valid)
        self.assertEqual(message, "ok")
        backup = queries.backup_database(self.root / "backup.db")
        self.assertTrue(backup.is_file())


    def test_read_queries_do_not_create_missing_database_or_parent_directory(self):
        with self.assertRaises(FileNotFoundError):
            queries.search_cpus("13700K")
        with self.assertRaises(FileNotFoundError):
            queries.get_cpu_by_id(1)
        with self.assertRaises(FileNotFoundError):
            queries.get_cpu_by_name("Intel Core i7-13700K")
        self.assertTrue(self.root.exists())
        self.assertFalse(self.db_path.exists())
        self.assertFalse(self.db_path.parent.exists())

if __name__ == "__main__":
    unittest.main()
