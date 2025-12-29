"""Common utilities for PSNI data sources."""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path.home() / ".cache" / "bolster" / "psni"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class PSNIDataError(Exception):
    """Base exception for PSNI data errors."""

    pass


class PSNIDataNotFoundError(PSNIDataError):
    """Data file not available."""

    pass


class PSNIValidationError(PSNIDataError):
    """Data validation failed."""

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


def hash_url(url: str) -> str:
    """Generate a safe filename from a URL."""
    return hashlib.md5(url.encode()).hexdigest()


def get_cached_file(url: str, cache_ttl_hours: int = 24) -> Optional[Path]:
    """Return cached file if exists and fresh, else None.

    Args:
        url: URL of the file
        cache_ttl_hours: Cache validity in hours

    Returns:
        Path to cached file if valid, None otherwise
    """
    url_hash = hash_url(url)
    ext = Path(url).suffix or ".bin"
    cache_path = CACHE_DIR / f"{url_hash}{ext}"

    if cache_path.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if age.total_seconds() < cache_ttl_hours * 3600:
            logger.info(f"Using cached file: {cache_path}")
            return cache_path

    return None


def download_file(url: str, cache_ttl_hours: int = 24, force_refresh: bool = False) -> Path:
    """Download a file with caching support.

    Args:
        url: URL to download
        cache_ttl_hours: Cache validity in hours (default: 24)
        force_refresh: Force re-download even if cached

    Returns:
        Path to downloaded file

    Raises:
        PSNIDataNotFoundError: If download fails
    """
    # Check cache first
    if not force_refresh:
        cached = get_cached_file(url, cache_ttl_hours)
        if cached:
            return cached

    # Download the file
    url_hash = hash_url(url)
    ext = Path(url).suffix or ".bin"
    cache_path = CACHE_DIR / f"{url_hash}{ext}"

    try:
        logger.info(f"Downloading {url}")
        response = requests.get(url, timeout=60)  # Longer timeout for large files
        response.raise_for_status()

        cache_path.write_bytes(response.content)
        logger.info(f"Saved to {cache_path} ({len(response.content) / 1024 / 1024:.1f} MB)")
        return cache_path

    except requests.RequestException as e:
        raise PSNIDataNotFoundError(f"Failed to download {url}: {e}")


def clear_cache(pattern: Optional[str] = None):
    """Clear cached files.

    Args:
        pattern: Optional glob pattern to match specific files (e.g., "*.csv")
                 If None, clears all cached files
    """
    if pattern:
        files = list(CACHE_DIR.glob(pattern))
    else:
        files = list(CACHE_DIR.glob("*"))

    for file in files:
        if file.is_file():
            file.unlink()
            logger.info(f"Deleted {file}")

    logger.info(f"Cleared {len(files)} cached files")
