"""Shared HTTP session with bounded retries and explicit timeouts."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .sources.errors import DataSourceError
from ..config import SETTINGS

HEADERS = {
    "User-Agent": "CPU_Data_offline/1.0 (+https://github.com/RsClad-STUDIO/CPU_Data_offline)",
    "Accept-Language": "en-US,en;q=0.9",
}


def build_session():
    retry = Retry(
        total=SETTINGS.http_retries,
        connect=SETTINGS.http_retries,
        read=SETTINGS.http_retries,
        status=SETTINGS.http_retries,
        backoff_factor=SETTINGS.retry_backoff,
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


def get(url, timeout=None):
    try:
        response = SESSION.get(
            url,
            timeout=(SETTINGS.http_connect_timeout, timeout or SETTINGS.http_read_timeout),
        )
        response.raise_for_status()
        return response
    except requests.HTTPError:
        # Preserve HTTP status so callers can distinguish a legitimate 404.
        raise
    except requests.RequestException as error:
        raise DataSourceError(f"HTTP request failed for {url}: {error}") from error
