"""NISRA Monthly Stillbirth Registrations Data Source.

Provides access to monthly stillbirth registration statistics for Northern Ireland.
A stillbirth is defined as a baby born after 24 weeks of pregnancy that did not
show any signs of life.

Data covers registrations by month from 2006 to present, updated monthly.

Data Source:
    **Mother Page**: https://www.nisra.gov.uk/publications/monthly-stillbirths

    The monthly Excel file contains a single "Stillbirths" sheet with counts
    by month of registration (rows) and year (columns), covering 2006 to present.

Update Frequency: Monthly (published ~6 weeks after reference month)
Geographic Coverage: Northern Ireland (resident stillbirths)

Example:
    >>> from bolster.data_sources.nisra import stillbirths
    >>> df = stillbirths.get_latest_stillbirths()
    >>> print(df.head())

    >>> # Total stillbirths in 2024
    >>> total_2024 = df[df['year'] == 2024]['stillbirths'].sum()
    >>> print(f"Stillbirths in 2024: {total_2024}")
"""

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
    safe_int,
)

logger = logging.getLogger(__name__)

STILLBIRTHS_PUBLICATION_URL = "https://www.nisra.gov.uk/publications/monthly-stillbirths"

MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def get_latest_stillbirths_publication_url() -> str:
    """Scrape NISRA stillbirths publication page to find the latest Excel file.

    Returns:
        URL of the latest monthly stillbirths Excel file

    Raises:
        NISRADataNotFoundError: If publication or file not found
    """
    try:
        response = session.get(STILLBIRTHS_PUBLICATION_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch stillbirths publication page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    excel_url = None
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        link_text = a_tag.get_text(strip=True).lower()
        if "monthly stillbirths" in link_text and href.endswith(".xlsx"):
            if href.startswith("/"):
                excel_url = f"https://www.nisra.gov.uk{href}"
            else:
                excel_url = href
            logger.info(f"Found stillbirths file: {excel_url}")
            break

    if not excel_url:
        raise NISRADataNotFoundError("Could not find Monthly Stillbirths Excel file on publication page")

    return excel_url


def parse_stillbirths_file(file_path: str | Path) -> pd.DataFrame:
    """Parse NISRA monthly stillbirths Excel file into long-format DataFrame.

    The file has a single "Stillbirths" sheet with months as rows and years
    as columns (wide format). This function melts it into long format.

    Args:
        file_path: Path to the downloaded stillbirths Excel file

    Returns:
        DataFrame with columns:
            - date: Timestamp (first day of registration month)
            - year: int
            - month: str (e.g. "January")
            - stillbirths: int

    Raises:
        NISRAValidationError: If file structure is unexpected
    """
    file_path = Path(file_path)

    try:
        raw = pd.read_excel(file_path, sheet_name="Stillbirths", header=None)
    except Exception as e:
        raise NISRAValidationError(f"Failed to read stillbirths file: {e}") from e

    # Locate the header row: first row where column 0 is "January" or similar month
    # or row where year integers appear across the row
    header_row_idx = None
    data_start_idx = None

    for i, row in raw.iterrows():
        cell = str(row.iloc[0]).strip()
        # Header row has "Month of Registration" or similar in col 0, years in other cols
        # Data rows start with month names
        if cell in MONTH_ORDER:
            data_start_idx = i
            header_row_idx = i - 1
            break

    if header_row_idx is None or data_start_idx is None:
        raise NISRAValidationError("Could not locate data rows in stillbirths sheet")

    # Extract year headers from header row
    header = raw.iloc[header_row_idx]
    years = []
    year_col_indices = []

    for col_idx, val in enumerate(header):
        if col_idx == 0:
            continue
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        # Year values may have notes appended like "2025\n[Note 1]"
        year_str = str(val).strip().split("\n")[0].strip()
        try:
            year = int(float(year_str))
            years.append(year)
            year_col_indices.append(col_idx)
        except (ValueError, TypeError):
            continue

    if not years:
        raise NISRAValidationError("Could not extract year headers from stillbirths sheet")

    # Extract monthly data rows (skip Total row and notes)
    records = []
    for i in range(data_start_idx, len(raw)):
        row = raw.iloc[i]
        month = str(row.iloc[0]).strip()
        if month not in MONTH_ORDER:
            break  # hit Total row or notes

        for year, col_idx in zip(years, year_col_indices):
            val = row.iloc[col_idx]
            count = safe_int(val)
            if count is None:
                continue  # not yet published (future months shown as "-")
            records.append({"year": year, "month": month, "stillbirths": count})

    if not records:
        raise NISRAValidationError("No data rows found in stillbirths sheet")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(
        df["year"].astype(str) + " " + df["month"], format="%Y %B"
    )
    df = df[["date", "year", "month", "stillbirths"]]
    df = df.sort_values("date").reset_index(drop=True)

    logger.info(f"Parsed stillbirths: {len(df)} rows, {df['year'].min()}-{df['year'].max()}")
    return df


def get_latest_stillbirths(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest monthly stillbirth registrations for Northern Ireland.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - date: Timestamp (first of registration month)
            - year: int
            - month: str
            - stillbirths: int

    Raises:
        NISRADataNotFoundError: If latest publication cannot be found
        NISRAValidationError: If file structure is unexpected

    Example:
        >>> df = get_latest_stillbirths()
        >>> annual = df.groupby('year')['stillbirths'].sum()
        >>> print(annual.tail())
    """
    excel_url = get_latest_stillbirths_publication_url()
    logger.info(f"Downloading stillbirths data from: {excel_url}")
    file_path = download_file(excel_url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)
    return parse_stillbirths_file(file_path)


def validate_stillbirths_data(df: pd.DataFrame) -> bool:
    """Validate stillbirths DataFrame for basic integrity.

    Args:
        df: DataFrame from get_latest_stillbirths()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If validation fails
    """
    required_cols = {"date", "year", "month", "stillbirths"}
    missing = required_cols - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if (df["stillbirths"] < 0).any():
        raise NISRAValidationError("Negative stillbirth counts found")

    # Annual totals should be within plausible range for NI (~40-130 per year)
    annual = df.groupby("year")["stillbirths"].sum()
    if (annual > 200).any():
        raise NISRAValidationError(f"Annual stillbirths implausibly high: {annual[annual > 200].to_dict()}")

    return True


def get_stillbirths_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter stillbirths data to a specific year.

    Args:
        df: DataFrame from get_latest_stillbirths()
        year: Year to filter

    Returns:
        Filtered DataFrame

    Example:
        >>> df = get_latest_stillbirths()
        >>> df_2024 = get_stillbirths_by_year(df, 2024)
        >>> print(df_2024['stillbirths'].sum())
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_stillbirth_rate(
    stillbirths_df: pd.DataFrame,
    births_df: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate monthly stillbirth rate per 1,000 total births (live + still).

    Args:
        stillbirths_df: DataFrame from get_latest_stillbirths()
        births_df: DataFrame from births.get_latest_births(event_type='registration')

    Returns:
        DataFrame with columns: date, year, month, stillbirths, live_births,
        total_births, stillbirth_rate

    Example:
        >>> from bolster.data_sources.nisra import stillbirths, births
        >>> sb = stillbirths.get_latest_stillbirths()
        >>> lb = births.get_latest_births(event_type='registration')
        >>> rate = stillbirths.get_stillbirth_rate(sb, lb)
        >>> print(rate[['year', 'month', 'stillbirth_rate']].tail(12))
    """
    # births_df has 'tests_conducted' or 'births_persons' depending on event_type
    births_col = next(
        (c for c in births_df.columns if "persons" in c.lower() or "births" in c.lower()),
        None,
    )
    if births_col is None:
        raise NISRAValidationError("Could not identify births count column in births DataFrame")

    live = births_df[["date", births_col]].rename(columns={births_col: "live_births"})
    merged = stillbirths_df.merge(live, on="date", how="inner")
    merged["total_births"] = merged["live_births"] + merged["stillbirths"]
    merged["stillbirth_rate"] = (
        (merged["stillbirths"] / merged["total_births"]) * 1000
    ).round(2)
    return merged


def get_annual_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate annual totals and trends for stillbirths.

    Args:
        df: DataFrame from get_latest_stillbirths()

    Returns:
        DataFrame with columns: year, total_stillbirths, yoy_change, yoy_pct_change

    Example:
        >>> df = get_latest_stillbirths()
        >>> summary = get_annual_summary(df)
        >>> print(summary.tail(5))
    """
    annual = df.groupby("year")["stillbirths"].sum().reset_index()
    annual = annual.rename(columns={"stillbirths": "total_stillbirths"})
    annual["yoy_change"] = annual["total_stillbirths"].diff()
    annual["yoy_pct_change"] = annual["total_stillbirths"].pct_change().mul(100).round(1)
    return annual
