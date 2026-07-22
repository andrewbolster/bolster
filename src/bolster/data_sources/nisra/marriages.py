"""NISRA Marriage and Civil Partnership Registrations Data Source.

Provides access to monthly marriage and civil partnership registration data for Northern Ireland.

Data includes:
- Monthly marriage registrations from 2006 to present
- Monthly civil partnership registrations from 2006 to present
- Total registrations by month and year
- Historical time series for trend analysis

Registrations represent when the event was registered, not when the ceremony occurred.
The data is published monthly with provisional figures for the current year and final figures for
previous years.

Data Source:
    **Marriages Mother Page**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/marriages
    **Civil Partnerships Page**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/civil-partnerships

    These pages list all relevant statistics publications in reverse chronological order
    (newest first). The module automatically scrapes these pages to find the latest
    publications, then downloads the Excel files.

Update Frequency: Monthly (published around 11th of the following month)
Geographic Coverage: Northern Ireland
Reference Date: Month of registration

Example:
    >>> from bolster.data_sources.nisra import marriages
    >>> # Get latest marriage registrations
    >>> df = marriages.get_latest_marriages()
    >>> sorted(df.columns.tolist())
    ['date', 'marriages', 'month', 'year']

    >>> # Get latest civil partnership registrations
    >>> cp_df = marriages.get_latest_civil_partnerships()
    >>> sorted(cp_df.columns.tolist())
    ['civil_partnerships', 'date', 'month', 'year']

    >>> # Filter for a specific year
    >>> df_2024 = df[df['year'] == 2024]
    >>> len(df_2024) > 0
    True
"""

import logging
import re
from pathlib import Path

import pandas as pd

from ._base import NISRAValidationError, download_file, find_publication_link

logger = logging.getLogger(__name__)

# Base URLs for marriage and civil partnership statistics
MARRIAGES_BASE_URL = "https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/marriages"
CIVIL_PARTNERSHIPS_BASE_URL = "https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/civil-partnerships"


def get_latest_marriages_publication_url() -> tuple[str, str]:
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
    excel_url = find_publication_link(
        hub_url=MARRIAGES_BASE_URL,
        pub_text_contains="Monthly Marriages",
        pub_href_contains="publications",
        file_href_contains="Marriages",
    )
    date_match = re.search(r"([A-Z][a-z]+)\s+(\d{4})\.xlsx", excel_url)
    pub_date = f"{date_match.group(1)} {date_match.group(2)}" if date_match else "Unknown"
    return excel_url, pub_date


