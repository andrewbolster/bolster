"""NISRA Northern Ireland Composite Economic Index Module.

This module provides access to the Northern Ireland Composite Economic Index (NICEI),
an experimental quarterly measure of economic performance based on official statistics.

The NICEI tracks five key sectors of the NI economy:
- Services
- Production (manufacturing and mining)
- Construction
- Agriculture
- Public Sector

Data Source: Northern Ireland Statistics and Research Agency provides the Northern Ireland
Composite Economic Index through their Economic Output statistics at https://www.nisra.gov.uk/statistics.
The NICEI is an experimental quarterly indicator that combines official statistics across five
key economic sectors to provide an overall measure of economic performance for Northern Ireland.

Update Frequency: Quarterly publications are released approximately 3 months after the end of
each quarter. The NICEI data is published as part of NISRA's Economic Output statistics series
by the Economic & Labour Market Statistics Branch, with data updated four times per year.

Data Coverage:
    - Quarterly time series from Q1 2006 to present
    - Indices and sector contributions to quarterly change
    - Private and public sector breakdowns
    - Base period: 2022=100

Examples:
    >>> from bolster.data_sources.nisra import composite_index
    >>> # Get latest NICEI data
    >>> nicei_df = composite_index.get_latest_nicei()
    >>> print(nicei_df.tail())

    >>> # Get sector contributions
    >>> contrib_df = composite_index.get_latest_nicei_contributions()
    >>> print(contrib_df.tail())

    >>> # Filter for specific year
    >>> nicei_2024 = composite_index.get_nicei_by_year(nicei_df, 2024)
    >>> print(f"Annual average 2024: {nicei_2024['nicei'].mean():.2f}")

    >>> # Analyze sectoral performance
    >>> latest = nicei_df.iloc[-1]
    >>> print(f"Q{latest['quarter']} {latest['year']} NICEI: {latest['nicei']:.2f}")
    >>> print(f"Services: {latest['services']:.2f}, Construction: {latest['construction']:.2f}")

Publication Details:
    - Frequency: Quarterly (published ~3 months after quarter end)
    - Published by: NISRA Economic & Labour Market Statistics Branch
    - Contact: economicstats@nisra.gov.uk
    - Mother page: https://www.nisra.gov.uk/statistics/economic-output-statistics/ni-composite-economic-index
    - Note: NICEI is an experimental statistic subject to revision

Author: Claude Code
Date: 2025-12-22
"""

import logging
from pathlib import Path
from typing import Tuple, Union

import pandas as pd

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, download_file

logger = logging.getLogger(__name__)

# Base URL for NICEI publications
NICEI_BASE_URL = "https://www.nisra.gov.uk"
NICEI_STATS_URL = "https://www.nisra.gov.uk/statistics/economic-output-statistics/ni-composite-economic-index"


