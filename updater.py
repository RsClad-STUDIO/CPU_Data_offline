"""
updater.py - CPUデータの取得・更新
  STEP1: PassMark /cpu-list/all  → CPU名 + スコア + 詳細URL
  STEP2: nanoreview.net          → 各CPUの詳細スペック
"""
import re
import time
import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from db import init_db, upsert_many, set_meta, get_meta, count_cpus

BASE_URL     = "https://www.cpubenchmark.net"
CPU_LIST_URL = f"{BASE_URL}/cpu-list/all"
NANOREVIEW   = "https://nanoreview.net/en/cpu"

class DataSourceParseError(RuntimeError):
    """Raised when a source response no longer matches the expected HTML structure."""


HEADERS = {
    "User-Agent": "CPU_Data_offline/1.0 (+https://github.com/RsClad-STUDIO/CPU_Data_offline)",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── ユーティリティ ───────────────────────────────────────

def _build_session():
    retry = Retry(
        total=3, connect=3, read=2, status=3, backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = _build_session()


def _get(url, timeout=20):
    resp = SESSION.get(url, timeout=(5, timeout))
    resp.raise_for_status()
    return resp

def _brand(name: str) -> str:
    n = name.strip().lower()
    if n.startswith("amd") or any(x in n for x in ("ryzen", "athlon", "threadripper", "epyc", "phenom", "sempron", "opteron")):
        return "AMD"
    if n.startswith("intel") or any(x in n for x in ("core", "pentium", "celeron", "xeon", "atom", "itanium")):
        return "Intel"
    if n.startswith("apple"):
        return "Apple"
    if n.startswith(("qualcomm", "snapdragon")):
        return "Qualcomm"
    if n.startswith(("arm ", "aarch64")):
        return "ARM"
    if n.startswith("nvidia"):
        return "NVIDIA"
    if n.startswith("mediatek"):
        return "MediaTek"
    if n.startswith("ampere"):
        return "Ampere"
    return "Unknown"

def _cpu_to_slug(name: str) -> str:
    """
    Passmark CPU名 → nanoreview.net URL スラグ
    例: "Intel Core i7-13700K"       → "intel-core-i7-13700k"
        "AMD Ryzen 9 7950X"          → "amd-ryzen-9-7950x"
        "Intel Core i5-4300U @ 1.90GHz" → "intel-core-i5-4300u"
    """
    # @ 以降（クロック表記）を除去
    name = re.sub(r'\s*@.*$', '', name).strip()
    name = name.lower()
    name = re.sub(r'[^a-z0-9\s\-]', '', name)
    name = re.sub(r'\s+', '-', name).strip('-')
    name = re.sub(r'-+', '-', name)
    return name


# ── STEP1: Passmark CPU一覧 ──────────────────────────────

def _parse_cpu_list_html(html: str) -> list:
    """Parse the all-vendor PassMark CPU list without making a network request."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="cputable") or soup.find("table")
    if table is None:
        raise DataSourceParseError("PassMark CPU table was not found")
    results = []
    for row in table.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) < 2:
            continue
        anchor = cols[0].find("a", href=True)
        if anchor is None:
            continue
        name = anchor.get_text(" ", strip=True)
        if not name:
            continue
        score_text = cols[1].get_text(" ", strip=True)
        match = re.search(r"[\d,]+", score_text)
        score = int(match.group(0).replace(",", "")) if match else None
        results.append({
            "name": name,
            "passmark_score": score,
            "detail_url": urljoin(BASE_URL + "/", anchor["href"].strip()),
        })
    if not results:
        raise DataSourceParseError("PassMark CPU table contained no recognizable rows")
    return results


def fetch_cpu_list() -> list:
    """Fetch CPU names, scores, and detail URLs for all vendors."""
    print(f"[PassMark] CPU一覧取得中: {CPU_LIST_URL}")
    response = _get(CPU_LIST_URL, timeout=30)
    results = _parse_cpu_list_html(response.text)
    print(f"[PassMark] {len(results)} 件取得")
    return results

# ── STEP2: nanoreview スペック ───────────────────────────

def fetch_nanoreview(slug: str) -> dict:
    """Fetch specifications. Only HTTP 404 is treated as a legitimate miss."""
    url = f"{NANOREVIEW}/{slug}"
    try:
        response = _get(url, timeout=12)
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            return {}
        raise
    return _parse_nanoreview_html(response.text)


def _parse_nanoreview_html(html: str) -> dict:
    """Extract key/value pairs from NanoReview's lists and specification tables."""
    soup = BeautifulSoup(html, "html.parser")
    specs = {}

    for ul in soup.find_all("ul", class_="flex"):
        for li in ul.find_all("li"):
            text = li.get_text(" ", strip=True)
            if ":" in text:
                key, _, value = text.partition(":")
                if key.strip() and value.strip():
                    specs[key.strip().lower()] = value.strip()

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2:
            key = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)).strip().lower()
            value = cells[1].get_text(" ", strip=True)
            if key and value:
                specs[key] = value

    for term in soup.find_all("dt"):
        definition = term.find_next_sibling("dd")
        if definition is not None:
            key = re.sub(r"\s+", " ", term.get_text(" ", strip=True)).strip().lower()
            value = definition.get_text(" ", strip=True)
            if key and value:
                specs[key] = value

    for div in soup.find_all("div", class_="card-block"):
        text = div.get_text(" ", strip=True)
        if "threads" in text.lower() and "socket" in text.lower():
            specs["_desc"] = text
            break

    if "_desc" not in specs:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            specs["_desc"] = meta["content"].strip()

    known = {
        "cores", "total cores", "total threads", "threads", "socket",
        "codename", "architecture", "memory types", "memory support",
        "tdp", "tdp (pl1)", "transistor size", "fabrication process",
    }
    if not known.intersection(specs) and not specs.get("_desc"):
        raise DataSourceParseError("NanoReview page contained no recognizable specifications")
    return specs

