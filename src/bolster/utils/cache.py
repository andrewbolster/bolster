"""File caching utilities for data sources.

Provides disk-based caching for downloaded files with configurable TTL.
Used by NISRA, PSNI, and other data source modules to avoid repeated
downloads of the same resources.

Cache Location:
    Files are cached in ``~/.cache/bolster/<namespace>/`` with filenames
    based on URL hashes. Each data source uses its own namespace.

Example:
    >>> from bolster.utils.cache import CachedDownloader, hash_url
    >>> hash_url("https://example.com/data.csv")
    '2a01ab0de708440185cbb6473893860c'
    >>> downloader = CachedDownloader("my_source")
    >>> downloader.namespace
    'my_source'
"""

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd

from .web import session as web_session

logger = logging.getLogger(__name__)

# Base cache directory
CACHE_BASE = Path.home() / ".cache" / "bolster"

# Process-wide hit/miss counters, surfaced in the pytest terminal summary
# (see tests/conftest.py) since CachedDownloader's own INFO-level logging
# is filtered out by pytest's log_cli_level=WARNING in CI.
hits = 0
misses = 0


class CacheError(Exception):
    """Base exception for cache operations."""

    pass


class DownloadError(CacheError):
    """Raised when a file download fails."""

    pass


def hash_url(url: str) -> str:
    """Generate a cache-safe filename from a URL using MD5 hash.

    Args:
        url: The URL to hash

    Returns:
        32-character hexadecimal MD5 hash string

    Example:
        >>> hash_url("https://example.com/data.csv")
        '2a01ab0de708440185cbb6473893860c'
    """
    return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


class CachedDownloader:
    """Disk-based file cache with TTL support.

    Provides download-with-cache functionality for data source modules.
    Each instance uses a namespace subdirectory for isolation.

    Args:
        namespace: Subdirectory name for this cache (e.g., "nisra", "psni")
        timeout: Request timeout in seconds (default: 60)

    Example:
        >>> downloader = CachedDownloader("psni", timeout=60)
        >>> downloader.namespace
        'psni'
        >>> downloader.timeout
        60
        >>> downloader.cache_dir.parts[-2:]
        ('bolster', 'psni')
    """

    def __init__(self, namespace: str, timeout: int = 60):
        """Initialize CachedDownloader with namespace and timeout.

        Args:
            namespace: Cache namespace for organizing files
            timeout: Timeout for HTTP requests in seconds
        """
        self.namespace = namespace
        self.timeout = timeout
        self.cache_dir = CACHE_BASE / namespace
        if not self.cache_dir.exists():
            logger.warning(
                f"Cache directory {self.cache_dir} did not exist — creating it fresh. "
                "If this is CI, a restored cache (e.g. actions/cache) should have already "
                "created this directory; a fresh create here likely means the cache "
                "missed or restored to an unexpected path."
            )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cached_file(self, url: str, cache_ttl_hours: int = 24) -> Path | None:
        """Return cached file if it exists and is fresh, else None.

        Args:
            url: URL of the file (used to generate cache filename)
            cache_ttl_hours: Maximum age in hours before cache is stale

        Returns:
            Path to cached file if valid and fresh, None otherwise
        """
        url_hash = hash_url(url)
        ext = Path(url).suffix or ".bin"
        cache_path = self.cache_dir / f"{url_hash}{ext}"

        global hits
        if cache_path.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
            if age.total_seconds() < cache_ttl_hours * 3600:
                logger.info(f"Using cached file: {cache_path}")
                hits += 1
                return cache_path

        return None

    def download(
        self,
        url: str,
        cache_ttl_hours: int = 24,
        force_refresh: bool = False,
        headers: dict | None = None,
    ) -> Path:
        """Download a file with caching support.

        Downloads a file from the given URL and caches it locally. If a valid
        cached version exists, returns that instead.

        Args:
            url: URL to download
            cache_ttl_hours: Cache validity in hours (default: 24)
            force_refresh: If True, bypass cache and re-download
            headers: Optional extra HTTP headers to include in the request
                (e.g. ``{"Referer": "...", "User-Agent": "..."}``)

        Returns:
            Path to the downloaded (or cached) file

        Raises:
            DownloadError: If download fails due to network or HTTP errors
        """
        # Check cache first
        if not force_refresh:
            cached = self.get_cached_file(url, cache_ttl_hours)
            if cached:
                return cached

        # Download the file
        global misses
        misses += 1
        url_hash = hash_url(url)
        ext = Path(url).suffix or ".bin"
        cache_path = self.cache_dir / f"{url_hash}{ext}"

        try:
            logger.info(f"Downloading {url}")
            # Use shared session with retry logic for resilient downloads
            response = web_session.get(url, timeout=self.timeout, headers=headers)
            response.raise_for_status()

            cache_path.write_bytes(response.content)
            size_mb = len(response.content) / 1024 / 1024
            logger.info(f"Saved to {cache_path} ({size_mb:.1f} MB)")
            return cache_path

        except Exception as e:
            raise DownloadError(f"Failed to download {url}: {e}") from e

    def clear(self, pattern: str | None = None) -> int:
        """Clear cached files.

        Args:
            pattern: Optional glob pattern (e.g., ``*.csv``). If None, clears all.

        Returns:
            Number of files deleted
        """
        files = list(self.cache_dir.glob(pattern)) if pattern else list(self.cache_dir.glob("*"))

        deleted = 0
        for file in files:
            if file.is_file():
                file.unlink()
                deleted += 1
                logger.info(f"Deleted {file}")

        logger.info(f"Cleared {deleted} cached files from {self.namespace}")
        return deleted


