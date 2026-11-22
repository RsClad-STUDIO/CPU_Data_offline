"""Application-level CPU update orchestration."""
import datetime
import time
from ..infrastructure.database import init_db, upsert_many, set_meta, get_meta, count_cpus
from ..infrastructure.http import get as _get, HEADERS, SESSION
from ..infrastructure.sources import passmark, nanoreview
from ..infrastructure.sources.errors import DataSourceError, DataSourceParseError

BASE_URL = passmark.BASE_URL
CPU_LIST_URL = passmark.CPU_LIST_URL
NANOREVIEW = nanoreview.NANOREVIEW
_brand = passmark._brand
_parse_cpu_list_html = passmark._parse_cpu_list_html
_parse_nanoreview_html = nanoreview._parse_nanoreview_html
_cpu_to_slug = nanoreview._cpu_to_slug
_parse_specs = nanoreview._parse_specs


def fetch_cpu_list():
    return passmark.fetch_cpu_list(get=_get)


def fetch_nanoreview(slug: str):
    return nanoreview.fetch_nanoreview(slug, get=_get)


def run_update(fast: bool = False):
    """Run a safe update with resumable checkpoints for full specification scans."""
    init_db()
    cpu_list = fetch_cpu_list()
    if not cpu_list:
        raise RuntimeError("PassMark returned an empty CPU list")

    if fast:
        records = []
        for item in cpu_list:
            records.append({
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
            })
        upsert_many(records)
        set_meta("last_updated", datetime.datetime.now().isoformat())
        set_meta("update_mode", "fast")
        print(f"[完了] {len(records)} 件をDBに保存しました（スコアのみ）")
        print("詳細スペックを取得するには: python cpu_lookup.py --update")
        return

    resume = get_meta("update_in_progress") == "true"
    checkpoint = get_meta("update_checkpoint") if resume else None
    if not resume:
        set_meta("update_checkpoint", "")
    start_index = 0
    if checkpoint:
        positions = [i for i, item in enumerate(cpu_list) if item["name"] == checkpoint]
        if positions:
            start_index = positions[-1] + 1
            print(f"[再開] {checkpoint} の次のCPUから処理します。")
        else:
            print("[注意] 前回のチェックポイントが一覧にないため、先頭から再処理します。")
            set_meta("update_checkpoint", "")

    set_meta("update_in_progress", "true")
    records = []
    hit = 0
    miss = 0

    def flush_batch():
        nonlocal records
        if records:
            upsert_many(records)
            set_meta("update_checkpoint", records[-1]["name"])
            records = []

    total = len(cpu_list)
    print(f"[NanoReview] 詳細スペック取得開始 ({total} 件)")
    print("  ※ 404はスコアのみ保存。通信障害・解析失敗時は中断し、次回はチェックポイントから再開します。")

    try:
        for index, item in enumerate(cpu_list[start_index:], start=start_index + 1):
            if index % 100 == 0:
                print(f"  {index}/{total} 件処理中... (取得成功: {hit}, 404: {miss})")

            specs = fetch_nanoreview(_cpu_to_slug(item["name"]))
            if specs:
                hit += 1
                record = _parse_specs(
                    item["name"], specs, item["detail_url"], item["passmark_score"]
                )
            else:
                miss += 1
                record = {
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

            records.append(record)
            if len(records) >= 100:
                flush_batch()
            time.sleep(0.5)

    except KeyboardInterrupt:
        flush_batch()
        print("[中断] 処理済みデータを保存しました。次回の完全更新で続きから再開します。")
        raise
    except Exception:
        flush_batch()
        raise

    flush_batch()
    set_meta("last_updated", datetime.datetime.now().isoformat())
    set_meta("update_mode", "full")
    set_meta("update_in_progress", "false")
    set_meta("update_checkpoint", "")
    print(f"\n[完了] 合計 {count_cpus()} 件保存 (今回のスペック取得: {hit}, 404: {miss})")



def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Update offline CPU database")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fast", action="store_true", help="PassMark list and scores only")
    group.add_argument("--full", action="store_true", help="Fetch detailed specifications")
    args = parser.parse_args(argv)
    run_update(fast=args.fast)



if __name__ == "__main__":
    main()
