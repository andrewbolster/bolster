"""Northern Ireland Planning Activity Statistics.

Quarterly and annual planning application statistics for Northern Ireland,
published by the Department for Infrastructure (DfI). Provides counts of
planning applications received, decided, approved and withdrawn, both
NI-wide as a quarterly time series back to Q1 2002/03 and broken down by
the 11 local councils.

Data Source:
    **Hub page**: https://www.infrastructure-ni.gov.uk/articles/planning-activity-statistics

    The module scrapes the hub page for the latest publication, then scrapes
    that publication page for the quarterly statistical tables Excel file.

Update Frequency:
    Quarterly (provisional) plus an annual final release after each
    financial year ends (April-March).

Geographic Coverage:
    Northern Ireland - whole-country totals plus the 11 local council areas
    (Antrim & Newtownabbey, Ards & North Down, Armagh City Banbridge &
    Craigavon, Belfast, Causeway Coast & Glens, Derry City & Strabane,
    Fermanagh & Omagh, Lisburn & Castlereagh, Mid & East Antrim, Mid Ulster,
    Newry Mourne & Down).

Time Series:
    Q1 2002/03 onwards for the NI-wide series (sheet 1.1).
    Recent quarters plus current/prior financial year for council-area data
    (sheet 1.2).

Example:
    >>> from bolster.data_sources.nisra import planning_statistics
    >>> df = planning_statistics.get_latest_data()
    >>> 'applications_received' in df.columns
    True
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    make_absolute_url,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)

PLANNING_HUB_URL = "https://www.infrastructure-ni.gov.uk/articles/planning-activity-statistics"
INFRA_BASE_URL = "https://www.infrastructure-ni.gov.uk"

# Quarter labels are like "Q1", "Q2", etc. in sheet 1.1
_VALID_QUARTERS = {"Q1", "Q2", "Q3", "Q4"}

# Financial-year quarter to calendar (start) month
_QUARTER_START_MONTH = {"Q1": 4, "Q2": 7, "Q3": 10, "Q4": 1}

# Council date labels in sheet 1.2 ("Apr-Jun 2025" etc.)
_COUNCIL_QUARTER_LABELS = {
    "Apr-Jun": "Q1",
    "Jul-Sep": "Q2",
    "Oct-Dec": "Q3",
    "Jan-Mar": "Q4",
}


def get_latest_publication_url() -> str:
    """Scrape the planning statistics hub page for the latest publication page URL.

    The hub lists publications newest-first; the first non-guidance link with
    a "Northern Ireland planning statistics" title is the latest release
    (provisional quarterly or final annual).

    Returns:
        URL of the latest publication page (containing the XLSX/ODS files).

    Raises:
        NISRADataNotFoundError: If the hub page cannot be fetched or no
            publication link can be located.

    Example:
        >>> url = get_latest_publication_url()
        >>> url.startswith("https://www.infrastructure-ni.gov.uk/publications/")
        True
    """
    try:
        response = session.get(PLANNING_HUB_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:  # pragma: no cover - network errors hard to simulate
        raise NISRADataNotFoundError(f"Failed to fetch planning hub page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        if "/publications/northern-ireland-planning-statistics-" not in href.lower():
            continue
        if "user-guidance" in href.lower() or "background" in text:
            continue
        return make_absolute_url(href, INFRA_BASE_URL)

    raise NISRADataNotFoundError("Could not locate latest planning statistics publication on hub page")


def get_latest_xlsx_url(publication_url: str | None = None) -> str:
    """Find the XLSX file URL on a planning statistics publication page.

    Args:
        publication_url: Publication page URL. If None, calls
            :func:`get_latest_publication_url` to find the most recent.

    Returns:
        URL of the quarterly statistical tables Excel file.

    Raises:
        NISRADataNotFoundError: If the publication page has no XLSX link.

    Example:
        >>> url = get_latest_xlsx_url()
        >>> url.endswith(".xlsx")
        True
    """
    if publication_url is None:
        publication_url = get_latest_publication_url()

    try:
        response = session.get(publication_url, timeout=30)
        response.raise_for_status()
    except Exception as e:  # pragma: no cover - network errors hard to simulate
        raise NISRADataNotFoundError(f"Failed to fetch publication page {publication_url}: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".xlsx"):
            return make_absolute_url(href, INFRA_BASE_URL)

    raise NISRADataNotFoundError(f"No XLSX file found on publication page {publication_url}")


def _parse_fy_quarter_to_date(financial_year: str, quarter: str) -> pd.Timestamp | None:
    """Convert a UK financial year + quarter to a calendar Timestamp.

    Args:
        financial_year: Financial year string like ``"2024/25"``.
        quarter: Quarter code (``Q1``-``Q4``). Q1 = Apr-Jun of the start year,
            Q4 = Jan-Mar of the second year.

    Returns:
        Timestamp for the first day of the quarter, or ``None`` if either
        input cannot be parsed.

    Example:
        >>> _parse_fy_quarter_to_date("2024/25", "Q1")
        Timestamp('2024-04-01 00:00:00')
        >>> _parse_fy_quarter_to_date("2024/25", "Q4")
        Timestamp('2025-01-01 00:00:00')
    """
    if not isinstance(financial_year, str) or quarter not in _QUARTER_START_MONTH:
        return None
    m = re.match(r"^(\d{4})/\d{2}$", financial_year.strip())
    if not m:
        return None
    start_year = int(m.group(1))
    month = _QUARTER_START_MONTH[quarter]
    year = start_year if quarter != "Q4" else start_year + 1
    return pd.Timestamp(year=year, month=month, day=1)


def parse_planning_applications(file_path: str | Path) -> pd.DataFrame:
    """Parse the NI-wide quarterly applications time series (sheet ``1.1``).

    Sheet 1.1 contains the quarterly headline series back to Q1 2002/03 with
    a merged-cell Year column (forward-filled here) plus an annual total row
    per financial year (filtered out).

    Args:
        file_path: Path to a downloaded planning statistics XLSX file.

    Returns:
        DataFrame with one row per quarter and columns:

        - ``date`` (datetime): First day of the calendar quarter
        - ``financial_year`` (str): e.g. ``"2024/25"``
        - ``quarter`` (str): One of ``Q1``-``Q4``
        - ``year`` (int): Calendar year of ``date``
        - ``applications_received`` (int)
        - ``applications_decided`` (int)
        - ``applications_approved`` (int)
        - ``applications_withdrawn`` (int)
        - ``approval_rate`` (float): Proportion 0.0-1.0
        - ``mid_year_population`` (int): NI mid-year population estimate
          used for that financial year's per-10,000 rates
        - ``applications_per_10k`` (float): Applications received per 10,000
          population

    Raises:
        NISRAValidationError: If the sheet structure is unexpected.

    Example:
        >>> import bolster.data_sources.nisra.planning_statistics as ps
        >>> path = ps.get_latest_data.__wrapped__ if False else None  # docs only
    """
    file_path = Path(file_path)
    try:
        raw = pd.read_excel(file_path, sheet_name="1.1", header=None)
    except Exception as e:
        raise NISRAValidationError(f"Failed to read planning sheet 1.1: {e}") from e

    if raw.shape[1] < 10:
        raise NISRAValidationError(f"Sheet 1.1 has only {raw.shape[1]} columns; expected at least 10")

    # Forward-fill the merged-cell Year column from row 4 (data start) onwards
    year_series = raw.iloc[4:, 0].ffill()

    records = []
    for i in range(4, len(raw)):
        fy = year_series.loc[i]
        quarter = str(raw.iloc[i, 1]).strip() if not pd.isna(raw.iloc[i, 1]) else ""
        if quarter not in _VALID_QUARTERS:
            # Skip year-total rows ("2002/03", "2025/26 ytd", source/notes, etc.)
            continue

        ts = _parse_fy_quarter_to_date(str(fy), quarter)
        if ts is None:
            continue

        records.append(
            {
                "date": ts,
                "financial_year": str(fy).strip(),
                "quarter": quarter,
                "year": ts.year,
                "applications_received": safe_int(raw.iloc[i, 2]),
                "mid_year_population": safe_int(raw.iloc[i, 3]),
                "applications_per_10k": safe_float(raw.iloc[i, 5]),
                "applications_decided": safe_int(raw.iloc[i, 6]),
                "applications_approved": safe_int(raw.iloc[i, 7]),
                "approval_rate": safe_float(raw.iloc[i, 8]),
                "applications_withdrawn": safe_int(raw.iloc[i, 9]),
            }
        )

    if not records:
        raise NISRAValidationError("No quarterly data rows parsed from sheet 1.1")

    df = pd.DataFrame.from_records(records)
    col_order = [
        "date",
        "financial_year",
        "quarter",
        "year",
        "applications_received",
        "applications_decided",
        "applications_approved",
        "applications_withdrawn",
        "approval_rate",
        "mid_year_population",
        "applications_per_10k",
    ]
    df = df[col_order].sort_values("date").reset_index(drop=True)

    logger.info(
        "Parsed planning sheet 1.1: %d quarters, %s %s to %s %s",
        len(df),
        df["quarter"].iloc[0],
        df["financial_year"].iloc[0],
        df["quarter"].iloc[-1],
        df["financial_year"].iloc[-1],
    )
    return df


def _parse_council_date_label(label: str) -> tuple[pd.Timestamp, str, str] | None:
    """Parse a council-area date label like ``"Apr-Jun 2025"``.

    Args:
        label: Date label from column 0 of sheet 1.2 sub-tables.

    Returns:
        Tuple of ``(timestamp, financial_year, quarter)`` or ``None`` if the
        label is not a parseable quarter row (skipping yearly totals,
        ``"Year to date ..."``, notes etc.).
    """
    if not isinstance(label, str):
        return None
    label = label.strip()
    m = re.match(r"^(Apr-Jun|Jul-Sep|Oct-Dec|Jan-Mar)\s+(\d{4})$", label)
    if not m:
        return None
    period, year_str = m.group(1), m.group(2)
    quarter = _COUNCIL_QUARTER_LABELS[period]
    calendar_year = int(year_str)
    month = _QUARTER_START_MONTH[quarter]
    ts = pd.Timestamp(year=calendar_year, month=month, day=1)
    # Map back to UK financial year (Q4 belongs to fy ending in this year)
    start = calendar_year - 1 if quarter == "Q4" else calendar_year
    fy = f"{start}/{str(start + 1)[-2:]}"
    return ts, fy, quarter


# Metric-name mapping for sheet 1.2 sub-tables (1.2.1 -> 1.2.5)
_COUNCIL_METRIC_TABLES = {
    "1.2.1": "applications_received",
    "1.2.2": "applications_decided",
    "1.2.3": "applications_approved",
    "1.2.4": "approval_rate",
    "1.2.5": "applications_withdrawn",
}


def parse_planning_by_council(file_path: str | Path) -> pd.DataFrame:
    """Parse the council-area planning applications data (sheet ``1.2``).

    Sheet 1.2 stacks five sub-tables (received / decided / approved /
    approval-rate / withdrawn) with one row per quarter and one column per
    of the 11 NI councils. This function unpivots all five into a tidy long
    DataFrame.

    Args:
        file_path: Path to a downloaded planning statistics XLSX file.

    Returns:
        DataFrame with one row per (date, council) and columns:

        - ``date`` (datetime), ``financial_year`` (str), ``quarter`` (str),
          ``year`` (int)
        - ``council`` (str): Council name
        - ``applications_received`` (int | None)
        - ``applications_decided`` (int | None)
        - ``applications_approved`` (int | None)
        - ``applications_withdrawn`` (int | None)
        - ``approval_rate`` (float | None): Proportion 0.0-1.0

    Raises:
        NISRAValidationError: If the sheet structure is unexpected (no
            council header rows / parseable date rows found).
    """
    file_path = Path(file_path)
    try:
        raw = pd.read_excel(file_path, sheet_name="1.2", header=None)
    except Exception as e:
        raise NISRAValidationError(f"Failed to read planning sheet 1.2: {e}") from e

    # Locate each sub-table by its label in column 0
    current_metric: str | None = None
    councils: list[str] | None = None

    rows: list[dict] = []
    for i in range(len(raw)):
        col0 = raw.iloc[i, 0]
        if isinstance(col0, str):
            stripped = col0.strip()
            # Match "Table 1.2.1 - ..." style headers
            m = re.match(r"^Table\s+(1\.2\.[1-5])\b", stripped)
            if m:
                current_metric = _COUNCIL_METRIC_TABLES.get(m.group(1))
                councils = None
                continue

        # Header row immediately follows (col0 is NaN, councils across)
        if current_metric is not None and councils is None:
            possible_header = [str(v).strip() for v in raw.iloc[i, 1:].tolist() if isinstance(v, str)]
            if len(possible_header) >= 11 and any("Antrim" in c for c in possible_header):
                councils = [str(v).strip() for v in raw.iloc[i, 1:].tolist()]
                continue

        if current_metric is None or councils is None:
            continue

        parsed = _parse_council_date_label(col0 if isinstance(col0, str) else "")
        if parsed is None:
            continue
        ts, fy, quarter = parsed

        for col_idx, council in enumerate(councils, start=1):
            if not council or council == "nan":
                continue
            val = raw.iloc[i, col_idx]
            value = safe_float(val) if current_metric == "approval_rate" else safe_int(val)
            rows.append(
                {
                    "date": ts,
                    "financial_year": fy,
                    "quarter": quarter,
                    "year": ts.year,
                    "council": council,
                    "metric": current_metric,
                    "value": value,
                }
            )

    if not rows:
        raise NISRAValidationError("No council-area rows parsed from sheet 1.2")

    long_df = pd.DataFrame.from_records(rows)

    # Pivot metric -> wide columns
    df = (
        long_df.pivot_table(
            index=["date", "financial_year", "quarter", "year", "council"],
            columns="metric",
            values="value",
            aggfunc="first",
        )
        .reset_index()
        .rename_axis(columns=None)
    )

    # Ensure all expected metric columns exist (in case a release omits one)
    for metric in _COUNCIL_METRIC_TABLES.values():
        if metric not in df.columns:
            df[metric] = pd.NA

    col_order = [
        "date",
        "financial_year",
        "quarter",
        "year",
        "council",
        "applications_received",
        "applications_decided",
        "applications_approved",
        "applications_withdrawn",
        "approval_rate",
    ]
    df = df[col_order].sort_values(["date", "council"]).reset_index(drop=True)

    logger.info("Parsed planning sheet 1.2: %d (date, council) rows", len(df))
    return df


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the NI-wide quarterly planning applications series.

    Args:
        force_refresh: If True, bypass the local cache and re-download.

    Returns:
        DataFrame from :func:`parse_planning_applications` (NI-wide
        quarterly time series, sheet 1.1).

    Raises:
        NISRADataNotFoundError: If the latest publication or XLSX cannot be
            located.
        NISRAValidationError: If the downloaded file cannot be parsed.

    Example:
        >>> df = get_latest_data()
        >>> 'applications_received' in df.columns
        True
    """
    xlsx_url = get_latest_xlsx_url()
    logger.info("Downloading planning statistics from %s", xlsx_url)
    # Quarterly cadence - 30 day cache is comfortable
    file_path = download_file(xlsx_url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)
    return parse_planning_applications(file_path)


