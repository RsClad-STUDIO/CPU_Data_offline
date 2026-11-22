"""Centralized, cross-platform application settings."""
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = int(env.get(name, default))
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _nonnegative_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = int(env.get(name, default))
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def _nonnegative_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = float(env.get(name, default))
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    db_path: Path
    http_connect_timeout: int = 5
    http_read_timeout: int = 20
    http_retries: int = 3
    retry_backoff: float = 0.5
    update_batch_size: int = 100
    nanoreview_delay: float = 0.5


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load settings; relative CPU_DATA_HOME paths are rooted at the project."""
    env = os.environ if environ is None else environ
    raw_data_dir = env.get("CPU_DATA_HOME")
    if raw_data_dir:
        data_dir = Path(raw_data_dir).expanduser()
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
    else:
        data_dir = PROJECT_ROOT / "data"

    return Settings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir.resolve(),
        db_path=(data_dir / "cpu.db").resolve(),
        http_connect_timeout=_positive_int(env, "CPU_HTTP_CONNECT_TIMEOUT", 5),
        http_read_timeout=_positive_int(env, "CPU_HTTP_READ_TIMEOUT", 20),
        http_retries=_nonnegative_int(env, "CPU_HTTP_RETRIES", 3),
        retry_backoff=_nonnegative_float(env, "CPU_HTTP_RETRY_BACKOFF", 0.5),
        update_batch_size=_positive_int(env, "CPU_UPDATE_BATCH_SIZE", 100),
        nanoreview_delay=_nonnegative_float(env, "CPU_NANOREVIEW_DELAY", 0.5),
    )


SETTINGS = load_settings()
