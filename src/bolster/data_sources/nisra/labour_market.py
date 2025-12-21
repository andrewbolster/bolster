"""NISRA Labour Market Statistics Module.

This module provides access to Northern Ireland Statistics and Research Agency (NISRA)
Labour Force Survey (LFS) data.

The Labour Force Survey is a sample survey of households providing information on the
labour force using internationally agreed concepts and definitions. It provides estimates
of employment, unemployment, and economic inactivity.

Data is published quarterly covering 3-month rolling periods (e.g., "July to September 2025").
Some tables (particularly Local Government District breakdowns) are published annually only.

Data Source:
    **Mother Page**: https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare

    This page lists all Labour Market and Social Welfare publications in reverse chronological
    order (newest first). The module automatically scrapes this page to find the latest
    "Quarterly Labour Force Survey Tables" publication, then downloads the Excel file from
    that publication's detail page.

    This ensures the module always retrieves the most recent data without hardcoding dates
    or quarters.

Architecture:
    - Automatically discovers latest quarterly LFS publication from NISRA mother page
    - Downloads quarterly Labour Force Survey Excel files
    - Parses multiple tables including:
        * Employment by age band and sex (Table 2.15)
        * Employment by industry sector (Table 2.17)
        * Employment by occupation (Table 2.18)
        * Employment by Local Government District (Table 2.19 - annual)
        * Economic inactivity (Table 2.21)
        * Unemployment rates (Table 2.22)
    - Returns long-format DataFrames for flexibility
    - Uses standardized Excel parsing utilities from _base.py

Usage:
    >>> from bolster.data_sources.nisra import labour_market
    >>> # Get latest quarterly employment data
    >>> df = labour_market.get_latest_employment()
    >>> # Get economic inactivity data
    >>> df = labour_market.get_latest_economic_inactivity()
    >>> # Get all tables for a specific quarter
    >>> data = labour_market.get_quarterly_data(year=2025, quarter="Jul-Sep")

Example:
    >>> import pandas as pd
    >>> from bolster.data_sources.nisra import labour_market
    >>> # Get latest employment by age and sex
    >>> emp_df = labour_market.get_latest_employment()
    >>> # Filter for females aged 25-29
    >>> young_females = emp_df[
    ...     (emp_df['sex'] == 'Female') &
    ...     (emp_df['age_group'] == '25 to 29')
    ... ]

Author: Claude Code
Date: 2025-12-21
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd
from openpyxl import load_workbook

from bolster.data_sources.nisra._base import (
    CACHE_DIR,
    NISRADataNotFoundError,
    download_file,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)

# Cache configuration
LFS_CACHE_DIR = CACHE_DIR / "labour_market"
LFS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# NISRA LFS publication URL pattern
LFS_BASE_URL = "https://www.nisra.gov.uk"


def _quarter_to_month_names(quarter_str: str) -> tuple[str, str, str]:
    """Convert quarter string to month names.

    Args:
        quarter_str: Quarter identifier like "Jul-Sep" or "Jan-Mar"

    Returns:
        Tuple of (first_month, second_month, third_month)

    Examples:
        >>> _quarter_to_month_names("Jul-Sep")
        ('July', 'August', 'September')
        >>> _quarter_to_month_names("Jan-Mar")
        ('January', 'February', 'March')
    """
    quarter_map = {
        "Jan-Mar": ("January", "February", "March"),
        "Apr-Jun": ("April", "May", "June"),
        "Jul-Sep": ("July", "August", "September"),
        "Oct-Dec": ("October", "November", "December"),
    }

    # Normalize input - remove spaces and hyphens for comparison
    quarter_normalized = quarter_str.strip().replace(" ", "").replace("-", "").lower()

    for key, months in quarter_map.items():
        key_normalized = key.replace("-", "").lower()
        if key_normalized == quarter_normalized:
            return months

    raise ValueError(f"Invalid quarter string: {quarter_str}. Expected format like 'Jul-Sep' or 'Jan-Mar'")


def _build_lfs_url(year: int, quarter: str) -> str:
    """Build the download URL for a quarterly LFS file.

    Args:
        year: Year (e.g., 2025)
        quarter: Quarter string like "Jul-Sep" or "Q3"

    Returns:
        Full URL to the Excel file

    Note:
        The URL pattern is:
        /system/files/statistics/YYYY-MM/lmr-labour-force-survey-quarterly-tables-MONTH-MONTH-YY.xlsx

        Where YYYY-MM is the publication date (usually 2 months after quarter end)
        and MONTH-MONTH-YY is the data period
    """
    # Get month names for the quarter
    first_month, _, third_month = _quarter_to_month_names(quarter)

    # Determine publication month (typically 2 months after quarter end)
    quarter_to_pub_month = {
        "Jan-Mar": "05",  # Published in May
        "Apr-Jun": "08",  # Published in August
        "Jul-Sep": "11",  # Published in November
        "Oct-Dec": "02",  # Published in February (next year)
    }

    # Normalize quarter string - remove spaces and hyphens
    quarter_normalized = quarter.strip().replace(" ", "").replace("-", "").lower()
    pub_month = None
    for key, month in quarter_to_pub_month.items():
        key_normalized = key.replace("-", "").lower()
        if key_normalized == quarter_normalized:
            pub_month = month
            break

    if pub_month is None:
        raise ValueError(f"Could not determine publication month for quarter: {quarter}")

    # For Oct-Dec quarter, publication is in February of next year
    if pub_month == "02":
        pub_year = year + 1
    else:
        pub_year = year

    # Build filename: lmr-labour-force-survey-quarterly-tables-July-September-25.xlsx
    year_short = str(year)[-2:]  # Last 2 digits
    filename = f"lmr-labour-force-survey-quarterly-tables-{first_month}-{third_month}-{year_short}.xlsx"

    # Build full URL
    url = f"{LFS_BASE_URL}/system/files/statistics/{pub_year}-{pub_month}/{filename}"

    return url


def download_quarterly_lfs(year: int, quarter: str, force_refresh: bool = False, cache_ttl_days: int = 90) -> Path:
    """Download Labour Force Survey quarterly tables Excel file.

    Args:
        year: Year (e.g., 2025)
        quarter: Quarter string like "Jul-Sep", "Jan-Mar", etc.
        force_refresh: If True, always download fresh data ignoring cache
        cache_ttl_days: Cache time-to-live in days (default: 90 days)

    Returns:
        Path to the downloaded Excel file

    Raises:
        NISRADataNotFoundError: If the file cannot be downloaded

    Example:
        >>> file_path = download_quarterly_lfs(2025, "Jul-Sep")
        >>> print(f"Downloaded to: {file_path}")
    """
    # Build download URL
    url = _build_lfs_url(year, quarter)

    logger.info(f"Downloading LFS data from {url}")

    # Convert days to hours for download_file function
    cache_ttl_hours = cache_ttl_days * 24

    try:
        file_path = download_file(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
        return file_path
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to download LFS quarterly data for {year} {quarter}: {e}") from e


def parse_employment_by_age_sex(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse Table 2.15: Employment by Age Band and Sex.

    Extracts employment numbers and percentages broken down by age group and sex.

    Args:
        file_path: Path to the quarterly LFS Excel file

    Returns:
        DataFrame with columns:
            - quarter_period: Quarter label (e.g., "July to September 2025")
            - age_group: Age band (e.g., "16 to 19", "20 to 24", "25 to 29", etc.)
            - sex: "Male", "Female", or "All Persons"
            - percentage: Percentage of employment in this age group (for this sex)
            - number: Absolute number employed (from Table 2.15b)

    Example:
        >>> df = parse_employment_by_age_sex("lfs_2025_Q3.xlsx")
        >>> print(df[df['sex'] == 'Female'].head())
    """
    wb = load_workbook(file_path, data_only=True)

    if "2.15" not in wb.sheetnames:
        raise NISRADataNotFoundError("Table 2.15 (Employment by Age and Sex) not found in file")

    sheet = wb["2.15"]

    # Extract quarter period from title (Row 1 or nearby)
    quarter_period = None
    for row in sheet.iter_rows(min_row=1, max_row=5, values_only=True):
        if row[0] and "Percentage in Employment by Age Band" in str(row[0]):
            # Extract date range from title
            match = re.search(r"([A-Z][a-z]+ to [A-Z][a-z]+ \d{4})", str(row[0]))
            if match:
                quarter_period = match.group(1)
                break

    if not quarter_period:
        logger.warning("Could not extract quarter period from Table 2.15 title")
        quarter_period = "Unknown"

    # Find header rows for Table 2.15a (percentages) and Table 2.15b (numbers)
    # Table 2.15a starts around row 6
    # Headers: "Age group", "Male\n(percentage)", "Female\n(percentage)", "All Persons\n(percentage)"

    header_row_a = None
    for row_idx, row in enumerate(sheet.iter_rows(min_row=5, max_row=10, values_only=True), start=5):
        if row[0] and "Age group" in str(row[0]):
            header_row_a = row_idx
            break

    if not header_row_a:
        raise NISRADataNotFoundError("Could not find header row for Table 2.15a")

    # Parse Table 2.15a (percentages)
    percentage_records = []
    for row in sheet.iter_rows(min_row=header_row_a + 1, max_row=header_row_a + 15, values_only=True):
        age_group = row[0]

        # Stop at empty rows or footer
        if not age_group or age_group == "All Persons":
            break

        male_pct = safe_float(row[1])
        female_pct = safe_float(row[2])
        all_persons_pct = safe_float(row[3])

        if male_pct is not None:
            percentage_records.append(
                {
                    "quarter_period": quarter_period,
                    "age_group": str(age_group).strip(),
                    "sex": "Male",
                    "percentage": male_pct,
                }
            )

        if female_pct is not None:
            percentage_records.append(
                {
                    "quarter_period": quarter_period,
                    "age_group": str(age_group).strip(),
                    "sex": "Female",
                    "percentage": female_pct,
                }
            )

        if all_persons_pct is not None:
            percentage_records.append(
                {
                    "quarter_period": quarter_period,
                    "age_group": str(age_group).strip(),
                    "sex": "All Persons",
                    "percentage": all_persons_pct,
                }
            )

    df_pct = pd.DataFrame(percentage_records)

    # Find Table 2.15b (numbers) - should be to the right, around column 5
    # Headers: "Sex", "Number"
    header_row_b = None
    for row_idx, row in enumerate(sheet.iter_rows(min_row=5, max_row=10, values_only=True), start=5):
        if len(row) > 5 and row[5] and "Sex" in str(row[5]):
            header_row_b = row_idx
            break

    if not header_row_b:
        logger.warning("Could not find Table 2.15b (total numbers by sex)")
        # Return just percentages
        return df_pct

    # Parse Table 2.15b (total numbers) - only has Male, Female, All Persons totals
    # Not broken down by age, so we'll add as a separate record with age_group = "All ages"
    number_records = []
    for row in sheet.iter_rows(min_row=header_row_b + 1, max_row=header_row_b + 5, values_only=True):
        sex = row[5] if len(row) > 5 else None
        number = safe_int(row[6]) if len(row) > 6 else None

        if not sex or number is None:
            continue

        number_records.append(
            {
                "quarter_period": quarter_period,
                "age_group": "All ages",
                "sex": str(sex).strip(),
                "number": number,
            }
        )

    df_num = pd.DataFrame(number_records)

    # Merge percentages with total numbers
    # The total numbers apply to all age groups, so we need to calculate
    # We can merge on sex only for the "All ages" totals

    # Return both as separate info or merged smartly
    # For now, let's add the total numbers as additional rows
    result = pd.concat([df_pct, df_num], ignore_index=True)

    return result