def parse_marriages_file(file_path: str | Path) -> pd.DataFrame:
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
        raise NISRAValidationError(f"Failed to read marriages file: {e}") from e

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
        >>> df = get_latest_marriages()
        >>> sorted(df.columns.tolist())
        ['date', 'marriages', 'month', 'year']

        >>> df_2024 = df[df['year'] == 2024]
        >>> total_2024 = df_2024['marriages'].sum()
        >>> bool(total_2024 > 0)
        True
    """
    # Discover latest publication
    excel_url, pub_date = get_latest_marriages_publication_url()

    logger.info(f"Downloading marriages data ({pub_date}) from: {excel_url}")

    # Cache for 30 days (monthly data, but infrequent updates)
    cache_ttl_hours = 30 * 24
    file_path = download_file(excel_url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    # Parse the file
    return parse_marriages_file(file_path)


def validate_marriages_temporal_continuity(df: pd.DataFrame) -> bool:  # pragma: no cover
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
        >>> bool(total > 0)
        True
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
        >>> sorted(summary.columns.tolist())
        ['avg_per_month', 'months_reported', 'total_marriages', 'year']
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


# ============================================================================
# Civil Partnership Functions
# ============================================================================


def get_latest_civil_partnerships_publication_url() -> tuple[str, str]:
    """Scrape NISRA civil partnerships page to find the latest monthly civil partnerships file.

    Returns:
        Tuple of (excel_file_url, publication_date)

    Raises:
        NISRADataNotFoundError: If publication or file not found
    """
    excel_url = find_publication_link(
        hub_url=CIVIL_PARTNERSHIPS_BASE_URL,
        pub_href_contains="monthly-civil-partnerships",
        file_href_contains="Partnership",
    )
    date_match = re.search(r"([A-Z][a-z]+)\s+(\d{4})\.xlsx", excel_url)
    pub_date = f"{date_match.group(1)} {date_match.group(2)}" if date_match else "Unknown"
    return excel_url, pub_date


def parse_civil_partnerships_file(file_path: str | Path) -> pd.DataFrame:
    """Parse NISRA monthly civil partnerships Excel file.

    The civil partnerships file contains a "Civil Partnerships" sheet with a wide-format table:
    - Rows: Months (January-December)
    - Columns: Years (2006-present)
    - Values: Number of civil partnership registrations

    Args:
        file_path: Path to the civil partnerships Excel file

    Returns:
        DataFrame with columns:
            - date: datetime (first day of month)
            - year: int (year of registration)
            - month: str (month name)
            - civil_partnerships: int (number of civil partnership registrations)

    Raises:
        NISRAValidationError: If file structure is unexpected
    """
    file_path = Path(file_path)

    try:
        # Read the Civil Partnerships sheet
        # Row 0: Title
        # Row 1: "This sheet contains..."
        # Row 2: "All Civil Partnerships"
        # Row 3: Headers (Month of Registration, 2006, 2007, ...)
        # Row 4+: Data (January, February, ...)
        df_raw = pd.read_excel(
            file_path,
            sheet_name="Civil Partnerships",
            header=None,
            skiprows=3,  # Skip to header row
            nrows=13,  # Read header + 12 months
        )
    except Exception as e:
        raise NISRAValidationError(f"Failed to read civil partnerships file: {e}") from e

    # First row is the header
    headers = df_raw.iloc[0].tolist()
    df_raw = df_raw.iloc[1:].reset_index(drop=True)
    df_raw.columns = headers

    # Find the month column
    month_col = None
    for col in df_raw.columns:
        col_str = str(col)
        if "Month" in col_str or "Registration" in col_str:
            month_col = col
            break

    if not month_col:
        month_col = df_raw.columns[0]

    # Rename month column
    df_raw = df_raw.rename(columns={month_col: "month"})

    # Filter out Total row and any non-month rows
    month_names = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    df_raw = df_raw[df_raw["month"].isin(month_names)].copy()

    # Identify year columns
    year_cols = []
    for col in df_raw.columns:
        if col == "month":
            continue
        col_str = str(col)
        year_match = re.search(r"(\d{4})", col_str)
        if year_match:
            year_cols.append((col, int(year_match.group(1))))

    # Build long-format data
    records = []
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

    for _, row in df_raw.iterrows():
        month_name = row["month"]
        month_num = month_map.get(month_name)

        if not month_num:
            continue

        for col, year in year_cols:
            val = row[col]
            if pd.notna(val) and val != "-":
                try:
                    civil_partnerships = int(float(val))
                except (ValueError, TypeError):
                    civil_partnerships = None

                if civil_partnerships is not None:
                    records.append(
                        {
                            "year": year,
                            "month": month_name,
                            "month_num": month_num,
                            "civil_partnerships": civil_partnerships,
                        }
                    )

    df = pd.DataFrame(records)

    # Create datetime column
    df["date"] = pd.to_datetime({"year": df["year"], "month": df["month_num"], "day": 1})

    # Select and reorder columns
    result = df[["date", "year", "month", "civil_partnerships"]].copy()

    # Sort by date
    result = result.sort_values("date").reset_index(drop=True)

    logger.info(
        f"Parsed {len(result)} monthly civil partnership records "
        f"({result['date'].min().strftime('%Y-%m')} to {result['date'].max().strftime('%Y-%m')})"
    )

    return result


def get_latest_civil_partnerships(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest monthly civil partnership registrations data.

    Automatically discovers and downloads the most recent civil partnership registrations
    from the NISRA website.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - date: datetime (first day of month)
            - year: int (year of registration)
            - month: str (month name)
            - civil_partnerships: int (number of civil partnership registrations)

    Raises:
        NISRADataNotFoundError: If latest publication cannot be found
        NISRAValidationError: If file structure is unexpected

    Example:
        >>> df = get_latest_civil_partnerships()
        >>> sorted(df.columns.tolist())
        ['civil_partnerships', 'date', 'month', 'year']
        >>> df_2024 = df[df['year'] == 2024]
        >>> total = df_2024['civil_partnerships'].sum()
        >>> bool(total >= 0)
        True
    """
    excel_url, pub_date = get_latest_civil_partnerships_publication_url()

    logger.info(f"Downloading civil partnerships data ({pub_date}) from: {excel_url}")

    cache_ttl_hours = 30 * 24
    file_path = download_file(excel_url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    return parse_civil_partnerships_file(file_path)


def get_civil_partnerships_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter civil partnership data for a specific year.

    Args:
        df: DataFrame from get_latest_civil_partnerships()
        year: Year to filter

    Returns:
        Filtered DataFrame
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_civil_partnerships_summary_by_year(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate annual civil partnership totals and statistics.

    Args:
        df: DataFrame from get_latest_civil_partnerships()

    Returns:
        DataFrame with columns:
            - year: int
            - total_civil_partnerships: int
            - months_reported: int
            - avg_per_month: float
    """
    summary = (
        df.groupby("year")
        .agg(
            total_civil_partnerships=("civil_partnerships", "sum"),
            months_reported=("civil_partnerships", lambda x: x.notna().sum()),
            avg_per_month=("civil_partnerships", "mean"),
        )
        .reset_index()
    )

    summary["avg_per_month"] = summary["avg_per_month"].round(1)

    return summary
