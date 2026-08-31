"""NICTS Quarterly Provisional Figures.

Provides access to the Northern Ireland Courts and Tribunals Service (NICTS)
quarterly business statistics, covering caseload across every tier of the NI
court system: receipts, disposals, waiting times, and judicial sitting days.

Ten court datasets are published in a single ODS workbook, one worksheet each:

- ``court_of_appeal_criminal`` - criminal appeals by type and result.
- ``court_of_appeal_civil`` - civil appeals received and disposed.
- ``high_court_chancery_division`` - Chancery business (incl. mortgages).
- ``high_court_kings_bench_division`` - King's Bench writs and outcomes.
- ``high_court_family_division`` - divorce, ancillary relief, and wardship.
- ``crown_court`` - Crown Court cases and defendants.
- ``county_court`` - County Court civil, family, and appeal business.
- ``magistrates_courts`` - Magistrates' Court criminal and civil business.
- ``children_order`` - public and private law Children Order proceedings.
- ``judge_court_sitting_days`` - sitting days and average sitting times.

Every worksheet shares the same period columns, so all ten concatenate into a
single tidy frame. Each row is one (court, category, subcategory, detail,
period) observation.

Data Source:
    **Publication Page**:
    https://www.justice-ni.gov.uk/publications/nicts-business-data

    The module scrapes this page for quarterly ODS bulletins
    (``nicts-quarterly-provisional-figures-<months>-<year>.ods``) and selects
    the most recent. Each bulletin carries the full series from 2017, so a
    single download gives complete history.

Update Frequency: Quarterly
Geographic Coverage: Northern Ireland
Reference Period: 2017 - present (annual totals to 2024, quarterly thereafter)

.. note::
    These are *provisional* figures and are revised in later bulletins. The
    frame mixes annual totals (``2024 Total``) and quarters (``2025 Q1``) in
    the same ``period`` column — filter on ``quarter.isna()`` to separate them,
    or summing across periods will double-count.

Example:
    >>> from bolster.data_sources.justice import nicts_quarterly
    >>> df = nicts_quarterly.get_crown_court()
    >>> set(df["court"]) == {"crown_court"}
    True
    >>> "value" in df.columns
    True
"""

import logging
import re
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
from odf.opendocument import load as load_ods
from odf.table import Table

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import scrape_file_links

from ._base import _parse_value, _sheet_rows, _strip_note_refs

logger = logging.getLogger(__name__)

# Publication landing page listing every quarterly bulletin
PUBLICATION_URL = "https://www.justice-ni.gov.uk/publications/nicts-business-data"

# Worksheets that carry front matter rather than court business data
_NON_DATA_SHEETS = {"cover_sheet", "contents", "notes"}

# Period column headers look like "2024 Total" or "2025 Q1"
_PERIOD_RE = re.compile(r"^(\d{4})\s+(Total|Q[1-4])$")

# Bulletin filenames encode their reporting quarter as a month range
_FILENAME_PERIOD_RE = re.compile(r"(january|april|july|october)\s*to\s*(march|june|september|december)\D{0,4}(\d{4})")
_MONTH_TO_QUARTER = {"january": 1, "april": 2, "july": 3, "october": 4}

# Bulletins are provisional but only republished quarterly
_CACHE_TTL_HOURS = 24 * 90

_downloader = CachedDownloader("nicts_quarterly", timeout=60)


class NICTSDataError(Exception):
    """Base exception for NICTS quarterly figures errors."""

    pass


class NICTSDataNotFoundError(NICTSDataError):
    """Raised when the bulletin cannot be located or downloaded."""

    pass


class NICTSValidationError(NICTSDataError):
    """Raised when parsed data fails validation."""

    pass


def _normalise_sheet_name(name: str) -> str:
    """Convert an ODS worksheet name into a stable court key.

    Worksheet names carry incidental punctuation that varies between bulletins
    (``Court_of_Appeal__Criminal``, ``Magistrates'_Courts``), so they are
    lowercased and reduced to single underscores.

    Args:
        name: Raw worksheet name from the workbook.

    Returns:
        Normalised key, e.g. ``magistrates_courts``.

    Example:
        >>> _normalise_sheet_name("Court_of_Appeal__Criminal")
        'court_of_appeal_criminal'
        >>> _normalise_sheet_name("Magistrates'_Courts")
        'magistrates_courts'
    """
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def _parse_period(label: str) -> tuple[int, int | None] | None:
    """Parse a period column header into (year, quarter).

    Args:
        label: Column header, e.g. ``"2024 Total"`` or ``"2025 Q1"``.

    Returns:
        Tuple of (year, quarter) with quarter ``None`` for annual totals, or
        ``None`` if the label is not a period.

    Example:
        >>> _parse_period("2025 Q3")
        (2025, 3)
        >>> _parse_period("2024 Total")
        (2024, None)
        >>> _parse_period("Business Area") is None
        True
    """
    match = _PERIOD_RE.match(label.strip())
    if not match:
        return None
    year = int(match.group(1))
    marker = match.group(2)
    return year, None if marker == "Total" else int(marker[1])


