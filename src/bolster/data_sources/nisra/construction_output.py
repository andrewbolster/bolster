"""NISRA Construction Output Statistics Module.

This module provides access to Northern Ireland's quarterly construction output statistics:
- All Work: Total construction output index
- New Work: New construction projects
- Repair and Maintenance: Repair and maintenance work

Data is published quarterly by NISRA's Economic & Labour Market Statistics Branch.

Data Source: Northern Ireland Statistics and Research Agency provides quarterly construction
output statistics through their Economic Output section at https://www.nisra.gov.uk/statistics/economic-output/construction-output-statistics.
The data tracks construction activity across all sectors using a chained volume measure
approach to provide comparable time series data for construction output analysis.

Update Frequency: Quarterly publications are released approximately 3 months after the end
of each quarter. Construction output statistics are published as part of NISRA's Economic
Output series, providing the official measure of construction sector performance in Northern
Ireland with data updated four times per year.

Data Coverage:
    - All Work: Q1 2000 - Present (quarterly, non-seasonally adjusted)
    - New Work: Q1 2000 - Present (quarterly, non-seasonally adjusted)
    - Repair and Maintenance: Q1 2000 - Present (quarterly, seasonally adjusted)
    - Base year: 2022 = 100 (chained volume measure)

Examples:
    >>> from bolster.data_sources.nisra import construction_output
    >>> # Get latest construction output data
    >>> df = construction_output.get_latest_construction_output()
    >>> print(df.head())

    >>> # Filter for specific year
    >>> df_2024 = construction_output.get_construction_by_year(df, 2024)
    >>> print(f"Q4 2024 All Work: {df_2024[df_2024['quarter']=='Q4']['all_work_index'].values[0]}")

    >>> # Get specific quarter
    >>> q2_2025 = construction_output.get_construction_by_quarter(df, 'Q2', 2025)
    >>> print(f"Q2 2025: All Work={q2_2025['all_work_index'].values[0]:.1f}")

    >>> # Calculate growth rates
    >>> df_growth = construction_output.calculate_growth_rates(df)
    >>> recent = df_growth.tail(4)
    >>> print(recent[['quarter', 'year', 'all_work_index', 'all_work_yoy_growth']])

Publication Details:
    - Frequency: Quarterly
    - Published by: NISRA Economic & Labour Market Statistics Branch
    - Contact: economicstats@nisra.gov.uk
    - Next release: Approximately 3 months after quarter end
    - Base year: 2022 (index = 100)
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, download_file

logger = logging.getLogger(__name__)

# Base URL for NISRA construction output statistics
CONSTRUCTION_BASE_URL = "https://www.nisra.gov.uk/statistics/economic-output/construction-output-statistics"


def get_latest_construction_publication_url() -> tuple[str, datetime]:
    """Get the URL of the latest Construction Output publication.

    Scrapes the NISRA Construction Output page to find the most recent publication.

    Returns:
        Tuple of (excel_url, publication_date)

    Raises:
        NISRADataNotFoundError: If unable to find the latest publication

    Example:
        >>> url, pub_date = get_latest_construction_publication_url()
        >>> print(f"Latest published: {pub_date.strftime('%Y-%m-%d')}")
    """
    from bs4 import BeautifulSoup

    logger.info("Fetching latest Construction Output publication URL...")

    try:
        response = session.get(CONSTRUCTION_BASE_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch Construction Output page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    # Find the link to the latest publication
    # Pattern: "Construction Output Statistics - Q2 - 2025" or similar
    publication_links = soup.find_all("a", href=True)

    for link in publication_links:
        link_text = link.get_text(strip=True)
        if "Construction Output Statistics" in link_text and "Q" in link_text:
            pub_url = link["href"]
            if not pub_url.startswith("http"):
                pub_url = f"https://www.nisra.gov.uk{pub_url}"

            # Get the Excel file URL from the publication page
            try:
                pub_response = session.get(pub_url, timeout=30)
                pub_response.raise_for_status()
            except Exception as e:
                raise NISRADataNotFoundError(f"Failed to fetch publication page: {e}") from e

            pub_soup = BeautifulSoup(pub_response.content, "html.parser")

            # Find Excel file link (construction tables)
            for file_link in pub_soup.find_all("a", href=True):
                href = file_link["href"]
                if ".xlsx" in href.lower() and "construction" in href.lower() and "table" in href.lower():
                    excel_url = href
                    if not excel_url.startswith("http"):
                        excel_url = f"https://www.nisra.gov.uk{excel_url}"

                    # Extract publication date
                    pub_date = datetime.now()
                    date_meta = pub_soup.find("meta", property="article:published_time")
                    if date_meta and date_meta.get("content"):
                        pub_date = datetime.fromisoformat(date_meta["content"].split("T")[0])

                    logger.info(
                        f"Found latest Construction Output publication: {excel_url} (published {pub_date.date()})"
                    )
                    return excel_url, pub_date

    raise NISRADataNotFoundError("Could not find latest Construction Output publication")


def parse_construction_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse NISRA Construction Output Excel file.

    Extracts the main construction output time series (Table 1.1) from the Excel file.

    Args:
        file_path: Path to the Construction Output Excel file

    Returns:
        DataFrame with columns:
            - date: datetime (first day of quarter)
            - quarter: str (e.g., 'Q1', 'Q2', 'Q3', 'Q4')
            - year: int
            - all_work_index: float (total construction output, NSA)
            - new_work_index: float (new construction work, NSA)
            - repair_maintenance_index: float (repair and maintenance, SA)

    Example:
        >>> df = parse_construction_file("construction-tables-q2-2025.xlsx")
        >>> print(df[df['year'] == 2025].tail())
    """
    logger.info(f"Parsing Construction Output file: {file_path}")

    # Read Table 1.1: Main construction output indices
    # Skip first 4 rows to get to the header
    df = pd.read_excel(file_path, sheet_name="Table_1.1", skiprows=4)

    # Drop empty columns
    df = df.dropna(axis=1, how="all")

    # Rename columns for clarity
    df.columns = [
        "time_period",
        "quarter_num",
        "new_work_index",
        "new_work_qoq_change",
        "repair_maintenance_index",
        "repair_maintenance_qoq_change",
        "all_work_index",
        "all_work_qoq_change",
        "extra",  # Sometimes there's an extra column
    ]

    # Drop the extra column if it exists
    if "extra" in df.columns:
        df = df.drop(columns=["extra"])

    # Remove first row with "Not applicable" values
    df = df[df["new_work_qoq_change"] != "Not applicable"].reset_index(drop=True)

    # Extract year and quarter from time period
    def parse_time_period(time_str):
        # Remove [R] and [P] markers
        time_str = re.sub(r"\s*\[[RP]\]", "", str(time_str))

        # Extract year from "Jan to Mar 2000" format
        match = re.search(r"(\d{4})", time_str)
        if match:
            return int(match.group(1))
        return None

    df["year"] = df["time_period"].apply(parse_time_period)

    # Map quarter number to quarter code
    quarter_map = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}
    df["quarter"] = df["quarter_num"].map(quarter_map)

    # Create date column (first day of quarter)
    quarter_to_month = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}
    df["month"] = df["quarter"].map(quarter_to_month)
    df["date"] = pd.to_datetime({"year": df["year"], "month": df["month"], "day": 1})

    # Select and order columns
    result = df[
        [
            "date",
            "quarter",
            "year",
            "all_work_index",
            "new_work_index",
            "repair_maintenance_index",
        ]
    ].copy()

    # Remove any rows with missing data
    result = result.dropna().reset_index(drop=True)

    # Convert indices to float
    result["all_work_index"] = result["all_work_index"].astype(float)
    result["new_work_index"] = result["new_work_index"].astype(float)
    result["repair_maintenance_index"] = result["repair_maintenance_index"].astype(float)

    logger.info(
        f"Parsed {len(result)} quarters of Construction Output data ({result['year'].min()}-{result['year'].max()})"
    )

    return result


