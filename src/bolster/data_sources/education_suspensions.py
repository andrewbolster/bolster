"""Pupil Suspensions and Expulsions in Northern Ireland.

Provides access to annual suspension and expulsion statistics for pupils of
compulsory school age in Northern Ireland, published by the Department of
Education Northern Ireland (DE NI).

Data covers pupil suspensions broken down by:
- Trend over time (Table 1, from 2011/12 to present)
- School type (Primary, Non Grammar, Grammar, Special) (Table 2)
- School management type (Controlled, Voluntary, etc.) (Table 3)
- Number of suspension occasions (Once, Twice, Three or more) (Table 4)
- Suspension duration (Table 5)
- Key Stage (Foundation/KS1, KS2, KS3, KS4) (Table 6)
- Pupil characteristics (sex, age, ethnicity, SEN, religion) (Table 7)
- Education Authority Region (Table 8)
- Reason for suspension (Table 9)

Data Source:
    **Stable Entry Point**: https://www.education-ni.gov.uk/articles/pupil-suspensions-and-expulsions

    The module scrapes the articles page to find the latest publication link,
    then scrapes the publication page for the Excel data file URL.

Update Frequency: Annual
Geographic Coverage: Northern Ireland
Reference Period: 2011/12 – present

Example:
    >>> from bolster.data_sources.education_suspensions import get_latest_suspensions
    >>> df = get_latest_suspensions()
    >>> 'academic_year' in df.columns
    True
"""

import hashlib
import logging
from pathlib import Path
from urllib.parse import urljoin

import bs4
import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Stable entry point – lists all annual publications
ARTICLES_URL = "https://www.education-ni.gov.uk/articles/pupil-suspensions-and-expulsions"
BASE_URL = "https://www.education-ni.gov.uk"

# Cache directory for downloaded files (annual data – 7 day TTL is ample)
CACHE_DIR = Path.home() / ".cache" / "bolster" / "education_suspensions"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_CACHE_TTL_HOURS = 24 * 7  # 1 week


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EducationSuspensionsError(Exception):
    """Base exception for education suspensions data errors."""


class EducationSuspensionsNotFoundError(EducationSuspensionsError):
    """Raised when the data file or publication page cannot be found."""


