"""File caching utilities for data sources.

Provides disk-based caching for downloaded files with configurable TTL.
Used by NISRA, PSNI, and other data source modules to avoid repeated
downloads of the same resources.

Cache Location:
    Files are cached in ``~/.cache/bolster/<namespace>/`` with filenames
    based on URL hashes. Each data source uses its own namespace.

Example:
    >>> from bolster.utils.cache import CachedDownloader
    >>> downloader = CachedDownloader("my_source")
    >>> path = downloader.download("https://example.com/data.csv", cache_ttl_hours=24)
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .web import session as web_session

logger = logging.getLogger(__name__)

# Base cache directory
CACHE_BASE = Path.home() / ".cache" / "bolster"


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
    return hashlib.md5(url.encode()).hexdigest()


class CachedDownloader:
    """Disk-based file cache with TTL support.

    Provides download-with-cache functionality for data source modules.
    Each instance uses a namespace subdirectory for isolation.

    Args:
        namespace: Subdirectory name for this cache (e.g., "nisra", "psni")
        timeout: Request timeout in seconds (default: 60)

    Example:
        >>> downloader = CachedDownloader("psni", timeout=60)
        >>> path = downloader.download(
        ...     "https://example.com/data.csv",
        ...     cache_ttl_hours=24
        ... )  # doctest: +SKIP
    """

    def __init__(self, namespace: str, timeout: int = 60):
        self.namespace = namespace
        self.timeout = timeout
        self.cache_dir = CACHE_BASE / namespace
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cached_file(self, url: str, cache_ttl_hours: int = 24) -> Optional[Path]:
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

        if cache_path.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
            if age.total_seconds() < cache_ttl_hours * 3600:
                logger.info(f"Using cached file: {cache_path}")
                return cache_path

        return None

    def download(self, url: str, cache_ttl_hours: int = 24, force_refresh: bool = False) -> Path:
        """Download a file with caching support.

        Downloads a file from the given URL and caches it locally. If a valid
        cached version exists, returns that instead.

        Args:
            url: URL to download
            cache_ttl_hours: Cache validity in hours (default: 24)
            force_refresh: If True, bypass cache and re-download

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
        url_hash = hash_url(url)
        ext = Path(url).suffix or ".bin"
        cache_path = self.cache_dir / f"{url_hash}{ext}"

        try:
            logger.info(f"Downloading {url}")
            # Use shared session with retry logic for resilient downloads
            response = web_session.get(url, timeout=self.timeout)
            response.raise_for_status()

            cache_path.write_bytes(response.content)
            size_mb = len(response.content) / 1024 / 1024
            logger.info(f"Saved to {cache_path} ({size_mb:.1f} MB)")
            return cache_path

        except Exception as e:
            raise DownloadError(f"Failed to download {url}: {e}")

    def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cached files.

        Args:
            pattern: Optional glob pattern (e.g., ``*.csv``). If None, clears all.

        Returns:
            Number of files deleted
        """
        if pattern:
            files = list(self.cache_dir.glob(pattern))
        else:
            files = list(self.cache_dir.glob("*"))

        deleted = 0
        for file in files:
            if file.is_file():
                file.unlink()
                deleted += 1
                logger.info(f"Deleted {file}")

        logger.info(f"Cleared {deleted} cached files from {self.namespace}")
        return deleted