def _parse_specs(name: str, specs: dict, passmark_url: str, score) -> dict:
    """nanoreviewの生スペックをDB用dictに正規化"""
    desc = specs.get("_desc", "")

    # CPU family / core count
    family = specs.get("codename") or specs.get("architecture")
    cores = specs.get("total cores") or specs.get("cores")

    # スレッド数（説明文から）
    threads = specs.get("total threads") or specs.get("threads")
    if not threads:
        m = re.search(r'(\d+)\s+threads?', desc, re.I)
        if m:
            threads = m.group(1)

    # ソケット（説明文から）
    socket = specs.get("socket")
    if not socket:
        m = re.search(r'socket\s+([\w\-]+)', desc, re.I)
        if m:
            socket = m.group(1)

    # ベースクロック（説明文から）
    base_clock = specs.get("base frequency (p)") or specs.get("base frequency") or specs.get("base clock")
    if not base_clock:
        m = re.search(r'base clock.*?is\s+([\d.]+\s*(?:GHz|MHz))', desc, re.I)
        if m:
            base_clock = m.group(1)

    # ブーストクロック（説明文から）
    boost_clock = specs.get("turbo boost frequency (p)") or specs.get("turbo boost frequency") or specs.get("boost frequency")
    if not boost_clock:
        m = re.search(r'up to\s+([\d.]+\s*(?:GHz|MHz))', desc, re.I)
        if m:
            boost_clock = m.group(1)

    # TDP（先頭の数値+Wのみ）
    tdp = None
    raw_tdp = specs.get("tdp (pl1)") or specs.get("tdp", "")
    m = re.match(r'([\d.]+\s*W)', raw_tdp)
    if m:
        tdp = m.group(1)

    # 製造プロセス
    process = specs.get("fabrication process") or specs.get("transistor size")
    memory_support = specs.get("memory types") or specs.get("memory support")

    # 内蔵GPU（説明文から）
    igpu = specs.get("integrated gpu") or specs.get("integrated graphics")
    if not igpu:
        m = re.search(r'integrated graphics\s+(.+?)(?:\.|$)', desc, re.I)
        if m:
            igpu = m.group(1).strip()

    slug      = _cpu_to_slug(name)
    nano_url  = f"{NANOREVIEW}/{slug}"

    return {
        "name":           name,
        "brand":          _brand(name),
        "family":         family,
        "cores":          cores,
        "threads":        threads,
        "base_clock":     base_clock,
        "boost_clock":    boost_clock,
        "tdp":            tdp,
        "socket":         socket,
        "process":        process,
        "memory_support": memory_support,
        "igpu":           igpu,
        "passmark_score": score,
        "source_url":     nano_url,
    }


# ── メイン更新処理 ────────────────────────────────────────

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
    print(f"\\n[完了] 合計 {count_cpus()} 件保存 (今回のスペック取得: {hit}, 404: {miss})")


if __name__ == "__main__":
    import sys
    fast = "--fast" in sys.argv
    run_update(fast=fast)