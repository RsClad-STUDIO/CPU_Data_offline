"""End-to-end SQLite migration and recovery dry-run using disposable data only.

This script creates a synthetic legacy database inside a temporary directory,
runs the real migration and backup code against it, restores a copied backup,
and compares integrity and records. It never opens the configured application DB.

Run from the repository root after installing the project:
    python scripts/check_database_recovery.py
"""
from __future__ import annotations

from contextlib import closing
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import db


def create_legacy_database(path: Path) -> None:
    """Create a representative pre-v2 database with duplicate CPU names."""
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE cpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, brand TEXT, family TEXT, cores TEXT,
                threads TEXT, base_clock TEXT, boost_clock TEXT, tdp TEXT,
                socket TEXT, process TEXT, memory_support TEXT, igpu TEXT,
                passmark_score INTEGER, source_url TEXT, updated_at TEXT
            )
            """
        )
        columns = (
            "name, brand, family, cores, threads, base_clock, boost_clock, "
            "tdp, socket, process, memory_support, igpu, passmark_score, "
            "source_url, updated_at"
        )
        placeholders = ", ".join("?" for _ in range(15))
        conn.executemany(
            f"INSERT INTO cpus ({columns}) VALUES ({placeholders})",
            [
                (
                    "Intel Core i7-13700K", "Intel", None, "16", "24",
                    None, None, "125 W", "LGA1700", None, None, "UHD 770",
                    44000, "nanoreview", "2026-01-01T00:00:00+00:00",
                ),
                (
                    "intel core i7-13700k", "Intel", None, None, None,
                    "3.4 GHz", "5.4 GHz", None, None, "10 nm", None, None,
                    46000, "passmark", "2026-02-01T00:00:00+00:00",
                ),
                (
                    "AMD Ryzen 7 7800X3D", "AMD", "Raphael", "8", "16",
                    "4.2 GHz", "5.0 GHz", "120 W", "AM5", "5 nm", "DDR5",
                    None, 35000, "passmark", "2026-02-01T00:00:00+00:00",
                ),
            ],
        )


def inspect_database(path: Path) -> dict[str, object]:
    with closing(sqlite3.connect(path)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(cpus)")}
        count = conn.execute("SELECT COUNT(*) FROM cpus").fetchone()[0]
        version_row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        archive_count = (
            conn.execute("SELECT COUNT(*) FROM cpus_duplicate_archive").fetchone()[0]
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='cpus_duplicate_archive'"
            ).fetchone()
            else 0
        )
        rows = conn.execute(
            "SELECT name, cores, threads, base_clock, boost_clock, "
            "passmark_score FROM cpus ORDER BY name"
        ).fetchall()
    return {
        "integrity": integrity,
        "columns": columns,
        "count": count,
        "schema_version": version_row[0] if version_row else None,
        "archive_count": archive_count,
        "rows": rows,
    }


def main() -> int:
    original_db_path = db.DB_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="cpu-data-recovery-dry-run-") as temp:
            work = Path(temp)
            isolated_db = work / "legacy-cpu.db"
            create_legacy_database(isolated_db)

            # Redirect the real DB implementation to this disposable fixture.
            db.DB_PATH = str(isolated_db)
            db.init_db()

            migrated = inspect_database(isolated_db)
            assert migrated["integrity"] == "ok", migrated
            assert migrated["schema_version"] == str(db.SCHEMA_VERSION), migrated
            assert migrated["count"] == 2, migrated
            assert migrated["archive_count"] == 1, migrated
            assert "name_key" in migrated["columns"], migrated

            merged = next(
                row for row in migrated["rows"]
                if row[0].casefold() == "intel core i7-13700k"
            )
            assert merged[1] == "16" and merged[2] == "24", merged
            assert merged[3] == "3.4 GHz" and merged[4] == "5.4 GHz", merged
            assert merged[5] == 46000, merged

            auto_backups = list(work.glob("legacy-cpu.db.pre-v2-*.bak"))
            assert len(auto_backups) == 1, auto_backups
            auto_backup = inspect_database(auto_backups[0])
            assert auto_backup["integrity"] == "ok", auto_backup
            assert auto_backup["count"] == 3, auto_backup
            assert "name_key" not in auto_backup["columns"], auto_backup

            manual_backup = work / "manual-backup.db"
            db.backup_database(manual_backup)
            restored = work / "restored-cpu.db"
            shutil.copy2(manual_backup, restored)

            restored_state = inspect_database(restored)
            assert restored_state == migrated, (
                "Restored DB differs from migrated source",
                restored_state,
                migrated,
            )

            valid, detail = db.verify_database()
            assert valid and detail == "ok", detail

            print("PASS: isolated legacy DB migration")
            print("PASS: duplicate merge and archive preservation")
            print("PASS: automatic pre-migration backup contains original rows")
            print("PASS: manual backup and file-copy restore")
            print("PASS: integrity_check and restored record comparison")
            print("PASS: configured application database was not accessed")
            print(f"Result: {migrated['count']} migrated CPUs, "
                  f"{migrated['archive_count']} archived duplicate")
            return 0
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        db.DB_PATH = original_db_path


if __name__ == "__main__":
    raise SystemExit(main())
