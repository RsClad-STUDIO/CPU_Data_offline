"""PassMark CPU list acquisition and deterministic HTML parsing."""
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from ..http import get as _default_get
from .errors import DataSourceParseError
from ...domain.vendors import classify_vendor as _brand

BASE_URL = "https://www.cpubenchmark.net"
CPU_LIST_URL = f"{BASE_URL}/cpu-list/all"

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



def fetch_cpu_list(get=_default_get) -> list:
    """Fetch CPU names, scores, and detail URLs for all vendors."""
    print(f"[PassMark] CPU一覧取得中: {CPU_LIST_URL}")
    response = get(CPU_LIST_URL)
    results = _parse_cpu_list_html(response.text)
    print(f"[PassMark] {len(results)} 件取得")
    return results