def get_latest_nicei_publication_url() -> Tuple[str, int, str]:
    """Get the URL of the latest NICEI publication.

    Scrapes the NISRA NICEI statistics page to find the most recent quarterly publication.

    Returns:
        Tuple of (excel_url, year, quarter_str)

    Raises:
        NISRADataNotFoundError: If unable to find the latest publication

    Example:
        >>> url, year, quarter = get_latest_nicei_publication_url()
        >>> print(f"Latest NICEI: Q{quarter} {year}")
    """
    from bs4 import BeautifulSoup

    logger.info("Fetching latest NICEI publication URL...")

    try:
        response = session.get(NICEI_STATS_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch NICEI page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find the link to the latest publication
    # Pattern: "NICEI publication and tables Q# YYYY" or similar
    publication_links = soup.find_all("a", href=True)

    for link in publication_links:
        link_text = link.get_text(strip=True).lower()
        href = link["href"]

        # Look for publication links with quarter and year
        if "nicei" in link_text and "publication" in link_text and "tables" in link_text:
            # Extract quarter and year from link text or href
            import re

            # Try to extract from href first (more reliable)
            # Pattern: /publications/nicei-publication-and-tables-q2-2025
            match = re.search(r"nicei.*q(\d)-(\d{4})", href.lower())
            if match:
                quarter = int(match.group(1))
                year = int(match.group(2))

                pub_url = href
                if not pub_url.startswith("http"):
                    pub_url = f"{NICEI_BASE_URL}{pub_url}"

                # Get the Excel file URL from the publication page
                try:
                    pub_response = session.get(pub_url, timeout=30)
                    pub_response.raise_for_status()
                except Exception as e:
                    logger.warning(f"Failed to fetch publication page {pub_url}: {e}")
                    continue

                pub_soup = BeautifulSoup(pub_response.content, "html.parser")

                # Find Excel file link
                for file_link in pub_soup.find_all("a", href=True):
                    file_href = file_link["href"]
                    if ".xlsx" in file_href.lower() and "nicei" in file_href.lower():
                        excel_url = file_href
                        if not excel_url.startswith("http"):
                            excel_url = f"{NICEI_BASE_URL}{excel_url}"

                        logger.info(f"Found latest NICEI publication: Q{quarter} {year} at {excel_url}")
                        return excel_url, year, f"Q{quarter}"

    raise NISRADataNotFoundError("Could not find latest NICEI publication")


def parse_nicei_indices(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse NICEI Table 1: Index values by quarter.

    Extracts the main NICEI time series including overall index and sectoral breakdowns.

    Args:
        file_path: Path to the NICEI Excel file

    Returns:
        DataFrame with columns:
            - year: int
            - quarter: int (1-4)
            - nicei: float (composite economic index)
            - private_sector: float
            - public_sector: float
            - services: float
            - production: float
            - construction: float
            - agriculture: float

    Example:
        >>> df = parse_nicei_indices('/path/to/nicei.xlsx')
        >>> print(df[df['year'] == 2024].mean())
    """
    logger.info(f"Parsing NICEI indices from: {file_path}")

    # Read Table 1 - skip the title row, use row 2 as header
    df = pd.read_excel(file_path, sheet_name="Table 1", skiprows=1)

    # Rename columns to match the actual content
    # Row 2 has: Year, Quarter, NICEI, Private Sector, Public Sector, Services, Production, Construction, Agriculture
    df.columns = [
        "year",
        "quarter",
        "nicei",
        "private_sector",
        "public_sector",
        "services",
        "production",
        "construction",
        "agriculture",
    ]

    # Convert to appropriate types
    df["year"] = df["year"].astype(int)
    df["quarter"] = df["quarter"].astype(int)

    # Convert numeric columns
    for col in ["nicei", "private_sector", "public_sector", "services", "production", "construction", "agriculture"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remove any rows with NaN in year (footer rows, etc.)
    df = df.dropna(subset=["year", "quarter"]).reset_index(drop=True)

    logger.info(f"Parsed {len(df)} quarters of NICEI index data")
    return df


def parse_nicei_contributions(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse NICEI Table 11: Sector contributions to quarterly change.

    Extracts how much each sector contributed to the quarterly change in NICEI.

    Args:
        file_path: Path to the NICEI Excel file

    Returns:
        DataFrame with columns:
            - year: int
            - quarter: int (1-4)
            - nicei: float (index value)
            - nicei_quarterly_change: float (percentage point change from previous quarter)
            - public_sector_contribution: float
            - services_contribution: float
            - production_contribution: float
            - construction_contribution: float
            - agriculture_contribution: float

    Example:
        >>> df = parse_nicei_contributions('/path/to/nicei.xlsx')
        >>> # Find quarter with largest services contribution
        >>> print(df.loc[df['services_contribution'].idxmax()])
    """
    logger.info(f"Parsing NICEI sector contributions from: {file_path}")

    # Read Table 11 - has a multi-row header structure
    # Skip title row, next 2 rows are headers
    df = pd.read_excel(file_path, sheet_name="Table 11", skiprows=2)

    # Rename columns based on the structure
    # Columns: Year, Quarter, NICEI, NICEI Quarterly Change, Public Sector, Services, Production, Construction, Agriculture
    df.columns = [
        "year",
        "quarter",
        "nicei",
        "nicei_quarterly_change",
        "public_sector_contribution",
        "services_contribution",
        "production_contribution",
        "construction_contribution",
        "agriculture_contribution",
    ]

    # Convert to appropriate types
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["quarter"] = pd.to_numeric(df["quarter"], errors="coerce")

    # Convert numeric columns
    numeric_cols = [
        "nicei",
        "nicei_quarterly_change",
        "public_sector_contribution",
        "services_contribution",
        "production_contribution",
        "construction_contribution",
        "agriculture_contribution",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remove rows with NaN in year (first data row with no previous quarter, footer rows, etc.)
    df = df.dropna(subset=["year", "quarter", "nicei_quarterly_change"]).reset_index(drop=True)

    # Convert year and quarter to int after cleaning
    df["year"] = df["year"].astype(int)
    df["quarter"] = df["quarter"].astype(int)

    logger.info(f"Parsed {len(df)} quarters of NICEI contribution data")
    return df


def get_latest_nicei(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest NICEI index data.

    Downloads and parses the most recent NICEI publication.
    Results are cached for 90 days unless force_refresh=True.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with quarterly NICEI index values and sectoral breakdowns

    Example:
        >>> df = get_latest_nicei()
        >>> print(f"Latest NICEI: {df.iloc[-1]['nicei']:.2f}")
    """
    excel_url, year, quarter = get_latest_nicei_publication_url()

    # Cache for 90 days (quarterly publication)
    file_path = download_file(excel_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    return parse_nicei_indices(file_path)


def get_latest_nicei_contributions(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest NICEI sector contribution data.

    Downloads and parses sector contributions to quarterly change from the most recent
    NICEI publication. Results are cached for 90 days unless force_refresh=True.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with quarterly sector contributions to NICEI change

    Example:
        >>> df = get_latest_nicei_contributions()
        >>> latest = df.iloc[-1]
        >>> print(f"Q{latest['quarter']} {latest['year']} contributions:")
        >>> print(f"  Services: {latest['services_contribution']:.2f}")
    """
    excel_url, year, quarter = get_latest_nicei_publication_url()

    # Cache for 90 days (quarterly publication)
    file_path = download_file(excel_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    return parse_nicei_contributions(file_path)


def get_nicei_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter NICEI data for a specific year.

    Args:
        df: DataFrame from get_latest_nicei() or parse_nicei_indices()
        year: Year to filter for

    Returns:
        Filtered DataFrame containing only the specified year

    Example:
        >>> df = get_latest_nicei()
        >>> df_2024 = get_nicei_by_year(df, 2024)
        >>> print(f"2024 average NICEI: {df_2024['nicei'].mean():.2f}")
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_nicei_by_quarter(df: pd.DataFrame, year: int, quarter: int) -> pd.DataFrame:
    """Filter NICEI data for a specific quarter.

    Args:
        df: DataFrame from get_latest_nicei() or parse_nicei_indices()
        year: Year to filter for
        quarter: Quarter (1-4) to filter for

    Returns:
        Filtered DataFrame containing only the specified quarter (usually 1 row)

    Example:
        >>> df = get_latest_nicei()
        >>> q2_2024 = get_nicei_by_quarter(df, 2024, 2)
        >>> print(f"Q2 2024 NICEI: {q2_2024['nicei'].values[0]:.2f}")
    """
    return df[(df["year"] == year) & (df["quarter"] == quarter)].reset_index(drop=True)


def validate_composite_index_data(df: pd.DataFrame) -> bool:
    """Validate composite index data integrity.

    Args:
        df: DataFrame from composite index functions

    Returns:
        True if validation passes, False otherwise
    """
    if df.empty:
        logger.warning("Composite index data is empty")
        return False

    # Check for index-related columns
    index_indicators = ["index", "composite", "measure", "value"]
    has_index_data = any(indicator in " ".join(df.columns).lower() for indicator in index_indicators)
    if not has_index_data:
        logger.warning("No index indicators found in composite index data")
        return False

    return True
