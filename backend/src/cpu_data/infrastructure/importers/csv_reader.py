"""Read-only CSV decoding and structural validation for external CPU data."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Iterable


_NULL_VALUES = {"", "na", "n/a", "null", "none"}
_SUPPORTED_DELIMITERS = {",", "\t", ";"}


class CSVImportError(ValueError):
    """A CSV input or row does not satisfy the importer's structural rules."""


@dataclass(frozen=True, slots=True)
class CSVRow:
    """One parsed data row; row_number is the physical ending line in the file."""

    row_number: int
    values: dict[str, str | None]


@dataclass(frozen=True, slots=True)
class CSVDocument:
    """Decoded CSV data, without any database or filesystem write operation."""

    headers: tuple[str, ...]
    rows: tuple[CSVRow, ...]
    encoding: str
    delimiter: str


def _read_bytes(source: str | Path | bytes | bytearray) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if isinstance(source, (str, Path)):
        try:
            return Path(source).expanduser().read_bytes()
        except OSError as error:
            raise CSVImportError(f"Could not read CSV file: {error}") from error
    raise TypeError("source must be a path or bytes-like object")


def _decode(data: bytes, encoding: str | None) -> tuple[str, str]:
    candidates = [encoding] if encoding else (
        ["utf-8-sig", "cp932"] if not data.startswith(b"\xef\xbb\xbf")
        else ["utf-8-sig"]
    )
    errors = []
    for candidate in candidates:
        try:
            return data.decode(candidate, errors="strict"), candidate
        except (LookupError, UnicodeDecodeError) as error:
            errors.append(f"{candidate}: {error}")
    raise CSVImportError(
        "CSV encoding could not be decoded strictly; specify encoding explicitly. "
        + "; ".join(errors)
    )


def _normalize_cell(value: str) -> str | None:
    stripped = value.strip()
    if stripped.casefold() in _NULL_VALUES:
        return None
    return stripped


def read_csv(
    source: str | Path | bytes | bytearray,
    *,
    encoding: str | None = None,
    delimiter: str = ",",
) -> CSVDocument:
    """Read and validate a CSV without touching any database.

    Encoding detection is strict: UTF-8 (including BOM) is preferred, with
    CP932 as the fallback. Callers can force an encoding when the source is
    known. Delimiter selection is explicit to avoid unreliable guessing.
    """
    if delimiter not in _SUPPORTED_DELIMITERS:
        raise ValueError("delimiter must be comma, tab, or semicolon")

    data = _read_bytes(source)
    if not data:
        raise CSVImportError("CSV file is empty")

    decoded, detected_encoding = _decode(data, encoding)
    reader = csv.reader(StringIO(decoded, newline=""), delimiter=delimiter, strict=True)

    try:
        raw_headers = next(reader)
    except StopIteration as error:
        raise CSVImportError("CSV file does not contain a header row") from error
    except csv.Error as error:
        raise CSVImportError(f"Invalid CSV header: {error}") from error

    headers = tuple(header.strip() for header in raw_headers)
    if not headers or any(not header for header in headers):
        raise CSVImportError("CSV header contains an empty column name")

    normalized_headers = [header.casefold() for header in headers]
    if len(set(normalized_headers)) != len(normalized_headers):
        raise CSVImportError("CSV header contains duplicate column names")

    rows: list[CSVRow] = []
    try:
        for raw_row in reader:
            line_number = reader.line_num
            if not raw_row or all(not cell.strip() for cell in raw_row):
                continue
            if len(raw_row) != len(headers):
                raise CSVImportError(
                    f"CSV row ending at line {line_number} has "
                    f"{len(raw_row)} fields; expected {len(headers)}"
                )
            rows.append(CSVRow(
                row_number=line_number,
                values={
                    header: _normalize_cell(value)
                    for header, value in zip(headers, raw_row)
                },
            ))
    except csv.Error as error:
        raise CSVImportError(
            f"Invalid CSV data near line {reader.line_num}: {error}"
        ) from error

    return CSVDocument(
        headers=headers,
        rows=tuple(rows),
        encoding=detected_encoding,
        delimiter=delimiter,
    )
