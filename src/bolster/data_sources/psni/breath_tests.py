"""PSNI Preliminary Breath Tests Statistics.

Preliminary breath tests (PBTs) conducted by the PSNI in Northern Ireland:
how many tests were carried out, their results, the reason a test was
carried out, and when they happened.

This is a distinct dataset from
:mod:`bolster.data_sources.psni.motoring_offences`'s ``drink-drug-driving``
offence series — that series covers enforcement *outcomes* for drink/drug
driving offences; this module covers the tests themselves, whether or not
they led to an offence.

Data available:
    - Annual totals and positive/failed-to-provide rate, 2010 to present
    - Annual breakdown by result (zero, pass, warning, fail, failed to
      provide), 2010 to present
    - Annual breakdown by reason for test (moving traffic offence, road
      traffic collision, suspicion of alcohol, other), 2010 to present
    - Current-year breakdown by month, day of week and time of day

Data Source:
    **Primary Source**: PSNI Motoring Offence Statistics — "Additional drink
    and drug driving statistics" section

    https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/motoring-offence-statistics

    The PBT figures are published as a supplementary workbook alongside the
    main motoring offences statistics, not as their own standalone page.
    Published under the Open Government Licence v3.0.

Update Frequency: Annual
Geographic Coverage: Northern Ireland (no district-level breakdown in this
    workbook)
Reference Period: 2010 to present (month/day/time breakdowns: current year
    only)

Note:
    The PSNI website returns HTTP 403 to automated requests for HTML pages
    from some IPs (Cloudflare reputation-based, not a blanket block) — the
    workbook asset itself (under ``sites/default/files/...``) doesn't have
    this issue once its URL is known. See
    :mod:`bolster.data_sources.psni.security_situation` for the same caveat.

Example:
    >>> from bolster.data_sources.psni import breath_tests
    >>> df = breath_tests.get_annual_totals()  # doctest: +SKIP
    >>> int(df['year'].min())  # doctest: +SKIP
    2010
"""

import logging
import re

import pandas as pd

from bolster.utils.cache import load_workbook
from bolster.utils.web import scrape_file_links

from ._base import PSNIDataNotFoundError, PSNIValidationError, download_file

logger = logging.getLogger(__name__)

MOTORING_OFFENCE_STATISTICS_URL = (
    "https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/motoring-offence-statistics"
)

_CACHE_TTL_HOURS = 24 * 30

# Sheets keyed by year with no trailing Total row: sheet name -> (result column names).
_ANNUAL_SHEETS: dict[str, list[str]] = {
    "Year": ["year", "total_tests", "positive_or_failed_to_provide", "pct_positive_or_failed_to_provide"],
    "Result": ["year", "zero", "pass", "warning", "fail", "failed_to_provide", "total"],
    "Reason": ["year", "moving_traffic_offence", "road_traffic_collision", "suspicion_of_alcohol", "other", "total"],
}

# Sheets covering only the current year, with a trailing "Total" row to drop:
# sheet name -> (category column name, result column names).
_CURRENT_YEAR_SHEETS: dict[str, tuple[str, list[str]]] = {
    "Month_of_year": ("month", ["total_tests", "positive_or_failed_to_provide", "pct_positive_or_failed_to_provide"]),
    "Day_of_week": (
        "day_of_week",
        ["total_tests", "positive_or_failed_to_provide", "pct_positive_or_failed_to_provide"],
    ),
    "Time_of_day": (
        "time_of_day",
        ["total_tests", "positive_or_failed_to_provide", "pct_positive_or_failed_to_provide"],
    ),
}

_TITLE_YEAR_RE = re.compile(r"(\d{4})\s*$")


def find_latest_workbook_url() -> str:
    """Find the URL of the current PBT accompanying spreadsheet.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        PSNIDataNotFoundError: If the page can't be fetched or has no
            matching ``.xlsx`` link.
    """
    links = scrape_file_links(MOTORING_OFFENCE_STATISTICS_URL, ".xlsx")
    matches = [link["url"] for link in links if "pbt" in link["url"].lower()]

    if not matches:
        raise PSNIDataNotFoundError(f"No PBT workbook link found on {MOTORING_OFFENCE_STATISTICS_URL}")

    return matches[0]


