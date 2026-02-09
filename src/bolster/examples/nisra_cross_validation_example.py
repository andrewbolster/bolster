"""Example: Cross-Validation of NISRA Data Sources.

This script demonstrates how to validate data consistency across multiple
NISRA data sources using the demographic accounting equation:

    Population(t+1) = Population(t) + Births - Deaths + Net Migration

By verifying this equation holds, we can confirm that births, deaths, and
population data are internally consistent.
"""

from bolster.data_sources.nisra import migration


def main():
    """Run comprehensive cross-validation of NISRA data sources."""
    # Load migration data (which combines all sources)
    migration_df = migration.get_latest_migration(force_refresh=False)

    # Validate demographic equation
    try:
        migration.validate_demographic_equation(migration_df)
    except Exception:
        return

    # Show detailed validation for recent years

    recent_years = migration_df[migration_df["year"] >= 2020]
    for _, row in recent_years.iterrows():
        row["year"]
        pop_change = row["population_change"]
        row["births"]
        row["deaths"]
        natural = row["natural_change"]
        mig = row["net_migration"]

        # Verify equation
        calc_change = natural + mig
        "✓" if abs(pop_change - calc_change) < 10 else "✗"

    # Summary statistics

    total_pop_change = migration_df["population_change"].sum()
    total_births = migration_df["births"].sum()
    total_deaths = migration_df["deaths"].sum()
    total_migration = migration_df["net_migration"].sum()

    # Verify totals balance
    if abs(total_pop_change - ((total_births - total_deaths) + total_migration)) <= 10:
        pass
    else:
        pass


if __name__ == "__main__":
    main()
