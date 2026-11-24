"""CSV import preview and isolated transactional application use cases."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Mapping

from ..domain.cpu import CPURecord
from ..domain.identity import normalize_cpu_name
from ..infrastructure import database
from ..infrastructure.importers.csv_mapper import CSVPreview, preview_csv


def preview_csv_import(
    source: str | Path | bytes | bytearray,
    *,
    encoding: str | None = None,
    delimiter: str = ",",
    column_mapping: Mapping[str, str] | None = None,
    source_name: str | None = None,
    retrieved_at: str | None = None,
    profile: str | None = None,
) -> CSVPreview:
    """Preview a CSV against existing CPU names using a read-only DB connection.

    The database must already exist and contain the current CPU table. This
    function never initializes, migrates, or writes to the database. Provenance
    values are caller-supplied; retrieved_at is not inferred from local time.
    """
    with closing(database.get_readonly_connection()) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cpus'"
        ).fetchone()
        if table_exists is None:
            # Preserve the historical sqlite3.OperationalError contract for
            # databases that exist but have not been initialized.
            connection.execute("SELECT name FROM cpus LIMIT 0")

        available_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(cpus)")
        }
        # Preview historically supports minimal CPU tables containing only
        # id/name. Capture a stale-write fingerprint only when the complete
        # application schema is present; apply_csv_import independently
        # validates that full schema before any write.
        fingerprint_fields = {"id", *_IMPORT_FIELDS, "updated_at"}
        can_fingerprint = fingerprint_fields.issubset(available_columns)
        selected_columns = [
            field for field in ("id", *_IMPORT_FIELDS, "updated_at")
            if field in available_columns
        ]
        if "name" not in selected_columns:
            raise sqlite3.DatabaseError("CPU table is missing the required name column")
        existing_records = connection.execute(
            "SELECT " + ", ".join(selected_columns) + " FROM cpus ORDER BY id"
        ).fetchall()

    preview = preview_csv(
        source,
        existing_records=existing_records,
        encoding=encoding,
        delimiter=delimiter,
        column_mapping=column_mapping,
        source_name=source_name,
        retrieved_at=retrieved_at,
        profile=profile,
    )
    existing_by_key = {
        normalize_cpu_name(record["name"]): record
        for record in existing_records
    }
    rows = tuple(
        replace(
            row,
            expected_existing_sha256=(
                _existing_record_fingerprint(
                    existing_by_key[normalize_cpu_name(row.record.name)]
                )
                if can_fingerprint
                else None
            ),
        )
        if row.status == "update" and row.record is not None
        else row
        for row in preview.rows
    )
    return replace(preview, rows=rows)



# The write path requires an explicit database path. It never falls back to
# SETTINGS/DB_PATH and never initializes or migrates the target database.
@dataclass(frozen=True, slots=True)
class CSVImportResult:
    inserted: int
    updated: int
    unchanged: int


_IMPORT_FIELDS = tuple(CPURecord.__dataclass_fields__)
_CLEARABLE_FIELDS = frozenset(_IMPORT_FIELDS) - {"name"}


def _existing_record_fingerprint(record: Mapping[str, object]) -> str:
    fields = ("id", *_IMPORT_FIELDS, "updated_at")
    snapshot = {field: record[field] for field in fields}
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _open_existing_import_database(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path).expanduser().resolve()
    configured_path = Path(database.DB_PATH).expanduser().resolve()
    if path == configured_path:
        raise ValueError("CSV import writes are disabled for the configured application database")
    temporary_root = Path(tempfile.gettempdir()).resolve()
    try:
        common_path = os.path.commonpath((str(path), str(temporary_root)))
    except ValueError as error:
        raise ValueError(
            "CSV import writes are restricted to temporary SQLite databases"
        ) from error
    if os.path.normcase(common_path) != os.path.normcase(str(temporary_root)):
        raise ValueError("CSV import writes are restricted to temporary SQLite databases")
    if not path.is_file():
        raise FileNotFoundError(path)
    if configured_path.is_file() and os.path.samefile(path, configured_path):
        raise ValueError("CSV import writes are disabled for the configured application database")
    connection = sqlite3.connect(
        path.as_uri() + "?mode=rw",
        uri=True,
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _validate_import_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not {"cpus", "meta"}.issubset(tables):
        raise sqlite3.DatabaseError("Import target is missing required tables")

    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(cpus)")
    }
    required = {"id", "name", "name_key", *_IMPORT_FIELDS, "updated_at"}
    if not required.issubset(columns):
        raise sqlite3.DatabaseError("Import target CPU schema is incomplete")

    version = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if version is None or str(version["value"]) != str(database.SCHEMA_VERSION):
        raise sqlite3.DatabaseError("Import target schema version is unsupported")

    unique_name_key = False
    for index in connection.execute("PRAGMA index_list('cpus')"):
        if not index["unique"] or index["partial"]:
            continue
        index_name = str(index["name"]).replace('"', '""')
        indexed_columns = [
            row["name"]
            for row in connection.execute(f'PRAGMA index_info("{index_name}")')
        ]
        if indexed_columns == ["name_key"]:
            unique_name_key = True
            break
    if not unique_name_key:
        raise sqlite3.DatabaseError("Import target is missing the unique CPU identity index")

    for row in connection.execute("SELECT name, name_key FROM cpus"):
        try:
            expected_key = normalize_cpu_name(row["name"])
        except ValueError as error:
            raise sqlite3.DatabaseError("Import target contains an invalid CPU name") from error
        if row["name_key"] != expected_key:
            raise sqlite3.DatabaseError("Import target contains an inconsistent CPU identity key")


def apply_csv_import(
    preview: CSVPreview,
    *,
    database_path: str | Path,
) -> CSVImportResult:
    """Atomically apply a validated preview to an explicitly selected SQLite file.

    The caller must supply an existing, initialized database path. This
    function does not use the application's configured DB_PATH, create a
    database, run migrations, or fetch external data. Blank values preserve
    existing fields; clear_fields explicitly sets selected fields to NULL.
    Any invalid/stale row or SQL error rolls the entire batch back.
    """
    if not isinstance(preview, CSVPreview):
        raise TypeError("preview must be a CSVPreview")

    rejected = [
        row for row in preview.rows
        if row.status not in {"new", "update"} or row.record is None or row.errors
    ]
    if rejected:
        raise ValueError("CSV preview contains ambiguous or invalid rows")
    if any(
        row.status == "update" and row.expected_existing_sha256 is None
        for row in preview.rows
    ):
        raise ValueError("CSV preview is missing the existing-record snapshot; create a fresh preview")

    seen_keys: set[str] = set()
    for row in preview.rows:
        if row.record is None:
            raise ValueError("CSV preview row has no CPU record")
        key = normalize_cpu_name(row.record.name)
        if key in seen_keys:
            raise ValueError("CSV preview contains duplicate normalized CPU names")
        seen_keys.add(key)
        invalid_clear_fields = set(row.clear_fields) - _CLEARABLE_FIELDS
        if invalid_clear_fields:
            raise ValueError(
                "CSV preview contains unsupported clear fields: "
                + ", ".join(sorted(invalid_clear_fields))
            )

    connection = _open_existing_import_database(database_path)
    inserted = updated = unchanged = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        _validate_import_schema(connection)

        for row in preview.rows:
            record = row.record
            assert record is not None
            values = record.to_mapping()
            name_key = normalize_cpu_name(record.name)
            existing = connection.execute(
                "SELECT id, " + ", ".join(_IMPORT_FIELDS) + ", updated_at"
                + " FROM cpus WHERE name_key = ?",
                (name_key,),
            ).fetchone()

            if row.status == "new":
                if existing is not None:
                    raise ValueError(
                        f"CSV preview is stale; CPU already exists: {record.name}"
                    )
                columns = ("name_key", *_IMPORT_FIELDS, "updated_at")
                now = datetime.now(timezone.utc).isoformat()
                placeholders = ", ".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO cpus ({', '.join(columns)}) "
                    f"VALUES ({placeholders})",
                    (name_key, *(values[field] for field in _IMPORT_FIELDS), now),
                )
                inserted += 1
                continue

            if existing is None:
                raise ValueError(
                    f"CSV preview is stale; CPU no longer exists: {record.name}"
                )
            if _existing_record_fingerprint(existing) != row.expected_existing_sha256:
                raise ValueError(
                    f"CSV preview is stale; existing CPU changed after preview: {record.name}"
                )

            target = {"name": record.name}
            for field in _IMPORT_FIELDS:
                if field == "name":
                    continue
                if field in row.clear_fields:
                    target[field] = None
                elif values[field] is not None:
                    target[field] = values[field]
                else:
                    target[field] = existing[field]

            changed = any(existing[field] != value for field, value in target.items())
            if not changed:
                unchanged += 1
                continue

            assignments = [f"{field} = ?" for field in target]
            params = list(target.values())
            assignments.append("updated_at = ?")
            params.extend((datetime.now(timezone.utc).isoformat(), existing["id"]))
            connection.execute(
                f"UPDATE cpus SET {', '.join(assignments)} WHERE id = ?",
                params,
            )
            updated += 1

        connection.commit()
        return CSVImportResult(
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
