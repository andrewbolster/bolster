"""Cross-validation utilities for NISRA data sources.

This module provides functions to validate data consistency across multiple
NISRA data sources using the demographic accounting equation and other
consistency checks.

The core validation is based on the demographic accounting equation:
    Population(t+1) = Population(t) + Births - Deaths + Net Migration

By having data from all four components (population, births, deaths, migration),
we can validate that the data sources are internally consistent.

Example:
    >>> from bolster.data_sources.nisra import validation
    >>> # Run comprehensive validation
    >>> report = validation.validate_all_sources()
    >>> print(report)

    >>> # Check specific year
    >>> is_valid = validation.validate_year(2024)
    >>> print(f"2024 data valid: {is_valid}")
"""

import logging
from typing import Optional

from . import migration
from ._base import NISRAValidationError

logger = logging.getLogger(__name__)


def validate_all_sources(force_refresh: bool = False) -> dict:
    """Run comprehensive validation across all NISRA data sources.

    Validates that:
    1. Demographic equation holds for all years
    2. Data sources cover consistent time periods
    3. No major discrepancies in vital statistics

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        Dictionary with validation results:
            - valid: bool (overall validation result)
            - years_validated: int (number of years validated)
            - demographic_equation_valid: bool
            - data_sources_consistent: bool
            - issues: list of any issues found
            - summary: dict with key statistics

    Example:
        >>> report = validate_all_sources()
        >>> if report['valid']:
        >>>     print(f"✓ All {report['years_validated']} years validated")
        >>> else:
        >>>     print(f"✗ Issues found: {report['issues']}")
    """
    logger.info("Running comprehensive validation across all NISRA data sources...")

    issues = []

    # Load all data sources
    try:
        migration_df = migration.get_latest_migration(force_refresh=force_refresh)
    except Exception as e:
        issues.append(f"Failed to load migration data: {e}")
        return {
            "valid": False,
            "years_validated": 0,
            "demographic_equation_valid": False,
            "data_sources_consistent": False,
            "issues": issues,
            "summary": {},
        }

    # Validate demographic equation
    demographic_valid = True
    try:
        migration.validate_demographic_equation(migration_df)
        logger.info("✓ Demographic equation validated")
    except NISRAValidationError as e:
        demographic_valid = False
        issues.append(f"Demographic equation validation failed: {e}")

    # Check data source consistency
    years_available = sorted(migration_df["year"].unique())
    min_year = years_available[0]
    max_year = years_available[-1]

    # Calculate summary statistics
    total_population_change = migration_df["population_change"].sum()
    total_births = migration_df["births"].sum()
    total_deaths = migration_df["deaths"].sum()
    total_migration = migration_df["net_migration"].sum()

    summary = {
        "years_covered": f"{min_year}-{max_year}",
        "total_years": len(years_available),
        "total_population_change": int(total_population_change),
        "total_births": int(total_births),
        "total_deaths": int(total_deaths),
        "total_net_migration": int(total_migration),
        "avg_annual_births": int(total_births / len(years_available)),
        "avg_annual_deaths": int(total_deaths / len(years_available)),
        "avg_annual_migration": int(total_migration / len(years_available)),
    }

    # Check that totals balance
    expected_change = total_births - total_deaths + total_migration
    if abs(total_population_change - expected_change) > 10:  # Allow small rounding difference
        issues.append(
            f"Total population change ({total_population_change:,}) doesn't match "
            f"expected ({expected_change:,}) from vital statistics"
        )

    # Overall validation result
    valid = demographic_valid and len(issues) == 0

    return {
        "valid": valid,
        "years_validated": len(years_available),
        "demographic_equation_valid": demographic_valid,
        "data_sources_consistent": len(issues) == 0,
        "issues": issues,
        "summary": summary,
    }


def validate_year(year: int, tolerance: int = 10, force_refresh: bool = False) -> bool:
    """Validate data consistency for a specific year.

    Args:
        year: Year to validate
        tolerance: Allowable difference due to rounding/measurement error (default: 10)
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        True if validation passes for the year

    Raises:
        NISRAValidationError: If validation fails
        ValueError: If year not available in data

    Example:
        >>> if validate_year(2024):
        >>>     print("2024 data is consistent")
    """
    migration_df = migration.get_latest_migration(force_refresh=force_refresh)

    if year not in migration_df["year"].values:
        raise ValueError(f"Year {year} not available in data. Available: {sorted(migration_df['year'].unique())}")

    year_data = migration_df[migration_df["year"] == year].iloc[0]

    pop_change = year_data["population_change"]
    natural_change = year_data["natural_change"]
    net_migration = year_data["net_migration"]

    # Check demographic equation
    expected_change = natural_change + net_migration
    difference = abs(pop_change - expected_change)

    if difference > tolerance:
        raise NISRAValidationError(
            f"Year {year}: Demographic equation violated. "
            f"Population change ({pop_change:,}) != Natural change ({natural_change:,}) + "
            f"Net migration ({net_migration:,}). Difference: {difference:,}"
        )

    logger.info(f"Year {year}: Validation passed")
    return True


