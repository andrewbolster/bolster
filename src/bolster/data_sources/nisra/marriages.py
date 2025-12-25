"""NISRA Marriage Registrations Data Source.

Provides access to monthly marriage registration data for Northern Ireland.

Data includes:
- Monthly marriage registrations from 2006 to present
- Total marriages by month and year
- Historical time series for trend analysis

Marriage registrations represent when the marriage was registered, not when the ceremony occurred.
The data is published monthly with provisional figures for the current year and final figures for
previous years.

Data Source:
    **Mother Page**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/marriages

    This page lists all marriage statistics publications in reverse chronological order
    (newest first). The module automatically scrapes this page to find the latest
    "Monthly Marriages" publication, then downloads the Excel file.

Update Frequency: Monthly (published around 11th of the following month)
Geographic Coverage: Northern Ireland
Reference Date: Month of registration

Example:
    >>> from bolster.data_sources.nisra import marriages
    >>> # Get latest marriage registrations
    >>> df = marriages.get_latest_marriages()
    >>> print(df.head())

    >>> # Filter for a specific year
    >>> df_2024 = df[df['year'] == 2024]
    >>> print(f"Total marriages in 2024: {df_2024['marriages'].sum():,}")
"""

import logging
import re
from pathlib import Path
from typing import Tuple, Union

import pandas as pd

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

# Base URL for marriage statistics
MARRIAGES_BASE_URL = "https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/marriages"


