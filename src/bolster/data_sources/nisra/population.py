"""NISRA Mid-Year Population Estimates Data Source.

Provides access to mid-year population estimates for Northern Ireland with breakdowns by:
- Geography (Northern Ireland, Parliamentary Constituencies, Health and Social Care Trusts)
- Sex (All persons, Males, Females)
- Age (5-year age bands: 00-04, 05-09, ..., 85-89, 90+)
- Year (1971-present for NI overall, 2021-present for sub-geographies)

Mid-year estimates are referenced to June 30th of each year.

Data Source:
    **Mother Page**: https://www.nisra.gov.uk/statistics/people-and-communities/population

    This page lists all population statistics publications in reverse chronological order
    (newest first). The module automatically scrapes this page to find the latest
    "Mid-Year Population Estimates for Small Geographical Areas" publication, then downloads
    the age bands Excel file from that publication's detail page.

    The files contain complete time series data in a pre-processed "Flat" format, making
    this one of the most analysis-ready NISRA datasets.

Update Frequency: Annual (published ~6 months after reference date)
Geographic Coverage: Northern Ireland
Reference Date: June 30th of each year

Example:
    >>> from bolster.data_sources.nisra import population
    >>> # Get latest population estimates for all geographies
    >>> df = population.get_latest_population()
    >>> print(df.head())

    >>> # Get only Northern Ireland overall
    >>> ni_df = population.get_latest_population(area='Northern Ireland')
"""

import logging
import re
from pathlib import Path
from typing import Literal, Optional, Union

import pandas as pd

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

# Base URL for population statistics
POPULATION_BASE_URL = "https://www.nisra.gov.uk/statistics/people-and-communities/population"


