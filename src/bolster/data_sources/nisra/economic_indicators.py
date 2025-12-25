"""NISRA Economic Indicators Module.

This module provides access to Northern Ireland's quarterly economic output indicators:
- Index of Services (IOS): Measures output in the services sector
- Index of Production (IOP): Measures output in production industries

Both indices are published quarterly by NISRA's Economic & Labour Market Statistics Branch.

Data Coverage:
    - Index of Services: Q1 2005 - Present (quarterly)
    - Index of Production: Q1 2005 - Present (quarterly)
    - Both include NI and UK comparator data

Examples:
    >>> from bolster.data_sources.nisra import economic_indicators
    >>> # Get latest Index of Services data
    >>> ios_df = economic_indicators.get_latest_index_of_services()
    >>> print(ios_df.head())

    >>> # Get latest Index of Production data
    >>> iop_df = economic_indicators.get_latest_index_of_production()
    >>> print(iop_df.head())

    >>> # Filter for specific year
    >>> ios_2024 = economic_indicators.get_ios_by_year(ios_df, 2024)
    >>> print(f"NI Services Q4 2024: {ios_2024[ios_2024['quarter']=='Q4']['ni_index'].values[0]}")

    >>> # Compare NI vs UK performance
    >>> latest_q = ios_df.iloc[-1]
    >>> print(f"Latest quarter: {latest_q['quarter']} {latest_q['year']}")
    >>> print(f"NI: {latest_q['ni_index']}, UK: {latest_q['uk_index']}")

Publication Details:
    - Frequency: Quarterly
    - Published by: NISRA Economic & Labour Market Statistics Branch
    - Contact: economicstats@nisra.gov.uk
    - Next release: Approximately 3 months after quarter end
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import pandas as pd

from ._base import NISRADataNotFoundError, download_file

logger = logging.getLogger(__name__)

# Base URLs for NISRA economic output publications
IOS_BASE_URL = "https://www.nisra.gov.uk/statistics/economic-output/index-services"
IOP_BASE_URL = "https://www.nisra.gov.uk/statistics/economic-output/index-production"


def get_latest_ios_publication_url() -> Tuple[str, datetime]:
    """Get the URL of the latest Index of Services publication.

    Scrapes the NISRA Index of Services page to find the most recent publication.

    Returns:
        Tuple of (excel_url, publication_date)

    Raises:
        NISRADataNotFoundError: If unable to find the latest publication

    Example:
        >>> url, pub_date = get_latest_ios_publication_url()
        >>> print(f"Latest IOS published: {pub_date.strftime('%Y-%m-%d')}")
        >>> print(f"Data URL: {url}")
    """
    import requests
    from bs4 import BeautifulSoup

    logger.info("Fetching latest Index of Services publication URL...")

    try:
        response = requests.get(IOS_BASE_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to fetch IOS page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find the link to the latest publication
    # Pattern: "Index of Services (IOS) Statistical Bulletin and Tables - Quarter X YYYY"
    publication_links = soup.find_all("a", href=True)

    for link in publication_links:
        link_text = link.get_text(strip=True)
        if "Statistical Bulletin and Tables" in link_text and "Quarter" in link_text:
            pub_url = link["href"]
            if not pub_url.startswith("http"):
                pub_url = f"https://www.nisra.gov.uk{pub_url}"

            # Get the Excel file URL from the publication page
            try:
                pub_response = requests.get(pub_url, timeout=30)
                pub_response.raise_for_status()
            except requests.RequestException as e:
                raise NISRADataNotFoundError(f"Failed to fetch publication page: {e}")

            pub_soup = BeautifulSoup(pub_response.content, "html.parser")

            # Find Excel file link
            for file_link in pub_soup.find_all("a", href=True):
                href = file_link["href"]
                if ".xlsx" in href.lower() and "tables" in href.lower():
                    excel_url = href
                    if not excel_url.startswith("http"):
                        excel_url = f"https://www.nisra.gov.uk{excel_url}"

                    # Extract publication date from page
                    pub_date = datetime.now()  # Default to now
                    date_meta = pub_soup.find("meta", property="article:published_time")
                    if date_meta and date_meta.get("content"):
                        pub_date = datetime.fromisoformat(date_meta["content"].split("T")[0])

                    logger.info(f"Found latest IOS publication: {excel_url} (published {pub_date.date()})")
                    return excel_url, pub_date

    raise NISRADataNotFoundError("Could not find latest Index of Services publication")


def get_latest_iop_publication_url() -> Tuple[str, datetime]:
    """Get the URL of the latest Index of Production publication.

    Scrapes the NISRA Index of Production page to find the most recent publication.

    Returns:
        Tuple of (excel_url, publication_date)

    Raises:
        NISRADataNotFoundError: If unable to find the latest publication

    Example:
        >>> url, pub_date = get_latest_iop_publication_url()
        >>> print(f"Latest IOP published: {pub_date.strftime('%Y-%m-%d')}")
    """
    import requests
    from bs4 import BeautifulSoup

    logger.info("Fetching latest Index of Production publication URL...")

    try:
        response = requests.get(IOP_BASE_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to fetch IOP page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find the link to the latest publication
    publication_links = soup.find_all("a", href=True)

    for link in publication_links:
        link_text = link.get_text(strip=True)
        if "Statistical Bulletin and Tables" in link_text and "Quarter" in link_text:
            pub_url = link["href"]
            if not pub_url.startswith("http"):
                pub_url = f"https://www.nisra.gov.uk{pub_url}"

            # Get the Excel file URL from the publication page
            try:
                pub_response = requests.get(pub_url, timeout=30)
                pub_response.raise_for_status()
            except requests.RequestException as e:
                raise NISRADataNotFoundError(f"Failed to fetch publication page: {e}")

            pub_soup = BeautifulSoup(pub_response.content, "html.parser")

            # Find Excel file link
            for file_link in pub_soup.find_all("a", href=True):
                href = file_link["href"]
                if ".xlsx" in href.lower() and "tables" in href.lower():
                    excel_url = href
                    if not excel_url.startswith("http"):
                        excel_url = f"https://www.nisra.gov.uk{excel_url}"

                    # Extract publication date
                    pub_date = datetime.now()
                    date_meta = pub_soup.find("meta", property="article:published_time")
                    if date_meta and date_meta.get("content"):
                        pub_date = datetime.fromisoformat(date_meta["content"].split("T")[0])

                    logger.info(f"Found latest IOP publication: {excel_url} (published {pub_date.date()})")
                    return excel_url, pub_date

    raise NISRADataNotFoundError("Could not find latest Index of Production publication")


def parse_ios_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse NISRA Index of Services Excel file.

    Extracts the main IOS time series (Table 1.1) from the Excel file.

    Args:
        file_path: Path to the IOS Excel file

    Returns:
        DataFrame with columns:
            - date: datetime (first day of quarter)
            - quarter: str (e.g., 'Q1', 'Q2', 'Q3', 'Q4')
            - year: int
            - ni_index: float (Northern Ireland index value)
            - uk_index: float (UK index value)

    Example:
        >>> df = parse_ios_file("ios-q3-2025-tables.xlsx")
        >>> print(df[df['year'] == 2025].tail())
    """
    logger.info(f"Parsing Index of Services file: {file_path}")

    # Read Table 1.1: Overall Index of Services
    df = pd.read_excel(file_path, sheet_name="Table_1_1", skiprows=2)

    # Rename columns
    df.columns = ["quarter_label", "ni_index", "uk_index"]

    # Extract year and quarter from label (e.g., "Q1 2005")
    df[["quarter", "year"]] = df["quarter_label"].str.extract(r"(Q[1-4])\s+(\d{4})")
    df["year"] = df["year"].astype(int)

    # Create date column (first day of quarter)
    quarter_to_month = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}
    df["month"] = df["quarter"].map(quarter_to_month)
    df["date"] = pd.to_datetime({"year": df["year"], "month": df["month"], "day": 1})

    # Select and order columns
    result = df[["date", "quarter", "year", "ni_index", "uk_index"]].copy()

    # Remove any rows with missing data
    result = result.dropna().reset_index(drop=True)

    logger.info(f"Parsed {len(result)} quarters of IOS data ({result['year'].min()}-{result['year'].max()})")

    return result