class EducationSuspensionsParseError(EducationSuspensionsError):
    """Raised when parsing the data file fails in an unexpected way."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hash_url(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _cached_file(url: str) -> Path | None:
    """Return path to a cached copy of *url* if it exists and is fresh."""
    url_hash = _hash_url(url)
    ext = Path(url.split("?")[0]).suffix or ".xlsx"
    cache_path = CACHE_DIR / f"{url_hash}{ext}"
    if cache_path.exists():
        from datetime import datetime

        age_hours = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).total_seconds() / 3600
        if age_hours < _CACHE_TTL_HOURS:
            logger.debug("Using cached file: %s", cache_path)
            return cache_path
    return None


def _download_file(url: str, force_refresh: bool = False) -> Path:
    """Download *url* to the local cache, returning the cache path."""
    if not force_refresh:
        cached = _cached_file(url)
        if cached:
            return cached

    url_hash = _hash_url(url)
    ext = Path(url.split("?")[0]).suffix or ".xlsx"
    cache_path = CACHE_DIR / f"{url_hash}{ext}"

    try:
        logger.info("Downloading %s", url)
        response = session.get(url, timeout=60)
        response.raise_for_status()
        cache_path.write_bytes(response.content)
        logger.info("Saved to %s", cache_path)
        return cache_path
    except Exception as exc:
        raise EducationSuspensionsNotFoundError(f"Failed to download {url}: {exc}") from exc


def _extract_data_rows(ws_rows: list[tuple], header_row_idx: int) -> pd.DataFrame:
    """Build a DataFrame from raw worksheet rows given the 0-based header row index."""
    header = ws_rows[header_row_idx]
    data = ws_rows[header_row_idx + 1 :]
    df = pd.DataFrame(data, columns=header)
    # Drop fully-None columns and fully-None rows
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    # The first column of every table is None (blank leading column in Excel)
    if df.columns[0] is None:
        df = df.iloc[:, 1:]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public: URL discovery
# ---------------------------------------------------------------------------


def get_suspensions_publication_url() -> str:
    """Scrape education-ni.gov.uk to find the latest suspensions XLSX URL.

    The function follows a two-step chain:
    1. Fetches the stable articles page and extracts the most recent
       publications link for pupil suspensions/expulsions.
    2. Fetches that publication page and extracts the XLSX download link.

    Returns:
        Absolute URL of the latest suspensions XLSX file.

    Raises:
        EducationSuspensionsNotFoundError: If the publication or XLSX link
            cannot be found.
    """
    # Step 1 – find the most recent publication page
    try:
        resp = session.get(ARTICLES_URL, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise EducationSuspensionsNotFoundError(f"Failed to fetch articles page {ARTICLES_URL}: {exc}") from exc

    soup = bs4.BeautifulSoup(resp.content, "html.parser")
    pub_href = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "suspension" in href.lower() and "/publications/" in href:
            pub_href = href
            break  # first match is the most recent

    if not pub_href:
        raise EducationSuspensionsNotFoundError(f"Could not find a suspensions publication link on {ARTICLES_URL}")

    pub_url = urljoin(BASE_URL, pub_href)
    logger.info("Found publication page: %s", pub_url)

    # Step 2 – find the XLSX on that publication page
    try:
        resp2 = session.get(pub_url, timeout=30)
        resp2.raise_for_status()
    except Exception as exc:
        raise EducationSuspensionsNotFoundError(f"Failed to fetch publication page {pub_url}: {exc}") from exc

    soup2 = bs4.BeautifulSoup(resp2.content, "html.parser")
    for a in soup2.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".xlsx") or href.lower().endswith(".xls"):
            xlsx_url = href if href.startswith("http") else urljoin(BASE_URL, href)
            logger.info("Found XLSX URL: %s", xlsx_url)
            return xlsx_url

    raise EducationSuspensionsNotFoundError(f"Could not find XLSX link on publication page {pub_url}")


# ---------------------------------------------------------------------------
# Public: Parsing
# ---------------------------------------------------------------------------


def parse_suspensions_file(file_path: str | Path) -> pd.DataFrame:
    """Parse the DE NI suspensions XLSX file into a tidy DataFrame.

    Reads Table 1 (annual trend) and produces one row per academic year
    with standardised column names.  Table 1 is the only table with a
    multi-year time series; the remaining tables are single-year snapshots
    and are intentionally not included in the tidy output (use
    :func:`parse_all_tables` for those).

    Args:
        file_path: Path to the downloaded XLSX file.

    Returns:
        DataFrame with columns:
            - ``academic_year``: Academic year string, e.g. ``"2024/25"``
            - ``pupils_suspended``: Number of pupils suspended (int)
            - ``pct_pupils_suspended``: Percentage of all pupils suspended (float, 0–1)

    Raises:
        EducationSuspensionsParseError: If the file cannot be parsed.
    """
    try:
        wb_dict = pd.read_excel(file_path, sheet_name=None, header=None)
    except Exception as exc:
        raise EducationSuspensionsParseError(f"Failed to read Excel file {file_path}: {exc}") from exc

    if "Table 1" not in wb_dict:
        raise EducationSuspensionsParseError("Expected sheet 'Table 1' not found in workbook")

    raw = wb_dict["Table 1"]

    # Locate header row: the row that contains 'Year' in column B (index 1)
    header_row = None
    for i, row in raw.iterrows():
        if str(row.iloc[1]).strip() == "Year":
            header_row = i
            break

    if header_row is None:
        raise EducationSuspensionsParseError("Could not locate header row in Table 1")

    # Slice from header row onwards
    df = raw.iloc[header_row:].copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)

    # Keep only columns B (Year) and C (pupils suspended) and D (percentage)
    # The Excel has a blank leading column A, so after reset our useful columns
    # are at positions 1, 2, 3 (0-based).
    df = df.iloc[:, 1:4].copy()
    df.columns = ["academic_year", "pupils_suspended", "pct_pupils_suspended"]

    # Drop summary/footer rows (non-year values in academic_year column)
    df = df[df["academic_year"].notna()].copy()
    df = df[df["academic_year"].astype(str).str.match(r"^\d{4}/\d{2}$")].copy()

    # Coerce types
    df["academic_year"] = df["academic_year"].astype(str)
    df["pupils_suspended"] = pd.to_numeric(df["pupils_suspended"], errors="coerce").astype("Int64")
    df["pct_pupils_suspended"] = pd.to_numeric(df["pct_pupils_suspended"], errors="coerce")

    return df.reset_index(drop=True)


def parse_all_tables(file_path: str | Path) -> dict[str, pd.DataFrame]:
    """Parse all tables from the DE NI suspensions XLSX into a dict of DataFrames.

    Each table is lightly cleaned (blank leading column removed, empty rows/cols
    dropped) but otherwise returned in its natural structure.

    Args:
        file_path: Path to the downloaded XLSX file.

    Returns:
        Dictionary mapping sheet names to DataFrames.

    Raises:
        EducationSuspensionsParseError: If the file cannot be read.
    """
    try:
        wb_dict = pd.read_excel(file_path, sheet_name=None, header=None)
    except Exception as exc:
        raise EducationSuspensionsParseError(f"Failed to read Excel file {file_path}: {exc}") from exc

    result: dict[str, pd.DataFrame] = {}
    for sheet_name, raw_df in wb_dict.items():
        if sheet_name == "Table of contents":
            continue
        # Locate header row (first row after the title rows, identified by
        # a non-None value in column B that is a string)
        header_row = None
        for i, row in raw_df.iterrows():
            val = row.iloc[1]
            if val is not None and isinstance(val, str) and val.strip() and not val.strip().startswith("Table"):
                header_row = i
                break
        if header_row is None:
            result[sheet_name] = raw_df
            continue

        df = raw_df.iloc[header_row:].copy()
        df.columns = df.iloc[0]
        df = df.iloc[1:].reset_index(drop=True)
        # Drop blank leading column
        if df.columns[0] is None:
            df = df.iloc[:, 1:]
        # Drop fully None columns and rows, and rows after the first total/source row
        df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
        # Truncate at rows where all data columns are None (footer notes)
        first_col = df.columns[0]
        footer_mask = df[first_col].isna() | df[first_col].astype(str).str.startswith("Source")
        if footer_mask.any():
            first_footer = footer_mask.idxmax()
            df = df.loc[: first_footer - 1]
        result[sheet_name] = df.reset_index(drop=True)

    return result


# ---------------------------------------------------------------------------
# Public: High-level entry points
# ---------------------------------------------------------------------------


def get_latest_suspensions(force_refresh: bool = False) -> pd.DataFrame:
    """Download and return the latest NI pupil suspensions time-series data.

    This is the main entry point.  Returns Table 1 (annual trend) parsed
    into a tidy DataFrame via :func:`parse_suspensions_file`.

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with columns ``academic_year``, ``pupils_suspended``,
        ``pct_pupils_suspended``.

    Raises:
        EducationSuspensionsNotFoundError: If the source cannot be located.
        EducationSuspensionsParseError: If the file cannot be parsed.

    Example:
        >>> df = get_latest_suspensions()
        >>> 'academic_year' in df.columns
        True
    """
    xlsx_url = get_suspensions_publication_url()
    file_path = _download_file(xlsx_url, force_refresh=force_refresh)
    return parse_suspensions_file(file_path)


def validate_suspensions_data(df: pd.DataFrame) -> bool:
    """Validate the structure and basic integrity of a suspensions DataFrame.

    Checks performed:
    - Required columns present
    - At least one row of data
    - ``pupils_suspended`` values are non-negative
    - ``pct_pupils_suspended`` values are in [0, 1]

    Args:
        df: DataFrame as returned by :func:`parse_suspensions_file` or
            :func:`get_latest_suspensions`.

    Returns:
        ``True`` if the data passes all checks.

    Raises:
        ValueError: If any check fails, with a descriptive message.
    """
    required = {"academic_year", "pupils_suspended", "pct_pupils_suspended"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if len(df) == 0:
        raise ValueError("DataFrame is empty")

    if (df["pupils_suspended"].dropna() < 0).any():
        raise ValueError("pupils_suspended contains negative values")

    pct = df["pct_pupils_suspended"].dropna()
    if (pct < 0).any() or (pct > 1).any():
        raise ValueError("pct_pupils_suspended values outside [0, 1]")

    return True