def _load_workbook(force_refresh: bool = False) -> pd.ExcelFile:
    """Download and open the PBT workbook, using the on-disk cache.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        An open :class:`pandas.ExcelFile` for the workbook.

    Raises:
        PSNIDataNotFoundError: If the workbook cannot be downloaded.
    """
    url = find_latest_workbook_url()
    return load_workbook(url, download_file, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)


def _sheet(name: str, force_refresh: bool = False) -> pd.DataFrame:
    """Read one workbook sheet as a header-less DataFrame."""
    workbook = _load_workbook(force_refresh)
    if name not in workbook.sheet_names:
        raise PSNIDataNotFoundError(f"Sheet {name!r} missing from workbook; have {workbook.sheet_names}")
    return pd.read_excel(workbook, sheet_name=name, header=None)


def _title_year(sheet: pd.DataFrame) -> int:
    """Extract the reporting year from a current-year sheet's title row.

    Example titles: "Number of preliminary breath tests by month of year, 2025".
    """
    title = str(sheet.iat[0, 0])
    match = _TITLE_YEAR_RE.search(title)
    if not match:
        raise PSNIValidationError(f"Could not find a year in sheet title: {title!r}")
    return int(match.group(1))


def _read_table(sheet: pd.DataFrame, column_names: list[str], stop_labels: set[str] | None = None) -> pd.DataFrame:
    """Extract the data block below row 2's header, stopping at a blank or stop-labelled row.

    Every sheet in this workbook shares the same shape: a title row, a unit
    row, a header row at index 2, then data rows.

    Args:
        sheet: Header-less sheet DataFrame.
        column_names: Names for the columns actually used (may be fewer than
            the sheet's raw column count, e.g. to drop a trailing blank
            column).
        stop_labels: First-column values that end the data block without
            being included in it (e.g. a trailing "Total" row).

    Returns:
        DataFrame with ``column_names`` as columns and only the data rows.

    Raises:
        PSNIValidationError: If no data rows are found.
    """
    stop_labels = stop_labels or set()
    rows: list[int] = []
    for index in range(3, len(sheet)):
        label = sheet.iat[index, 0]
        if pd.isna(label) or str(label).strip() in stop_labels:
            break
        rows.append(index)

    if not rows:
        raise PSNIValidationError("No data rows found below the header row")

    block = sheet.loc[rows, : len(column_names) - 1].copy()
    block.columns = column_names
    return block.reset_index(drop=True)


def _annual_sheet(sheet_name: str, force_refresh: bool) -> pd.DataFrame:
    """Parse one of the year-keyed sheets (Year, Result, Reason)."""
    columns = _ANNUAL_SHEETS[sheet_name]
    sheet = _sheet(sheet_name, force_refresh)
    table = _read_table(sheet, columns)
    table["year"] = table["year"].astype(int)
    for column in columns[1:]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


def _current_year_sheet(sheet_name: str, force_refresh: bool) -> pd.DataFrame:
    """Parse one of the current-year breakdown sheets, dropping the trailing Total row."""
    category_column, value_columns = _CURRENT_YEAR_SHEETS[sheet_name]
    sheet = _sheet(sheet_name, force_refresh)
    year = _title_year(sheet)
    table = _read_table(sheet, [category_column, *value_columns], stop_labels={"Total"})
    for column in value_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table.insert(0, "year", year)
    return table


# ── Public accessors ─────────────────────────────────────────────────────────


def get_annual_totals(force_refresh: bool = False) -> pd.DataFrame:
    """Return annual PBT totals and the positive/failed-to-provide rate (Year sheet).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year``, ``total_tests``,
        ``positive_or_failed_to_provide`` and
        ``pct_positive_or_failed_to_provide``.

    Example:
        >>> df = get_annual_totals()  # doctest: +SKIP
        >>> bool((df['year'] >= 2010).all())  # doctest: +SKIP
        True
    """
    return _annual_sheet("Year", force_refresh)


