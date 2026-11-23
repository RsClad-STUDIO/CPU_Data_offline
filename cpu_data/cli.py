#!/usr/bin/env python3
"""
cpu_lookup.py - CPU情報検索CLIツール
使い方:
  python cpu_lookup.py           # 対話モード
  python cpu_lookup.py --update  # データ更新
  python cpu_lookup.py --fast    # 高速更新（Passmarkスコアのみ）
  python cpu_lookup.py "i7-13700K"  # 直接検索
"""
import sys
import argparse
from .database import search_cpus, get_meta, count_cpus
from .database_location import configure_database, DatabaseSelectionRequired
from .infrastructure import database as database_store

# ── rich が使えれば使う ──────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH = True
    console = Console()
except ImportError:
    RICH = False


# ── 表示関数 ────────────────────────────────────────────

FIELD_LABELS = [
    ("brand",           "メーカー"),
    ("family",          "ファミリー"),
    ("cores",           "コア数"),
    ("threads",         "スレッド数"),
    ("base_clock",      "ベースクロック"),
    ("boost_clock",     "ブーストクロック"),
    ("tdp",             "TDP"),
    ("socket",          "ソケット"),
    ("process",         "製造プロセス"),
    ("memory_support",  "メモリ対応"),
    ("igpu",            "内蔵GPU"),
    ("passmark_score",  "Passmarkスコア"),
]


def _fmt_score(score):
    if score is None:
        return "N/A"
    return f"{score:,}"


def print_cpu_detail_rich(row):
    name = row["name"]
    lines = []
    for field, label in FIELD_LABELS:
        val = row[field]
        if val is None or val == "":
            val = "―"
        if field == "passmark_score":
            val = _fmt_score(row[field])
        lines.append(f"  [bold]{label:<14}[/bold]: {val}")
    body = "\n".join(lines)
    console.print(Panel(body, title=f"[cyan bold]{name}[/]", expand=False))


def print_cpu_detail_plain(row):
    name = row["name"]
    print(f"\n── {name} " + "─" * max(0, 50 - len(name)))
    for field, label in FIELD_LABELS:
        val = row[field]
        if val is None or val == "":
            val = "―"
        if field == "passmark_score":
            val = _fmt_score(row[field])
        print(f"  {label:<14}: {val}")
    print()


def print_cpu_detail(row):
    if RICH:
        print_cpu_detail_rich(row)
    else:
        print_cpu_detail_plain(row)


def print_results_rich(rows):
    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold cyan")
    table.add_column("#",         style="dim",       width=4)
    table.add_column("CPU名",     min_width=30)
    table.add_column("メーカー",  width=8)
    table.add_column("コア",      width=6)
    table.add_column("スレッド",  width=8)
    table.add_column("TDP",       width=8)
    table.add_column("Passmark",  justify="right", width=10)

    for i, row in enumerate(rows, 1):
        table.add_row(
            str(i),
            row["name"],
            row["brand"] or "―",
            row["cores"] or "―",
            row["threads"] or "―",
            row["tdp"] or "―",
            _fmt_score(row["passmark_score"]),
        )
    console.print(table)


def print_results_plain(rows):
    print(f"\n{'#':<4} {'CPU名':<40} {'メーカー':<8} {'コア':<6} {'Passmark':>10}")
    print("─" * 72)
    for i, row in enumerate(rows, 1):
        score = _fmt_score(row["passmark_score"])
        print(f"{i:<4} {row['name']:<40} {(row['brand'] or '―'):<8} {(row['cores'] or '―'):<6} {score:>10}")
    print()


def print_results(rows):
    if RICH:
        print_results_rich(rows)
    else:
        print_results_plain(rows)


def print_info(msg):
    if RICH:
        console.print(f"[dim]{msg}[/]")
    else:
        print(msg)


def print_error(msg):
    if RICH:
        console.print(f"[red]{msg}[/]")
    else:
        print(f"エラー: {msg}")


def print_header():
    if RICH:
        console.print(Panel(
            "[bold cyan]CPU Lookup[/] — オフラインCPU情報検索ツール\n"
            "[dim]型番の一部を入力して検索。:q または Ctrl+C で終了。:u で更新[/]",
            expand=False
        ))
    else:
        print("=" * 50)
        print("  CPU Lookup — オフラインCPU情報検索ツール")
        print("  型番の一部を入力して検索。:q で終了。:u で更新")
        print("=" * 50)


