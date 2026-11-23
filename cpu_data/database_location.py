"""Resolve, persist, and safely migrate the user's active SQLite database location."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .config import PROJECT_ROOT, SETTINGS
from .infrastructure import database

LEGACY_DB_PATH = (PROJECT_ROOT / "data" / "cpu.db").resolve()
SETTINGS_FILE = SETTINGS.config_dir / "settings.json"


class DatabaseSelectionRequired(RuntimeError):
    """Raised when a non-interactive run needs the user to choose a database."""


def _load_saved_path() -> Path | None:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        value = data.get("database_path")
        return Path(value).expanduser().resolve() if value else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, AttributeError):
        raise RuntimeError(f"設定ファイルを読み込めません: {SETTINGS_FILE}")


def _save_path(path: Path) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if SETTINGS_FILE.exists():
        try:
            existing = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                raise ValueError("settings root must be an object")
        except (OSError, ValueError):
            raise RuntimeError(f"既存の設定ファイルが破損しているため更新できません: {SETTINGS_FILE}")
    existing["database_path"] = str(path.resolve())
    fd, temporary = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=SETTINGS_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(existing, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _validate_database(path: Path) -> tuple[int, int]:
    """Return (schema version, CPU row count) without modifying the database."""
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result[0] if result else 'no result'}")
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "cpus" not in tables:
            raise RuntimeError("CPUテーブルが存在しないDBです")
        count = conn.execute("SELECT COUNT(*) FROM cpus").fetchone()[0]
        version = 0
        if "meta" in tables:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if row:
                try:
                    version = int(row[0])
                except (TypeError, ValueError):
                    raise RuntimeError("DBのschema_versionが不正です")
        if version > database.SCHEMA_VERSION:
            raise RuntimeError(
                f"DB schema version {version} は、このアプリが対応する "
                f"{database.SCHEMA_VERSION} より新しいため使用できません"
            )
        return version, count
    finally:
        conn.close()


def migrate_database(source: Path, destination: Path) -> Path:
    """Copy a database using SQLite Backup API and validate before activation."""
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        return destination
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    _validate_database(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.migration-", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(temporary)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        source_version, source_count = _validate_database(source)
        copied_version, copied_count = _validate_database(temporary)
        if (source_version, source_count) != (copied_version, copied_count):
            raise RuntimeError("移行元とコピー先のDB内容が一致しません")
        if destination.exists():
            raise FileExistsError(destination)
        # Atomic creation fails if another process has already created the target.
        os.link(temporary, destination)
        temporary.unlink()
        return destination
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _ask_choice(prompt: str, choices: tuple[str, ...], interactive: bool) -> str:
    if not interactive:
        raise DatabaseSelectionRequired(
            "使用するDBの選択が必要です。対話モードで起動するか、"
            "--db-location <保存先ディレクトリ> を指定してください。"
        )
    while True:
        answer = input(prompt).strip().lower()
        if answer in choices:
            return answer
        print("選択肢を入力してください。")


def resolve_database_path(db_location: str | None = None, interactive: bool = True) -> Path:
    """Choose the active DB path, asking before legacy selection or migration."""
    if os.environ.get("CPU_DATA_HOME"):
        return SETTINGS.db_path

    if db_location:
        selected_dir = Path(db_location).expanduser()
        if not selected_dir.is_absolute():
            selected_dir = Path.cwd() / selected_dir
        selected = (selected_dir / "cpu.db").resolve()
        _save_path(selected)
        return selected

    saved = _load_saved_path()
    if saved is not None:
        return saved

    current = SETTINGS.db_path
    legacy = LEGACY_DB_PATH
    current_exists = current.is_file()
    legacy_exists = legacy.is_file()

    if current == legacy:
        return current
    if current_exists and legacy_exists:
        choice = _ask_choice(
            f"新旧両方のDBが見つかりました。\n1) 新しいDB: {current}\n"
            f"2) 旧DB: {legacy}\n使用するDBを選択してください [1/2]: ",
            ("1", "2"), interactive,
        )
        selected = current if choice == "1" else legacy
        _save_path(selected)
        return selected

    if legacy_exists and not current_exists:
        choice = _ask_choice(
            f"旧保存先にDBが見つかりました: {legacy}\n"
            f"新しい保存先: {current}\n"
            "1) 新しい保存先へコピーして使用\n"
            "2) 旧DBを元の場所のまま使用\n"
            "選択してください [1/2]: ",
            ("1", "2"), interactive,
        )
        if choice == "1":
            migrate_database(legacy, current)
            selected = current
        else:
            selected = legacy
        _save_path(selected)
        return selected

    return current


def configure_database(db_location: str | None = None, interactive: bool = True) -> Path:
    path = resolve_database_path(db_location=db_location, interactive=interactive)
    database.DB_PATH = path
    return path
