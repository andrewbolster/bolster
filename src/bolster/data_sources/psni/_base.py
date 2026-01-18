"""Common utilities for PSNI data sources.

This module provides shared functionality for all PSNI (Police Service of
Northern Ireland) data source modules, including:

- **Caching**: Download and cache data files with configurable TTL
- **Geographic codes**: LGD and NUTS3 code mappings for cross-dataset integration
- **Exceptions**: Standardized error handling for data operations

Cache Location:
    Files are cached in ``~/.cache/bolster/psni/`` with filenames based on
    URL hashes. Cache validity is configurable per-request.

Geographic Code Systems:
    - **LGD codes** (N09000XXX): ONS Local Government District codes for NI
    - **NUTS3 codes** (UKN0X): EU statistical region codes for aggregation

Example:
    >>> from bolster.data_sources.psni._base import get_lgd_code, get_nuts3_code
    >>> get_lgd_code("Belfast City")
    'N09000003'
    >>> get_nuts3_code("Belfast City")
    'UKN01'
"""

import logging
from pathlib import Path
from typing import Optional

from bolster.utils.cache import CachedDownloader, DownloadError

logger = logging.getLogger(__name__)

# Shared downloader instance for PSNI data sources
_downloader = CachedDownloader("psni", timeout=60)


class PSNIDataError(Exception):
    """Base exception for PSNI data errors.

    All PSNI-specific exceptions inherit from this class, allowing
    callers to catch all PSNI errors with a single except clause.
    """

    pass


class PSNIDataNotFoundError(PSNIDataError):
    """Raised when a PSNI data file cannot be downloaded or accessed.

    This exception is raised when:
    - Network requests fail (timeout, connection errors)
    - HTTP errors occur (404, 500, etc.)
    - The requested resource is unavailable
    """

    pass


class PSNIValidationError(PSNIDataError):
    """Raised when PSNI data fails validation checks.

    This exception is raised when:
    - CSV structure doesn't match expected columns
    - Data contains invalid or unexpected values
    - Required fields are missing or malformed
    """

    pass


# Geographic Code Mappings
# Policing Districts map 1:1 to Local Government Districts (LGDs) established 2015
# This enables cross-comparison with other NISRA datasets

LGD_CODES = {
    "Antrim & Newtownabbey": "N09000001",
    "Ards & North Down": "N09000011",
    "Armagh City Banbridge & Craigavon": "N09000002",
    "Belfast City": "N09000003",
    "Causeway Coast & Glens": "N09000004",
    "Derry City & Strabane": "N09000005",
    "Fermanagh & Omagh": "N09000006",
    "Lisburn & Castlereagh City": "N09000007",
    "Mid & East Antrim": "N09000008",
    "Mid Ulster": "N09000009",
    "Newry Mourne & Down": "N09000010",
}

# NUTS3 regional codes for aggregation
# NUTS = Nomenclature of Territorial Units for Statistics (EU standard)
NUTS3_CODES = {
    "Belfast City": "UKN01",  # Belfast
    "Lisburn & Castlereagh City": "UKN06",  # Outer Belfast
    "Antrim & Newtownabbey": "UKN06",  # Outer Belfast
    "Ards & North Down": "UKN06",  # Outer Belfast
    "Armagh City Banbridge & Craigavon": "UKN05",  # West and South of NI
    "Newry Mourne & Down": "UKN05",  # West and South of NI
    "Mid Ulster": "UKN05",  # West and South of NI
    "Fermanagh & Omagh": "UKN03",  # West and South of NI
    "Derry City & Strabane": "UKN02",  # Outer Belfast
    "Causeway Coast & Glens": "UKN04",  # East of NI
    "Mid & East Antrim": "UKN04",  # East of NI
}

# NUTS region names for reference
# Source: ONS NUTS Level 3 (January 2024) Names and Codes
NUTS_REGION_NAMES = {
    "UKN01": "Belfast",
    "UKN02": "Outer Belfast",
    "UKN03": "West and South of Northern Ireland",
    "UKN04": "East of Northern Ireland",
    "UKN05": "West and South of Northern Ireland",
    "UKN06": "Outer Belfast",
}


def get_lgd_code(district_name: str) -> Optional[str]:
    """Get LGD code for a policing district.

    Args:
        district_name: Policing district name (e.g., "Belfast City")

    Returns:
        LGD code (e.g., "N09000003") or None if not found

    Example:
        >>> get_lgd_code("Belfast City")
        'N09000003'
    """
    return LGD_CODES.get(district_name)


def get_nuts3_code(district_name: str) -> Optional[str]:
    """Get NUTS3 regional code for a policing district.

    Args:
        district_name: Policing district name (e.g., "Belfast City")

    Returns:
        NUTS3 code (e.g., "UKN01") or None if not found

    Example:
        >>> get_nuts3_code("Belfast City")
        'UKN01'
    """
    return NUTS3_CODES.get(district_name)


def get_nuts_region_name(nuts3_code: str) -> Optional[str]:
    """Get descriptive name for a NUTS3 region code.

    Args:
        nuts3_code: NUTS3 code (e.g., "UKN01")

    Returns:
        Region name (e.g., "Belfast") or None if not found

    Example:
        >>> get_nuts_region_name("UKN01")
        'Belfast'
    """
    return NUTS_REGION_NAMES.get(nuts3_code)


def download_file(url: str, cache_ttl_hours: int = 24, force_refresh: bool = False) -> Path:
    """Download a file with caching support.

    Downloads a file from the given URL and caches it locally. If a valid
    cached version exists, returns that instead. Uses a 60-second timeout
    for network requests.

    Args:
        url: URL to download
        cache_ttl_hours: Cache validity in hours (default: 24)
        force_refresh: If True, bypass cache and re-download

    Returns:
        Path to the downloaded (or cached) file

    Raises:
        PSNIDataNotFoundError: If download fails due to network or HTTP errors

    Example:
        >>> from bolster.data_sources.psni._base import download_file
        >>> path = download_file(
        ...     "https://example.com/data.csv",
        ...     cache_ttl_hours=24
        ... )  # doctest: +SKIP
    """
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise PSNIDataNotFoundError(str(e)) from e


def clear_cache(pattern: Optional[str] = None) -> int:
    """Clear cached files from the PSNI cache directory.

    Args:
        pattern: Optional glob pattern to match specific files (e.g., "*.csv").
                 If None, clears all cached files in the directory.

    Returns:
        Number of files deleted

    Example:
        >>> from bolster.data_sources.psni._base import clear_cache
        >>> deleted = clear_cache("*.csv")  # doctest: +SKIP
    """
    return _downloader.clear(pattern)
