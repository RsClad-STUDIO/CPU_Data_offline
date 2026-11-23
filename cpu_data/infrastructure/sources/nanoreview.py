"""NanoReview acquisition and CPU specification normalization."""
import re
import requests
from bs4 import BeautifulSoup
from ..http import get as _default_get
from .errors import DataSourceParseError
from ...domain.vendors import classify_vendor as _brand

NANOREVIEW = "https://nanoreview.net/en/cpu"
NANOREVIEW_SOC = "https://nanoreview.net/en/soc"

def _cpu_to_slug(name: str) -> str:
    """Normalize a PassMark CPU name to a NanoReview CPU slug."""
    name = re.sub(r"\s*@.*$", "", name).strip()
    name = re.sub(r"\s*\([^)]*\)", "", name).strip()
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s\-]", "", name)
    name = re.sub(r"\s+", "-", name).strip("-")
    return re.sub(r"-+", "-", name)


def nanoreview_url(name: str) -> str:
    """Build the NanoReview CPU/SoC URL for a PassMark model name."""
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    if normalized.startswith(("snapdragon", "qualcomm snapdragon")):
        model = re.sub(r"^qualcomm\s+", "", normalized)
        model = re.sub(r"^snapdragon\s*", "", model)
        model = re.sub(r"[^a-z0-9]+", "-", model).strip("-")
        # NanoReview's Snapdragon 888 page retains its historical 875 slug.
        if model == "888":
            model = "875"
        return f"{NANOREVIEW_SOC}/qualcomm-snapdragon-{model}"
    return f"{NANOREVIEW}/{_cpu_to_slug(name)}"


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


def fetch_nanoreview(slug: str, get=_default_get) -> dict:
    """Fetch specifications. Only HTTP 404 is treated as a legitimate miss."""
    url = slug if slug.startswith(("https://", "http://")) else f"{NANOREVIEW}/{slug}"
    try:
        response = get(url)
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            return {}
        raise
    return _parse_nanoreview_html(response.text)


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
    igpu = specs.get("integrated graphics") or specs.get("integrated gpu")
    if not igpu:
        m = re.search(r'integrated graphics\s+(.+?)(?:\.|$)', desc, re.I)
        if m:
            igpu = m.group(1).strip()

    nano_url  = nanoreview_url(name)

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

, '', name).strip()
    name = re.sub(r'\s*\([^)]*\)', '', name).strip()
    name = name.lower()
    name = re.sub(r'[^a-z0-9\s\-]', '', name)
    name = re.sub(r'\s+', '-', name).strip('-')
    name = re.sub(r'-+', '-', name)
    return name



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


def fetch_nanoreview(slug: str, get=_default_get) -> dict:
    """Fetch specifications. Only HTTP 404 is treated as a legitimate miss."""
    url = slug if slug.startswith(("https://", "http://")) else f"{NANOREVIEW}/{slug}"
    try:
        response = get(url)
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            return {}
        raise
    return _parse_nanoreview_html(response.text)


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
    igpu = specs.get("integrated graphics") or specs.get("integrated gpu")
    if not igpu:
        m = re.search(r'integrated graphics\s+(.+?)(?:\.|$)', desc, re.I)
        if m:
            igpu = m.group(1).strip()

    nano_url  = nanoreview_url(name)"

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

