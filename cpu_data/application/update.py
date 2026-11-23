"""UI-independent CPU update use case with progress events and cancellation."""
from __future__ import annotations

from dataclasses import dataclass
import datetime
import threading
import time
from typing import Callable

from ..infrastructure.database import (
    init_db, upsert_many, set_meta, get_meta, count_cpus,
)
from ..infrastructure.http import get as _get, HEADERS, SESSION
from ..infrastructure.sources import passmark, nanoreview
from ..infrastructure.sources.errors import DataSourceError, DataSourceParseError
from ..config import SETTINGS
from ..domain.cpu import CPURecord


BATCH_SIZE = SETTINGS.update_batch_size
REQUEST_DELAY_SECONDS = SETTINGS.nanoreview_delay

BASE_URL = passmark.BASE_URL
CPU_LIST_URL = passmark.CPU_LIST_URL
NANOREVIEW = nanoreview.NANOREVIEW
_brand = passmark._brand
_parse_cpu_list_html = passmark._parse_cpu_list_html
_parse_nanoreview_html = nanoreview._parse_nanoreview_html
_cpu_to_slug = nanoreview._cpu_to_slug
_nanoreview_url = nanoreview.nanoreview_url
_parse_specs = nanoreview._parse_specs


@dataclass(frozen=True)
class UpdateStarted:
    mode: str
    total: int
    start_index: int


@dataclass(frozen=True)
class UpdateProgress:
    mode: str
    processed: int
    total: int
    cpu_name: str
    status: str  # success, not_found, or skipped
    succeeded: int
    not_found: int


@dataclass(frozen=True)
class UpdateBatchSaved:
    mode: str
    saved: int
    checkpoint: str | None


@dataclass(frozen=True)
class UpdateCompleted:
    mode: str
    total: int
    processed: int
    succeeded: int
    not_found: int
    database_count: int


@dataclass(frozen=True)
class UpdateCancelled:
    mode: str
    total: int
    processed: int
    checkpoint: str | None


@dataclass(frozen=True)
class UpdateFailed:
    mode: str
    total: int
    processed: int
    error: Exception


@dataclass(frozen=True)
class UpdateResult:
    mode: str
    status: str
    total: int
    processed: int
    succeeded: int
    not_found: int
    database_count: int | None = None


