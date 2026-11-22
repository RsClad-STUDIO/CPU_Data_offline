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
from db import init_db, upsert_many, set_meta, count_cpus

BASE_URL     = "https://www.cpubenchmark.net"
CPU_LIST_URL = f"{BASE_URL}/cpu-list/all"
NANOREVIEW   = "https://nanoreview.net/en/cpu"

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
    n = name.lower()
    if any(x in n for x in ["intel","core","pentium","celeron","xeon","atom","itanium"]):
        return "Intel"
    if any(x in n for x in ["amd","ryzen","athlon","threadripper","epyc","phenom","sempron","opteron"]):
        return "AMD"
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
        raise RuntimeError("PassMark CPU table was not found")
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
        raise RuntimeError("PassMark CPU table contained no recognizable rows")
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
            key = re.sub(r"\\s+", " ", term.get_text(" ", strip=True)).strip().lower()
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
        raise RuntimeError("NanoReview page contained no recognizable specifications")
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
    """
    fast=True  : Passmark一覧のみ（スコア+名前）→ 数分
    fast=False : Passmark一覧 + nanoreviewスペック → 数時間
    """
    init_db()

    # STEP1: Passmark一覧
    cpu_list = fetch_cpu_list()
    if not cpu_list:
        print("[中止] CPUリストが取得できませんでした。ネット接続を確認してください。")
        return

    if fast:
        records = []
        for item in cpu_list:
            records.append({
                "name":           item["name"],
                "brand":          _brand(item["name"]),
                "family":         None,
                "cores":          None,
                "threads":        None,
                "base_clock":     None,
                "boost_clock":    None,
                "tdp":            None,
                "socket":         None,
                "process":        None,
                "memory_support": None,
                "igpu":           None,
                "passmark_score": item["passmark_score"],
                "source_url":     item["detail_url"],
            })
        upsert_many(records)
        set_meta("last_updated", datetime.datetime.now().isoformat())
        set_meta("update_mode", "fast")
        print(f"[完了] {len(records)} 件をDBに保存しました（スコアのみ）")
        print("詳細スペックを取得するには: python cpu_lookup.py --update")
        return

    # STEP2: nanoreviewスペック取得
    total   = len(cpu_list)
    records = []
    hit     = 0
    miss    = 0

    print(f"[nanoreview] 詳細スペック取得開始 ({total} 件)")
    print("  ※ 404のCPUはスコアのみ保存。Ctrl+C で中断→再開可能。")

    for i, item in enumerate(cpu_list, 1):
        if i % 100 == 0:
            print(f"  {i}/{total} 件処理中... (取得成功: {hit}, 404スキップ: {miss})")

        slug  = _cpu_to_slug(item["name"])
        specs = fetch_nanoreview(slug)

        if specs:
            hit += 1
            rec = _parse_specs(item["name"], specs, item["detail_url"], item["passmark_score"])
        else:
            miss += 1
            rec = {
                "name":           item["name"],
                "brand":          _brand(item["name"]),
                "family":         None,
                "cores":          None,
                "threads":        None,
                "base_clock":     None,
                "boost_clock":    None,
                "tdp":            None,
                "socket":         None,
                "process":        None,
                "memory_support": None,
                "igpu":           None,
                "passmark_score": item["passmark_score"],
                "source_url":     item["detail_url"],
            }

        records.append(rec)

        # 100件ごとに中間保存
        if len(records) >= 100:
            upsert_many(records)
            records = []

        time.sleep(0.5)

    if records:
        upsert_many(records)

    set_meta("last_updated", datetime.datetime.now().isoformat())
    set_meta("update_mode", "full")
    print(f"\n[完了] 合計 {count_cpus()} 件保存 (スペック取得: {hit}, スコアのみ: {miss})")


if __name__ == "__main__":
    import sys
    fast = "--fast" in sys.argv
    run_update(fast=fast)