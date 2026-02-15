"""Common utilities for NISRA data sources."""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Shared downloader instance for NISRA data sources
_downloader = CachedDownloader("nisra", timeout=30)

# Expose cache directory for modules that need subdirectories
CACHE_DIR = _downloader.cache_dir


class NISRADataError(Exception):
    """Base exception for NISRA data errors."""

    pass


class NISRADataNotFoundError(NISRADataError):
    """Data file not available."""

    pass


class NISRAValidationError(NISRADataError):
    """Data validation failed."""

    pass


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
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise NISRADataNotFoundError(str(e)) from e


def scrape_download_links(page_url: str, file_extension: str = ".xlsx") -> list[dict]:
    """Scrape download links from a NISRA page.

    Args:
        page_url: URL of the NISRA page to scrape
        file_extension: File extension to filter for (default: .xlsx)

    Returns:
        List of dicts with 'url' and 'text' keys
    """
    try:
        response = session.get(page_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataError(f"Failed to fetch page {page_url}: {e}") from e

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


def clear_cache(pattern: Optional[str] = None) -> int:
    """Clear cached files.

    Args:
        pattern: Optional glob pattern to match specific files (e.g., "*.xlsx")
                 If None, clears all cached files

    Returns:
        Number of files deleted
    """
    return _downloader.clear(pattern)


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


def extract_column_mapping(sheet, header_row: int, column_names: list[str]) -> dict[str, int]:
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


def make_absolute_url(url: str, base_url: str) -> str:
    """Convert a relative URL to absolute.

    Args:
        url: URL that may be relative (starting with /) or absolute
        base_url: Base URL to prepend for relative URLs (e.g., "https://www.nisra.gov.uk")

    Returns:
        Absolute URL

    Example:
        >>> make_absolute_url("/publications/file.xlsx", "https://www.nisra.gov.uk")
        'https://www.nisra.gov.uk/publications/file.xlsx'
        >>> make_absolute_url("https://example.com/file.xlsx", "https://www.nisra.gov.uk")
        'https://example.com/file.xlsx'
    """
    if url.startswith("/"):
        return f"{base_url}{url}"
    if not url.startswith("http"):
        return f"{base_url}/{url}"
    return url


def parse_month_year(month_str: str, format: str = "%B %Y") -> Optional[pd.Timestamp]:
    """Parse a month-year string to datetime.

    Args:
        month_str: String like "April 2008" or "Jan 2024"
        format: strftime format string (default: "%B %Y" for full month name)

    Returns:
        pandas Timestamp or None if parsing fails

    Example:
        >>> parse_month_year("April 2008")
        Timestamp('2008-04-01 00:00:00')
        >>> parse_month_year("Jan 2024", format="%b %Y")
        Timestamp('2024-01-01 00:00:00')
    """
    if month_str is None or (isinstance(month_str, str) and month_str.strip() == ""):
        return None

    try:
        return pd.to_datetime(month_str, format=format)
    except (ValueError, TypeError):
        return None


def add_date_columns(df: pd.DataFrame, source_col: str, date_col: str = "date") -> pd.DataFrame:
    """Add standardized date, year, and month columns from a source column.

    Parses a column containing "Month Year" strings (e.g., "April 2008") and adds:
    - date: pandas datetime
    - year: integer year
    - month: full month name (e.g., "January")

    Args:
        df: DataFrame to modify
        source_col: Column name containing "Month Year" strings
        date_col: Name for the date column (default: "date")

    Returns:
        DataFrame with added columns (rows with invalid dates are dropped)

    Example:
        >>> df = pd.DataFrame({"treatment_month": ["April 2008", "May 2008"]})
        >>> df = add_date_columns(df, "treatment_month")
        >>> df.columns.tolist()
        ['treatment_month', 'date', 'year', 'month']
    """
    df = df.copy()
    df[date_col] = df[source_col].apply(parse_month_year)
    df = df.dropna(subset=[date_col])

    # Handle empty DataFrame after dropping invalid dates
    if len(df) == 0:
        df["year"] = pd.Series(dtype=int)
        df["month"] = pd.Series(dtype=str)
        return df

    df["year"] = df[date_col].dt.year.astype(int)
    df["month"] = df[date_col].dt.strftime("%B")
    return df


def parse_age_breakdowns(row, age_columns_map: dict[str, int], start_idx: int = None) -> list[dict]:
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
