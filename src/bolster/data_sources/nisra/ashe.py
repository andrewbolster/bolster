"""NISRA Annual Survey of Hours and Earnings (ASHE) Module.

This module provides access to Northern Ireland's earnings statistics:
- Median weekly, hourly, and annual earnings
- Breakdowns by employment type, sector, geography, occupation, industry
- Gender pay gap analysis
- Historical timeseries from 1997 to present

Data is published annually in October by NISRA's Economic & Labour Market Statistics Branch.

Data Coverage:
    - Weekly Earnings: 1997 - Present (annual, full-time/part-time/all)
    - Hourly Earnings: 1997 - Present (annual, excluding overtime)
    - Annual Earnings: 1999 - Present (annual, full-time/part-time/all)
    - Geographic: 11 Local Government Districts (workplace vs residence basis)
    - Sector: Public vs Private sector comparison (2005 - Present)

Examples:
    >>> from bolster.data_sources.nisra import ashe
    >>> # Get latest weekly earnings timeseries
    >>> df = ashe.get_latest_ashe_timeseries(metric='weekly')
    >>> print(df.tail())

    >>> # Get geographic earnings by workplace
    >>> df_geo = ashe.get_latest_ashe_geography(basis='workplace')
    >>> print(df_geo[['lgd', 'median_weekly_earnings']].sort_values('median_weekly_earnings', ascending=False))

    >>> # Get public vs private sector comparison
    >>> df_sector = ashe.get_latest_ashe_sector()
    >>> print(df_sector[df_sector['year'] == 2025])

Publication Details:
    - Frequency: Annual (October publication)
    - Reference period: April of each year
    - Published by: NISRA Economic & Labour Market Statistics Branch
    - Contact: economicstats@nisra.gov.uk
    - Base: Employee jobs in Northern Ireland (not self-employed)
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Union

import pandas as pd

from ._base import NISRADataNotFoundError, download_file

logger = logging.getLogger(__name__)

# Base URL for NISRA ASHE statistics
ASHE_BASE_URL = "https://www.nisra.gov.uk/statistics/work-pay-and-benefits/annual-survey-hours-and-earnings"


def get_latest_ashe_publication_url() -> tuple[str, int]:
    """Get the URL of the latest ASHE publication and its year.

    Scrapes the NISRA ASHE page to find the most recent publication.

    Returns:
        Tuple of (publication_url, year)

    Raises:
        NISRADataNotFoundError: If unable to find the latest publication

    Example:
        >>> url, year = get_latest_ashe_publication_url()
        >>> print(f"Latest ASHE: {year} at {url}")
    """
    import requests
    from bs4 import BeautifulSoup

    logger.info("Fetching latest ASHE publication URL...")

    try:
        response = requests.get(ASHE_BASE_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to fetch ASHE page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find the link to the latest publication
    # Pattern: "Employee earnings in NI 2025" or "Employee earnings in Northern Ireland 2025"
    publication_links = soup.find_all("a", href=True)

    for link in publication_links:
        link_text = link.get_text(strip=True)
        # Match "Employee earnings in Northern Ireland YYYY" or "Employee earnings in NI YYYY"
        match = re.search(r"Employee earnings in (?:Northern Ireland|NI)\s+(\d{4})", link_text)
        if match:
            year = int(match.group(1))
            pub_url = link["href"]
            if not pub_url.startswith("http"):
                pub_url = f"https://www.nisra.gov.uk{pub_url}"

            logger.info(f"Found latest ASHE publication: {year} at {pub_url}")
            return pub_url, year

    raise NISRADataNotFoundError("Could not find latest ASHE publication")


def get_ashe_file_url(year: int, file_type: str = "timeseries") -> str:
    """Construct URL for ASHE file based on year and file type.

    Args:
        year: Publication year (e.g., 2025)
        file_type: Type of file - 'timeseries' or 'linked'

    Returns:
        URL to the Excel file

    Example:
        >>> url = get_ashe_file_url(2025, 'timeseries')
        >>> print(url)
    """
    # ASHE is published in October
    month = 10

    if file_type == "timeseries":
        # Pattern: ASHE-1997-{year}-headline-timeseries.xlsx
        filename = f"ASHE-1997-{year}-headline-timeseries.xlsx"
    elif file_type == "linked":
        # Pattern: ASHE-{year}-linked.xlsx
        filename = f"ASHE-{year}-linked.xlsx"
    else:
        raise ValueError(f"Unknown file_type: {file_type}. Use 'timeseries' or 'linked'")

    url = f"https://www.nisra.gov.uk/system/files/statistics/{year}-{month:02d}/{filename}"
    logger.info(f"Constructed ASHE file URL: {url}")
    return url


def parse_ashe_timeseries_weekly(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse ASHE weekly earnings timeseries.

    Extracts the weekly earnings data from the timeseries Excel file.

    Args:
        file_path: Path to the ASHE timeseries Excel file

    Returns:
        DataFrame with columns:
            - year: int
            - work_pattern: str ('Full-time', 'Part-time', 'All')
            - median_weekly_earnings: float (£)

    Example:
        >>> df = parse_ashe_timeseries_weekly("ASHE-1997-2025-headline-timeseries.xlsx")
        >>> print(df[df['year'] == 2025])
    """
    logger.info(f"Parsing ASHE weekly earnings from: {file_path}")

    # Read Weekly sheet, skip first 4 rows to get to header
    df = pd.read_excel(file_path, sheet_name="Weekly", skiprows=4)

    # Convert to long format
    records = []
    for _, row in df.iterrows():
        year = int(row["Year"])
        for work_pattern in ["Full-time", "Part-time", "All"]:
            records.append(
                {"year": year, "work_pattern": work_pattern, "median_weekly_earnings": float(row[work_pattern])}
            )

    result = pd.DataFrame(records)
    logger.info(f"Parsed {len(result)} weekly earnings records ({result['year'].min()}-{result['year'].max()})")
    return result


