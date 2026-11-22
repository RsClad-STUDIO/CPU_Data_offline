"""SQLite persistence layer for CPU records; public functions remain CLI-compatible."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import re
from pathlib import Path
import sqlite3
import unicodedata

from ..config import SETTINGS

PROJECT_ROOT = os.fspath(SETTINGS.project_root)
DB_PATH = SETTINGS.db_path
CPU_COLUMNS = (
    "name", "brand", "family", "cores", "threads", "base_clock",
    "boost_clock", "tdp", "socket", "process", "memory_support",
    "igpu", "passmark_score", "source_url", "updated_at",
)
INSERT_COLUMNS = (
    "name", "name_key", "brand", "family", "cores", "threads",
    "base_clock", "boost_clock", "tdp", "socket", "process",
    "memory_support", "igpu", "passmark_score", "source_url", "updated_at",
)


def normalize_cpu_name(name: str) -> str:
    """Normalize an exact model name for case-insensitive uniqueness."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("CPU name must be a non-empty string")
    value = unicodedata.normalize("NFKC", name)
    return re.sub(r"\s+", " ", value).strip().casefold()


def get_connection() -> sqlite3.Connection:
    """Create a configured connection. Internal callers close it in _connection."""
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def _connection():
    conn = get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _create_archive(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cpus_duplicate_archive (
            archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_id INTEGER NOT NULL, archived_at TEXT NOT NULL,
            name TEXT NOT NULL, name_key TEXT, brand TEXT, family TEXT,
            cores TEXT, threads TEXT, base_clock TEXT, boost_clock TEXT,
            tdp TEXT, socket TEXT, process TEXT, memory_support TEXT,
            igpu TEXT, passmark_score INTEGER, source_url TEXT, updated_at TEXT
        )
    """)


def _timestamp_key(value):
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _completeness(row):
    count = sum(row[c] not in (None, "") for c in CPU_COLUMNS if c != "updated_at")
    return count, _timestamp_key(row["updated_at"]), -int(row["id"])


def _merge(rows):
    ordered = sorted(rows, key=_completeness, reverse=True)
    merged = {c: ordered[0][c] for c in CPU_COLUMNS}
    for row in ordered[1:]:
        for column in CPU_COLUMNS:
            if column != "updated_at" and merged[column] in (None, ""):
                if row[column] not in (None, ""):
                    merged[column] = row[column]
    scored = [r for r in rows if r["passmark_score"] is not None]
    if scored:
        newest = max(scored, key=lambda r: (_timestamp_key(r["updated_at"]), -int(r["id"])))
        merged["passmark_score"] = newest["passmark_score"]
    dates = [r["updated_at"] for r in rows if r["updated_at"]]
    if dates:
        merged["updated_at"] = max(dates, key=_timestamp_key)
    return merged


def _migrate_name_key(conn):
    if "name_key" not in _columns(conn, "cpus"):
        conn.execute("ALTER TABLE cpus ADD COLUMN name_key TEXT")
    rows = conn.execute("SELECT * FROM cpus ORDER BY id").fetchall()
    for row in rows:
        key = normalize_cpu_name(row["name"]) if row["name"] and row["name"].strip() else f"__legacy_id__:{row['id']}"
        conn.execute("UPDATE cpus SET name_key = ? WHERE id = ?", (key, row["id"]))

    duplicates = conn.execute("""
        SELECT name_key FROM cpus GROUP BY name_key HAVING COUNT(*) > 1
    """).fetchall()
    _create_archive(conn)
    archive_columns = (
        "original_id", "archived_at", "name", "name_key", "brand", "family",
        "cores", "threads", "base_clock", "boost_clock", "tdp", "socket",
        "process", "memory_support", "igpu", "passmark_score", "source_url", "updated_at",
    )
    archive_sql = (
        f"INSERT INTO cpus_duplicate_archive ({', '.join(archive_columns)}) "
        f"VALUES ({', '.join('?' for _ in archive_columns)})"
    )
    for item in duplicates:
        group = conn.execute(
            "SELECT * FROM cpus WHERE name_key = ? ORDER BY id",
            (item["name_key"],),
        ).fetchall()
        merged = _merge(group)
        survivor = max(group, key=_completeness)["id"]
        archived_at = datetime.now(timezone.utc).isoformat()
        for row in group:
            if row["id"] == survivor:
                continue
            conn.execute(archive_sql, (
                row["id"], archived_at, row["name"], row["name_key"], row["brand"],
                row["family"], row["cores"], row["threads"], row["base_clock"],
                row["boost_clock"], row["tdp"], row["socket"], row["process"],
                row["memory_support"], row["igpu"], row["passmark_score"],
                row["source_url"], row["updated_at"],
            ))
            conn.execute("DELETE FROM cpus WHERE id = ?", (row["id"],))
        conn.execute(
            "UPDATE cpus SET " + ", ".join(f"{c} = ?" for c in CPU_COLUMNS) + " WHERE id = ?",
            tuple(merged[c] for c in CPU_COLUMNS) + (survivor,),
        )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_cpus_name_key ON cpus(name_key)")


def backup_database(destination) -> Path:
    """Create a consistent SQLite backup without overwriting an existing file."""
    target = Path(destination).expanduser().resolve()
    source_path = Path(DB_PATH).expanduser().resolve()
    if target == source_path:
        raise ValueError("Backup destination must differ from the active database")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)

    with _connection() as source:
        destination_connection = sqlite3.connect(target)
        try:
            source.backup(destination_connection)
        finally:
            destination_connection.close()
    return target


def verify_database() -> tuple[bool, str]:
    """Run SQLite's integrity_check and return (is_valid, result_text)."""
    with _connection() as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    return result == "ok", result


def _read_schema_version():
    path = Path(DB_PATH)
    if not path.exists():
        return None
    with sqlite3.connect(path) as conn:
        has_meta = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        if not has_meta:
            return None
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None


def _backup_before_schema_upgrade():
    path = Path(DB_PATH)
    if not path.exists():
        return None
    version = _read_schema_version()
    if version is not None and version >= 2:
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = path.with_name(f"{path.name}.pre-v2-{timestamp}.bak")
    return backup_database(destination)


def init_db():
    """Create tables and apply an idempotent, data-preserving migration."""
    migration_backup = _backup_before_schema_upgrade()
    with _connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cpus (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                brand TEXT, family TEXT, cores TEXT, threads TEXT,
                base_clock TEXT, boost_clock TEXT, tdp TEXT, socket TEXT,
                process TEXT, memory_support TEXT, igpu TEXT,
                passmark_score INTEGER, source_url TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON cpus(name)")
        _migrate_name_key(conn)
        conn.execute("""
            INSERT INTO meta(key, value) VALUES('schema_version', '2')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """)
        if migration_backup is not None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('last_migration_backup', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(migration_backup),),
            )


def search_cpus(query: str, limit: int = 20):
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with _connection() as conn:
        return conn.execute("""
            SELECT * FROM cpus
            WHERE name LIKE ? ESCAPE '\\'
            ORDER BY CASE WHEN name LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END,
                     passmark_score IS NULL ASC, passmark_score DESC
            LIMIT ?
        """, (f"%{escaped}%", f"{escaped}%", limit)).fetchall()


def get_cpu_by_id(cpu_id: int):
    with _connection() as conn:
        return conn.execute("SELECT * FROM cpus WHERE id = ?", (cpu_id,)).fetchone()


def _prepare(data):
    if not isinstance(data, dict):
        raise TypeError("CPU record must be a dictionary")
    name = data.get("name")
    record = {c: data.get(c) for c in INSERT_COLUMNS}
    record["name"] = name.strip() if isinstance(name, str) else name
    record["name_key"] = normalize_cpu_name(name)
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    return record


def _upsert_sql():
    cols = ", ".join(INSERT_COLUMNS)
    values = ", ".join(f":{c}" for c in INSERT_COLUMNS)
    updates = [
        f"{c} = COALESCE(excluded.{c}, cpus.{c})"
        for c in INSERT_COLUMNS if c not in ("name_key", "updated_at")
    ]
    updates.append("updated_at = excluded.updated_at")
    return f"INSERT INTO cpus ({cols}) VALUES ({values}) ON CONFLICT(name_key) DO UPDATE SET " + ", ".join(updates)


def upsert_cpu(data: dict):
    with _connection() as conn:
        conn.execute(_upsert_sql(), _prepare(data))


def upsert_many(records: list):
    if not records:
        return
    prepared = [_prepare(record) for record in records]
    with _connection() as conn:
        conn.executemany(_upsert_sql(), prepared)


def set_meta(key: str, value: str):
    with _connection() as conn:
        conn.execute("""
            INSERT INTO meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))


def get_meta(key: str):
    with _connection() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def count_cpus() -> int:
    with _connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM cpus").fetchone()[0]


def db_exists() -> bool:
    return os.path.exists(DB_PATH) and count_cpus() > 0
