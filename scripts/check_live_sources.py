"""Opt-in live smoke test for the configured CPU data sources.

This script performs one logical fetch per source (the shared HTTP retry policy
may issue additional attempts). It does not read or modify the local database.
Run from the repository root after installing the project dependencies:

    python scripts/check_live_sources.py
"""
from __future__ import annotations

import sys

from cpu_data.infrastructure.sources.nanoreview import (
    _parse_specs,
    fetch_nanoreview,
)
from cpu_data.infrastructure.sources.passmark import fetch_cpu_list


def main() -> int:
    failures: list[str] = []

    print("== PassMark ==")
    try:
        cpus = fetch_cpu_list()
        if not cpus:
            raise RuntimeError("CPU list is empty")
        target = next(
            (cpu for cpu in cpus if "i7-13700k" in cpu["name"].casefold()),
            None,
        )
        if target is None:
            raise RuntimeError(
                "CPU list parsed, but the expected Intel Core i7-13700K row was not found"
            )
        print(
            f"PASS: parsed {len(cpus)} CPU rows; "
            f"matched {target['name']} (score={target['passmark_score']})"
        )
    except Exception as error:
        failures.append(f"PassMark: {type(error).__name__}: {error}")
        print(f"FAIL: {failures[-1]}")

    print("\n== NanoReview ==")
    try:
        raw_specs = fetch_nanoreview("intel-core-i7-13700k")
        if not raw_specs:
            raise RuntimeError("CPU page returned no specifications (possible 404)")
        normalized = _parse_specs(
            "Intel Core i7-13700K",
            raw_specs,
            "https://www.cpubenchmark.net/cpu.php?cpu=Intel+Core+i7-13700K",
            None,
        )
        if not normalized.get("cores") or not normalized.get("threads"):
            raise RuntimeError(
                "Parsed page, but normalized core/thread counts are missing"
            )
        print(
            "PASS: parsed Intel Core i7-13700K; "
            f"cores={normalized['cores']}, threads={normalized['threads']}, "
            f"socket={normalized.get('socket')}, "
            f"iGPU={normalized.get('igpu')}"
        )
    except Exception as error:
        failures.append(f"NanoReview: {type(error).__name__}: {error}")
        print(f"FAIL: {failures[-1]}")

    print("\n== Result ==")
    if failures:
        print("Live source smoke test FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Live source smoke test PASSED. No local database was accessed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