def get_latest_council_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the council-area planning applications data.

    Args:
        force_refresh: If True, bypass the local cache and re-download.

    Returns:
        DataFrame from :func:`parse_planning_by_council` (one row per
        date, council).

    Raises:
        NISRADataNotFoundError: If the latest publication or XLSX cannot be
            located.
        NISRAValidationError: If the downloaded file cannot be parsed.

    Example:
        >>> df = get_latest_council_data()
        >>> 'council' in df.columns
        True
    """
    xlsx_url = get_latest_xlsx_url()
    file_path = download_file(xlsx_url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)
    return parse_planning_by_council(file_path)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate an NI-wide planning applications DataFrame.

    Args:
        df: DataFrame from :func:`get_latest_data` or
            :func:`parse_planning_applications`.

    Returns:
        ``True`` if all checks pass.

    Raises:
        NISRAValidationError: If the DataFrame is empty, missing required
            columns, has implausible values, or has too short a time series.

    Example:
        >>> df = get_latest_data()
        >>> validate_data(df)
        True
    """
    if df is None or df.empty:
        raise NISRAValidationError("Planning DataFrame is empty")

    required = {
        "date",
        "financial_year",
        "quarter",
        "year",
        "applications_received",
        "applications_decided",
        "applications_approved",
        "applications_withdrawn",
        "approval_rate",
    }
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < 40:
        raise NISRAValidationError(f"Too few quarters ({len(df)}); expected 40+ since 2002/03")

    if not set(df["quarter"].unique()).issubset(_VALID_QUARTERS):
        raise NISRAValidationError(f"Unexpected quarter values: {sorted(df['quarter'].unique())}")

    for col in ("applications_received", "applications_decided", "applications_approved"):
        vals = df[col].dropna()
        if (vals < 0).any():
            raise NISRAValidationError(f"Negative values found in {col}")
        # NI quarterly application volumes have historically been ~2k-9k
        if (vals > 50_000).any():
            raise NISRAValidationError(f"Implausibly high values in {col} (>50,000 in a quarter)")

    rates = df["approval_rate"].dropna()
    if ((rates < 0) | (rates > 1.0001)).any():
        raise NISRAValidationError("approval_rate outside the [0, 1] range")

    return True


