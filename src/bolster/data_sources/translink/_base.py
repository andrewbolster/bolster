"""Common utilities for Translink data sources."""

import logging
from pathlib import Path

from bolster.utils.cache import CachedDownloader, DownloadError

logger = logging.getLogger(__name__)

_downloader = CachedDownloader("translink", timeout=30)

TRANSLINK_BASE_URL = "https://www.translink.co.uk"
VMI_URL = "https://vpos.translinkniplanner.co.uk/velocmap/vmi/VMI"

OPENDATANI_METRO_GLIDER_URL = (
    "https://admin.opendatani.gov.uk/dataset/6d9677cf-8d03-4851-985c-16f73f7dd5fb"
    "/resource/f2c58049-7ca9-4576-b3bd-1b3d8a8674e0/download/metro-glider-16042026.zip"
)
OPENDATANI_ULSTERBUS_URL = (
    "https://admin.opendatani.gov.uk/dataset/c1acee5b-a400-46bd-a795-9bf7637ff879"
    "/resource/291cbb54-7bb3-4df7-8599-0c8f49a20be6/download/ulb-gle-16042026.zip"
)

# .NET ticks epoch offset (100ns ticks since 0001-01-01 → Unix seconds)
_NET_TICKS_EPOCH = 621_355_968_000_000_000
_NET_TICKS_PER_SECOND = 10_000_000


def net_ticks_to_timestamp(ticks: int):
    """Convert a .NET DateTime ticks value to a pandas Timestamp (UTC)."""
    import pandas as pd

    unix_seconds = (ticks - _NET_TICKS_EPOCH) / _NET_TICKS_PER_SECOND
    return pd.Timestamp(unix_seconds, unit="s", tz="UTC")


# Operator code normalisation: VMI uses TM for Metro buses
OPERATOR_ALIASES = {"TM": "MET"}

KNOWN_OPERATORS = {"FY", "GLE", "GDR", "MET", "TM", "ULB", "UTS"}


class TranslinkDataError(Exception):
    """Base exception for Translink data errors."""


class TranslinkDataNotFoundError(TranslinkDataError):
    """Raised when a Translink endpoint or resource cannot be reached."""


class TranslinkValidationError(TranslinkDataError):
    """Raised when Translink data fails validation checks."""


def download_file(
    url: str,
    cache_ttl_hours: int = 24,
    force_refresh: bool = False,
) -> Path:
    """Download a file with caching. Raises TranslinkDataNotFoundError on failure."""
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise TranslinkDataNotFoundError(str(e)) from e


def clear_cache(pattern: str | None = None) -> int:
    """Clear cached Translink files. Returns number of files deleted."""
    return _downloader.clear(pattern)