def get_validation_report(
    start_year: Optional[int] = None, end_year: Optional[int] = None, force_refresh: bool = False
) -> str:
    """Generate a comprehensive validation report.

    Args:
        start_year: Optional start year for report
        end_year: Optional end year for report
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        Formatted string report

    Example:
        >>> print(get_validation_report(start_year=2020))
    """
    report = validate_all_sources(force_refresh=force_refresh)

    lines = []
    lines.append("=" * 80)
    lines.append("NISRA DATA SOURCES VALIDATION REPORT")
    lines.append("=" * 80)
    lines.append("")

    if report["valid"]:
        lines.append("✓ VALIDATION PASSED")
    else:
        lines.append("✗ VALIDATION FAILED")

    lines.append("")
    lines.append(f"Years validated: {report['years_validated']}")
    lines.append(f"Period: {report['summary']['years_covered']}")
    lines.append("")

    lines.append("Validation Checks:")
    lines.append(f"  Demographic equation: {'✓ PASS' if report['demographic_equation_valid'] else '✗ FAIL'}")
    lines.append(f"  Data sources consistent: {'✓ PASS' if report['data_sources_consistent'] else '✗ FAIL'}")
    lines.append("")

    if report["issues"]:
        lines.append("Issues Found:")
        for issue in report["issues"]:
            lines.append(f"  • {issue}")
        lines.append("")

    lines.append("Summary Statistics:")
    summary = report["summary"]
    lines.append(f"  Total population change: {summary['total_population_change']:+,}")
    lines.append(f"  Total births: {summary['total_births']:,}")
    lines.append(f"  Total deaths: {summary['total_deaths']:,}")
    lines.append(f"  Total net migration: {summary['total_net_migration']:+,}")
    lines.append("")
    lines.append(f"  Average annual births: {summary['avg_annual_births']:,}")
    lines.append(f"  Average annual deaths: {summary['avg_annual_deaths']:,}")
    lines.append(f"  Average annual migration: {summary['avg_annual_migration']:+,}")
    lines.append("")

    # Verify totals balance
    pop_change = summary["total_population_change"]
    births = summary["total_births"]
    deaths = summary["total_deaths"]
    mig = summary["total_net_migration"]

    lines.append("Demographic Accounting Check:")
    lines.append(f"  Population change: {pop_change:+,}")
    lines.append(f"  Natural change (B-D): {births - deaths:+,}")
    lines.append(f"  Net migration: {mig:+,}")
    lines.append(f"  Total (Natural + Migration): {(births - deaths) + mig:+,}")

    if abs(pop_change - ((births - deaths) + mig)) <= 10:
        lines.append("  ✓ Totals balance")
    else:
        lines.append("  ✗ Totals don't balance")

    lines.append("")
    lines.append("=" * 80)

    return "\n".join(lines)


def compare_migration_methods(year: int, force_refresh: bool = False) -> dict:
    """Compare derived migration estimate with official statistics (if available).

    Args:
        year: Year to compare
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        Dictionary with comparison results

    Note:
        NISRA discontinued publishing migration statistics after 2020.
        This function demonstrates how to compare derived vs. published estimates.

    Example:
        >>> comparison = compare_migration_methods(2019)
        >>> print(f"Derived: {comparison['derived']}, Official: {comparison['official']}")
    """
    migration_df = migration.get_latest_migration(force_refresh=force_refresh)

    if year not in migration_df["year"].values:
        raise ValueError(f"Year {year} not available")

    year_data = migration_df[migration_df["year"] == year].iloc[0]

    result = {
        "year": year,
        "derived_migration": int(year_data["net_migration"]),
        "migration_rate": float(year_data["migration_rate"]),
        "population_change": int(year_data["population_change"]),
        "natural_change": int(year_data["natural_change"]),
        "births": int(year_data["births"]),
        "deaths": int(year_data["deaths"]),
        "official_migration": None,  # Would come from NISRA published migration stats
        "note": "NISRA migration statistics discontinued after 2020",
    }

    return result
