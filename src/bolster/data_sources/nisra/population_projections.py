"""NISRA Population Projections for Northern Ireland.

Provides access to official NISRA population projections with demographic breakdowns
by year, age, sex, and geography. Projections extend from the base year (e.g., 2022)
into the future (typically 50 years) to support demographic planning and policy analysis.

Data includes:
- Projected population by single year of age (0-90+)
- Breakdowns by sex (Males, Females, All Persons)
- Geographic coverage (Northern Ireland overall)
- Multiple projection variants (principal, high, low population scenarios)

Data Source:
    **Principal Projection**: https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland
    **Variant Projections**: https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland-variant-projections

    The principal projection publication provides 2 Excel files:
    - NPP22_ppp_age_sexv2.xlsx: Population by age and sex (RECOMMENDED - uses "Flat File" sheet)
    - NPP22_ppp_coc.xlsx: Components of change summary

    The variant projections provide 13 additional files with different demographic assumptions
    (high/low fertility, mortality, migration scenarios).

    This module uses the "Flat File" sheet which is already in perfect long format,
    requiring no data transformation.

Update Frequency: Biennial (every 2 years, e.g., 2022-based, 2024-based)
Geographic Coverage: Northern Ireland
Projection Horizon: Typically 50 years (e.g., 2022-2072)

Example:
    >>> from bolster.data_sources.nisra import population_projections
    >>>
    >>> # Get all projections (default: principal projection)
    >>> df = population_projections.get_latest_projections()
    >>> print(df.head())
    >>>
    >>> # Filter to specific year and demographics
    >>> df_2030 = df[(df['year'] == 2030) & (df['sex'] == 'All Persons')]
    >>> total_2030 = df_2030['population'].sum()
    >>> print(f"Projected NI population in 2030: {total_2030:,}")
    >>>
    >>> # Get projections for specific year range
    >>> df_decade = population_projections.get_latest_projections(
    ...     area='Northern Ireland',
    ...     start_year=2025,
    ...     end_year=2035
    ... )
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
)

logger = logging.getLogger(__name__)

# Publication URLs
PROJECTIONS_PRINCIPAL_URL = "https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland"
PROJECTIONS_VARIANTS_URL = (
    "https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland-variant-projections"
)


def get_latest_projections_publication_url(variant: str = "principal") -> str:
    """Discover latest population projections publication URL.

    Args:
        variant: Projection variant ('principal', 'hhh', 'lll', etc.). Default: 'principal'

    Returns:
        URL to latest projections Excel file

    Raises:
        NISRADataNotFoundError: If publication cannot be found
    """
    if variant == "principal":
        pub_url = PROJECTIONS_PRINCIPAL_URL
        file_pattern = "NPP22_ppp_age_sexv2.xlsx"
    else:
        pub_url = PROJECTIONS_VARIANTS_URL
        file_pattern = f"NPP22_{variant}_coc.xlsx"

    try:
        response = session.get(pub_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch projections publication page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find Excel link matching the pattern
    excel_url = None

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if file_pattern in href and href.endswith(".xlsx"):
            # Make absolute URL
            if href.startswith("/"):
                excel_url = f"https://www.nisra.gov.uk{href}"
            elif not href.startswith("http"):
                excel_url = f"https://www.nisra.gov.uk/{href}"
            else:
                excel_url = href

            logger.info(f"Found projections file: {excel_url}")
            break

    if not excel_url:
        raise NISRADataNotFoundError(f"Could not find {file_pattern} on {pub_url}")

    return excel_url


def parse_projections_file(file_path: Path, variant: str = "principal") -> pd.DataFrame:
    """Parse downloaded projections Excel file into long-format DataFrame.

    For principal projection, uses the "Flat File" sheet which is already in
    perfect long format requiring no transformation.

    Args:
        file_path: Path to downloaded NPP22_ppp_age_sexv2.xlsx or variant file
        variant: Projection variant ('principal' or variant code)

    Returns:
        DataFrame with columns:
            - year: int (projection year)
            - base_year: int (base year for projection, e.g., 2022)
            - age_group: str (5-year age band, e.g., "00-04", "05-09", "90+")
            - sex: str ("Males", "Females", "All Persons")
            - area: str (geographic area, typically "Northern Ireland")
            - population: int (projected population count)

    Raises:
        NISRAValidationError: If file format unexpected or data invalid
    """
    try:
        if variant == "principal":
            # Read Flat File sheet - already in perfect long format
            df = pd.read_excel(file_path, sheet_name="Flat File")
        else:
            # For variant projections, read PERSONS sheet
            # This is wide format and needs transformation
            df = pd.read_excel(file_path, sheet_name="PERSONS", skiprows=6, index_col=0)
            # TODO: Implement wide-to-long transformation for variants
            raise NotImplementedError(f"Variant projection parsing not yet implemented: {variant}")

    except Exception as e:
        raise NISRAValidationError(f"Failed to read projections from {file_path}: {e}")

    # Standardize column names (Flat File uses: Area, Area_Code, Projection, Mid-Year, Sex, Age, Age_5, NPP)
    df = df.rename(
        columns={
            "Mid-Year": "year",
            "Sex": "sex",
            "Age_5": "age_group",
            "Area": "area",
            "NPP": "population",
        }
    )

    # Add base_year column (extract from Projection column if present, or default to 2022)
    if "Projection" in df.columns:
        # Extract base year from projection name (e.g., "Principal Projection" -> 2022)
        df["base_year"] = 2022  # Default for 2022-based projections
    else:
        df["base_year"] = 2022

    # Select and reorder columns
    columns_to_keep = ["year", "base_year", "age_group", "sex", "area", "population"]
    df = df[columns_to_keep]

    # Clean data types
    df["year"] = df["year"].astype(int)
    df["base_year"] = df["base_year"].astype(int)
    df["population"] = df["population"].astype(int)

    # Sort by year, age, sex
    df = df.sort_values(["year", "age_group", "sex"]).reset_index(drop=True)

    logger.info(
        f"Parsed projections: {len(df)} rows, "
        f"years {df['year'].min()}-{df['year'].max()}, "
        f"{len(df['age_group'].unique())} age groups"
    )

    return df


def validate_projections_totals(df: pd.DataFrame) -> bool:
    """Validate that All Persons = Males + Females for each year/age/area.

    Args:
        df: DataFrame from get_latest_projections()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If totals don't match
    """
    # Check for empty DataFrame
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    # Check for required columns
    required_cols = ["year", "age_group", "sex", "area", "population"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise NISRAValidationError(f"Missing required columns: {missing_cols}")

    # Check for negative population
    if (df["population"] < 0).any():
        raise NISRAValidationError("Found negative population values")

    # Check sex totals
    tolerance = 5  # Allow small rounding differences
    mismatches = []

    for (year, age, area), group in df.groupby(["year", "age_group", "area"]):
        males = group[group["sex"] == "Males"]["population"].sum()
        females = group[group["sex"] == "Females"]["population"].sum()
        all_persons = group[group["sex"] == "All Persons"]["population"].sum()

        if all_persons > 0:  # Only check if data exists
            difference = abs((males + females) - all_persons)
            if difference > tolerance:
                mismatches.append(
                    f"Year {year}, Age {age}, Area {area}: "
                    f"Males ({males}) + Females ({females}) != All Persons ({all_persons}), "
                    f"difference: {difference}"
                )

    if mismatches:
        raise NISRAValidationError(f"Found {len(mismatches)} sex totals mismatch(es):\n" + "\n".join(mismatches[:5]))

    logger.info(
        f"Validation passed: Sex totals consistent for all {len(df.groupby(['year', 'age_group', 'area']))} groups"
    )
    return True


def validate_projection_coverage(df: pd.DataFrame) -> bool:
    """Validate that projections cover expected year range.

    Args:
        df: DataFrame from get_latest_projections()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If year range is incomplete or suspicious
    """
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    years = sorted(df["year"].unique())

    # Should have at least 20 years of projections
    if len(years) < 20:
        raise NISRAValidationError(f"Expected at least 20 years of projections, got {len(years)}")

    # Years should be continuous (no gaps)
    for i in range(len(years) - 1):
        gap = years[i + 1] - years[i]
        if gap > 1:
            raise NISRAValidationError(f"Gap of {gap} years between {years[i]} and {years[i + 1]}")

    logger.info(f"Validation passed: Projections cover {len(years)} years ({years[0]}-{years[-1]})")
    return True


def get_latest_projections(
    area: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    variant: str = "principal",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get latest NISRA population projections with optional filtering.

    Args:
        area: Filter to specific geographic area (e.g., "Northern Ireland"). Default: no filter
        start_year: Filter projections >= this year. Default: no filter
        end_year: Filter projections <= this year. Default: no filter
        variant: Projection variant ('principal', 'hhh', 'lll', etc.). Default: 'principal'
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with population projections

    Raises:
        NISRADataNotFoundError: If publication cannot be found
        NISRAValidationError: If data fails integrity checks

    Example:
        >>> # Get all projections
        >>> df = get_latest_projections()
        >>>
        >>> # Get Northern Ireland projections for 2030s
        >>> df_ni_2030s = get_latest_projections(
        ...     area='Northern Ireland',
        ...     start_year=2030,
        ...     end_year=2039
        ... )
        >>>
        >>> # Get working-age population projection
        >>> df_2030 = get_latest_projections(start_year=2030, end_year=2030)
        >>> working_age = df_2030[
        ...     (df_2030['sex'] == 'All Persons') &
        ...     (df_2030['age_group'].isin(['15-19', '20-24', ..., '60-64']))
        ... ]
    """
    logger.info(f"Fetching latest population projections (variant: {variant})...")

    # Get publication URL
    excel_url = get_latest_projections_publication_url(variant=variant)

    # Download file (with caching, TTL=168 hours = 7 days for biennial data)
    file_path = download_file(excel_url, cache_ttl_hours=168, force_refresh=force_refresh)

    # Parse into DataFrame
    df = parse_projections_file(file_path, variant=variant)

    # Validate data
    validate_projections_totals(df)
    validate_projection_coverage(df)

    # Apply filters
    if area is not None:
        df = df[df["area"] == area]

    if start_year is not None:
        df = df[df["year"] >= start_year]

    if end_year is not None:
        df = df[df["year"] <= end_year]

    logger.info(f"Successfully loaded projections: {len(df)} rows, years {df['year'].min()}-{df['year'].max()}")

    return df