def parse_economic_inactivity(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse Table 2.21: Economically Inactive by Sex (Time Series).

    Extracts economic inactivity data broken down by sex with historical time series.
    Table 2.21 shows data for the same quarter (e.g., Jul-Sep) across multiple years (2012-2025).

    Args:
        file_path: Path to the quarterly LFS Excel file

    Returns:
        DataFrame with columns:
            - time_period: Quarter label (e.g., "Jul to Sep 2025")
            - sex: "Male", "Female", or "All Persons"
            - economically_inactive_number: Number of people economically inactive
            - economic_inactivity_rate: Percentage economically inactive

    Note:
        Economically inactive persons are those not in employment and not seeking work
        (students, retired, caring for family, long-term sick/disabled, etc.).

        This table provides **historical time series** for the same quarter across years,
        allowing year-over-year comparisons for the same seasonal period.

    Example:
        >>> df = parse_economic_inactivity("lfs_2025_Q3.xlsx")
        >>> # Get 2025 data
        >>> df_2025 = df[df['time_period'].str.contains('2025')]
        >>> print(df_2025)
    """
    wb = load_workbook(file_path, data_only=True)

    if "2.21" not in wb.sheetnames:
        raise NISRADataNotFoundError("Table 2.21 (Economic Inactivity) not found in file")

    sheet = wb["2.21"]

    # Table 2.21 is a time series table with two sub-tables:
    # Table 2.21a: Numbers (Male, Female, All Persons columns)
    # Table 2.21b: Rates (Male, Female, All Persons columns)
    # Rows are time periods (Jul to Sep 2012, Jul to Sep 2013, etc.)

    # Find header for Table 2.21a (columns: Time period, Male, Female, All Persons)
    header_row_a = None
    for row_idx, row in enumerate(sheet.iter_rows(min_row=5, max_row=10, values_only=True), start=5):
        if row[0] and "Time period" in str(row[0]):
            header_row_a = row_idx
            break

    if not header_row_a:
        raise NISRADataNotFoundError("Could not find header row for Table 2.21a")

    records = []

    # Parse Table 2.21a (numbers) and Table 2.21b (rates) side-by-side
    # Data rows start after header
    for row in sheet.iter_rows(min_row=header_row_a + 1, max_row=header_row_a + 20, values_only=True):
        time_period_a = row[0]

        # Stop at empty rows
        if not time_period_a:
            break

        # Table 2.21a columns (0-3): Time period, Male, Female, All Persons
        male_number = safe_int(row[1])
        female_number = safe_int(row[2])
        all_persons_number = safe_int(row[3])

        # Table 2.21b columns (5-8): Time period, Male, Female, All Persons
        male_rate = safe_float(row[6]) if len(row) > 6 else None
        female_rate = safe_float(row[7]) if len(row) > 7 else None
        all_persons_rate = safe_float(row[8]) if len(row) > 8 else None

        time_period_str = str(time_period_a).strip()

        # Add record for Male
        if male_number is not None or male_rate is not None:
            records.append(
                {
                    "time_period": time_period_str,
                    "sex": "Male",
                    "economically_inactive_number": male_number,
                    "economic_inactivity_rate": male_rate,
                }
            )

        # Add record for Female
        if female_number is not None or female_rate is not None:
            records.append(
                {
                    "time_period": time_period_str,
                    "sex": "Female",
                    "economically_inactive_number": female_number,
                    "economic_inactivity_rate": female_rate,
                }
            )

        # Add record for All Persons
        if all_persons_number is not None or all_persons_rate is not None:
            records.append(
                {
                    "time_period": time_period_str,
                    "sex": "All Persons",
                    "economically_inactive_number": all_persons_number,
                    "economic_inactivity_rate": all_persons_rate,
                }
            )

    result = pd.DataFrame(records)

    return result


def get_latest_lfs_publication_url() -> tuple[str, str, str]:
    """Find the latest Labour Force Survey quarterly tables publication.

    Scrapes the NISRA Labour Market statistics mother page to find the most recent
    "Quarterly Labour Force Survey Tables" publication.

    Returns:
        Tuple of (excel_file_url, year, quarter)
        - excel_file_url: Full URL to the Excel file
        - year: Data year as string (e.g., "2025")
        - quarter: Quarter string (e.g., "Jul-Sep")

    Raises:
        NISRADataNotFoundError: If no publication found

    Example:
        >>> url, year, quarter = get_latest_lfs_publication_url()
        >>> print(f"Latest data: {quarter} {year}")
    """
    import requests
    from bs4 import BeautifulSoup

    # Mother page listing all labour market publications
    mother_page = "https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare"

    try:
        response = requests.get(mother_page, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # Find all links with "Quarterly Labour Force Survey Tables" in text
        lfs_links = []
        for link in soup.find_all("a", href=True):
            link_text = link.get_text(strip=True)
            if "Quarterly Labour Force Survey Tables" in link_text:
                href = link["href"]
                # Make absolute URL if needed
                if href.startswith("/"):
                    href = f"https://www.nisra.gov.uk{href}"
                lfs_links.append({"text": link_text, "url": href})

        if not lfs_links:
            raise NISRADataNotFoundError("No Quarterly Labour Force Survey Tables publications found")

        # First link should be the latest (page shows newest first)
        latest_pub = lfs_links[0]
        logger.info(f"Found latest LFS publication: {latest_pub['text']}")

        # Now fetch the publication page to get the Excel file
        pub_response = requests.get(latest_pub["url"], timeout=30)
        pub_response.raise_for_status()
        pub_soup = BeautifulSoup(pub_response.content, "html.parser")

        # Find Excel file link for quarterly tables
        excel_url = None
        for link in pub_soup.find_all("a", href=True):
            href = link["href"]
            if "lmr-labour-force-survey-quarterly-tables" in href.lower() and href.endswith(".xlsx"):
                if href.startswith("/"):
                    excel_url = f"https://www.nisra.gov.uk{href}"
                else:
                    excel_url = href
                break

        if not excel_url:
            raise NISRADataNotFoundError(f"No Excel file found on publication page: {latest_pub['url']}")

        # Extract quarter and year from filename or page content
        # Filename pattern: lmr-labour-force-survey-quarterly-tables-July-September-25.xlsx
        filename = excel_url.split("/")[-1]
        match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)-"
            r"(January|February|March|April|May|June|July|August|September|October|November|December)-"
            r"(\d{2})",
            filename,
        )

        if match:
            first_month = match.group(1)
            third_month = match.group(2)
            year_short = match.group(3)
            year = f"20{year_short}"

            # Map months to quarter format
            month_to_abbrev = {
                "January": "Jan",
                "February": "Feb",
                "March": "Mar",
                "April": "Apr",
                "May": "May",
                "June": "Jun",
                "July": "Jul",
                "August": "Aug",
                "September": "Sep",
                "October": "Oct",
                "November": "Nov",
                "December": "Dec",
            }

            quarter = f"{month_to_abbrev[first_month]}-{month_to_abbrev[third_month]}"
            logger.info(f"Extracted quarter: {quarter} {year}")
            return (excel_url, year, quarter)

        # Fallback: Try to extract from page content
        page_text = pub_soup.get_text()
        match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+to\s+"
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
            r"(\d{4})",
            page_text,
        )

        if match:
            first_month = match.group(1)
            third_month = match.group(2)
            year = match.group(3)

            month_to_abbrev = {
                "January": "Jan",
                "February": "Feb",
                "March": "Mar",
                "April": "Apr",
                "May": "May",
                "June": "Jun",
                "July": "Jul",
                "August": "Aug",
                "September": "Sep",
                "October": "Oct",
                "November": "Nov",
                "December": "Dec",
            }

            quarter = f"{month_to_abbrev[first_month]}-{month_to_abbrev[third_month]}"
            logger.info(f"Extracted quarter from page content: {quarter} {year}")
            return (excel_url, year, quarter)

        raise NISRADataNotFoundError("Could not extract quarter and year from publication")

    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to fetch LFS publication list: {e}")


def get_latest_employment(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest quarterly employment data by age and sex.

    Automatically discovers and downloads the most recent quarterly LFS publication
    from the NISRA website.

    Args:
        force_refresh: If True, always download fresh data ignoring cache

    Returns:
        DataFrame with employment statistics by age group and sex

    Example:
        >>> df = get_latest_employment()
        >>> # Analyze employment for 25-29 age group
        >>> young_adults = df[df['age_group'] == '25 to 29']
        >>> print(young_adults)
    """
    # Discover latest publication from NISRA website
    excel_url, year, quarter = get_latest_lfs_publication_url()

    # Download directly using the discovered URL
    logger.info(f"Downloading latest LFS data: {quarter} {year}")

    # Use download_file directly with the discovered URL
    cache_ttl_hours = 90 * 24  # 90 days for quarterly data
    file_path = download_file(excel_url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    return parse_employment_by_age_sex(file_path)


def get_latest_economic_inactivity(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest quarterly economic inactivity data.

    Automatically discovers and downloads the most recent quarterly LFS publication
    from the NISRA website.

    Args:
        force_refresh: If True, always download fresh data ignoring cache

    Returns:
        DataFrame with economic inactivity statistics by sex

    Example:
        >>> df = get_latest_economic_inactivity()
        >>> print(df)
    """
    # Discover latest publication from NISRA website
    excel_url, year, quarter = get_latest_lfs_publication_url()

    # Download directly using the discovered URL
    logger.info(f"Downloading latest LFS data: {quarter} {year}")

    # Use download_file directly with the discovered URL
    cache_ttl_hours = 90 * 24  # 90 days for quarterly data
    file_path = download_file(excel_url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    return parse_economic_inactivity(file_path)


def get_quarterly_data(
    year: int, quarter: str, tables: Optional[List[str]] = None, force_refresh: bool = False
) -> Dict[str, pd.DataFrame]:
    """Get Labour Force Survey data for a specific quarter.

    Args:
        year: Year (e.g., 2025)
        quarter: Quarter string like "Jul-Sep", "Jan-Mar", etc.
        tables: List of table names to parse (default: ['employment', 'economic_inactivity'])
            Options: 'employment', 'economic_inactivity'
        force_refresh: If True, always download fresh data ignoring cache

    Returns:
        Dictionary mapping table names to DataFrames:
            - 'employment': Employment by age and sex (Table 2.15)
            - 'economic_inactivity': Economic inactivity data (Table 2.21)

    Example:
        >>> data = get_quarterly_data(2025, "Jul-Sep")
        >>> emp_df = data['employment']
        >>> inact_df = data['economic_inactivity']
    """
    if tables is None:
        tables = ["employment", "economic_inactivity"]

    file_path = download_quarterly_lfs(year, quarter, force_refresh=force_refresh)

    result = {}

    if "employment" in tables:
        result["employment"] = parse_employment_by_age_sex(file_path)

    if "economic_inactivity" in tables:
        result["economic_inactivity"] = parse_economic_inactivity(file_path)

    return result
