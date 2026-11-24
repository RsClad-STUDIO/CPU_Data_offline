"""Application use case for safe, read-only CSV import previews."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Mapping

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
        existing_records = connection.execute(
            "SELECT name FROM cpus ORDER BY id"
        ).fetchall()

    return preview_csv(
        source,
        existing_records=existing_records,
        encoding=encoding,
        delimiter=delimiter,
        column_mapping=column_mapping,
        source_name=source_name,
        retrieved_at=retrieved_at,
        profile=profile,
    )