def _parse_sheet(court: str, rows: list[list[str]]) -> pd.DataFrame:
    """Reshape one court worksheet into tidy long format.

    Each sheet has two or three label columns followed by the shared period
    columns. The label columns are mapped onto ``category`` / ``subcategory`` /
    ``detail``; two-label sheets leave ``detail`` empty.

    Args:
        court: Normalised court key.
        rows: Raw text rows from :func:`_sheet_rows`.

    Returns:
        DataFrame with columns court, category, subcategory, detail, period,
        year, quarter, value. Empty if no header row is found.
    """
    header_idx = None
    for idx, row in enumerate(rows[:10]):
        if any(_parse_period(cell) for cell in row):
            header_idx = idx
            break
    if header_idx is None:
        logger.warning(f"No period header found in sheet {court}; skipping")
        return pd.DataFrame()

    header = rows[header_idx]
    periods = [(col_idx, cell.strip(), _parse_period(cell)) for col_idx, cell in enumerate(header)]
    periods = [(col_idx, label, parsed) for col_idx, label, parsed in periods if parsed]
    n_labels = periods[0][0]

    records = []
    for row in rows[header_idx + 1 :]:
        labels = [_strip_note_refs(cell) for cell in row[:n_labels]]
        if not any(labels):
            continue
        labels += [""] * (3 - len(labels))

        for col_idx, label, parsed in periods:
            year, quarter = parsed
            records.append(
                {
                    "court": court,
                    "category": labels[0] or None,
                    "subcategory": labels[1] or None,
                    "detail": labels[2] or None,
                    "period": label,
                    "year": year,
                    "quarter": quarter,
                    "value": _parse_value(row[col_idx]) if col_idx < len(row) else float("nan"),
                }
            )

    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df["quarter"] = df["quarter"].astype("Int64")
    return df


def list_publications(base_url: str = PUBLICATION_URL) -> list[dict]:
    """List every quarterly bulletin linked from the publication page.

    Args:
        base_url: URL of the NICTS business data listing page.

    Returns:
        List of dicts with ``url``, ``year`` and ``quarter``, newest first.

    Raises:
        NICTSDataNotFoundError: If the page cannot be fetched or no bulletins
            are found.

    Example:
        >>> pubs = list_publications()
        >>> pubs[0]["url"].endswith(".ods")
        True
        >>> pubs[0]["year"] >= pubs[-1]["year"]
        True
    """
    try:
        links = scrape_file_links(base_url, file_extension=".ods")
    except Exception as e:
        raise NICTSDataNotFoundError(f"Failed to fetch publication page {base_url}: {e}") from e

    publications: dict[str, dict] = {}
    for link in links:
        url = link["url"]
        slug = re.sub(r"[^a-z0-9]+", " ", unquote(url).lower())
        match = _FILENAME_PERIOD_RE.search(slug)
        if not match:
            continue
        publications[url] = {
            "url": url,
            "year": int(match.group(3)),
            "quarter": _MONTH_TO_QUARTER[match.group(1)],
        }

    if not publications:
        raise NICTSDataNotFoundError(f"No quarterly bulletins found on {base_url}")

    return sorted(publications.values(), key=lambda p: (p["year"], p["quarter"]), reverse=True)


def find_latest_publication(base_url: str = PUBLICATION_URL) -> dict:
    """Find the most recent quarterly bulletin.

    Args:
        base_url: URL of the NICTS business data listing page.

    Returns:
        Dict with ``url``, ``year`` and ``quarter`` for the newest bulletin.

    Raises:
        NICTSDataNotFoundError: If no bulletin can be located.

    Example:
        >>> latest = find_latest_publication()
        >>> 1 <= latest["quarter"] <= 4
        True
    """
    latest = list_publications(base_url)[0]
    logger.info(f"Latest NICTS bulletin: {latest['year']} Q{latest['quarter']} ({latest['url']})")
    return latest


def download_file(url: str, cache_ttl_hours: int = _CACHE_TTL_HOURS, force_refresh: bool = False) -> Path:
    """Download a bulletin ODS file with caching.

    Args:
        url: URL of the ODS file.
        cache_ttl_hours: Cache validity in hours (default: 90 days).
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        Path to the downloaded (or cached) file.

    Raises:
        NICTSDataNotFoundError: If the download fails.
    """
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise NICTSDataNotFoundError(str(e)) from e


