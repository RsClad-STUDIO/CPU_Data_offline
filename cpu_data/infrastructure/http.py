"""Shared HTTP session with bounded retries and explicit timeouts."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {
    "User-Agent": "CPU_Data_offline/1.0 (+https://github.com/RsClad-STUDIO/CPU_Data_offline)",
    "Accept-Language": "en-US,en;q=0.9",
}


def build_session():
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


SESSION = build_session()


def get(url, timeout=20):
    response = SESSION.get(url, timeout=(5, timeout))
    response.raise_for_status()
    return response