def get_latest_construction_output(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest Construction Output data.

    Downloads and parses the most recent NISRA Construction Output publication.
    Results are cached for 7 days unless force_refresh=True.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with quarterly Construction Output data

    Example:
        >>> df = get_latest_construction_output()
        >>> print(f"Latest quarter: {df.iloc[-1]['quarter']} {df.iloc[-1]['year']}")
        >>> print(f"All Work Index: {df.iloc[-1]['all_work_index']:.1f}")
    """
    excel_url, pub_date = get_latest_construction_publication_url()

    # Cache for 7 days (168 hours)
    file_path = download_file(excel_url, cache_ttl_hours=168, force_refresh=force_refresh)

    return parse_construction_file(file_path)


# ============================================================================
# Helper Functions for Analysis
# ============================================================================


def get_construction_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter Construction Output data for a specific year.

    Args:
        df: Construction Output DataFrame
        year: Year to filter for

    Returns:
        DataFrame with only the specified year's data

    Example:
        >>> df = get_latest_construction_output()
        >>> df_2024 = get_construction_by_year(df, 2024)
        >>> print(df_2024)
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_construction_by_quarter(df: pd.DataFrame, quarter: str, year: int) -> pd.DataFrame:
    """Get Construction Output data for a specific quarter.

    Args:
        df: Construction Output DataFrame
        quarter: Quarter code (e.g., 'Q1', 'Q2', 'Q3', 'Q4')
        year: Year

    Returns:
        DataFrame with single row for the specified quarter

    Example:
        >>> df = get_latest_construction_output()
        >>> q2_2025 = get_construction_by_quarter(df, 'Q2', 2025)
        >>> print(f"Q2 2025 All Work: {q2_2025['all_work_index'].values[0]:.1f}")
    """
    return df[(df["quarter"] == quarter) & (df["year"] == year)].reset_index(drop=True)


def calculate_growth_rates(df: pd.DataFrame, periods: int = 4) -> pd.DataFrame:
    """Calculate year-on-year growth rates for Construction Output indices.

    Args:
        df: Construction Output DataFrame
        periods: Number of quarters for comparison (default: 4 for YoY)

    Returns:
        DataFrame with additional columns:
            - all_work_yoy_growth: All Work percentage change vs same quarter previous year
            - new_work_yoy_growth: New Work percentage change vs same quarter previous year
            - repair_maintenance_yoy_growth: R&M percentage change vs same quarter previous year

    Example:
        >>> df = get_latest_construction_output()
        >>> df_growth = calculate_growth_rates(df)
        >>> recent = df_growth.tail(4)
        >>> print(recent[['quarter', 'year', 'all_work_index', 'all_work_yoy_growth']])
    """
    result = df.copy()

    # Calculate year-on-year growth rates
    result["all_work_yoy_growth"] = result["all_work_index"].pct_change(periods=periods) * 100
    result["new_work_yoy_growth"] = result["new_work_index"].pct_change(periods=periods) * 100
    result["repair_maintenance_yoy_growth"] = result["repair_maintenance_index"].pct_change(periods=periods) * 100

    return result


def get_summary_statistics(df: pd.DataFrame, start_year: Optional[int] = None, end_year: Optional[int] = None) -> dict:
    """Calculate summary statistics for Construction Output.

    Args:
        df: Construction Output DataFrame
        start_year: Optional start year for summary
        end_year: Optional end year for summary

    Returns:
        Dictionary with summary statistics:
            - period: Time period covered
            - all_work_mean: Mean All Work index value
            - all_work_min: Minimum All Work index value
            - all_work_max: Maximum All Work index value
            - new_work_mean: Mean New Work index value
            - repair_maintenance_mean: Mean Repair & Maintenance index value
            - quarters_count: Number of quarters included

    Example:
        >>> df = get_latest_construction_output()
        >>> stats = get_summary_statistics(df, start_year=2020)
        >>> print(f"All Work mean since 2020: {stats['all_work_mean']:.1f}")
    """
    filtered = df.copy()

    if start_year:
        filtered = filtered[filtered["year"] >= start_year]
    if end_year:
        filtered = filtered[filtered["year"] <= end_year]

    return {
        "period": f"{filtered['year'].min()}-{filtered['year'].max()}",
        "all_work_mean": float(filtered["all_work_index"].mean()),
        "all_work_min": float(filtered["all_work_index"].min()),
        "all_work_max": float(filtered["all_work_index"].max()),
        "new_work_mean": float(filtered["new_work_index"].mean()),
        "new_work_min": float(filtered["new_work_index"].min()),
        "new_work_max": float(filtered["new_work_index"].max()),
        "repair_maintenance_mean": float(filtered["repair_maintenance_index"].mean()),
        "repair_maintenance_min": float(filtered["repair_maintenance_index"].min()),
        "repair_maintenance_max": float(filtered["repair_maintenance_index"].max()),
        "quarters_count": len(filtered),
    }


def validate_construction_data(df: pd.DataFrame) -> bool:  # pragma: no cover
    """Validate construction output data integrity.

    Args:
        df: DataFrame from construction output functions

    Returns:
        True if validation passes, False otherwise
    """
    if df.empty:
        logger.warning("Construction data is empty")
        return False

    # Check for time series structure
    time_cols = ["quarter", "year", "date", "period"]
    has_time_data = any(col in df.columns for col in time_cols)
    if not has_time_data:
        logger.warning("No time series columns found in construction data")
        return False

    return True