def get_annual_by_result(force_refresh: bool = False) -> pd.DataFrame:
    """Return annual PBT counts by result (Result sheet).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year``, ``zero``, ``pass``, ``warning``,
        ``fail``, ``failed_to_provide`` and ``total``.

    Example:
        >>> df = get_annual_by_result()  # doctest: +SKIP
        >>> {'zero', 'pass', 'fail', 'total'}.issubset(df.columns)  # doctest: +SKIP
        True
    """
    return _annual_sheet("Result", force_refresh)


def get_annual_by_reason(force_refresh: bool = False) -> pd.DataFrame:
    """Return annual PBT counts by reason for test (Reason sheet).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year``, ``moving_traffic_offence``,
        ``road_traffic_collision``, ``suspicion_of_alcohol``, ``other`` and
        ``total``.

    Example:
        >>> df = get_annual_by_reason()  # doctest: +SKIP
        >>> 'suspicion_of_alcohol' in df.columns  # doctest: +SKIP
        True
    """
    return _annual_sheet("Reason", force_refresh)


def get_by_month(force_refresh: bool = False) -> pd.DataFrame:
    """Return the current year's PBT counts by month (Month_of_year sheet).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year``, ``month``, ``total_tests``,
        ``positive_or_failed_to_provide`` and
        ``pct_positive_or_failed_to_provide``, covering only the workbook's
        most recent year (this breakdown is not published as a historical
        time series).

    Example:
        >>> df = get_by_month()  # doctest: +SKIP
        >>> len(df)  # doctest: +SKIP
        12
    """
    return _current_year_sheet("Month_of_year", force_refresh)


def get_by_day_of_week(force_refresh: bool = False) -> pd.DataFrame:
    """Return the current year's PBT counts by day of week (Day_of_week sheet).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year``, ``day_of_week``, ``total_tests``,
        ``positive_or_failed_to_provide`` and
        ``pct_positive_or_failed_to_provide``.

    Example:
        >>> df = get_by_day_of_week()  # doctest: +SKIP
        >>> len(df)  # doctest: +SKIP
        7
    """
    return _current_year_sheet("Day_of_week", force_refresh)


def get_by_time_of_day(force_refresh: bool = False) -> pd.DataFrame:
    """Return the current year's PBT counts by time of day (Time_of_day sheet).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year``, ``time_of_day`` (three-hour bands,
        e.g. ``"0000 - 0259"``), ``total_tests``,
        ``positive_or_failed_to_provide`` and
        ``pct_positive_or_failed_to_provide``.

    Example:
        >>> df = get_by_time_of_day()  # doctest: +SKIP
        >>> len(df)  # doctest: +SKIP
        8
    """
    return _current_year_sheet("Time_of_day", force_refresh)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_data(df: pd.DataFrame, value_column: str | None = None) -> bool:
    """Check that a parsed PBT DataFrame is structurally sound.

    Args:
        df: DataFrame returned by any of this module's accessors.
        value_column: Numeric column to check; inferred from the frame when
            omitted.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        PSNIValidationError: If the frame is empty, missing its value
            column, has no non-null values, contains negative counts, or
            contains implausible years.

    Example:
        >>> validate_data(get_annual_totals())  # doctest: +SKIP
        True
    """
    if df.empty:
        raise PSNIValidationError("DataFrame is empty")

    if value_column is None:
        candidates = [c for c in ("total_tests", "total") if c in df.columns]
        if not candidates:
            raise PSNIValidationError(f"No total column found in {list(df.columns)}")
        value_column = candidates[0]

    if value_column not in df.columns:
        raise PSNIValidationError(f"Missing expected column {value_column!r}")

    if df[value_column].notna().sum() == 0:
        raise PSNIValidationError(f"Column {value_column!r} contains no values")

    if (df[value_column].dropna() < 0).any():
        raise PSNIValidationError(f"Column {value_column!r} contains negative counts")

    if "year" in df.columns and not df["year"].between(2000, 2100).all():
        raise PSNIValidationError("Year column contains implausible values")

    return True
