"""NISRA Quarterly Employment Survey (QES) for Northern Ireland.

Provides quarterly employee job estimates for Northern Ireland by broad industry
sector, both seasonally adjusted and unadjusted. The QES is used by the ONS as
the primary source for NI estimates within UK-wide quarterly workforce statistics.

Sectors covered:
- Manufacturing
- Construction
- Services
- Other Industries
- All Industries (total)

Data Source:
    **Statistics page**: https://www.nisra.gov.uk/statistics/work-pay-and-benefits/quarterly-employment-survey
    The module scrapes this page to find the latest quarterly supplementary tables,
    then downloads the Excel file.

Update Frequency: Quarterly (published ~2 weeks after reference quarter)
Geographic Coverage: Northern Ireland
Time Series: Q1 2005 to present (seasonally adjusted); Q1 2005 unadjusted

Example:
    >>> from bolster.data_sources.nisra import quarterly_employment_survey as qes
    >>> df = qes.get_latest_qes()
    >>> print(df.tail(4))

    >>> # Total employee jobs trend
    >>> growth = qes.get_qes_growth(df)
    >>> print(growth[['quarter_label', 'total_jobs', 'total_yoy']].tail(8))
"""

import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

QES_STATS_URL = "https://www.nisra.gov.uk/statistics/work-pay-and-benefits/quarterly-employment-survey"
QES_BASE_URL = "https://www.nisra.gov.uk"

# Quarter abbreviations used in QES file date labels
_QUARTER_MONTHS = {"Mar": (3, 1), "Jun": (6, 2), "Sep": (9, 3), "Dec": (12, 4)}