def parse_ashe_timeseries_hourly(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse ASHE hourly earnings timeseries.

    Extracts the hourly earnings data (excluding overtime) from the timeseries Excel file.

    Args:
        file_path: Path to the ASHE timeseries Excel file

    Returns:
        DataFrame with columns:
            - year: int
            - work_pattern: str ('Full-time', 'Part-time', 'All')
            - median_hourly_earnings: float (£)

    Example:
        >>> df = parse_ashe_timeseries_hourly("ASHE-1997-2025-headline-timeseries.xlsx")
        >>> print(df[df['year'] == 2025])
    """
    logger.info(f"Parsing ASHE hourly earnings from: {file_path}")

    # Read Hourly sheet, skip first 4 rows to get to header
    df = pd.read_excel(file_path, sheet_name="Hourly", skiprows=4)

    # Convert to long format
    records = []
    for _, row in df.iterrows():
        year = int(row["Year"])
        for work_pattern in ["Full-time", "Part-time", "All"]:
            records.append(
                {"year": year, "work_pattern": work_pattern, "median_hourly_earnings": float(row[work_pattern])}
            )

    result = pd.DataFrame(records)
    logger.info(f"Parsed {len(result)} hourly earnings records ({result['year'].min()}-{result['year'].max()})")
    return result


def parse_ashe_timeseries_annual(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse ASHE annual earnings timeseries.

    Extracts the annual earnings data from the timeseries Excel file.

    Args:
        file_path: Path to the ASHE timeseries Excel file

    Returns:
        DataFrame with columns:
            - year: int
            - work_pattern: str ('Full-time', 'Part-time', 'All')
            - median_annual_earnings: float (£)

    Example:
        >>> df = parse_ashe_timeseries_annual("ASHE-1997-2025-headline-timeseries.xlsx")
        >>> print(df[df['year'] == 2025])
    """
    logger.info(f"Parsing ASHE annual earnings from: {file_path}")

    # Read Annual sheet, skip first 4 rows to get to header
    df = pd.read_excel(file_path, sheet_name="Annual", skiprows=4)

    # Convert to long format
    records = []
    for _, row in df.iterrows():
        year = int(row["Year"])
        for work_pattern in ["Full-time", "Part-time", "All"]:
            records.append(
                {"year": year, "work_pattern": work_pattern, "median_annual_earnings": float(row[work_pattern])}
            )

    result = pd.DataFrame(records)
    logger.info(f"Parsed {len(result)} annual earnings records ({result['year'].min()}-{result['year'].max()})")
    return result


def parse_ashe_geography(file_path: Union[str, Path], basis: str = "workplace", year: int = None) -> pd.DataFrame:
    """Parse ASHE geographic earnings data.

    Extracts earnings by Local Government District from the linked tables file.

    Args:
        file_path: Path to the ASHE linked tables Excel file
        basis: 'workplace' (MapA) or 'residence' (MapB)
        year: Year of the data (if not provided, will be extracted from file)

    Returns:
        DataFrame with columns:
            - year: int
            - lgd: str (Local Government District name)
            - basis: str ('workplace' or 'residence')
            - median_weekly_earnings: float (£)

    Example:
        >>> df = parse_ashe_geography("ASHE-2025-linked.xlsx", basis='workplace', year=2025)
        >>> print(df.sort_values('median_weekly_earnings', ascending=False))
    """
    logger.info(f"Parsing ASHE geography ({basis}) from: {file_path}")

    # Select the correct sheet
    sheet_name = "MapA" if basis == "workplace" else "MapB"

    # Read the sheet, skip first 2 rows to get to data
    df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=2)

    # The first column has LGD names, second column has earnings
    df.columns = ["lgd", "median_weekly_earnings"]

    # Remove any NaN rows
    df = df.dropna()

    # Extract year from data if not provided
    if year is None:
        # Try to extract from filename
        match = re.search(r"ASHE-(\d{4})-linked", str(file_path))
        if match:
            year = int(match.group(1))
        else:
            year = datetime.now().year

    # Add metadata columns
    df["year"] = year
    df["basis"] = basis

    # Reorder columns
    df = df[["year", "lgd", "basis", "median_weekly_earnings"]]

    # Convert earnings to float
    df["median_weekly_earnings"] = df["median_weekly_earnings"].astype(float)

    logger.info(f"Parsed {len(df)} LGD earnings records for {year} ({basis} basis)")
    return df


