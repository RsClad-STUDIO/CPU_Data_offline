#!/usr/bin/env python3
"""CPU information search CLI and command-line adapter."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from .application import queries
from .database_location import configure_database, DatabaseSelectionRequired
from .infrastructure import database as database_store
from . import updater as update_service

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    RICH = True
    console = Console()
except ImportError:
    RICH = False


FIELD_LABELS = [
    ("brand", "メーカー"),
    ("family", "ファミリー"),
    ("cores", "コア数"),
    ("threads", "スレッド数"),
    ("base_clock", "ベースクロック"),
    ("boost_clock", "ブーストクロック"),
    ("tdp", "TDP"),
    ("socket", "ソケット"),
    ("process", "製造プロセス"),
    ("memory_support", "メモリ対応"),
    ("igpu", "内蔵GPU"),
    ("passmark_score", "Passmarkスコア"),
]


def _fmt_score(score):
    return "N/A" if score is None else f"{score:,}"


def print_cpu_detail_rich(row):
    lines = []
    for field, label in FIELD_LABELS:
        value = row[field]
        if value is None or value == "":
            value = "―"
        if field == "passmark_score":
            value = _fmt_score(row[field])
        lines.append(f"  [bold]{label:<14}[/bold]: {value}")
    console.print(Panel("\n".join(lines), title=f"[cyan bold]{row['name']}[/]", expand=False))


def print_cpu_detail_plain(row):
    name = row["name"]
    print(f"\n── {name} " + "─" * max(0, 50 - len(name)))
    for field, label in FIELD_LABELS:
        value = row[field]
        if value is None or value == "":
            value = "―"
        if field == "passmark_score":
            value = _fmt_score(row[field])
        print(f"  {label:<14}: {value}")
    print()


def print_cpu_detail(row):
    print_cpu_detail_rich(row) if RICH else print_cpu_detail_plain(row)


def print_results_rich(rows):
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("CPU名", min_width=30)
    table.add_column("メーカー", width=8)
    table.add_column("コア", width=6)
    table.add_column("スレッド", width=8)
    table.add_column("TDP", width=8)
    table.add_column("Passmark", justify="right", width=10)
    for index, row in enumerate(rows, 1):
        table.add_row(
            str(index), row["name"], row["brand"] or "―",
            row["cores"] or "―", row["threads"] or "―",
            row["tdp"] or "―", _fmt_score(row["passmark_score"]),
        )
    console.print(table)


def print_results_plain(rows):
    print(f"\n{'#':<4} {'CPU名':<40} {'メーカー':<8} {'コア':<6} {'Passmark':>10}")
    print("─" * 72)
    for index, row in enumerate(rows, 1):
        print(
            f"{index:<4} {row['name']:<40} {(row['brand'] or '―'):<8} "
            f"{(row['cores'] or '―'):<6} {_fmt_score(row['passmark_score']):>10}"
        )
    print()


def print_results(rows):
    print_results_rich(rows) if RICH else print_results_plain(rows)


def print_info(message):
    console.print(f"[dim]{message}[/]") if RICH else print(message)


def print_error(message):
    console.print(f"[red]{message}[/]") if RICH else print(f"エラー: {message}", file=sys.stderr)


def print_header():
    if RICH:
        console.print(Panel(
            "[bold cyan]CPU Lookup[/] — オフラインCPU情報検索ツール\n"
            "[dim]型番の一部を入力して検索。:q または Ctrl+C で終了。:u で更新[/]",
            expand=False,
        ))
    else:
        print("=" * 50)
        print("  CPU Lookup — オフラインCPU情報検索ツール")
        print("  型番の一部を入力して検索。:q で終了。:u で更新")
        print("=" * 50)


def ensure_db():
    """Check for an existing database without triggering a first download."""
    if database_store.DB_PATH.is_file():
        return True
    print("データベースが見つかりません。")
    print("初回データ取得を行うには、次を明示的に実行してください:")
    print("  cpu-lookup update --mode fast")
    print("または: python cpu_lookup.py --fast")
    return False


def _event_to_stderr(event):
    if isinstance(event, update_service.UpdateStarted):
        print(f"更新開始: mode={event.mode}, total={event.total}, resume={event.start_index}", file=sys.stderr)
    elif isinstance(event, update_service.UpdateProgress):
        label = {"success": "取得", "not_found": "詳細なし", "skipped": "スキップ"}.get(event.status, event.status)
        print(
            f"進捗: {event.processed}/{event.total} {label}: {event.cpu_name}",
            file=sys.stderr,
        )
    elif isinstance(event, update_service.UpdateBatchSaved):
        print(f"DB保存: {event.saved}件 / checkpoint={event.checkpoint or '-'}", file=sys.stderr)
    elif isinstance(event, update_service.UpdateCancelled):
        print(f"更新中断: {event.processed}/{event.total}", file=sys.stderr)
    elif isinstance(event, update_service.UpdateFailed):
        print(f"更新失敗: {event.error}", file=sys.stderr)


def _run_update_in_adapter(fast=False):
    """Run the use case in a worker so Ctrl+C can request graceful cancellation."""
    token = update_service.CancellationToken()
    outcome = {}
    events = []

    def worker():
        try:
            outcome["result"] = update_service.run_update(
                fast=fast,
                event_handler=events.append,
                cancellation_token=token,
            )
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=worker, name="cpu-data-update", daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(0.2)
            while events:
                _event_to_stderr(events.pop(0))
    except KeyboardInterrupt:
        token.cancel()
        print("中断要求を送信しました。保存処理の完了を待っています...", file=sys.stderr)
        while thread.is_alive():
            thread.join(0.2)
            while events:
                _event_to_stderr(events.pop(0))
    while events:
        _event_to_stderr(events.pop(0))

    if "error" in outcome:
        error = outcome["error"]
        if isinstance(error, KeyboardInterrupt):
            return None, 130
        raise error
    result = outcome.get("result")
    if result is None:
        raise RuntimeError("更新処理から結果が返されませんでした")
    if result.status == "cancelled":
        return result, 130
    return result, 0


def _json_output(command, ok, data=None, error=None, warnings=None, exit_code=None):
    payload = {
        "schema_version": 1,
        "command": command,
        "ok": bool(ok),
        "data": data,
        "warnings": warnings or [],
    }
    if error is not None:
        payload["error"] = error
    print(json.dumps(payload, ensure_ascii=False, default=str))
    if exit_code is not None:
        return exit_code
    return 0 if ok else 1


def _cpu_payload(row):
    return dict(row) if row is not None else None


def _run_search(query, limit, output_format):
    try:
        rows = queries.search_cpus(query, limit=limit)
    except (TypeError, ValueError) as error:
        return _json_output("search", False, error={"code": "invalid_query", "message": str(error)}, exit_code=2) if output_format == "json" else (print_error(str(error)) or 2)
    data = [_cpu_payload(row) for row in rows]
    if output_format == "json":
        return _json_output("search", True, data={"items": data, "count": len(data)})
    if not rows:
        print_info(f"「{query}」に一致するCPUが見つかりませんでした。")
    elif len(rows) == 1:
        print_cpu_detail(rows[0])
    else:
        print_results(rows)
    return 0


def _run_show(identifier, output_format):
    row = None
    if identifier.isdecimal():
        try:
            row = queries.get_cpu_by_id(int(identifier))
        except ValueError:
            row = None
    else:
        row = queries.get_cpu_by_name(identifier)
    if row is not None:
        data = _cpu_payload(row)
        if output_format == "json":
            return _json_output("show", True, data=data)
        print_cpu_detail(row)
        return 0

    candidates = [] if identifier.isdecimal() else [
        _cpu_payload(item) for item in queries.search_cpus(identifier, limit=20)
    ]
    if output_format == "json":
        return _json_output(
            "show", False,
            data={"candidates": candidates},
            error={
                "code": "not_found" if not candidates else "ambiguous",
                "message": "CPUが見つかりません" if not candidates else "完全一致するCPUがありません。候補を確認してください",
            },
            exit_code=3,
        )
    if candidates:
        print_info("完全一致するCPUはありません。候補を表示します:")
        print_results(candidates)
    else:
        print_error(f"CPUが見つかりません: {identifier}")
    return 3


def _run_stats(output_format):
    data = queries.get_database_stats()
    if output_format == "json":
        return _json_output("stats", True, data=data)
    for key, value in data.items():
        print(f"{key}: {value}")
    return 0


def _run_db_command(action, destination, output_format):
    if action == "verify":
        valid, message = queries.verify_database()
        data = {"valid": valid, "result": message}
        if output_format == "json":
            return _json_output("db verify", valid, data=data, error=None if valid else {
                "code": message, "message": "データベースの整合性検査に失敗しました"
            })
        print_info(f"整合性検査: {'OK' if valid else 'NG'} ({message})")
        return 0 if valid else 1
    if action == "backup":
        if not destination:
            return 2
        try:
            path = queries.backup_database(destination)
        except Exception as error:
            if output_format == "json":
                return _json_output("db backup", False, error={
                    "code": type(error).__name__, "message": str(error)
                })
            print_error(f"バックアップ失敗: {error}")
            return 1
        data = {"backup_path": str(path)}
        if output_format == "json":
            return _json_output("db backup", True, data=data)
        print_info(f"バックアップを作成しました: {path}")
        return 0
    return 2


def search_loop(initial_query: str | None = None):
    print_header()
    stats = queries.get_database_stats()
    print_info(f"DB: {stats['cpu_count']:,} 件  最終更新: {stats['last_updated'] or '不明'}")
    while True:
        try:
            if initial_query:
                query = initial_query.strip()
                initial_query = None
            else:
                query = (console.input("\n[bold green]検索>[/] ") if RICH else input("\n検索> ")).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n終了します。")
            break
        if not query:
            continue
        if query in (":q", ":quit", "exit", "quit"):
            print("終了します。")
            break
        if query in (":u", ":update", ":uf", ":fastupdate"):
            try:
                _, code = _run_update_in_adapter(fast=query in (":uf", ":fastupdate"))
                if code == 130:
                    print_info("更新を中断しました。保存済みデータは保持されています。")
            except Exception as error:
                print_error(f"更新失敗: {error}")
            continue
        _run_search(query, 20, "text")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="CPU情報オフライン検索ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="search/show/stats/update/db または従来形式の検索語")
    parser.add_argument("target", nargs="?", help="検索語、CPU ID/名称、またはdbサブコマンド")
    parser.add_argument("extra", nargs="?", help="db backupの保存先")
    parser.add_argument("--db-location", help="DB保存先ディレクトリ。CPU_DATA_HOMEが優先されます")
    parser.add_argument("--mode", choices=("fast", "full"), help="updateコマンドの更新モード")
    parser.add_argument("--limit", type=int, default=20, help="searchの最大表示件数")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="出力形式")
    update_group = parser.add_mutually_exclusive_group()
    update_group.add_argument("--update", action="store_true", help="データを完全更新")
    update_group.add_argument("--fast", action="store_true", help="高速更新（PassMarkのみ）")
    args = parser.parse_args(argv)

    commands = {"search", "show", "stats", "update", "db"}
    if args.mode and args.query != "update":
        parser.error("--mode は update コマンドと併用してください")
    if args.mode and (args.fast or args.update):
        parser.error("--mode と --fast / --update は併用できません")
    if args.query == "update" and not args.mode:
        parser.error("update コマンドには --mode fast または --mode full が必要です")
    if args.limit < 1:
        parser.error("--limit は1以上を指定してください")
    if args.query == "db" and args.target not in ("verify", "backup"):
        parser.error("dbには verify または backup を指定してください")
    if args.query == "db" and args.target == "verify" and args.extra:
        parser.error("db verifyに余分な引数は指定できません")
    if args.query == "db" and args.target == "backup" and not args.extra:
        parser.error("db backupには保存先を指定してください")
    if args.query in ("search", "show") and not args.target:
        parser.error(f"{args.query}には検索語またはCPU ID/名称が必要です")
    if args.query in ("stats",) and args.target:
        parser.error("statsに余分な引数は指定できません")
    if args.query != "update" and args.mode:
        parser.error("--mode は update コマンドと併用してください")
    if args.query in commands and args.query not in ("db", "update") and args.extra:
        parser.error("余分な引数が指定されています")

    try:
        configure_database(
            db_location=args.db_location,
            interactive=bool(sys.stdin and sys.stdin.isatty()),
        )
    except DatabaseSelectionRequired as error:
        print_error(str(error))
        return 2
    except Exception as error:
        print_error(f"DB保存先の決定に失敗しました: {error}")
        return 1

    if args.query == "search":
        return _run_search(args.target, args.limit, args.format)
    if args.query == "show":
        return _run_show(args.target, args.format)
    if args.query == "stats":
        return _run_stats(args.format)
    if args.query == "db":
        return _run_db_command(args.target, args.extra, args.format)
    if args.query == "update" or args.update or args.fast:
        try:
            result, code = _run_update_in_adapter(
                fast=args.fast or args.mode == "fast"
            )
        except Exception as error:
            if args.format == "json":
                return _json_output("update", False, error={
                    "code": type(error).__name__, "message": str(error)
                })
            print_error(f"更新失敗: {error}")
            return 1
        if code == 130:
            if args.format == "json":
                return _json_output("update", False, data={"status": "cancelled"}, exit_code=130)
            print_info("更新を中断しました。保存済みデータは保持されています。")
            return 130
        if args.format == "json":
            return _json_output("update", True, data={
                "mode": result.mode, "status": result.status, "total": result.total,
                "processed": result.processed, "succeeded": result.succeeded,
                "not_found": result.not_found, "database_count": result.database_count,
            })
        print_info(f"更新完了: DB {result.database_count}件")
        return 0

    if args.query is None and not ensure_db():
        return 1
    search_loop(initial_query=args.query)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