def bind_download_file(
    downloader: CachedDownloader,
    error_cls: type[Exception],
    default_ttl_hours: int,
) -> Callable[..., Path]:
    """Build a module-level ``download_file`` bound to one downloader.

    Every publication-catalogue module (``dfc.child_maintenance``,
    ``justice.pps_statistical_bulletin``, and similar) defines a
    near-identical five-line ``download_file`` that just wraps
    :meth:`CachedDownloader.download` and converts :class:`DownloadError`
    to the module's own not-found exception. This is that wrapper, factored
    out so it isn't independently reimplemented per module (see issue #2072).

    Args:
        downloader: The module's ``CachedDownloader`` instance.
        error_cls: Exception class to raise in place of ``DownloadError``.
        default_ttl_hours: Default ``cache_ttl_hours`` for the returned function.

    Returns:
        A ``download_file(url, cache_ttl_hours=default_ttl_hours, force_refresh=False) -> Path``
        function bound to ``downloader``.

    Example:
        >>> class _NotFoundError(Exception): pass
        >>> _dl = CachedDownloader("doctest-bind-download-file")
        >>> download_file = bind_download_file(_dl, _NotFoundError, 24)
        >>> download_file.__name__
        'download_file'
    """

    def download_file(url: str, cache_ttl_hours: int = default_ttl_hours, force_refresh: bool = False) -> Path:
        try:
            return downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
        except DownloadError as e:
            raise error_cls(str(e)) from e

    return download_file


def stitch_publications(
    publications: list[dict],
    fetch_one: Callable[[dict], pd.DataFrame],
    dedup_keys: list[str],
    sort_keys: list[str] | None = None,
    errors: tuple[type[Exception], ...] = (Exception,),
) -> pd.DataFrame:
    """Download, parse, and merge several publications into one tidy frame.

    Several short-window data sources (e.g. quarterly bulletins that only
    show the last few periods) recover their full back series by merging
    consecutive releases — each module reimplemented the same download-parse-
    skip-concat-dedup-sort shape to do it (see issue #2072). This is that
    shape, factored out.

    A per-publication failure is logged and skipped rather than aborting the
    whole merge — one broken publication in the middle of a back-series pull
    shouldn't cost the ones on either side of it.

    Args:
        publications: Publication records, as returned by a module's own
            ``list_publications()``, newest first.
        fetch_one: Downloads and parses a single publication record into a
            DataFrame in the module's canonical shape. Raising is treated as
            "skip this publication."
        dedup_keys: Columns identifying a duplicate row across publications.
        sort_keys: Columns to sort the result by. Defaults to ``dedup_keys``.
        errors: Exception types from ``fetch_one`` that are caught, logged,
            and skipped rather than propagated. Defaults to catching anything,
            since a single publication's parse failure is exactly the case
            this function exists to tolerate.

    Returns:
        Concatenated frame, deduplicated on ``dedup_keys`` (first occurrence —
        i.e. the newest publication — wins), sorted by ``sort_keys``.

    Raises:
        ValueError: If every publication failed and nothing could be merged.

    Example:
        >>> import pandas as pd
        >>> pubs = [{"url": "a"}, {"url": "b"}]
        >>> def fetch(pub):
        ...     return pd.DataFrame({"id": [1, 2], "value": [pub["url"], pub["url"]]})
        >>> stitch_publications(pubs, fetch, dedup_keys=["id"])["value"].tolist()
        ['a', 'a']
    """
    logger_ = logging.getLogger(__name__)
    frames = []
    for publication in publications:
        try:
            frames.append(fetch_one(publication))
        except errors as e:
            logger_.warning("Skipping publication %s: %s", publication.get("url", publication), e)

    if not frames:
        raise ValueError("No publications could be parsed")

    keys = sort_keys or dedup_keys
    df = pd.concat(frames, ignore_index=True)
    return df.drop_duplicates(subset=dedup_keys, keep="first").sort_values(keys).reset_index(drop=True)
