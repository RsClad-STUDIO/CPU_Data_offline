"""Typed CPU record used between source adapters and persistence."""
from dataclasses import asdict, dataclass
from collections.abc import Mapping
from typing import Any


@dataclass(frozen=True, slots=True)
class CPURecord:
    name: str
    brand: str | None = None
    family: str | None = None
    cores: str | None = None
    threads: str | None = None
    base_clock: str | None = None
    boost_clock: str | None = None
    tdp: str | None = None
    socket: str | None = None
    process: str | None = None
    memory_support: str | None = None
    igpu: str | None = None
    passmark_score: int | None = None
    source_url: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("CPU name must be a non-empty string")
        if self.passmark_score is not None:
            if isinstance(self.passmark_score, bool) or not isinstance(self.passmark_score, int):
                raise ValueError("PassMark score must be an integer or None")
            if self.passmark_score < 0:
                raise ValueError("PassMark score must not be negative")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "CPURecord":
        name = values.get("name")
        if not isinstance(name, str):
            raise ValueError("CPU name must be a string")
        score = values.get("passmark_score")
        if score is not None:
            if isinstance(score, bool):
                raise ValueError("PassMark score must be an integer or None")
            try:
                converted_score = int(score)
                if not isinstance(score, str) and score != converted_score:
                    raise ValueError("PassMark score must be an integer or None")
                score = converted_score
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("PassMark score must be an integer or None") from error

        string_fields = (
            "brand", "family", "cores", "threads", "base_clock", "boost_clock",
            "tdp", "socket", "process", "memory_support", "igpu", "source_url",
        )
        normalized = {
            field: (
                str(values[field]).strip()
                if values.get(field) is not None else None
            )
            for field in string_fields
        }
        return cls(
            name=name.strip(),
            passmark_score=score,
            **normalized,
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)
