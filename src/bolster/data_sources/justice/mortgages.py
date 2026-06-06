"""NICTS Mortgages: Action for Possession Data.

Provides access to quarterly statistics on mortgage possession proceedings in
the Chancery Division of the Northern Ireland High Court, published by the
Northern Ireland Courts and Tribunals Service (NICTS).

Three datasets are available:

- **Cases received** - writs and originating summonses issued (Table 1).
- **Cases disposed** - cases concluded by the court (Table 2).
- **Final orders** - the type of final order made, e.g. possession,
  suspended possession, strike out (Table 3, available from 2017 onwards).

Data Source:
    **Publication Page**:
    https://www.justice-ni.gov.uk/publications/nicts-mortgages-action-possession

    The module scrapes this page to find the latest quarterly ODS file
    (``mortgages-bulletin-tables-<period>.ods``), which contains separate
    worksheets for received, disposed and final-order statistics.

Update Frequency: Quarterly
Geographic Coverage: Northern Ireland
Reference Period: 2007 - present (final orders: 2017 - present)

This data pairs well with :mod:`bolster.data_sources.ni_house_price_index`
for contextualising the housing market against repossession activity.

Example:
    >>> from bolster.data_sources.justice import mortgages
    >>> df = mortgages.get_cases_received()
    >>> "applications" in df.columns
    True
    >>> {"Q1", "Q2", "Q3", "Q4"}.issubset(set(df["quarter"]))
    True
"""

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import bs4
import pandas as pd

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Publication landing page listing every quarterly bulletin
PUBLICATION_URL = "https://www.justice-ni.gov.uk/publications/nicts-mortgages-action-possession"
BASE_URL = "https://www.justice-ni.gov.uk"

# Worksheet names within the ODS bulletin
SHEET_RECEIVED = "Mortgages_received"
SHEET_DISPOSED = "Mortgages_disposed"
SHEET_FINAL_ORDERS = "Mortgages_final_orders"

# Quarter labels in publication order
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

# Shared downloader instance (ODS files are tiny, cache for a week)
_downloader = CachedDownloader("justice_mortgages", timeout=60)


class MortgagesDataError(Exception):
    """Base exception for NICTS mortgages data errors."""

    pass


class MortgagesDataNotFoundError(MortgagesDataError):
    """Raised when the data file cannot be located or downloaded."""

    pass


class MortgagesValidationError(MortgagesDataError):
    """Raised when downloaded data fails validation."""

    pass


def get_latest_publication_url(base_url: str = PUBLICATION_URL) -> str:
    """Find the URL of the most recent mortgages bulletin ODS file.

    Scrapes the publication landing page for links to ``.ods`` files and
    returns the first one found (the page lists newest first).

    Args:
        base_url: URL of the publication listing page.

    Returns:
        Absolute URL of the latest ODS bulletin file.

    Raises:
        MortgagesDataNotFoundError: If the page cannot be fetched or no ODS
            link is found.

    Example:
        >>> url = get_latest_publication_url()  # doctest: +SKIP
        >>> url.endswith(".ods")  # doctest: +SKIP
        True
    """
    try:
        response = session.get(base_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise MortgagesDataNotFoundError(f"Failed to fetch publication page {base_url}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, features="html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".ods"):
            if href.startswith("/"):
                href = urlparse(base_url)._replace(path=href, query="", fragment="").geturl()
            logger.info(f"Found latest mortgages bulletin: {href}")
            return href

    raise MortgagesDataNotFoundError(f"Could not find an ODS file on {base_url}")


def download_file(url: str, cache_ttl_hours: int = 24 * 7, force_refresh: bool = False) -> Path:
    """Download a bulletin ODS file with caching.

    Args:
        url: URL of the ODS file to download.
        cache_ttl_hours: Cache validity in hours (default: 7 days, since data
            is published quarterly).
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        Path to the downloaded (or cached) file.

    Raises:
        MortgagesDataNotFoundError: If the download fails.
    """
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise MortgagesDataNotFoundError(str(e)) from e


def _parse_quarterly_table(file_path: Path, sheet_name: str, value_label: str) -> pd.DataFrame:
    """Parse a wide quarterly table (Table 1/2) into tidy long format.

    The received/disposed worksheets have one row per year with four quarterly
    columns, an annual total, and a year-on-year percentage difference. This
    reshapes them into one row per (year, quarter).

    Args:
        file_path: Path to the ODS file.
        sheet_name: Worksheet name to read.
        value_label: Name for the value column (e.g. "applications").

    Returns:
        DataFrame with columns: year, quarter, period, ``value_label``,
        annual_total, annual_pct_change.
    """
    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine="odf")

    # Locate the header row (the one whose first cell is exactly "Year").
    header_idx = None
    for idx in range(min(10, len(raw))):
        if str(raw.iloc[idx, 0]).strip() == "Year":
            header_idx = idx
            break
    if header_idx is None:
        raise MortgagesValidationError(f"Could not find 'Year' header row in sheet {sheet_name}")

    records = []
    for _, row in raw.iloc[header_idx + 1 :].iterrows():
        year_cell = row.iloc[0]
        if pd.isna(year_cell):
            continue
        try:
            year = int(float(year_cell))
        except (ValueError, TypeError):
            # Footer / note rows after the data block
            continue

        annual_total = _safe_int(row.iloc[5])
        annual_pct = _safe_float(row.iloc[6])

        for q_idx, quarter in enumerate(QUARTERS, start=1):
            value = _safe_int(row.iloc[q_idx])
            records.append(
                {
                    "year": year,
                    "quarter": quarter,
                    "period": pd.Period(f"{year}{quarter}", freq="Q"),
                    value_label: value,
                    "annual_total": annual_total,
                    "annual_pct_change": annual_pct,
                }
            )

    df = pd.DataFrame.from_records(records)
    return df.sort_values(["year", "quarter"]).reset_index(drop=True)


