"""Centralized, cross-platform application settings."""
from dataclasses import dataclass
import os
import sys
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


def default_data_dir(platform: str | None = None, environ: Mapping[str, str] | None = None,
                     home: Path | None = None) -> Path:
    """Return the platform-standard per-user application data directory."""
    env = os.environ if environ is None else environ
    system = sys.platform if platform is None else platform
    user_home = Path.home() if home is None else Path(home)
    if system in ("nt", "win32"):
        root = env.get("LOCALAPPDATA")
        return (Path(root) if root else user_home / "AppData" / "Local") / "CPU_Data_offline"
    if system == "darwin":
        return user_home / "Library" / "Application Support" / "CPU_Data_offline"
    xdg_data = env.get("XDG_DATA_HOME")
    root = Path(xdg_data).expanduser() if xdg_data else user_home / ".local" / "share"
    return root / "cpu-data-offline"


def default_config_dir(platform: str | None = None, environ: Mapping[str, str] | None = None,
                       home: Path | None = None) -> Path:
    """Return the platform-standard per-user configuration directory."""
    env = os.environ if environ is None else environ
    system = os.name if platform is None else platform
    user_home = Path.home() if home is None else Path(home)
    if system == "nt":
        root = env.get("APPDATA")
        return (Path(root) if root else user_home / "AppData" / "Roaming") / "CPU_Data_offline"
    if system == "darwin":
        return user_home / "Library" / "Preferences" / "CPU_Data_offline"
    xdg_config = env.get("XDG_CONFIG_HOME")
    root = Path(xdg_config).expanduser() if xdg_config else user_home / ".config"
    return root / "cpu-data-offline"


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    db_path: Path
    config_dir: Path
    http_connect_timeout: int = 5
    http_read_timeout: int = 20
    http_retries: int = 3
    retry_backoff: float = 0.5
    update_batch_size: int = 100
    nanoreview_delay: float = 0.5


def load_settings(environ: Mapping[str, str] | None = None,
                  platform: str | None = None, home: Path | None = None) -> Settings:
    """Load settings. CPU_DATA_HOME overrides the OS-standard data directory."""
    env = os.environ if environ is None else environ
    raw_data_dir = env.get("CPU_DATA_HOME")
    data_dir = Path(raw_data_dir).expanduser() if raw_data_dir else default_data_dir(platform, env, home)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    config_dir = default_config_dir(platform, env, home)
    return Settings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir.resolve(),
        db_path=(data_dir / "cpu.db").resolve(),
        config_dir=config_dir.resolve(),
        http_connect_timeout=_positive_int(env, "CPU_HTTP_CONNECT_TIMEOUT", 5),
        http_read_timeout=_positive_int(env, "CPU_HTTP_READ_TIMEOUT", 20),
        http_retries=_nonnegative_int(env, "CPU_HTTP_RETRIES", 3),
        retry_backoff=_nonnegative_float(env, "CPU_HTTP_RETRY_BACKOFF", 0.5),
        update_batch_size=_positive_int(env, "CPU_UPDATE_BATCH_SIZE", 100),
        nanoreview_delay=_nonnegative_float(env, "CPU_NANOREVIEW_DELAY", 0.5),
    )


SETTINGS = load_settings()