def get_latest_population_publication_url() -> tuple[str, int]:
    """Scrape NISRA population mother page to find the latest MYE age bands file.

    Navigates the publication structure:
    1. Scrapes mother page for latest "Mid-Year Population Estimates" publication
    2. Follows link to publication detail page
    3. Finds age bands Excel file

    Returns:
        Tuple of (excel_file_url, year)

    Raises:
        NISRADataNotFoundError: If publication or file not found
    """
    from bs4 import BeautifulSoup

    mother_page = POPULATION_BASE_URL

    try:
        response = session.get(mother_page, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch population mother page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    # Find latest "Mid-Year Population Estimates for Small Geographical Areas" publication
    # Pattern: "2024 Mid-Year Population Estimates for Small Geographical Areas"
    pub_link = None
    pub_year = None

    for link in soup.find_all("a", href=True):
        link_text = link.get_text(strip=True)

        # Match pattern with year
        match = re.search(r"(\d{4})\s+Mid-Year Population Estimates.*Small Geographical Areas", link_text)

        if match and "publications" in link["href"]:
            year = int(match.group(1))
            href = link["href"]

            if href.startswith("/"):
                href = f"https://www.nisra.gov.uk{href}"

            # Take first match (should be newest due to reverse chronological order)
            pub_link = href
            pub_year = year
            logger.info(f"Found {year} Mid-Year Population Estimates publication")
            break

    if not pub_link:
        raise NISRADataNotFoundError("Could not find Mid-Year Population Estimates publication on mother page")

    # Scrape the publication page for age bands Excel file
    try:
        pub_response = session.get(pub_link, timeout=30)
        pub_response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch publication page: {e}") from e

    pub_soup = BeautifulSoup(pub_response.content, "html.parser")

    # Find age bands Excel file
    # Pattern: "MYE24_AGE_BANDS_NI_HSCT_PC.xlsx" or similar
    excel_url = None

    for link in pub_soup.find_all("a", href=True):
        href = link["href"]

        if "AGE_BANDS" in href.upper() and href.endswith(".xlsx"):
            if href.startswith("/"):
                href = f"https://www.nisra.gov.uk{href}"

            excel_url = href
            logger.info(f"Found age bands file for {pub_year}")
            break

    if not excel_url:
        raise NISRADataNotFoundError("Could not find age bands Excel file on publication page")

    return excel_url, pub_year


def parse_population_file(
    file_path: Union[str, Path],
    area: Optional[
        Literal[
            "all",
            "Northern Ireland",
            "Parliamentary Constituencies (2024)",
            "Health and Social Care Trusts",
            "Parliamentary Constituencies (2008)",
        ]
    ] = "all",
) -> pd.DataFrame:
    """Parse NISRA mid-year population estimates Excel file.

    The population file contains a "Flat" sheet with pre-processed long-format data,
    making this one of the easiest NISRA datasets to work with.

    Args:
        file_path: Path to the population Excel file
        area: Which geographic area(s) to return:
            - "all": All geographic breakdowns
            - "Northern Ireland": NI overall only (1971-present)
            - "Parliamentary Constituencies (2024)": 2024 constituencies (2021-present)
            - "Health and Social Care Trusts": HSC Trusts (2021-present)
            - "Parliamentary Constituencies (2008)": 2008 constituencies (2021-present)

    Returns:
        DataFrame with columns:
            - area: str (e.g., "1. Northern Ireland")
            - area_code: str (ONS geography code)
            - area_name: str (full area name)
            - year: int (reference year)
            - sex: str ("All persons", "Males", "Females")
            - age_5: str (5-year age band: "00-04", "05-09", ..., "90+")
            - age_band: str (custom age band)
            - age_broad: str (broad age band: "00-15", "16-39", "40-64", "65+")
            - population: int (mid-year estimate)

    Raises:
        NISRAValidationError: If file structure is unexpected
    """
    file_path = Path(file_path)

    try:
        # Read the Flat sheet - it's already in perfect long format
        df = pd.read_excel(file_path, sheet_name="Flat")
    except Exception as e:
        raise NISRAValidationError(f"Failed to read population file: {e}") from e

    # Validate expected columns
    expected_cols = {"area", "area_code", "area_name", "year", "sex", "age_5", "age_band", "age_broad", "MYE"}
    if not expected_cols.issubset(df.columns):
        missing = expected_cols - set(df.columns)
        raise NISRAValidationError(f"Missing expected columns: {missing}") from e

    # Rename MYE to population for clarity
    df = df.rename(columns={"MYE": "population"})

    # Filter by area if specified
    if area and area != "all":
        # Map user-friendly names to area column values
        area_map = {
            "Northern Ireland": "1. Northern Ireland",
            "Parliamentary Constituencies (2024)": "2. Parliamentary Constituencies (2024)",
            "Health and Social Care Trusts": "3. Health and Social Care Trusts",
            "Parliamentary Constituencies (2008)": "4. Parliamentary Constituencies (2008)",
        }

        area_value = area_map.get(area)
        if not area_value:
            raise ValueError(f"Invalid area: {area}. Choose from: {list(area_map.keys())}")

        df = df[df["area"] == area_value].copy()

        if df.empty:
            raise NISRAValidationError(f"No data found for area: {area}")

    # Sort for consistent output
    return df.sort_values(["area", "year", "sex", "age_5"]).reset_index(drop=True)


def get_latest_population(
    area: Optional[
        Literal[
            "all",
            "Northern Ireland",
            "Parliamentary Constituencies (2024)",
            "Health and Social Care Trusts",
            "Parliamentary Constituencies (2008)",
        ]
    ] = "all",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the latest mid-year population estimates.

    Automatically discovers and downloads the most recent population estimates
    from the NISRA website.

    Args:
        area: Which geographic area(s) to return (default: "all")
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - area, area_code, area_name: Geographic identifiers
            - year: Reference year
            - sex: "All persons", "Males", or "Females"
            - age_5: 5-year age band
            - age_band, age_broad: Alternative age groupings
            - population: Mid-year estimate

    Raises:
        NISRADataNotFoundError: If latest publication cannot be found
        NISRAValidationError: If file structure is unexpected

    Example:
        >>> # Get all data
        >>> df = get_latest_population()

        >>> # Get only Northern Ireland overall
        >>> ni_df = get_latest_population(area='Northern Ireland')

        >>> # Calculate total NI population in latest year
        >>> ni_2024 = ni_df[(ni_df['year'] == 2024) & (ni_df['sex'] == 'All persons')]
        >>> total = ni_2024['population'].sum()
    """
    # Discover latest publication
    excel_url, year = get_latest_population_publication_url()

    logger.info(f"Downloading {year} mid-year population estimates from: {excel_url}")

    # Cache for 180 days (annual data, infrequent updates)
    cache_ttl_hours = 180 * 24
    file_path = download_file(excel_url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    # Parse the file
    return parse_population_file(file_path, area=area)


def validate_population_totals(df: pd.DataFrame) -> bool:
    """Validate that Males + Females population equals All persons for each group.

    Args:
        df: DataFrame from parse_population_file or get_latest_population

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If validation fails
    """
    # Get unique combinations of area, year, age_5
    groups = df.groupby(["area_name", "year", "age_5"])

    for (area_name, year, age_band), group_data in groups:
        all_persons = group_data[group_data["sex"] == "All persons"]["population"].sum()
        males = group_data[group_data["sex"] == "Males"]["population"].sum()
        females = group_data[group_data["sex"] == "Females"]["population"].sum()

        if all_persons != males + females:
            raise NISRAValidationError(
                f"{area_name} {year} {age_band}: All persons ({all_persons}) != Males ({males}) + Females ({females})"
            )

    num_groups = len(groups)
    logger.info(f"Validation passed: Males + Females = All persons for {num_groups} groups")
    return True


def get_population_by_year(
    df: pd.DataFrame,
    year: int,
    sex: Optional[Literal["All persons", "Males", "Females"]] = "All persons",
) -> pd.DataFrame:
    """Filter population data for a specific year and optional sex.

    Args:
        df: DataFrame from get_latest_population()
        year: Year to filter
        sex: Sex category to filter (default: "All persons")

    Returns:
        Filtered DataFrame

    Example:
        >>> df = get_latest_population(area='Northern Ireland')
        >>> pop_2024 = get_population_by_year(df, 2024)
        >>> # Calculate total population
        >>> total = pop_2024['population'].sum()
    """
    filtered = df[df["year"] == year].copy()

    if sex:
        filtered = filtered[filtered["sex"] == sex]

    return filtered.reset_index(drop=True)


def get_population_pyramid_data(
    df: pd.DataFrame,
    year: int,
    area_name: Optional[str] = "NORTHERN IRELAND",
) -> pd.DataFrame:
    """Prepare data for population pyramid visualization.

    Returns males and females by age band for a specific year and area,
    formatted for easy pyramid plotting.

    Args:
        df: DataFrame from get_latest_population()
        year: Year to visualize
        area_name: Area name to filter (default: "NORTHERN IRELAND")

    Returns:
        DataFrame with columns:
            - age_5: Age band
            - males: Male population (positive values)
            - females: Female population (negative values for pyramid)

    Example:
        >>> df = get_latest_population(area='Northern Ireland')
        >>> pyramid = get_population_pyramid_data(df, 2024)
        >>> # Plot with matplotlib/plotly
        >>> import matplotlib.pyplot as plt
        >>> plt.barh(pyramid['age_5'], pyramid['males'], label='Males')
        >>> plt.barh(pyramid['age_5'], pyramid['females'], label='Females')
    """
    filtered = df[(df["year"] == year) & (df["area_name"] == area_name)].copy()

    # Get males and females separately and aggregate by age_5
    # (file has multiple rows per age_5 due to different age_band groupings)
    males = filtered[filtered["sex"] == "Males"].groupby("age_5")["population"].sum().reset_index()
    males = males.rename(columns={"population": "males"})

    females = filtered[filtered["sex"] == "Females"].groupby("age_5")["population"].sum().reset_index()
    females = females.rename(columns={"population": "females"})
    # Make females negative for pyramid visualization
    females["females"] = -females["females"]

    # Merge
    pyramid = males.merge(females, on="age_5", how="outer")

    # Sort by age band
    return pyramid.sort_values("age_5").reset_index(drop=True)