def parse_iop_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse NISRA Index of Production Excel file.

    Extracts the main IOP time series (Table 1) from the Excel file.

    Args:
        file_path: Path to the IOP Excel file

    Returns:
        DataFrame with columns:
            - date: datetime (first day of quarter)
            - quarter: str (e.g., 'Q1', 'Q2', 'Q3', 'Q4')
            - year: int
            - ni_index: float (Northern Ireland index value)
            - uk_index: float (UK index value)

    Example:
        >>> df = parse_iop_file("iop-q3-2025-tables.xlsx")
        >>> print(df[df['year'] == 2025].tail())
    """
    logger.info(f"Parsing Index of Production file: {file_path}")

    # Read Table 1: Overall Index of Production
    df = pd.read_excel(file_path, sheet_name="Table_1", skiprows=2)

    # Rename columns (note: UK column may have trailing space)
    df.columns = ["quarter_label", "ni_index", "uk_index"]

    # Clean up column names
    df.columns = [col.strip() for col in df.columns]

    # Extract year and quarter from label (e.g., "Q1 2005")
    df[["quarter", "year"]] = df["quarter_label"].str.extract(r"(Q[1-4])\s+(\d{4})")
    df["year"] = df["year"].astype(int)

    # Create date column (first day of quarter)
    quarter_to_month = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}
    df["month"] = df["quarter"].map(quarter_to_month)
    df["date"] = pd.to_datetime({"year": df["year"], "month": df["month"], "day": 1})

    # Select and order columns
    result = df[["date", "quarter", "year", "ni_index", "uk_index"]].copy()

    # Remove any rows with missing data
    result = result.dropna().reset_index(drop=True)

    logger.info(f"Parsed {len(result)} quarters of IOP data ({result['year'].min()}-{result['year'].max()})")

    return result


def get_latest_index_of_services(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest Index of Services data.

    Downloads and parses the most recent NISRA Index of Services publication.
    Results are cached for 7 days unless force_refresh=True.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with quarterly Index of Services data for NI and UK

    Example:
        >>> df = get_latest_index_of_services()
        >>> print(f"Latest quarter: {df.iloc[-1]['quarter']} {df.iloc[-1]['year']}")
        >>> print(f"NI Index: {df.iloc[-1]['ni_index']}")
    """
    excel_url, pub_date = get_latest_ios_publication_url()

    # Cache for 7 days (168 hours)
    file_path = download_file(excel_url, cache_ttl_hours=168, force_refresh=force_refresh)

    return parse_ios_file(file_path)


