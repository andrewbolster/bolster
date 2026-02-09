"""NISRA Migration Estimates (Derived from Demographic Components).

Provides derived migration estimates for Northern Ireland based on the demographic
accounting equation:

    Net Migration = Population Change - Natural Change
    Net Migration = ΔPopulation - (Births - Deaths)

This module calculates migration by combining data from:
- Mid-year population estimates (population.py)
- Monthly birth registrations (births.py)
- Weekly death registrations (deaths.py)

The demographic accounting equation must hold for any geographic area:
    Population(t+1) = Population(t) + Births - Deaths + Net Migration

By rearranging, we can derive net migration from observed population changes
and vital events.

Data Source:
    This module combines three NISRA data sources:
    - **Population**: https://www.nisra.gov.uk/statistics/people-and-communities/population
    - **Births**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/births
    - **Deaths**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/deaths

Note on NISRA Migration Statistics:
    NISRA previously published long-term international migration statistics
    (last updated 2020). These are no longer maintained. This module provides
    an alternative approach by deriving migration from demographic components.

Update Frequency: Annual (follows mid-year population estimates schedule)
Geographic Coverage: Northern Ireland
Reference Period: Calendar year (aggregated from monthly/weekly vital events)

Example:
    >>> from bolster.data_sources.nisra import migration
    >>> # Get derived migration estimates
    >>> df = migration.get_latest_migration()
    >>> print(df.head())

    >>> # Validate demographic accounting equation
    >>> is_valid = migration.validate_demographic_equation(df)
    >>> print(f"Data validation: {'PASS' if is_valid else 'FAIL'}")

    >>> # Get migration for specific year
    >>> df_2024 = migration.get_migration_by_year(df, 2024)
"""

import logging
from typing import Optional

import pandas as pd

from . import births, deaths, population
from ._base import NISRAValidationError

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
    annual = population_df[population_df["sex"] == "All persons"].groupby("year")["population"].sum().reset_index()

    return annual


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
    migration_df = derive_migration(pop_df, births_df, deaths_df)

    return migration_df


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