class CancellationToken:
    """Thread-safe cancellation signal shared by an adapter and the use case."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise _CancellationRequested


class _CancellationRequested(Exception):
    pass


def fetch_cpu_list():
    return passmark.fetch_cpu_list(get=_get)


def fetch_nanoreview(slug: str):
    return nanoreview.fetch_nanoreview(slug, get=_get)


def _emit(handler, event):
    if handler is not None:
        handler(event)


def _record_without_specs(item):
    return {
        "name": item["name"],
        "brand": _brand(item["name"]),
        "family": None,
        "cores": None,
        "threads": None,
        "base_clock": None,
        "boost_clock": None,
        "tdp": None,
        "socket": None,
        "process": None,
        "memory_support": None,
        "igpu": None,
        "passmark_score": item["passmark_score"],
        "source_url": item["detail_url"],
    }


def run_update(
    fast: bool = False,
    *,
    event_handler: Callable[[object], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    request_delay_seconds: float | None = None,
    wait: Callable[[float], None] | None = None,
):
    """Run an update and report immutable events to the calling adapter.

    No terminal I/O or KeyboardInterrupt handling occurs here. Adapters may
    provide a cancellation token and event handler. The wait function and delay
    are injectable so desktop adapters can control scheduling and tests need
    not wait for real network politeness intervals.
    """
    mode = "fast" if fast else "full"
    token = cancellation_token or CancellationToken()
    delay = REQUEST_DELAY_SECONDS if request_delay_seconds is None else request_delay_seconds
    wait_fn = wait or time.sleep
    if delay < 0:
        raise ValueError("request_delay_seconds must not be negative")

    if token.is_cancelled:
        _emit(event_handler, UpdateCancelled(mode, 0, 0, None))
        return UpdateResult(mode, "cancelled", 0, 0, 0, 0, None)

    try:
        init_db()
        cpu_list = fetch_cpu_list()
        if not cpu_list:
            raise RuntimeError("PassMark returned an empty CPU list")
    except Exception as error:
        _emit(event_handler, UpdateFailed(mode, 0, 0, error))
        raise

    total = len(cpu_list)
    if token.is_cancelled:
        _emit(event_handler, UpdateCancelled(mode, total, 0, None))
        return UpdateResult(mode, "cancelled", total, 0, 0, 0, count_cpus())
    start_index = 0
    if not fast:
        resume = get_meta("update_in_progress") == "true"
        checkpoint = get_meta("update_checkpoint") if resume else None
        if not resume:
            set_meta("update_checkpoint", "")
        if checkpoint:
            positions = [i for i, item in enumerate(cpu_list) if item["name"] == checkpoint]
            if positions:
                start_index = positions[-1] + 1
            else:
                set_meta("update_checkpoint", "")
        set_meta("update_in_progress", "true")

    _emit(event_handler, UpdateStarted(mode, total, start_index))
    records = []
    succeeded = 0
    not_found = 0
    processed = 0
    last_checkpoint = get_meta("update_checkpoint") if not fast else None

    def flush_batch():
        nonlocal records, last_checkpoint
        if not records:
            return
        normalized = [
            CPURecord.from_mapping(record).to_mapping() for record in records
        ]
        upsert_many(normalized)
        saved = len(records)
        if not fast:
            last_checkpoint = records[-1]["name"]
            set_meta("update_checkpoint", last_checkpoint)
        records = []
        _emit(event_handler, UpdateBatchSaved(mode, saved, last_checkpoint))

    try:
        if fast:
            for item in cpu_list:
                token.raise_if_cancelled()
                records.append(_record_without_specs(item))
                processed += 1
                succeeded += 1
                _emit(event_handler, UpdateProgress(
                    mode, processed, total, item["name"], "success", succeeded, not_found
                ))
                if len(records) >= BATCH_SIZE:
                    flush_batch()
            token.raise_if_cancelled()
            flush_batch()
            set_meta("last_updated", datetime.datetime.now().isoformat())
            set_meta("update_mode", "fast")
            result = UpdateResult(mode, "completed", total, processed, succeeded, not_found, count_cpus())
            _emit(event_handler, UpdateCompleted(
                mode, total, processed, succeeded, not_found, result.database_count
            ))
            return result

        for index, item in enumerate(cpu_list[start_index:], start=start_index + 1):
            token.raise_if_cancelled()
            specs = fetch_nanoreview(_nanoreview_url(item["name"]))
            token.raise_if_cancelled()
            if specs:
                record = _parse_specs(
                    item["name"], specs, item["detail_url"], item["passmark_score"]
                )
                succeeded += 1
                status = "success"
            else:
                record = _record_without_specs(item)
                not_found += 1
                status = "not_found"

            records.append(record)
            processed += 1
            _emit(event_handler, UpdateProgress(
                mode, index, total, item["name"], status, succeeded, not_found
            ))
            if len(records) >= BATCH_SIZE:
                flush_batch()
            if delay:
                wait_fn(delay)
                token.raise_if_cancelled()

        token.raise_if_cancelled()
        flush_batch()
        set_meta("last_updated", datetime.datetime.now().isoformat())
        set_meta("update_mode", "full")
        set_meta("update_in_progress", "false")
        set_meta("update_checkpoint", "")
        result = UpdateResult(mode, "completed", total, processed, succeeded, not_found, count_cpus())
        _emit(event_handler, UpdateCompleted(
            mode, total, processed, succeeded, not_found, result.database_count
        ))
        return result

    except _CancellationRequested:
        flush_batch()
        _emit(event_handler, UpdateCancelled(mode, total, processed, last_checkpoint))
        return UpdateResult(mode, "cancelled", total, processed, succeeded, not_found, count_cpus())
    except Exception as error:
        try:
            flush_batch()
        finally:
            _emit(event_handler, UpdateFailed(mode, total, processed, error))
        raise


def main(argv=None):
    """Compatibility entry point routed through the CLI adapter."""
    import sys

    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--full" in arguments:
        arguments[arguments.index("--full")] = "--update"
    elif "--fast" not in arguments and "--update" not in arguments:
        arguments.append("--update")

    from ..cli import main as cli_main
    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