def _parse_final_orders(file_path: Path, sheet_name: str = SHEET_FINAL_ORDERS) -> pd.DataFrame:
    """Parse the final-orders worksheet (Table 3) into tidy long format.

    The final-orders worksheet is wide: order types are rows and time periods
    (years 2017-2024, then individual quarters) are columns. This melts it into
    one row per (order_type, period).

    Args:
        file_path: Path to the ODS file.
        sheet_name: Worksheet name to read.

    Returns:
        DataFrame with columns: order_type, year, quarter, period, count.
        Annual columns (pre-quarterly years) have quarter set to None and
        period set to an annual Period.

    Raises:
        MortgagesValidationError: If the header row cannot be found.
    """
    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine="odf")

    header_idx = None
    for idx in range(min(10, len(raw))):
        if str(raw.iloc[idx, 0]).strip() == "Final Order":
            header_idx = idx
            break
    if header_idx is None:
        raise MortgagesValidationError(f"Could not find 'Final Order' header row in sheet {sheet_name}")

    headers = raw.iloc[header_idx].tolist()
    records = []
    for _, row in raw.iloc[header_idx + 1 :].iterrows():
        order_type = row.iloc[0]
        if pd.isna(order_type) or not str(order_type).strip():
            continue
        order_type = str(order_type).strip()

        for col_idx in range(1, len(headers)):
            label = headers[col_idx]
            if pd.isna(label):
                continue
            year, quarter, period = _parse_period_label(label)
            if period is None:
                continue
            count = _safe_int(row.iloc[col_idx])
            records.append(
                {
                    "order_type": order_type,
                    "year": year,
                    "quarter": quarter,
                    "period": period,
                    "count": count,
                }
            )

    df = pd.DataFrame.from_records(records)
    return df.sort_values(["order_type", "year"]).reset_index(drop=True)


def _parse_period_label(label) -> tuple[int | None, str | None, pd.Period | None]:
    """Parse a final-orders column label into (year, quarter, Period).

    Handles annual labels (e.g. ``2017``, ``2017.0``) and quarterly labels
    (e.g. ``2025 Q1``).

    Args:
        label: Raw column header value.

    Returns:
        Tuple of (year, quarter, Period). Annual labels have quarter ``None``
        and an annual-frequency Period. Returns (None, None, None) if the
        label cannot be parsed.
    """
    text = str(label).strip()

    # Quarterly: "2025 Q1"
    m = re.match(r"^(\d{4})\s*Q([1-4])$", text)
    if m:
        year = int(m.group(1))
        quarter = f"Q{m.group(2)}"
        return year, quarter, pd.Period(f"{year}{quarter}", freq="Q")

    # Annual: "2017" or "2017.0"
    m = re.match(r"^(\d{4})(?:\.0)?$", text)
    if m:
        year = int(m.group(1))
        return year, None, pd.Period(str(year), freq="Y")

    return None, None, None


def _safe_int(val) -> int | None:
    """Convert a cell value to int, returning None for blanks/placeholders."""
    if val is None or (isinstance(val, float) and pd.isna(val)) or val == "" or val == "-":
        return None
    try:
        return int(round(float(val)))
    except (ValueError, TypeError):
        return None


