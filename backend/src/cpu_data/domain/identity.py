"""Canonical CPU identity normalization shared by domain consumers."""
from __future__ import annotations

import re
import unicodedata


def normalize_cpu_name(name: str) -> str:
    """Normalize an exact model name for case-insensitive identity matching."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("CPU name must be a non-empty string")
    value = unicodedata.normalize("NFKC", name)
    return re.sub(r"\s+", " ", value).strip().casefold()