def parse_data(file_path: Path) -> pd.DataFrame:
    """Parse every court worksheet from a bulletin into one tidy frame.

    Args:
        file_path: Path to the ODS bulletin file.

    Returns:
        DataFrame with columns court, category, subcategory, detail, period,
        year, quarter, value — all ten courts concatenated.

    Raises:
        NICTSDataError: If the workbook contains no parseable court data.
    """
    doc = load_ods(str(Path(file_path)))

    frames = []
    for table in doc.spreadsheet.getElementsByType(Table):
        court = _normalise_sheet_name(table.getAttribute("name") or "")
        if not court or court in _NON_DATA_SHEETS:
            continue
        frame = _parse_sheet(court, _sheet_rows(table))
        if not frame.empty:
            frames.append(frame)

    if not frames:
        raise NICTSDataError(f"No court worksheets found in {file_path}")

    return pd.concat(frames, ignore_index=True)


def get_latest_data(court: str = "all", force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the latest quarterly bulletin.

    Args:
        court: Court key to return (see :func:`list_courts`), or ``"all"`` for
            every court in one frame.
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame with columns court, category, subcategory, detail,
        period, year, quarter, value.

    Raises:
        NICTSDataNotFoundError: If ``court`` is not a known court key.

    Example:
        >>> df = get_latest_data("county_court")
        >>> set(df["court"]) == {"county_court"}
        True
    """
    latest = find_latest_publication()
    df = parse_data(download_file(latest["url"], force_refresh=force_refresh))

    if court == "all":
        return df

    available = sorted(df["court"].unique())
    if court not in available:
        raise NICTSDataNotFoundError(f"Unknown court '{court}'. Available: {', '.join(available)}")

    return df[df["court"] == court].reset_index(drop=True)


def list_courts(force_refresh: bool = False) -> list[str]:
    """List the court keys available in the latest bulletin.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Sorted list of court keys.

    Example:
        >>> "crown_court" in list_courts()
        True
    """
    return sorted(get_latest_data(force_refresh=force_refresh)["court"].unique())


def get_crown_court(force_refresh: bool = False) -> pd.DataFrame:
    """Get Crown Court business (Table 6).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of Crown Court receipts, disposals, and waiting times at
        both case and defendant level.

    Example:
        >>> df = get_crown_court()
        >>> "Received" in set(df["subcategory"])
        True
    """
    return get_latest_data("crown_court", force_refresh=force_refresh)


def get_magistrates_courts(force_refresh: bool = False) -> pd.DataFrame:
    """Get Magistrates' Courts business (Table 8).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of Magistrates' Court criminal and civil business.

    Example:
        >>> df = get_magistrates_courts()
        >>> set(df["court"]) == {"magistrates_courts"}
        True
    """
    return get_latest_data("magistrates_courts", force_refresh=force_refresh)


def get_county_court(force_refresh: bool = False) -> pd.DataFrame:
    """Get County Court business (Table 7).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of County Court civil, family, and appeal business.

    Example:
        >>> df = get_county_court()
        >>> set(df["court"]) == {"county_court"}
        True
    """
    return get_latest_data("county_court", force_refresh=force_refresh)


def get_sitting_days(force_refresh: bool = False) -> pd.DataFrame:
    """Get judicial sitting days and average sitting times (Table 10).

    Sitting *times* are reported as durations and are returned in fractional
    hours, so a published ``6485:30`` becomes ``6485.5``.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of sitting days and times by judge level and court type.

    Example:
        >>> df = get_sitting_days()
        >>> "Total Sitting Days" in set(df["category"])
        True
    """
    return get_latest_data("judge_court_sitting_days", force_refresh=force_refresh)


def validate_data(df: pd.DataFrame, min_records: int = 1000) -> bool:
    """Validate a parsed NICTS quarterly DataFrame.

    Checks structure and sanity:

    - Required columns are present.
    - There are at least ``min_records`` rows.
    - Years fall within a plausible range (2017 onwards).
    - Quarters, where present, are 1-4.
    - All non-null values are non-negative.

    Args:
        df: DataFrame to validate.
        min_records: Minimum acceptable number of rows.

    Returns:
        True if the data passes all checks.

    Raises:
        NICTSValidationError: If any validation check fails.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        Traceback (most recent call last):
        ...
        bolster.data_sources.justice.nicts_quarterly.NICTSValidationError: DataFrame is empty
    """
    if df is None or df.empty:
        raise NICTSValidationError("DataFrame is empty")

    required = {"court", "category", "period", "year", "quarter", "value"}
    missing = required - set(df.columns)
    if missing:
        raise NICTSValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise NICTSValidationError(f"Too few records: {len(df)} < {min_records}")

    if df["year"].min() < 2017 or df["year"].max() > 2100:
        raise NICTSValidationError(f"Year range out of bounds: {df['year'].min()}-{df['year'].max()}")

    quarters = df["quarter"].dropna()
    if not quarters.empty and (quarters.min() < 1 or quarters.max() > 4):
        raise NICTSValidationError(f"Quarter out of bounds: {quarters.min()}-{quarters.max()}")

    values = df["value"].dropna()
    if (values < 0).any():
        raise NICTSValidationError("Negative values found in column 'value'")

    return True


def clear_cache() -> int:
    """Clear all cached NICTS bulletin files.

    Returns:
        Number of files deleted.
    """
    return _downloader.clear()