def _safe_float(val) -> float | None:
    """Convert a cell value to float, returning None for blanks/placeholders."""
    if val is None or (isinstance(val, float) and pd.isna(val)) or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def parse_data(file_path: Path) -> dict[str, pd.DataFrame]:
    """Parse all mortgage tables from a bulletin ODS file.

    Args:
        file_path: Path to the ODS bulletin file.

    Returns:
        Dictionary with keys ``received``, ``disposed`` and ``final_orders``
        mapping to tidy long-format DataFrames. ``final_orders`` may be absent
        if the file pre-dates 2017.

    Example:
        >>> tables = parse_data(download_file(get_latest_publication_url()))  # doctest: +SKIP
        >>> sorted(tables)  # doctest: +SKIP
        ['disposed', 'final_orders', 'received']
    """
    file_path = Path(file_path)
    available = set(pd.ExcelFile(file_path, engine="odf").sheet_names)

    tables: dict[str, pd.DataFrame] = {
        "received": _parse_quarterly_table(file_path, SHEET_RECEIVED, "applications"),
        "disposed": _parse_quarterly_table(file_path, SHEET_DISPOSED, "applications"),
    }
    if SHEET_FINAL_ORDERS in available:
        tables["final_orders"] = _parse_final_orders(file_path, SHEET_FINAL_ORDERS)

    return tables


def get_latest_data(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Download and parse the latest mortgages bulletin.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Dictionary of tidy DataFrames keyed ``received``, ``disposed`` and
        (where available) ``final_orders``.

    Example:
        >>> data = get_latest_data()
        >>> "received" in data and "disposed" in data
        True
    """
    url = get_latest_publication_url()
    file_path = download_file(url, force_refresh=force_refresh)
    return parse_data(file_path)


def get_cases_received(force_refresh: bool = False) -> pd.DataFrame:
    """Get quarterly mortgage possession cases received (Table 1).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        DataFrame with columns: year, quarter, period, applications,
        annual_total, annual_pct_change. One row per (year, quarter) from 2007.

    Example:
        >>> df = get_cases_received()
        >>> "applications" in df.columns
        True
    """
    return get_latest_data(force_refresh=force_refresh)["received"]


def get_cases_disposed(force_refresh: bool = False) -> pd.DataFrame:
    """Get quarterly mortgage possession cases disposed (Table 2).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        DataFrame with columns: year, quarter, period, applications,
        annual_total, annual_pct_change. One row per (year, quarter) from 2007.

    Example:
        >>> df = get_cases_disposed()
        >>> "applications" in df.columns
        True
    """
    return get_latest_data(force_refresh=force_refresh)["disposed"]


def get_final_orders(force_refresh: bool = False) -> pd.DataFrame:
    """Get mortgage possession final orders by type (Table 3).

    Final orders have been published from 2017 onwards. Earlier years are
    reported annually; from 2025 they are broken down by quarter.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        DataFrame with columns: order_type, year, quarter, period, count.

    Raises:
        MortgagesDataNotFoundError: If the bulletin does not include final
            orders (e.g. very old files).

    Example:
        >>> df = get_final_orders()  # doctest: +SKIP
        >>> "order_type" in df.columns  # doctest: +SKIP
        True
    """
    data = get_latest_data(force_refresh=force_refresh)
    if "final_orders" not in data:
        raise MortgagesDataNotFoundError("Final orders data not available in this bulletin")
    return data["final_orders"]


def validate_data(df: pd.DataFrame, value_col: str = "applications", min_records: int = 40) -> bool:
    """Validate a parsed quarterly mortgages DataFrame.

    Checks structure and sanity of received/disposed tables:

    - Required columns are present.
    - There are at least ``min_records`` rows (>= 10 years of quarters).
    - Years fall within a plausible range (2007 onwards).
    - All non-null counts are non-negative.

    Args:
        df: DataFrame to validate (received or disposed).
        value_col: Name of the count column to check (default: "applications").
        min_records: Minimum acceptable number of rows.

    Returns:
        True if the data passes all checks.

    Raises:
        MortgagesValidationError: If any validation check fails.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        Traceback (most recent call last):
        ...
        bolster.data_sources.justice.mortgages.MortgagesValidationError: DataFrame is empty
    """
    if df is None or df.empty:
        raise MortgagesValidationError("DataFrame is empty")

    required = {"year", "quarter", "period", value_col}
    missing = required - set(df.columns)
    if missing:
        raise MortgagesValidationError(f"Missing required columns: {missing}")

    if len(df) < min_records:
        raise MortgagesValidationError(f"Too few records: {len(df)} < {min_records}")

    if df["year"].min() < 2007 or df["year"].max() > 2100:
        raise MortgagesValidationError(f"Year range out of bounds: {df['year'].min()}-{df['year'].max()}")

    values = df[value_col].dropna()
    if (values < 0).any():
        raise MortgagesValidationError(f"Negative values found in column '{value_col}'")

    return True


def clear_cache() -> int:
    """Clear all cached mortgages bulletin files.

    Returns:
        Number of files deleted.
    """
    return _downloader.clear()
