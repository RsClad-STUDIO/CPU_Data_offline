"""Map CSV columns to CPU records and classify rows without database access."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable, Mapping

from ...domain.cpu import CPURecord
from ...domain.identity import normalize_cpu_name
from .csv_reader import CSVDocument, read_csv


class CSVMappingError(ValueError):
    """CSV headers cannot be mapped unambiguously to CPU fields."""


@dataclass(frozen=True, slots=True)
class CSVPreviewRow:
    row_number: int
    status: str
    record: CPURecord | None
    unknown_fields: Mapping[str, str | None]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CSVPreview:
    headers: tuple[str, ...]
    rows: tuple[CSVPreviewRow, ...]
    unknown_columns: tuple[str, ...]
    encoding: str
    delimiter: str
    sha256: str
    source: str | None = None
    retrieved_at: str | None = None
    profile: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        values = Counter(row.status for row in self.rows)
        return {
            "new": values["new"],
            "update": values["update"],
            "ambiguous": values["ambiguous"],
            "error": values["error"],
        }


_FIELD_ALIASES = {
    "name": (
        "name", "cpu", "cpu name", "cpu model", "processor",
        "processor name", "model", "cpu名", "cpu名称", "製品名",
    ),
    "brand": ("brand", "manufacturer", "vendor", "maker", "メーカー", "製造元"),
    "family": ("family", "family name", "codename", "code name", "開発コード"),
    "cores": ("cores", "core count", "total cores", "コア数"),
    "threads": ("threads", "thread count", "logical processors", "スレッド数"),
    "base_clock": ("base clock", "base frequency", "base frequency clock", "ベースクロック"),
    "boost_clock": ("boost clock", "max boost", "maximum frequency", "最大ブーストクロック"),
    "tdp": ("tdp", "thermal design power", "消費電力"),
    "socket": ("socket", "socket type", "ソケット"),
    "process": ("process", "process node", "lithography", "製造プロセス"),
    "memory_support": ("memory support", "memory type", "対応メモリ"),
    "igpu": ("igpu", "integrated graphics", "integrated gpu", "内蔵gpu", "内蔵グラフィックス"),
    # Deliberately excludes generic "score", "rating", and single-thread scores.
    "passmark_score": ("passmark score", "passmark cpu mark", "cpu mark"),
    "source_url": ("source url", "detail url", "url", "source"),
}
_VALID_FIELDS = frozenset(CPURecord.__dataclass_fields__)


def _header_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)


_ALIAS_TO_FIELD = {
    _header_key(alias): field
    for field, aliases in _FIELD_ALIASES.items()
    for alias in aliases
}


def _resolve_columns(
    headers: tuple[str, ...],
    column_mapping: Mapping[str, str] | None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    explicit = dict(column_mapping or {})
    unknown_headers = set(explicit) - set(headers)
    if unknown_headers:
        raise CSVMappingError(
            "Explicit mapping references missing CSV columns: "
            + ", ".join(sorted(unknown_headers))
        )

    resolved: dict[str, str] = {}
    for header in headers:
        target = explicit.get(header)
        if target is None:
            target = _ALIAS_TO_FIELD.get(_header_key(header))
        if target is None:
            continue
        if target not in _VALID_FIELDS:
            raise CSVMappingError(f"Unsupported CPU field in mapping: {target}")
        if target in resolved.values():
            previous = next(key for key, value in resolved.items() if value == target)
            raise CSVMappingError(
                f"Multiple CSV columns map to '{target}': '{previous}' and '{header}'"
            )
        resolved[header] = target

    if "name" not in resolved.values():
        raise CSVMappingError(
            "A CPU name column is required; map one explicitly to 'name' if needed"
        )
    return resolved, tuple(header for header in headers if header not in resolved)


def _build_record(
    values: Mapping[str, str | None],
    resolved: Mapping[str, str],
) -> CPURecord:
    mapped: dict[str, Any] = {
        target: values.get(header)
        for header, target in resolved.items()
    }
    raw_score = mapped.get("passmark_score")
    if raw_score is not None:
        if not re.fullmatch(r"[0-9]+", raw_score.strip()):
            raise ValueError(
                "PassMark score must be a non-negative whole number; "
                "decimal or formatted values are not accepted"
            )
        mapped["passmark_score"] = int(raw_score)
    return CPURecord.from_mapping(mapped)


def preview_csv(
    source: str | Path | bytes | bytearray,
    *,
    existing_records: Iterable[Mapping[str, Any]] = (),
    encoding: str | None = None,
    delimiter: str = ",",
    column_mapping: Mapping[str, str] | None = None,
    source: str | None = None,
    retrieved_at: str | None = None,
    profile: str | None = None,
) -> CSVPreview:
    """Create a deterministic import preview; never opens or writes a database.

    Existing records must be supplied by the caller. Matching is exact after
    the same NFKC/whitespace/case normalization used by the database unique key.
    Fuzzy matches are never inferred.
    """
    document: CSVDocument = read_csv(source, encoding=encoding, delimiter=delimiter)
    resolved, unknown_columns = _resolve_columns(document.headers, column_mapping)

    prepared: list[tuple[int, CPURecord | None, dict[str, str | None], tuple[str, ...]]] = []
    imported_keys: Counter[str] = Counter()
    existing_by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)

    for existing in existing_records:
        if isinstance(existing, Mapping):
            name = existing.get("name")
        else:
            try:
                name = existing["name"]
            except (KeyError, IndexError, TypeError):
                name = getattr(existing, "name", None)
        if isinstance(name, str) and name.strip():
            existing_by_key[normalize_cpu_name(name)].append(existing)

    for row in document.rows:
        unknown = {key: row.values[key] for key in unknown_columns}
        try:
            record = _build_record(row.values, resolved)
            imported_keys[normalize_cpu_name(record.name)] += 1
            prepared.append((row.row_number, record, unknown, ()))
        except (TypeError, ValueError) as error:
            prepared.append((row.row_number, None, unknown, (str(error),)))

    preview_rows: list[CSVPreviewRow] = []
    for row_number, record, unknown, errors in prepared:
        if record is None:
            status = "error"
        else:
            key = normalize_cpu_name(record.name)
            if imported_keys[key] > 1:
                status = "ambiguous"
                errors = ("Duplicate normalized CPU name in the CSV input",)
            elif len(existing_by_key[key]) > 1:
                status = "ambiguous"
                errors = ("Multiple existing records have the same normalized CPU name",)
            elif len(existing_by_key[key]) == 1:
                status = "update"
            else:
                status = "new"
        preview_rows.append(CSVPreviewRow(
            row_number=row_number,
            status=status,
            record=record,
            unknown_fields=unknown,
            errors=errors,
        ))

    return CSVPreview(
        headers=document.headers,
        rows=tuple(preview_rows),
        unknown_columns=unknown_columns,
        encoding=document.encoding,
        delimiter=document.delimiter,
        sha256=document.sha256,
        source=source,
        retrieved_at=retrieved_at,
        profile=profile,
    )
