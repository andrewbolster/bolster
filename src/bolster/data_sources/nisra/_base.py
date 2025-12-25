"""Common utilities for NISRA data sources."""

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path.home() / ".cache" / "bolster" / "nisra"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class NISRADataError(Exception):
    """Base exception for NISRA data errors."""

    pass


class NISRADataNotFoundError(NISRADataError):
    """Data file not available."""

    pass


class NISRAValidationError(NISRADataError):
    """Data validation failed."""

    pass


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
    # Create a safe filename from URL
    url_hash = hash_url(url)
    # Extract file extension from URL
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
        NISRADataNotFoundError: If download fails
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
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        cache_path.write_bytes(response.content)
        logger.info(f"Saved to {cache_path}")
        return cache_path

    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to download {url}: {e}")


def scrape_download_links(page_url: str, file_extension: str = ".xlsx") -> list[dict]:
    """Scrape download links from a NISRA page.

    Args:
        page_url: URL of the NISRA page to scrape
        file_extension: File extension to filter for (default: .xlsx)

    Returns:
        List of dicts with 'url' and 'text' keys
    """
    try:
        response = requests.get(page_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise NISRADataError(f"Failed to fetch page {page_url}: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if file_extension in href.lower():
            # Make absolute URL
            if href.startswith("/"):
                url = f"https://www.nisra.gov.uk{href}"
            elif not href.startswith("http"):
                url = f"https://www.nisra.gov.uk/{href}"
            else:
                url = href

            links.append({"url": url, "text": a_tag.get_text(strip=True)})

    return links


def clear_cache(pattern: Optional[str] = None):
    """Clear cached files.

    Args:
        pattern: Optional glob pattern to match specific files (e.g., "*.xlsx")
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


# Excel parsing utilities


def safe_int(val) -> Optional[int]:
    """Safely convert a value to integer, handling None, '', and '-' placeholders.

    Args:
        val: Value to convert (can be int, float, str, or None)

    Returns:
        Integer value or None if conversion fails or value is placeholder
    """
    if val is None or val == "" or val == "-":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def safe_float(val) -> Optional[float]:
    """Safely convert a value to float, handling None, '', and '-' placeholders.

    Args:
        val: Value to convert (can be int, float, str, or None)

    Returns:
        Float value or None if conversion fails or value is placeholder
    """
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def find_header_row(sheet, expected_columns: list[str], max_rows: int = 20) -> Optional[int]:
    """Find the row number containing expected column headers in an Excel sheet.

    Args:
        sheet: openpyxl worksheet object
        expected_columns: List of column names to search for (case-insensitive, partial match)
        max_rows: Maximum number of rows to search (default: 20)

    Returns:
        1-based row number where headers are found, or None if not found

    Example:
        >>> sheet = wb['Table 1a']
        >>> header_row = find_header_row(sheet, ['Week Ending', 'Total Deaths'])
        >>> # Returns 4 if headers are in row 4
    """
    for row_idx, row in enumerate(sheet.iter_rows(min_row=1, max_row=max_rows, values_only=True), 1):
        # Convert row to lowercase strings for comparison
        row_str = [str(cell).lower() if cell else "" for cell in row]

        # Check if all expected columns are present (partial match)
        matches = 0
        for expected in expected_columns:
            expected_lower = expected.lower()
            if any(expected_lower in cell for cell in row_str):
                matches += 1

        # If we found all expected columns, this is likely the header row
        if matches == len(expected_columns):
            logger.debug(f"Found header row at row {row_idx}")
            return row_idx

    logger.warning(f"Could not find header row with columns: {expected_columns}")
    return None


def extract_column_mapping(sheet, header_row: int, column_names: List[str]) -> Dict[str, int]:
    """Extract a mapping of column names to their indices (0-based) from a header row.

    Args:
        sheet: openpyxl worksheet object
        header_row: 1-based row number containing headers
        column_names: List of column names to find (case-insensitive, partial match)

    Returns:
        Dictionary mapping column names to 0-based column indices

    Example:
        >>> mapping = extract_column_mapping(sheet, 4, ['Week Ending', 'Total Deaths'])
        >>> # Returns {'Week Ending': 1, 'Total Deaths': 3}
        >>> week_ending_idx = mapping['Week Ending']
    """
    headers = list(sheet[header_row])
    mapping = {}

    for col_name in column_names:
        col_name_lower = col_name.lower()

        # Search for matching column
        for idx, cell in enumerate(headers):
            if cell.value and col_name_lower in str(cell.value).lower():
                mapping[col_name] = idx
                break

    # Log any missing columns
    missing = set(column_names) - set(mapping.keys())
    if missing:
        logger.warning(f"Could not find columns: {missing}")

    return mapping


def parse_age_breakdowns(row, age_columns_map: Dict[str, int], start_idx: int = None) -> List[dict]:
    """Parse age breakdown columns into a list of age band dictionaries.

    This creates a flexible structure that can handle changing age bands across years.

    Args:
        row: Excel row tuple (values_only=True)
        age_columns_map: Mapping of age range labels to column indices
                        e.g., {'0-7 days': 20, '7 days-1 year': 21, ...}
        start_idx: If age columns are sequential, just provide the starting index
                   and it will use positional extraction

    Returns:
        List of dicts with 'age_range' and 'deaths' keys

    Example:
        >>> age_map = {'0-7 days': 20, '7 days-1 year': 21, '1-14': 22}
        >>> result = parse_age_breakdowns(row, age_map)
        >>> # [{'age_range': '0-7 days', 'deaths': 1}, ...]
    """
    age_breakdowns = []

    for age_range, col_idx in age_columns_map.items():
        deaths = safe_int(row[col_idx])
        if deaths is not None:  # Only include if we have data
            age_breakdowns.append({"age_range": age_range, "deaths": deaths})

    return age_breakdowns
