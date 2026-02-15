"""NISRA Migration Estimates - Official and Derived.

This module provides access to NISRA migration data through two approaches:

1. **Official Migration Statistics**: Published NISRA long-term international migration
   estimates from administrative data and the International Passenger Survey (IPS).

2. **Derived Migration Estimates**: Calculated from demographic components using the
   demographic accounting equation:

       Net Migration = Population Change - Natural Change
       Net Migration = ΔPopulation - (Births - Deaths)

Both approaches are useful:
- Official statistics are authoritative but published with a lag
- Derived estimates can be calculated for more recent periods
- Comparing both validates the demographic equation approach

Data Sources:
    **Official Migration**: https://www.nisra.gov.uk/statistics/population/long-term-international-migration-statistics

    **Derived Migration** (combines three NISRA sources):
    - **Population**: https://www.nisra.gov.uk/statistics/people-and-communities/population
    - **Births**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/births
    - **Deaths**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/deaths

Update Frequency: Annual (both official and derived)
Geographic Coverage: Northern Ireland
Reference Period: Mid-year (July to June) for official; Calendar year for derived

Example:
    >>> from bolster.data_sources.nisra import migration
    >>>
    >>> # Get official NISRA migration statistics
    >>> official = migration.get_official_migration()
    >>> print(official.head())
    >>>
    >>> # Get derived migration estimates (from demographic equation)
    >>> derived = migration.get_derived_migration()
    >>> print(derived.head())
    >>>
    >>> # Compare official vs derived for validation
    >>> comparison = migration.compare_official_vs_derived(official, derived)
    >>> print(comparison[comparison['exceeds_threshold']])
"""

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from . import births, deaths, population
from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)


