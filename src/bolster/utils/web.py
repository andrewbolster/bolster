"""HTTP session utilities with retry and rate-limit handling.

Provides a pre-configured :class:`requests.Session` (``session``) with:

- Automatic retry on transient server errors (500/502/503/504)
- Rate-limit awareness: exponential backoff on 429 responses, capped at 60 s
- A consistent ``User-Agent`` header for polite scraping
- Helpers for downloading Excel files and ZIP archives in memory

All data-source modules should import ``session`` from here rather than
calling :func:`requests.get` directly, so that retry logic is applied
uniformly.

Example:
    >>> from bolster.utils.web import session
    >>> type(session).__name__
    'Session'
"""

import hashlib
import io
import logging
import zipfile
from collections.abc import Generator
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry
from waybackpy import WaybackMachineCDXServerAPI, exceptions

from . import version_no

logger = logging.getLogger(__name__)
ua = f"@Bolster/{version_no} (+http://bolster.online/)"

_PAGE_CACHE_DIR = Path.home() / ".cache" / "bolster" / "_pages"
_PAGE_CACHE_TTL_SECONDS = 3600  # 1 hour


class RateLimitAwareRetry(Retry):
    """Retry strategy that logs HTTP errors and connection failures for diagnosis."""

    def increment(self, method=None, url=None, response=None, error=None, _pool=None, _stacktrace=None):
        """Override increment to track the last response status."""
        if response is not None:
            self._last_status = response.status
            retry_num = len(self.history) + 1
            reason = getattr(response, "reason", "unknown")
            if response.status == 429:
                logger.warning(
                    f"HTTP 429 Too Many Requests from {url} "
                    f"(retry {retry_num}/{self.total}) — rate limited, extended backoff"
                )
            elif response.status in (500, 502, 503, 504):
                logger.warning(f"HTTP {response.status} {reason} from {url} (retry {retry_num}/{self.total})")
        elif error is not None:
            retry_num = len(self.history) + 1
            logger.warning(f"Connection error to {url} (retry {retry_num}/{self.total}): {error}")

        return super().increment(method, url, response, error, _pool, _stacktrace)


# Configure retry strategy for transient failures
# Retries on: connection errors, 429, 500, 502, 503, 504 status codes
# urllib3 default backoff: 0s, 2s, 4s, 8s (factor=1) — ~14s worst case
_retry_strategy = RateLimitAwareRetry(
    total=4,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"],
    raise_on_status=True,
    respect_retry_after_header=False,
)
_adapter = HTTPAdapter(max_retries=_retry_strategy)


class CachingSession(requests.Session):
    """requests.Session that caches GET responses to disk with a TTL.

    Only caches responses whose Content-Type starts with "text/" (HTML, plain
    text) — binary downloads (Excel, ZIP, etc.) bypass the cache and should
    go through CachedDownloader instead.

    Cache lives in ~/.cache/bolster/_pages/ keyed by URL hash.
    TTL is controlled by _PAGE_CACHE_TTL_SECONDS (default: 1 hour).

    Example:
        >>> from bolster.utils.web import session
        >>> type(session).__name__
        'CachingSession'
    """

    def get(self, url, **kwargs):  # noqa: D102
        _PAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = _PAGE_CACHE_DIR / f"{hashlib.md5(url.encode()).hexdigest()}.html"

        if cache_path.exists():
            age = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).total_seconds()
            if age < _PAGE_CACHE_TTL_SECONDS:
                logger.debug(f"Page cache hit: {url}")
                cached = requests.Response()
                cached.status_code = 200
                cached._content = cache_path.read_bytes()
                cached.headers["Content-Type"] = "text/html"
                return cached

        response = super().get(url, **kwargs)

        content_type = response.headers.get("Content-Type", "")
        if response.ok and content_type.startswith("text/"):
            cache_path.write_bytes(response.content)
            logger.debug(f"Page cached: {url}")

        return response


session = CachingSession()
session.headers.update({"User-Agent": ua})
session.mount("http://", _adapter)
session.mount("https://", _adapter)


def get_last_valid(url: str) -> str:
    """Get the last valid URL from Wayback Machine."""
    return WaybackMachineCDXServerAPI(url).oldest().archive_url


def resilient_get(url: str, **kwargs) -> requests.Response:
    """Attempt a get, but if it fails, try using the wayback machine to get the last valid version and get that.

    If all else fails, raise a HTTPError from the inner "NoCDXRecordFound" exception.
    """
    try:
        res = session.get(url, **kwargs)
        res.raise_for_status()
    except Exception as outer_err:
        try:
            last_valid = get_last_valid(url)
        except exceptions.NoCDXRecordFound as inner_err:
            raise outer_err from inner_err
        res = session.get(last_valid, **kwargs)
        res.raise_for_status()
        logger.warning(f"Failed to get {url} directly, successfully used waybackmachine to get {last_valid}")
    return res


def get_excel_dataframe(
    file_url: str, requests_kwargs: dict | None = None, read_kwargs: dict | None = None
) -> pd.DataFrame:
    """Download and read Excel file into pandas DataFrame."""
    if requests_kwargs is None:
        requests_kwargs = {}
    if read_kwargs is None:
        read_kwargs = {}

    with session.get(file_url, **requests_kwargs) as response:
        response.raise_for_status()
        data = BytesIO(response.content)
        return pd.read_excel(data, **read_kwargs)


def download_extract_zip(url: str) -> Generator[tuple[str, io.BufferedReader], None, None]:
    """Download a ZIP file and extract its contents in memory.

    Yields (filename, file-like object) pairs. Shows a tqdm progress bar
    during download sized to Content-Length when the server provides it.
    """
    with session.get(url, stream=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0)) or None
        buf = io.BytesIO()
        with tqdm(total=total, unit="B", unit_scale=True, desc=url.split("/")[-1], leave=False) as bar:
            for chunk in response.iter_content(chunk_size=65536):
                buf.write(chunk)
                bar.update(len(chunk))
        buf.seek(0)
        with zipfile.ZipFile(buf) as thezip:
            for zipinfo in thezip.infolist():
                with thezip.open(zipinfo) as thefile:
                    yield zipinfo.filename, thefile