def parse_ashe_sector(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse ASHE public vs private sector earnings.

    Extracts public and private sector earnings timeseries from the linked tables file.

    Args:
        file_path: Path to the ASHE linked tables Excel file

    Returns:
        DataFrame with columns:
            - year: int
            - location: str ('Northern Ireland' or 'United Kingdom')
            - sector: str ('Public' or 'Private')
            - median_weekly_earnings: float (£)

    Example:
        >>> df = parse_ashe_sector("ASHE-2025-linked.xlsx")
        >>> print(df[df['year'] == 2025])
    """
    logger.info(f"Parsing ASHE sector data from: {file_path}")

    # Read Figure5 sheet, skip first 3 rows to get to header
    df = pd.read_excel(file_path, sheet_name="Figure5", skiprows=3)

    # Columns should be: Year, NI Public, NI Private, UK Public, UK Private
    df.columns = ["Year", "NI Public", "NI Private", "UK Public", "UK Private"]

    # Convert to long format
    records = []
    for _, row in df.iterrows():
        year = int(row["Year"])
        records.append(
            {
                "year": year,
                "location": "Northern Ireland",
                "sector": "Public",
                "median_weekly_earnings": float(row["NI Public"]),
            }
        )
        records.append(
            {
                "year": year,
                "location": "Northern Ireland",
                "sector": "Private",
                "median_weekly_earnings": float(row["NI Private"]),
            }
        )
        records.append(
            {
                "year": year,
                "location": "United Kingdom",
                "sector": "Public",
                "median_weekly_earnings": float(row["UK Public"]),
            }
        )
        records.append(
            {
                "year": year,
                "location": "United Kingdom",
                "sector": "Private",
                "median_weekly_earnings": float(row["UK Private"]),
            }
        )

    result = pd.DataFrame(records)
    logger.info(f"Parsed {len(result)} sector earnings records ({result['year'].min()}-{result['year'].max()})")
    return result


def get_latest_ashe_timeseries(metric: str = "weekly", force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest ASHE timeseries data.

    Downloads and parses the most recent ASHE timeseries publication.
    Results are cached for 90 days unless force_refresh=True.

    Args:
        metric: Type of earnings - 'weekly', 'hourly', or 'annual'
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with timeseries earnings data (1997-present for weekly/hourly, 1999-present for annual)

    Example:
        >>> df = get_latest_ashe_timeseries(metric='weekly')
        >>> latest = df[df['year'] == df['year'].max()]
        >>> print(f"Latest NI median weekly earnings (all): £{latest[latest['work_pattern']=='All']['median_weekly_earnings'].values[0]:.2f}")
    """
    _, year = get_latest_ashe_publication_url()
    file_url = get_ashe_file_url(year, file_type="timeseries")

    # Cache for 90 days (published annually)
    file_path = download_file(file_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    if metric == "weekly":
        return parse_ashe_timeseries_weekly(file_path)
    elif metric == "hourly":
        return parse_ashe_timeseries_hourly(file_path)
    elif metric == "annual":
        return parse_ashe_timeseries_annual(file_path)
    else:
        raise ValueError(f"Unknown metric: {metric}. Use 'weekly', 'hourly', or 'annual'")


def get_latest_ashe_geography(basis: str = "workplace", force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest ASHE geographic earnings data.

    Downloads and parses the most recent ASHE linked tables publication.
    Results are cached for 90 days unless force_refresh=True.

    Args:
        basis: 'workplace' (where employees work) or 'residence' (where employees live)
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with earnings by Local Government District

    Example:
        >>> df = get_latest_ashe_geography(basis='workplace')
        >>> print(df.sort_values('median_weekly_earnings', ascending=False).head())
    """
    _, year = get_latest_ashe_publication_url()
    file_url = get_ashe_file_url(year, file_type="linked")

    # Cache for 90 days (published annually)
    file_path = download_file(file_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    return parse_ashe_geography(file_path, basis=basis, year=year)


def get_latest_ashe_sector(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest ASHE public vs private sector earnings data.

    Downloads and parses the most recent ASHE linked tables publication.
    Results are cached for 90 days unless force_refresh=True.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with public and private sector earnings timeseries (2005-present)

    Example:
        >>> df = get_latest_ashe_sector()
        >>> latest = df[df['year'] == df['year'].max()]
        >>> ni_latest = latest[latest['location'] == 'Northern Ireland']
        >>> print(ni_latest[['sector', 'median_weekly_earnings']])
    """
    _, year = get_latest_ashe_publication_url()
    file_url = get_ashe_file_url(year, file_type="linked")

    # Cache for 90 days (published annually)
    file_path = download_file(file_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    return parse_ashe_sector(file_path)


# ============================================================================
# Helper Functions for Analysis
# ============================================================================


def get_earnings_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter earnings data for a specific year.

    Args:
        df: ASHE DataFrame
        year: Year to filter for

    Returns:
        DataFrame with only the specified year's data

    Example:
        >>> df = get_latest_ashe_timeseries('weekly')
        >>> df_2025 = get_earnings_by_year(df, 2025)
        >>> print(df_2025)
    """
    return df[df["year"] == year].reset_index(drop=True)


def calculate_growth_rates(df: pd.DataFrame, periods: int = 1) -> pd.DataFrame:
    """Calculate year-on-year growth rates for earnings.

    Args:
        df: ASHE DataFrame with 'year' and earnings column
        periods: Number of years for comparison (default: 1 for YoY)

    Returns:
        DataFrame with additional growth rate column

    Example:
        >>> df = get_latest_ashe_timeseries('weekly')
        >>> df_growth = calculate_growth_rates(df)
        >>> recent = df_growth[df_growth['work_pattern'] == 'All'].tail(5)
        >>> print(recent[['year', 'median_weekly_earnings', 'earnings_yoy_growth']])
    """
    result = df.copy()

    # Identify the earnings column
    earnings_col = None
    for col in ["median_weekly_earnings", "median_hourly_earnings", "median_annual_earnings"]:
        if col in result.columns:
            earnings_col = col
            break

    if earnings_col is None:
        raise ValueError("No earnings column found in DataFrame")

    # Calculate growth rate for each work pattern/sector/geography
    # Group by non-year, non-earnings columns
    group_cols = [col for col in result.columns if col not in ["year", earnings_col]]

    if group_cols:
        result["earnings_yoy_growth"] = result.groupby(group_cols)[earnings_col].pct_change(periods=periods) * 100
    else:
        result["earnings_yoy_growth"] = result[earnings_col].pct_change(periods=periods) * 100

    return result


def get_gender_pay_gap(df_weekly: pd.DataFrame) -> pd.DataFrame:
    """Calculate gender pay gap from weekly earnings data.

    Note: This requires weekly earnings data broken down by gender, which may not
    be available in the timeseries file. Use the linked tables file instead.

    Args:
        df_weekly: Weekly earnings DataFrame with 'sex' or 'gender' column

    Returns:
        DataFrame with gender pay gap by year

    Example:
        >>> # This requires data from the linked tables file with gender breakdown
        >>> # Not available in the simple timeseries
        >>> pass
    """
    # Placeholder - would need gender-specific data from linked tables
    raise NotImplementedError("Gender pay gap calculation requires gender-specific data from linked tables file")
