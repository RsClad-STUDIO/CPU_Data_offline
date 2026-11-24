"""UI-independent query and database utility use cases.

These functions are shared by the CLI and future desktop/web adapters. They
return application data or raise exceptions; they never print or prompt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..infrastructure import database


def _record_dict(row):
    """Detach application results from sqlite3.Row and its connection layer."""
    return dict(row) if row is not None else None


def search_cpus(query: str, limit: int = 20):
    """Search CPU records, preserving the infrastructure layer's ordering."""
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")
    return [
        _record_dict(row)
        for row in database.search_cpus(normalized, limit=limit)
    ]


def get_cpu_by_id(cpu_id: int):
    """Return one CPU by its numeric database identifier, or None."""
    if isinstance(cpu_id, bool) or not isinstance(cpu_id, int) or cpu_id < 1:
        raise ValueError("cpu_id must be a positive integer")
    return _record_dict(database.get_cpu_by_id(cpu_id))


def get_cpu_by_name(name: str):
    """Return an exact normalized CPU-name match, or None."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    return _record_dict(database.get_cpu_by_name(name))


def get_database_stats() -> dict[str, Any]:
    """Return database metadata without presentation-specific formatting."""
    path = Path(database.DB_PATH).expanduser().resolve()
    return {
        "database_path": str(path),
        "database_exists": path.is_file(),
        "cpu_count": database.count_cpus() if path.is_file() else 0,
        "schema_version": (
            int(database.get_meta("schema_version"))
            if path.is_file() and database.get_meta("schema_version") is not None
            else None
        ),
        "last_updated": database.get_meta("last_updated") if path.is_file() else None,
        "update_mode": database.get_meta("update_mode") if path.is_file() else None,
        "update_in_progress": (
            database.get_meta("update_in_progress") == "true" if path.is_file() else False
        ),
        "update_checkpoint": database.get_meta("update_checkpoint") if path.is_file() else None,
    }


def verify_database() -> tuple[bool, str]:
    """Check an existing initialized database without creating or modifying it."""
    return database.verify_database()


def backup_database(destination: str | Path) -> Path:
    """Create a consistent SQLite backup through the infrastructure layer."""
    return database.backup_database(destination)