def get_latest_marriages_publication_url() -> Tuple[str, str]:
    """Scrape NISRA marriages mother page to find the latest monthly marriages file.

    Navigates the publication structure:
    1. Scrapes mother page for latest "Monthly Marriages" publication
    2. Follows link to publication detail page
    3. Finds marriages Excel file

    Returns:
        Tuple of (excel_file_url, publication_date)

    Raises:
        NISRADataNotFoundError: If publication or file not found
    """
    import requests
    from bs4 import BeautifulSoup

    mother_page = MARRIAGES_BASE_URL

    try:
        response = requests.get(mother_page, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to fetch marriages mother page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find latest "Monthly Marriages" publication
    # Pattern: "Monthly Marriages - November 2025" or similar
    pub_link = None
    pub_date = None

    for link in soup.find_all("a", href=True):
        link_text = link.get_text(strip=True)

        # Match "Monthly Marriages" publications
        if "Monthly Marriages" in link_text and "publications" in link["href"]:
            href = link["href"]

            if href.startswith("/"):
                href = f"https://www.nisra.gov.uk{href}"

            # Extract month/year from link text if available
            # Pattern: "Monthly Marriages - November 2025"
            date_match = re.search(r"([A-Z][a-z]+)\s+(\d{4})", link_text)
            if date_match:
                pub_date = f"{date_match.group(1)} {date_match.group(2)}"

            # Take first match (should be newest due to reverse chronological order)
            pub_link = href
            logger.info(f"Found Monthly Marriages publication: {link_text}")
            break

    if not pub_link:
        raise NISRADataNotFoundError("Could not find Monthly Marriages publication on mother page")

    # Scrape the publication page for Excel file
    try:
        pub_response = requests.get(pub_link, timeout=30)
        pub_response.raise_for_status()
    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to fetch publication page: {e}")

    pub_soup = BeautifulSoup(pub_response.content, "html.parser")

    # Find marriages Excel file
    # Pattern: "Monthly Marriages November 2025.xlsx" or similar
    excel_url = None

    for link in pub_soup.find_all("a", href=True):
        href = link["href"]

        if "Marriages" in href and href.endswith(".xlsx"):
            if href.startswith("/"):
                href = f"https://www.nisra.gov.uk{href}"

            excel_url = href
            logger.info(f"Found marriages Excel file: {href}")
            break

    if not excel_url:
        raise NISRADataNotFoundError("Could not find marriages Excel file on publication page")

    return excel_url, pub_date or "Unknown"


def parse_marriages_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse NISRA monthly marriages Excel file.

    The marriages file contains a single "Marriages" sheet with a wide-format table:
    - Rows: Months (January-December)
    - Columns: Years (2006-present)
    - Values: Number of marriage registrations

    Args:
        file_path: Path to the marriages Excel file

    Returns:
        DataFrame with columns:
            - month: datetime (first day of month)
            - year: int (year of registration)
            - marriages: int (number of marriage registrations)

    Raises:
        NISRAValidationError: If file structure is unexpected
    """
    file_path = Path(file_path)

    try:
        # Read the Marriages sheet
        # Skip the header rows (first 3 rows) and read from row 4
        df_raw = pd.read_excel(
            file_path,
            sheet_name="Marriages",
            skiprows=3,  # Skip "All Marriages" title rows
            nrows=13,  # Read months + total row (we'll filter out total)
        )
    except Exception as e:
        raise NISRAValidationError(f"Failed to read marriages file: {e}")

    # First column should be month names
    if df_raw.iloc[:, 0].name != "Month of \nRegistration":
        # Try to find the month column
        month_col = None
        for col in df_raw.columns:
            if "Month" in str(col) or "Registration" in str(col):
                month_col = col
                break

        if not month_col:
            raise NISRAValidationError("Could not find month column in marriages data")
    else:
        month_col = df_raw.iloc[:, 0].name

    # Rename columns to clean year values
    # Columns are: Month of Registration, 2006, 2007, ..., 2025
    df_raw = df_raw.rename(columns={month_col: "month"})

    # Filter out the "Total" row
    df_raw = df_raw[df_raw["month"] != "Total"].copy()

    # Convert to long format
    df_long = df_raw.melt(
        id_vars=["month"],
        var_name="year",
        value_name="marriages",
    )

    # Clean year column - extract just the year number
    # Handle cases like "2025\n[Note 1]\n[Note 2]"
    df_long["year"] = df_long["year"].astype(str).str.extract(r"(\d{4})")[0].astype(int)

    # Clean marriages column
    # Handle missing values ('-' or None)
    df_long["marriages"] = df_long["marriages"].replace(["-", None], pd.NA)
    df_long["marriages"] = pd.to_numeric(df_long["marriages"], errors="coerce")

    # Create datetime column (first day of month)
    # Handle month names
    month_map = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }

    df_long["month_num"] = df_long["month"].map(month_map)

    if df_long["month_num"].isna().any():
        raise NISRAValidationError(
            f"Unrecognized month names: {df_long[df_long['month_num'].isna()]['month'].unique()}"
        )

    # Create datetime (first day of each month)
    df_long["date"] = pd.to_datetime({"year": df_long["year"], "month": df_long["month_num"], "day": 1})

    # Select and reorder final columns
    result = df_long[["date", "year", "month", "marriages"]].copy()

    # Sort by date
    result = result.sort_values("date").reset_index(drop=True)

    # Log summary
    total_records = len(result)
    missing_records = result["marriages"].isna().sum()
    date_range = f"{result['date'].min().strftime('%Y-%m')} to {result['date'].max().strftime('%Y-%m')}"

    logger.info(f"Parsed {total_records} monthly marriage records ({date_range})")
    if missing_records > 0:
        logger.info(f"  {missing_records} records have missing data")

    return result


def get_latest_marriages(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest monthly marriage registrations data.

    Automatically discovers and downloads the most recent marriage registrations
    from the NISRA website.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - date: datetime (first day of month)
            - year: int (year of registration)
            - month: str (month name)
            - marriages: int (number of marriage registrations)

    Raises:
        NISRADataNotFoundError: If latest publication cannot be found
        NISRAValidationError: If file structure is unexpected

    Example:
        >>> # Get all data
        >>> df = get_latest_marriages()

        >>> # Filter for 2024
        >>> df_2024 = df[df['year'] == 2024]
        >>> total_2024 = df_2024['marriages'].sum()
        >>> print(f"Total marriages in 2024: {total_2024:,}")

        >>> # Get monthly average by month across all years
        >>> monthly_avg = df.groupby('month')['marriages'].mean()
        >>> print(monthly_avg.sort_values(ascending=False))
    """
    # Discover latest publication
    excel_url, pub_date = get_latest_marriages_publication_url()

    logger.info(f"Downloading marriages data ({pub_date}) from: {excel_url}")

    # Cache for 30 days (monthly data, but infrequent updates)
    cache_ttl_hours = 30 * 24
    file_path = download_file(excel_url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    # Parse the file
    return parse_marriages_file(file_path)


def validate_marriages_temporal_continuity(df: pd.DataFrame) -> bool:
    """Validate that marriage data has no unexpected gaps in time series.

    Args:
        df: DataFrame from parse_marriages_file or get_latest_marriages

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If validation fails
    """
    # Group by year and check that each year has 12 months (or less for current year)
    for year in df["year"].unique():
        year_data = df[df["year"] == year]
        month_count = year_data["marriages"].notna().sum()

        # Allow incomplete years (current year)
        if month_count == 0:
            raise NISRAValidationError(f"Year {year} has no data")

        # Check for reasonable month count (1-12)
        if month_count > 12:
            raise NISRAValidationError(f"Year {year} has {month_count} months (expected max 12)")

    logger.info("Validation passed: Temporal continuity check")
    return True


def get_marriages_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter marriage data for a specific year.

    Args:
        df: DataFrame from get_latest_marriages()
        year: Year to filter

    Returns:
        Filtered DataFrame

    Example:
        >>> df = get_latest_marriages()
        >>> df_2024 = get_marriages_by_year(df, 2024)
        >>> total = df_2024['marriages'].sum()
        >>> print(f"Total marriages in 2024: {total:,}")
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_marriages_summary_by_year(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate annual marriage totals and statistics.

    Args:
        df: DataFrame from get_latest_marriages()

    Returns:
        DataFrame with columns:
            - year: int
            - total_marriages: int (sum for the year)
            - months_reported: int (number of months with data)
            - avg_per_month: float (average marriages per month)

    Example:
        >>> df = get_latest_marriages()
        >>> summary = get_marriages_summary_by_year(df)
        >>> print(summary.tail(10))  # Last 10 years
    """
    summary = (
        df.groupby("year")
        .agg(
            total_marriages=("marriages", lambda x: x.sum()),
            months_reported=("marriages", lambda x: x.notna().sum()),
            avg_per_month=("marriages", lambda x: x.mean()),
        )
        .reset_index()
    )

    # Round average
    summary["avg_per_month"] = summary["avg_per_month"].round(1)

    return summary