def get_annual_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a quarterly DataFrame to annual (financial-year) totals.

    Args:
        df: DataFrame from :func:`get_latest_data`.

    Returns:
        DataFrame with one row per financial year and columns:

        - ``financial_year`` (str)
        - ``applications_received`` (int)
        - ``applications_decided`` (int)
        - ``applications_approved`` (int)
        - ``applications_withdrawn`` (int)
        - ``approval_rate`` (float): Weighted by decisions
          (approved / decided)
        - ``quarters`` (int): Number of quarters aggregated (4 except for
          the current in-progress year)

    Example:
        >>> df = get_latest_data()
        >>> annual = get_annual_totals(df)
        >>> 'applications_received' in annual.columns
        True
    """
    grouped = df.groupby("financial_year", sort=False).agg(
        applications_received=("applications_received", "sum"),
        applications_decided=("applications_decided", "sum"),
        applications_approved=("applications_approved", "sum"),
        applications_withdrawn=("applications_withdrawn", "sum"),
        quarters=("quarter", "count"),
    )
    grouped["approval_rate"] = (grouped["applications_approved"] / grouped["applications_decided"]).round(4)
    return grouped.reset_index()[
        [
            "financial_year",
            "applications_received",
            "applications_decided",
            "applications_approved",
            "applications_withdrawn",
            "approval_rate",
            "quarters",
        ]
    ]


def get_council_summary(council_df: pd.DataFrame, financial_year: str | None = None) -> pd.DataFrame:
    """Summarise council-area data by council across all (or one) financial year.

    Args:
        council_df: DataFrame from :func:`get_latest_council_data`.
        financial_year: Optional financial year to filter to
            (e.g. ``"2024/25"``). If None, summarises across all available
            quarters.

    Returns:
        DataFrame with one row per council, sorted by
        ``applications_received`` descending.

    Example:
        >>> council_df = get_latest_council_data()
        >>> summary = get_council_summary(council_df, financial_year='2024/25')
        >>> 'council' in summary.columns
        True
    """
    df = council_df
    if financial_year is not None:
        df = df[df["financial_year"] == financial_year]

    grouped = df.groupby("council", sort=False).agg(
        applications_received=("applications_received", "sum"),
        applications_decided=("applications_decided", "sum"),
        applications_approved=("applications_approved", "sum"),
        applications_withdrawn=("applications_withdrawn", "sum"),
    )
    decided = grouped["applications_decided"].replace(0, pd.NA)
    grouped["approval_rate"] = (grouped["applications_approved"] / decided).round(4)
    return grouped.reset_index().sort_values("applications_received", ascending=False).reset_index(drop=True)