def get_latest_qes_publication_url() -> str:
    """Scrape the QES statistics page to find the latest supplementary tables Excel.

    Returns:
        URL of the latest QES supplementary tables Excel file

    Raises:
        NISRADataNotFoundError: If publication cannot be found
    """
    try:
        response = session.get(QES_STATS_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch QES statistics page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    # Find the supplementary tables publication link
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "supplementary-tables" not in href or "quarterly-employment-survey" not in href:
            continue

        pub_url = href if href.startswith("http") else f"{QES_BASE_URL}{href}"
        try:
            pub_resp = session.get(pub_url, timeout=30)
            pub_resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to fetch QES publication page {pub_url}: {e}")
            continue

        pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
        for file_link in pub_soup.find_all("a", href=True):
            file_href = file_link["href"]
            if "supplementary_tables" in file_href and file_href.endswith(".xlsx"):
                excel_url = file_href if file_href.startswith("http") else f"{QES_BASE_URL}{file_href}"
                logger.info(f"Found QES supplementary tables: {excel_url}")
                return excel_url

    raise NISRADataNotFoundError("Could not find QES supplementary tables Excel file")


def _parse_qes_date(label: str) -> pd.Timestamp | None:
    """Parse QES quarter label to Timestamp.

    Handles both Excel-parsed datetime objects (coerced to str) and
    string labels like "Dec-25 (Provisional)" or "Mar-24 (Revised)".

    Args:
        label: Quarter label string

    Returns:
        Timestamp for start of quarter, or None if unparseable
    """
    label = str(label).strip()

    # Try to detect if label looks like an ISO date string from Excel parsing
    # e.g. "2005-03-01 00:00:00" or "2005-06-01"
    iso_match = re.match(r"^(\d{4})-(\d{2})-\d{2}", label)
    if iso_match:
        year = int(iso_match.group(1))
        month = int(iso_match.group(2))
        for _abbr, (m, _q) in _QUARTER_MONTHS.items():
            if m == month:
                return pd.Timestamp(year=year, month=month, day=1)
        return None

    # Label format: "Mar-25 (Provisional)" or "Dec-24 (Revised)"
    str_match = re.match(r"^([A-Za-z]{3})-(\d{2})", label)
    if str_match:
        month_abbr = str_match.group(1).capitalize()
        year_2d = int(str_match.group(2))
        year = 2000 + year_2d if year_2d < 50 else 1900 + year_2d
        if month_abbr in _QUARTER_MONTHS:
            month, _ = _QUARTER_MONTHS[month_abbr]
            return pd.Timestamp(year=year, month=month, day=1)

    return None


def _quarter_from_month(month: int) -> int:
    """Map month number to quarter (1-4)."""
    return (month - 1) // 3 + 1


def parse_qes_file(file_path: str | Path, adjusted: bool = True) -> pd.DataFrame:
    """Parse QES supplementary tables Excel file into long-format DataFrame.

    Reads Table 5.2 (seasonally adjusted) or Table 5.3 (unadjusted), which
    contain quarterly employee job counts by broad industry sector.

    Args:
        file_path: Path to downloaded QES supplementary tables Excel file
        adjusted: If True, read Table 5.2 (seasonally adjusted).
                  If False, read Table 5.3 (unadjusted).

    Returns:
        DataFrame with columns:
            - date: Timestamp (first day of quarter)
            - year: int
            - quarter: int (1-4)
            - quarter_label: str (e.g. "Q1 2025")
            - manufacturing_jobs: int
            - construction_jobs: int
            - services_jobs: int
            - other_jobs: int
            - total_jobs: int
            - adjusted: bool (True if seasonally adjusted)

    Raises:
        NISRAValidationError: If file structure is unexpected
    """
    file_path = Path(file_path)
    sheet_name = "Table 5.2" if adjusted else "Table 5.3"

    try:
        raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    except Exception as e:
        raise NISRAValidationError(f"Failed to read QES file sheet {sheet_name}: {e}") from e

    # Row 2 (index 2) is the header row
    header_row = raw.iloc[2]

    # Map column positions for the "Employee Jobs" columns (not "Quarterly Change")
    col_map = {}
    for i, val in enumerate(header_row):
        val_str = str(val).replace("\n", " ").strip().upper()
        if "MANUFACTURING" in val_str and "EMPLOYEE JOBS" in val_str:
            col_map["manufacturing_jobs"] = i
        elif "CONSTRUCTION" in val_str and "EMPLOYEE JOBS" in val_str:
            col_map["construction_jobs"] = i
        elif "SERVICES" in val_str and "EMPLOYEE JOBS" in val_str:
            col_map["services_jobs"] = i
        elif "OTHER" in val_str and "EMPLOYEE JOBS" in val_str:
            col_map["other_jobs"] = i
        elif "ALL" in val_str and "EMPLOYEE JOBS" in val_str:
            col_map["total_jobs"] = i

    if len(col_map) < 5:
        raise NISRAValidationError(
            f"Could not locate all sector columns in {sheet_name}. Found: {list(col_map.keys())}"
        )

    # Data rows start at index 3
    records = []
    for i in range(3, len(raw)):
        row = raw.iloc[i]
        label = str(row.iloc[0]).strip()
        if not label or label == "nan":
            continue

        ts = _parse_qes_date(label)
        if ts is None:
            continue

        record = {
            "date": ts,
            "year": ts.year,
            "quarter": _quarter_from_month(ts.month),
            "quarter_label": f"Q{_quarter_from_month(ts.month)} {ts.year}",
            "adjusted": adjusted,
        }
        for col_name, col_idx in col_map.items():
            val = row.iloc[col_idx]
            record[col_name] = int(val) if not pd.isna(val) and val != "-" else None

        records.append(record)

    if not records:
        raise NISRAValidationError(f"No valid data rows found in QES {sheet_name}")

    df = pd.DataFrame(records)
    col_order = [
        "date",
        "year",
        "quarter",
        "quarter_label",
        "manufacturing_jobs",
        "construction_jobs",
        "services_jobs",
        "other_jobs",
        "total_jobs",
        "adjusted",
    ]
    df = df[col_order]
    df = df.sort_values("date").reset_index(drop=True)

    label = "adjusted" if adjusted else "unadjusted"
    logger.info(
        f"Parsed QES ({label}): {len(df)} quarters, "
        f"{df['year'].min()} Q{df['quarter'].iloc[0]}-{df['year'].max()} Q{df['quarter'].iloc[-1]}"
    )
    return df


def get_latest_qes(force_refresh: bool = False, adjusted: bool = True) -> pd.DataFrame:
    """Get the latest NI Quarterly Employment Survey data.

    Args:
        force_refresh: If True, bypass cache and download fresh data
        adjusted: If True (default), return seasonally adjusted series (Table 5.2).
                  If False, return unadjusted series (Table 5.3).

    Returns:
        DataFrame with columns: date, year, quarter, quarter_label,
        manufacturing_jobs, construction_jobs, services_jobs, other_jobs,
        total_jobs, adjusted

    Raises:
        NISRADataNotFoundError: If latest publication cannot be found
        NISRAValidationError: If file structure is unexpected

    Example:
        >>> df = get_latest_qes()
        >>> latest = df.iloc[-1]
        >>> print(f"NI employee jobs {latest['quarter_label']}: {latest['total_jobs']:,}")
        NI employee jobs Q4 2025: 843,860
    """
    excel_url = get_latest_qes_publication_url()
    logger.info(f"Downloading QES supplementary tables from: {excel_url}")
    file_path = download_file(excel_url, cache_ttl_hours=24 * 90, force_refresh=force_refresh)
    return parse_qes_file(file_path, adjusted=adjusted)


def validate_qes_data(df: pd.DataFrame) -> bool:
    """Validate QES DataFrame for basic integrity.

    Args:
        df: DataFrame from get_latest_qes()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If validation fails
    """
    required = {
        "date",
        "year",
        "quarter",
        "total_jobs",
        "manufacturing_jobs",
        "construction_jobs",
        "services_jobs",
        "other_jobs",
    }
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if len(df) < 40:
        raise NISRAValidationError(f"Too few rows ({len(df)}); expected 40+ quarters from 2005")

    if (df["total_jobs"] < 0).any():
        raise NISRAValidationError("Negative total_jobs values found")

    # Total jobs in NI should be roughly 600k-900k across the series
    if (df["total_jobs"] > 1_000_000).any():
        raise NISRAValidationError("total_jobs implausibly high (>1,000,000)")

    if (df["total_jobs"] < 500_000).any():
        raise NISRAValidationError("total_jobs implausibly low (<500,000)")

    return True


def get_qes_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter QES data to a specific year.

    Args:
        df: DataFrame from get_latest_qes()
        year: Year to filter

    Returns:
        Filtered DataFrame (up to 4 quarters)

    Example:
        >>> df = get_latest_qes()
        >>> df_2024 = get_qes_by_year(df, 2024)
        >>> print(df_2024[['quarter_label', 'total_jobs']])
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_qes_growth(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate quarter-on-quarter and year-on-year growth for total employee jobs.

    Args:
        df: DataFrame from get_latest_qes()

    Returns:
        DataFrame with additional columns:
            - total_qoq: Total jobs quarter-on-quarter change (absolute)
            - total_yoy: Total jobs year-on-year % change
            - services_yoy: Services jobs year-on-year % change
            - manufacturing_yoy: Manufacturing jobs year-on-year % change

    Example:
        >>> df = get_latest_qes()
        >>> growth = get_qes_growth(df)
        >>> print(growth[['quarter_label', 'total_jobs', 'total_yoy']].tail(8))
    """
    result = df.copy()
    result["total_qoq"] = result["total_jobs"].diff(1)
    result["total_yoy"] = result["total_jobs"].pct_change(4).mul(100).round(2)
    result["services_yoy"] = result["services_jobs"].pct_change(4).mul(100).round(2)
    result["manufacturing_yoy"] = result["manufacturing_jobs"].pct_change(4).mul(100).round(2)
    return result


def get_sector_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate each sector's share of total employee jobs.

    Args:
        df: DataFrame from get_latest_qes()

    Returns:
        DataFrame with additional columns:
            - manufacturing_share: Manufacturing % of total
            - construction_share: Construction % of total
            - services_share: Services % of total
            - other_share: Other industries % of total

    Example:
        >>> df = get_latest_qes()
        >>> shares = get_sector_shares(df)
        >>> latest = shares.iloc[-1]
        >>> print(f"Services share: {latest['services_share']:.1f}%")
    """
    result = df.copy()
    for sector in ("manufacturing", "construction", "services", "other"):
        result[f"{sector}_share"] = (result[f"{sector}_jobs"] / result["total_jobs"] * 100).round(1)
    return result