# ── DB初期化チェック ────────────────────────────────────

def ensure_db():
    """既存DBの有無だけを確認し、初回の自動取得は行わない。"""
    if database_store.DB_PATH.is_file():
        return True
    print("データベースが見つかりません。")
    print("初回データ取得を行うには、次を明示的に実行してください:")
    print("  cpu-lookup update --mode fast")
    print("または: python cpu_lookup.py --fast")
    return False



# ── 検索ループ ───────────────────────────────────────────

def search_loop(initial_query: str = None):
    print_header()

    n = count_cpus()
    last_updated = get_meta("last_updated") or "不明"
    print_info(f"DB: {n:,} 件  最終更新: {last_updated}")

    while True:
        try:
            if initial_query:
                query = initial_query.strip()
                initial_query = None
            else:
                if RICH:
                    query = console.input("\n[bold green]検索>[/] ").strip()
                else:
                    query = input("\n検索> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n終了します。")
            break

        if not query:
            continue

        # コマンド処理
        if query in (":q", ":quit", "exit", "quit"):
            print("終了します。")
            break

        if query in (":u", ":update"):
            try:
                from .updater import run_update
                run_update(fast=False)
            except KeyboardInterrupt:
                print_info("更新を中断しました。保存済みのデータは保持されています。")
            except Exception as e:
                print_error(f"更新失敗: {e}")
            continue

        if query in (":uf", ":fastupdate"):
            try:
                from .updater import run_update
                run_update(fast=True)
            except KeyboardInterrupt:
                print_info("高速更新を中断しました。")
            except Exception as e:
                print_error(f"更新失敗: {e}")
            continue

        # 検索実行
        rows = search_cpus(query)

        if not rows:
            print_info(f"「{query}」に一致するCPUが見つかりませんでした。")
            continue

        if len(rows) == 1:
            print_cpu_detail(rows[0])
            continue

        # 複数候補 → 一覧表示して選択
        print_results(rows)

        if RICH:
            sel = console.input(
                f"[bold]番号を選択 (1-{len(rows)}) / Enterでキャンセル>[/] "
            ).strip()
        else:
            sel = input(f"番号を選択 (1-{len(rows)}) / Enterでキャンセル> ").strip()

        if not sel:
            continue

        try:
            idx = int(sel) - 1
            if 0 <= idx < len(rows):
                print_cpu_detail(rows[idx])
            else:
                print_error("番号が範囲外です。")
        except ValueError:
            print_error("数字を入力してください。")


# ── エントリポイント ─────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CPU情報オフライン検索ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("query", nargs="?", help="検索するCPU型番")
    parser.add_argument("--db-location", help="DB保存先ディレクトリ（cpu.dbを配置）。CPU_DATA_HOMEが優先されます")
    parser.add_argument("--mode", choices=("fast", "full"), help="updateコマンドの更新モード")
    update_group = parser.add_mutually_exclusive_group()
    update_group.add_argument("--update", action="store_true", help="データを完全更新")
    update_group.add_argument("--fast", action="store_true", help="高速更新（PassMarkのみ）")
    args = parser.parse_args()
    if args.mode and args.query != "update":
        parser.error("--mode は update コマンドと併用してください")
    if args.mode and (args.fast or args.update):
        parser.error("--mode と --fast / --update は併用できません")
    if args.query == "update" and not args.mode:
        parser.error("update コマンドには --mode fast または --mode full が必要です")
    if args.query == "update":
        args.query = None

    try:
        configure_database(
            db_location=args.db_location,
            interactive=bool(sys.stdin and sys.stdin.isatty()),
        )
    except DatabaseSelectionRequired as e:
        print_error(str(e))
        sys.exit(2)
    except Exception as e:
        print_error(f"DB保存先の決定に失敗しました: {e}")
        sys.exit(1)

    if args.update or args.fast or args.mode:
        from .updater import run_update
        try:
            run_update(fast=(args.fast or args.mode == "fast"))
        except KeyboardInterrupt:
            print_info("更新を中断しました。保存済みのデータは保持されています。")
            sys.exit(130)
        except Exception as e:
            print_error(f"更新失敗: {e}")
            sys.exit(1)
        return

    try:
        if not ensure_db():
            sys.exit(1)
    except KeyboardInterrupt:
        print_info("初回セットアップを中断しました。")
        sys.exit(130)

    search_loop(initial_query=args.query)


if __name__ == "__main__":
    main()