def calculate_annual_births(births_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate monthly births data to annual totals.

    Args:
        births_df: DataFrame from births.get_latest_births(event_type='occurrence')

    Returns:
        DataFrame with columns:
            - year: int
            - births: int (total births in year)
    """
    # Filter for 'Persons' (total) and aggregate by year
    annual = births_df[births_df["sex"] == "Persons"].groupby(births_df["month"].dt.year)["births"].sum().reset_index()

    annual.columns = ["year", "births"]

    return annual


def calculate_annual_deaths(deaths_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate weekly deaths data to annual totals.

    Args:
        deaths_df: DataFrame from deaths.get_historical_deaths()

    Returns:
        DataFrame with columns:
            - year: int
            - deaths: int (total deaths in year)
    """
    # Use total_deaths column and aggregate by year
    annual = deaths_df.groupby("year")["total_deaths"].sum().reset_index()

    annual.columns = ["year", "deaths"]

    return annual


def calculate_annual_population(population_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate population data to annual totals for Northern Ireland.

    Args:
        population_df: DataFrame from population.get_latest_population(area='Northern Ireland')

    Returns:
        DataFrame with columns:
            - year: int
            - population: int (mid-year population estimate)
    """
    # Filter for 'All persons' and aggregate by year
    return population_df[population_df["sex"] == "All persons"].groupby("year")["population"].sum().reset_index()


def derive_migration(
    population_df: pd.DataFrame,
    births_df: pd.DataFrame,
    deaths_df: pd.DataFrame,
) -> pd.DataFrame:
    """Derive net migration from demographic components.

    Uses the demographic accounting equation:
        Net Migration = ΔPopulation - (Births - Deaths)

    Args:
        population_df: DataFrame from population.get_latest_population()
        births_df: DataFrame from births.get_latest_births(event_type='occurrence')
        deaths_df: DataFrame from deaths.get_latest_deaths()

    Returns:
        DataFrame with columns:
            - year: int
            - population_start: int (population at start of year, June 30 t-1)
            - population_end: int (population at end of year, June 30 t)
            - births: int (births in calendar year)
            - deaths: int (deaths in calendar year)
            - natural_change: int (births - deaths)
            - population_change: int (population_end - population_start)
            - net_migration: int (derived migration estimate)
            - migration_rate: float (per 1,000 population)

    Raises:
        NISRAValidationError: If data sources cannot be aligned
    """
    # Aggregate to annual data
    pop_annual = calculate_annual_population(population_df)
    births_annual = calculate_annual_births(births_df)
    deaths_annual = calculate_annual_deaths(deaths_df)

    # Merge all sources
    # Start with population data
    result = pop_annual.copy()
    result = result.rename(columns={"population": "population_end"})

    # Add previous year's population (population at start of period)
    result["population_start"] = result["population_end"].shift(1)

    # Add births and deaths
    result = result.merge(births_annual, on="year", how="left")
    result = result.merge(deaths_annual, on="year", how="left")

    # Calculate natural change
    result["natural_change"] = result["births"] - result["deaths"]

    # Calculate population change
    result["population_change"] = result["population_end"] - result["population_start"]

    # Derive net migration
    # Note: This represents the residual between observed population change
    # and natural change. It captures net migration plus any measurement error.
    result["net_migration"] = result["population_change"] - result["natural_change"]

    # Calculate migration rate per 1,000 population
    # Use average of start and end population as denominator
    avg_population = (result["population_start"] + result["population_end"]) / 2
    result["migration_rate"] = (result["net_migration"] / avg_population) * 1000

    # Drop rows with missing critical data
    # First drop first row (no previous year population)
    # Then drop any rows missing births or deaths data
    result = result.dropna(subset=["population_start", "births", "deaths"]).reset_index(drop=True)

    # Convert counts to integers
    for col in [
        "population_start",
        "population_end",
        "births",
        "deaths",
        "natural_change",
        "population_change",
        "net_migration",
    ]:
        result[col] = result[col].astype(int)

    # Round migration rate
    result["migration_rate"] = result["migration_rate"].round(2)

    # Log summary
    if not result.empty:
        latest_year = result["year"].max()
        latest_migration = result[result["year"] == latest_year]["net_migration"].values[0]
        date_range = f"{result['year'].min()}-{latest_year}"

        logger.info(f"Derived migration estimates for {len(result)} years ({date_range})")
        logger.info(f"  Latest year ({latest_year}): Net migration = {latest_migration:+,}")

    return result


def get_latest_migration(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest derived migration estimates for Northern Ireland.

    Automatically downloads the most recent population, births, and deaths data,
    then calculates net migration using the demographic accounting equation.

    Args:
        force_refresh: If True, bypass cache and download fresh data for all sources

    Returns:
        DataFrame with columns:
            - year: int
            - population_start, population_end: int (mid-year estimates)
            - births, deaths: int (annual totals)
            - natural_change: int (births - deaths)
            - population_change: int (year-over-year change)
            - net_migration: int (derived estimate)
            - migration_rate: float (per 1,000 population)

    Example:
        >>> # Get all migration data
        >>> df = get_latest_migration()

        >>> # Get recent migration trends
        >>> recent = df[df['year'] >= 2010]
        >>> print(recent[['year', 'net_migration', 'migration_rate']])

        >>> # Check if migration is positive or negative
        >>> df_2024 = df[df['year'] == 2024]
        >>> if df_2024['net_migration'].values[0] > 0:
        >>>     print("Net immigration")
        >>> else:
        >>>     print("Net emigration")
    """
    logger.info("Fetching data sources for migration calculation...")

    # Fetch all required data sources
    pop_df = population.get_latest_population(area="Northern Ireland", force_refresh=force_refresh)

    # For births, use occurrence data (actual birth dates) not registration dates
    births_df = births.get_latest_births(event_type="occurrence", force_refresh=force_refresh)

    # For deaths, use historical deaths data (provides annual totals)
    deaths_df = deaths.get_historical_deaths(force_refresh=force_refresh)

    # Derive migration from demographic components
    return derive_migration(pop_df, births_df, deaths_df)


def validate_demographic_equation(df: pd.DataFrame, tolerance: int = 100) -> bool:  # pragma: no cover
    """Validate that the demographic accounting equation holds.

    Checks that:
        Population Change = Natural Change + Net Migration

    Args:
        df: DataFrame from derive_migration() or get_latest_migration()
        tolerance: Allowable difference due to rounding/measurement error (default: 100)

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If equation doesn't hold within tolerance
    """
    for _, row in df.iterrows():
        year = row["year"]
        pop_change = row["population_change"]
        natural_change = row["natural_change"]
        migration = row["net_migration"]

        # Check equation
        expected_change = natural_change + migration
        difference = abs(pop_change - expected_change)

        if difference > tolerance:
            raise NISRAValidationError(
                f"Year {year}: Demographic equation violated. "
                f"Population change ({pop_change:,}) != Natural change ({natural_change:,}) + "
                f"Net migration ({migration:,}). Difference: {difference:,}"
            )

    logger.info(f"Validation passed: Demographic equation holds for {len(df)} years")
    return True


def get_migration_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter migration data for a specific year.

    Args:
        df: DataFrame from get_latest_migration()
        year: Year to filter

    Returns:
        Filtered DataFrame

    Example:
        >>> df = get_latest_migration()
        >>> df_2024 = get_migration_by_year(df, 2024)
        >>> print(f"Net migration in 2024: {df_2024['net_migration'].values[0]:+,}")
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_migration_summary_statistics(
    df: pd.DataFrame, start_year: Optional[int] = None, end_year: Optional[int] = None
) -> dict:
    """Calculate summary statistics for migration data.

    Args:
        df: DataFrame from get_latest_migration()
        start_year: Optional start year for analysis period
        end_year: Optional end year for analysis period

    Returns:
        Dictionary with summary statistics:
            - total_years: Number of years analyzed
            - avg_net_migration: Average annual net migration
            - avg_migration_rate: Average migration rate per 1,000
            - positive_years: Number of years with net immigration
            - negative_years: Number of years with net emigration
            - max_immigration_year: Year with highest immigration
            - max_immigration: Highest immigration value
            - max_emigration_year: Year with highest emigration
            - max_emigration: Highest emigration value (as negative)

    Example:
        >>> df = get_latest_migration()
        >>> stats = get_migration_summary_statistics(df, start_year=2010)
        >>> print(f"Average migration 2010-present: {stats['avg_net_migration']:+,.0f}")
        >>> print(f"Years with net immigration: {stats['positive_years']}")
    """
    # Filter by year range if specified
    filtered = df.copy()
    if start_year:
        filtered = filtered[filtered["year"] >= start_year]
    if end_year:
        filtered = filtered[filtered["year"] <= end_year]

    # Handle empty data
    if filtered.empty:
        return {
            "total_years": 0,
            "avg_net_migration": 0.0,
            "avg_migration_rate": 0.0,
            "positive_years": 0,
            "negative_years": 0,
            "max_immigration_year": None,
            "max_immigration": None,
            "max_emigration_year": None,
            "max_emigration": None,
        }

    # Calculate statistics
    stats = {
        "total_years": len(filtered),
        "avg_net_migration": filtered["net_migration"].mean(),
        "avg_migration_rate": filtered["migration_rate"].mean(),
        "positive_years": (filtered["net_migration"] > 0).sum(),
        "negative_years": (filtered["net_migration"] < 0).sum(),
    }

    # Find max immigration and emigration
    max_immigration_row = filtered.loc[filtered["net_migration"].idxmax()]
    min_migration_row = filtered.loc[filtered["net_migration"].idxmin()]

    stats["max_immigration_year"] = int(max_immigration_row["year"])
    stats["max_immigration"] = int(max_immigration_row["net_migration"])
    stats["max_emigration_year"] = int(min_migration_row["year"])
    stats["max_emigration"] = int(min_migration_row["net_migration"])

    return stats


# =============================================================================
# Official NISRA Migration Statistics
# =============================================================================

# Mother page URL for official migration publications
MIGRATION_MOTHER_PAGE = "https://www.nisra.gov.uk/statistics/population/long-term-international-migration-statistics"


def get_official_migration_publication_url() -> Tuple[str, int]:
    """Scrape NISRA migration mother page to find latest Official estimates file.

    Navigates the publication structure:
    1. Scrapes mother page for latest "Long-Term International Migration" publication
    2. Follows link to publication detail page
    3. Finds "Official" Excel file (Mig[YY][YY]-Official_1.xlsx)

    Returns:
        Tuple of (excel_file_url, publication_year)

    Raises:
        NISRADataNotFoundError: If publication or file not found
    """
    try:
        response = session.get(MIGRATION_MOTHER_PAGE, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch migration mother page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find latest publication link
    # Pattern: "Long-Term International Migration Statistics for Northern Ireland (YYYY)"
    pub_link = None
    pub_year = None

    for link in soup.find_all("a", href=True):
        link_text = link.get_text(strip=True)

        # Match publication title with year
        match = re.search(r"Long-Term International Migration.*\((\d{4})\)", link_text)

        if match and "publications" in link["href"]:
            year = int(match.group(1))
            href = link["href"]

            if href.startswith("/"):
                href = f"https://www.nisra.gov.uk{href}"

            # Take first match (newest publication)
            pub_link = href
            pub_year = year
            logger.info(f"Found {year} Long-Term International Migration publication")
            break

    if not pub_link:
        raise NISRADataNotFoundError("Could not find migration publication on mother page")

    # Now scrape the publication page for the Official estimates Excel file
    try:
        pub_response = session.get(pub_link, timeout=30)
        pub_response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch publication page {pub_link}: {e}")

    pub_soup = BeautifulSoup(pub_response.content, "html.parser")

    # Find Excel link matching pattern: Mig[YY][YY]-Official_1.xlsx
    excel_url = None

    for a_tag in pub_soup.find_all("a", href=True):
        href = a_tag["href"]
        if "Official" in href and href.endswith(".xlsx"):
            # Make absolute URL
            if href.startswith("/"):
                excel_url = f"https://www.nisra.gov.uk{href}"
            elif not href.startswith("http"):
                excel_url = f"https://www.nisra.gov.uk/{href}"
            else:
                excel_url = href

            logger.info(f"Found Official estimates file: {excel_url}")
            break

    if not excel_url:
        raise NISRADataNotFoundError(f"Could not find Official estimates Excel file on {pub_link}")

    return excel_url, pub_year


def parse_official_migration_file(file_path: Path) -> pd.DataFrame:
    """Parse downloaded official migration Excel file into DataFrame.

    Extracts Table 1.1 (Net International Migration time series) from the Official
    estimates file and transforms it into long-format DataFrame.

    Args:
        file_path: Path to downloaded Mig[YY][YY]-Official_1.xlsx file

    Returns:
        DataFrame with columns:
            - year: int (mid-year)
            - net_migration: int (net international migration)
            - date: pd.Timestamp (reference date, June 30 of end year)

    Raises:
        NISRAValidationError: If file format is unexpected or parsing fails
    """
    try:
        # Read Table 1.1 - Net International Migration time series
        # skiprows=2 to skip title and subtitle rows
        df = pd.read_excel(file_path, sheet_name="Table 1.1", skiprows=2)
    except Exception as e:
        raise NISRAValidationError(f"Failed to read Table 1.1 from {file_path}: {e}")

    # Find time period column (first column usually)
    time_col = df.columns[0]

    # Find net migration column (contains "Net" and "Migration" and "International")
    net_col = None
    for col in df.columns:
        if "Net" in str(col) and "Migration" in str(col) and "International" in str(col):
            net_col = col
            break

    if net_col is None:
        raise NISRAValidationError("Could not find 'Net International Migration' column in Table 1.1")

    # Extract relevant columns and clean
    result = pd.DataFrame(
        {
            "time_period": df[time_col],
            "net_migration": df[net_col],
        }
    )

    # Remove rows with NaN in critical columns
    result = result.dropna(subset=["time_period", "net_migration"])

    # Parse year from time_period (format: "Jul YYYY - Jun YYYY" or "YYYY - YYYY")
    # Extract the first year mentioned
    def extract_year(period_str):
        match = re.search(r"(\d{4})", str(period_str))
        return int(match.group(1)) if match else None

    result["year"] = result["time_period"].apply(extract_year)
    result = result.dropna(subset=["year"])
    result["year"] = result["year"].astype(int)

    # Create date column (reference date is June 30 of the end year, so add 1)
    result["date"] = pd.to_datetime(result["year"].astype(str) + "-06-30") + pd.DateOffset(years=1)

    # Convert net_migration to int
    result["net_migration"] = result["net_migration"].astype(int)

    # Select final columns
    result = result[["year", "net_migration", "date"]]

    # Sort by year
    result = result.sort_values("year").reset_index(drop=True)

    logger.info(f"Parsed official migration data: {len(result)} years ({result['year'].min()}-{result['year'].max()})")

    return result


def validate_official_migration(df: pd.DataFrame) -> bool:
    """Validate official migration data quality.

    Args:
        df: DataFrame from parse_official_migration_file() or get_official_migration()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If validation fails
    """
    # Check for empty DataFrame
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    # Check for required columns
    required_cols = ["year", "net_migration", "date"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise NISRAValidationError(f"Missing required columns: {missing_cols}")

    # Check for reasonable values (net migration should not exceed NI population ~1.9M)
    if (df["net_migration"].abs() > 1_900_000).any():
        raise NISRAValidationError("Found unreasonably large net_migration values")

    logger.info(f"Validation passed: Official migration data consistent for {len(df)} years")
    return True


def get_official_migration(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest official NISRA migration statistics.

    Automatically downloads the most recent official migration estimates from NISRA
    and parses them into a structured DataFrame.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - year: int (mid-year)
            - net_migration: int (net international migration)
            - date: pd.Timestamp (reference date)

    Raises:
        NISRADataNotFoundError: If publication cannot be found
        NISRAValidationError: If data fails validation

    Example:
        >>> # Get official migration data
        >>> official = get_official_migration()
        >>>
        >>> # Filter to recent years
        >>> recent = official[official['year'] >= 2010]
        >>> print(recent[['year', 'net_migration']])
    """
    logger.info("Fetching latest official migration statistics...")

    # Get latest publication URL
    excel_url, pub_year = get_official_migration_publication_url()

    # Download file (with caching, TTL=24 hours for annual data)
    file_path = download_file(excel_url, cache_ttl_hours=24, force_refresh=force_refresh)

    # Parse into DataFrame
    df = parse_official_migration_file(file_path)

    # Validate data
    validate_official_migration(df)

    logger.info(f"Successfully loaded official migration data: {len(df)} years, latest {df['year'].max()}")

    return df


# Alias for backward compatibility with existing derived migration function
get_derived_migration = get_latest_migration


def compare_official_vs_derived(
    official_df: pd.DataFrame,
    derived_df: pd.DataFrame,
    threshold: int = 1000,
) -> pd.DataFrame:
    """Compare official migration data with derived estimates for validation.

    Args:
        official_df: DataFrame from get_official_migration()
        derived_df: DataFrame from get_derived_migration() / get_latest_migration()
        threshold: Absolute difference threshold for flagging discrepancies (default: 1000)

    Returns:
        DataFrame with columns:
            - year: int
            - official_net_migration: int
            - derived_net_migration: int
            - absolute_difference: int
            - percent_difference: float
            - exceeds_threshold: bool

    Example:
        >>> official = get_official_migration()
        >>> derived = get_derived_migration()
        >>> comparison = compare_official_vs_derived(official, derived)
        >>>
        >>> # Show years with significant discrepancies
        >>> print(comparison[comparison['exceeds_threshold']])
        >>>
        >>> # Calculate mean error
        >>> print(f"Mean absolute error: {comparison['absolute_difference'].mean():,.0f}")
    """
    # Merge on year (inner join to get only overlapping years)
    comparison = official_df[["year", "net_migration"]].merge(
        derived_df[["year", "net_migration"]],
        on="year",
        suffixes=("_official", "_derived"),
    )

    # Rename columns for clarity
    comparison = comparison.rename(
        columns={
            "net_migration_official": "official_net_migration",
            "net_migration_derived": "derived_net_migration",
        }
    )

    # Calculate differences
    comparison["absolute_difference"] = (
        comparison["derived_net_migration"] - comparison["official_net_migration"]
    ).abs()

    comparison["percent_difference"] = (
        (comparison["derived_net_migration"] - comparison["official_net_migration"])
        / comparison["official_net_migration"].abs()
        * 100
    )

    # Flag discrepancies exceeding threshold
    comparison["exceeds_threshold"] = comparison["absolute_difference"] > threshold

    # Sort by year
    comparison = comparison.sort_values("year").reset_index(drop=True)

    # Log summary
    mean_abs_diff = comparison["absolute_difference"].mean()
    mean_pct_diff = comparison["percent_difference"].abs().mean()
    flagged_years = comparison["exceeds_threshold"].sum()

    logger.info(f"Cross-validation complete: {len(comparison)} overlapping years")
    logger.info(f"  Mean absolute difference: {mean_abs_diff:,.0f} people")
    logger.info(f"  Mean percentage difference: {mean_pct_diff:.1f}%")
    logger.info(f"  Years exceeding threshold ({threshold}): {flagged_years}")

    return comparison