def get_latest_index_of_production(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest Index of Production data.

    Downloads and parses the most recent NISRA Index of Production publication.
    Results are cached for 7 days unless force_refresh=True.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with quarterly Index of Production data for NI and UK

    Example:
        >>> df = get_latest_index_of_production()
        >>> print(f"Latest quarter: {df.iloc[-1]['quarter']} {df.iloc[-1]['year']}")
        >>> print(f"NI Index: {df.iloc[-1]['ni_index']}")
    """
    excel_url, pub_date = get_latest_iop_publication_url()

    # Cache for 7 days (168 hours)
    file_path = download_file(excel_url, cache_ttl_hours=168, force_refresh=force_refresh)

    return parse_iop_file(file_path)


# ============================================================================
# Helper Functions for Analysis
# ============================================================================


def get_ios_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter Index of Services data for a specific year.

    Args:
        df: Index of Services DataFrame
        year: Year to filter for

    Returns:
        DataFrame with only the specified year's data

    Example:
        >>> ios_df = get_latest_index_of_services()
        >>> ios_2024 = get_ios_by_year(ios_df, 2024)
        >>> print(ios_2024)
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_iop_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter Index of Production data for a specific year.

    Args:
        df: Index of Production DataFrame
        year: Year to filter for

    Returns:
        DataFrame with only the specified year's data

    Example:
        >>> iop_df = get_latest_index_of_production()
        >>> iop_2024 = get_iop_by_year(iop_df, 2024)
        >>> print(iop_2024)
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_ios_by_quarter(df: pd.DataFrame, quarter: str, year: int) -> pd.DataFrame:
    """Get Index of Services data for a specific quarter.

    Args:
        df: Index of Services DataFrame
        quarter: Quarter code (e.g., 'Q1', 'Q2', 'Q3', 'Q4')
        year: Year

    Returns:
        DataFrame with single row for the specified quarter

    Example:
        >>> ios_df = get_latest_index_of_services()
        >>> q3_2025 = get_ios_by_quarter(ios_df, 'Q3', 2025)
        >>> print(f"Q3 2025 NI: {q3_2025['ni_index'].values[0]}")
    """
    return df[(df["quarter"] == quarter) & (df["year"] == year)].reset_index(drop=True)


def get_iop_by_quarter(df: pd.DataFrame, quarter: str, year: int) -> pd.DataFrame:
    """Get Index of Production data for a specific quarter.

    Args:
        df: Index of Production DataFrame
        quarter: Quarter code (e.g., 'Q1', 'Q2', 'Q3', 'Q4')
        year: Year

    Returns:
        DataFrame with single row for the specified quarter

    Example:
        >>> iop_df = get_latest_index_of_production()
        >>> q3_2025 = get_iop_by_quarter(iop_df, 'Q3', 2025)
        >>> print(f"Q3 2025 NI: {q3_2025['ni_index'].values[0]}")
    """
    return df[(df["quarter"] == quarter) & (df["year"] == year)].reset_index(drop=True)


def calculate_ios_growth_rate(df: pd.DataFrame, periods: int = 4) -> pd.DataFrame:
    """Calculate year-on-year growth rate for Index of Services.

    Args:
        df: Index of Services DataFrame
        periods: Number of quarters for comparison (default: 4 for YoY)

    Returns:
        DataFrame with additional columns:
            - ni_growth_rate: NI percentage change vs same quarter previous year
            - uk_growth_rate: UK percentage change vs same quarter previous year

    Example:
        >>> ios_df = get_latest_index_of_services()
        >>> ios_growth = calculate_ios_growth_rate(ios_df)
        >>> recent = ios_growth.tail(4)
        >>> print(recent[['quarter', 'year', 'ni_index', 'ni_growth_rate']])
    """
    result = df.copy()

    # Calculate growth rates
    result["ni_growth_rate"] = result["ni_index"].pct_change(periods=periods) * 100
    result["uk_growth_rate"] = result["uk_index"].pct_change(periods=periods) * 100

    return result


def calculate_iop_growth_rate(df: pd.DataFrame, periods: int = 4) -> pd.DataFrame:
    """Calculate year-on-year growth rate for Index of Production.

    Args:
        df: Index of Production DataFrame
        periods: Number of quarters for comparison (default: 4 for YoY)

    Returns:
        DataFrame with additional columns:
            - ni_growth_rate: NI percentage change vs same quarter previous year
            - uk_growth_rate: UK percentage change vs same quarter previous year

    Example:
        >>> iop_df = get_latest_index_of_production()
        >>> iop_growth = calculate_iop_growth_rate(iop_df)
        >>> recent = iop_growth.tail(4)
        >>> print(recent[['quarter', 'year', 'ni_index', 'ni_growth_rate']])
    """
    result = df.copy()

    # Calculate growth rates
    result["ni_growth_rate"] = result["ni_index"].pct_change(periods=periods) * 100
    result["uk_growth_rate"] = result["uk_index"].pct_change(periods=periods) * 100

    return result


def get_ios_summary_statistics(
    df: pd.DataFrame, start_year: Optional[int] = None, end_year: Optional[int] = None
) -> Dict:
    """Calculate summary statistics for Index of Services.

    Args:
        df: Index of Services DataFrame
        start_year: Optional start year for summary
        end_year: Optional end year for summary

    Returns:
        Dictionary with summary statistics:
            - period: Time period covered
            - ni_mean: Mean NI index value
            - ni_min: Minimum NI index value
            - ni_max: Maximum NI index value
            - uk_mean: Mean UK index value
            - uk_min: Minimum UK index value
            - uk_max: Maximum UK index value
            - quarters_count: Number of quarters included

    Example:
        >>> ios_df = get_latest_index_of_services()
        >>> stats = get_ios_summary_statistics(ios_df, start_year=2020)
        >>> print(f"NI mean index since 2020: {stats['ni_mean']:.1f}")
    """
    filtered = df.copy()

    if start_year:
        filtered = filtered[filtered["year"] >= start_year]
    if end_year:
        filtered = filtered[filtered["year"] <= end_year]

    return {
        "period": f"{filtered['year'].min()}-{filtered['year'].max()}",
        "ni_mean": float(filtered["ni_index"].mean()),
        "ni_min": float(filtered["ni_index"].min()),
        "ni_max": float(filtered["ni_index"].max()),
        "uk_mean": float(filtered["uk_index"].mean()),
        "uk_min": float(filtered["uk_index"].min()),
        "uk_max": float(filtered["uk_index"].max()),
        "quarters_count": len(filtered),
    }


def get_iop_summary_statistics(
    df: pd.DataFrame, start_year: Optional[int] = None, end_year: Optional[int] = None
) -> Dict:
    """Calculate summary statistics for Index of Production.

    Args:
        df: Index of Production DataFrame
        start_year: Optional start year for summary
        end_year: Optional end year for summary

    Returns:
        Dictionary with summary statistics (same format as get_ios_summary_statistics)

    Example:
        >>> iop_df = get_latest_index_of_production()
        >>> stats = get_iop_summary_statistics(iop_df, start_year=2020)
        >>> print(f"NI mean index since 2020: {stats['ni_mean']:.1f}")
    """
    filtered = df.copy()

    if start_year:
        filtered = filtered[filtered["year"] >= start_year]
    if end_year:
        filtered = filtered[filtered["year"] <= end_year]

    return {
        "period": f"{filtered['year'].min()}-{filtered['year'].max()}",
        "ni_mean": float(filtered["ni_index"].mean()),
        "ni_min": float(filtered["ni_index"].min()),
        "ni_max": float(filtered["ni_index"].max()),
        "uk_mean": float(filtered["uk_index"].mean()),
        "uk_min": float(filtered["uk_index"].min()),
        "uk_max": float(filtered["uk_index"].max()),
        "quarters_count": len(filtered),
    }
