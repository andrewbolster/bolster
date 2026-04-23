# Quickstart Guide: NISRA Migration and Population Projections

**Feature**: 001-nisra-migration-projections\
**Date**: 2026-02-15

## Installation

This feature is part of the bolster library. Ensure you have the latest version:

```bash
cd /path/to/bolster
uv sync
```

## Quick Examples

### 1. Access Official Migration Statistics

```python
from bolster.data_sources.nisra import migration_official

# Get all official migration data
df = migration_official.get_latest_migration_official()

print(df.head())
# Output:
#    year  immigration  emigration  net_migration       date
# 0  2010        20000       15000           5000 2010-12-31
# 1  2011        22000       14000           8000 2011-12-31
# 2  2012        19000       16000           3000 2012-12-31

# Get summary of migration trends
print(f"Years covered: {df['year'].min()} to {df['year'].max()}")
print(f"Average net migration: {df['net_migration'].mean():,.0f}")

# Validate data integrity
is_valid = migration_official.validate_migration_arithmetic(df)
print(f"Data validation: {'PASS' if is_valid else 'FAIL'}")
```

### 2. Access Population Projections

```python
from bolster.data_sources.nisra import population_projections

# Get all projections for Northern Ireland
df = population_projections.get_latest_projections(area="Northern Ireland")

print(df.head())
# Output:
#    year  base_year age_group     sex              area  population   variant
# 0  2023       2022     00-04    Male  Northern Ireland       60000 principal
# 1  2023       2022     00-04  Female  Northern Ireland       57000 principal
# 2  2023       2022     00-04  All persons Northern Ireland  117000 principal

# Get projections for a specific year
df_2030 = population_projections.get_latest_projections(area="Northern Ireland", start_year=2030, end_year=2030)

# Calculate total projected population for 2030
total_2030 = df_2030[df_2030["sex"] == "All persons"]["population"].sum()
print(f"Projected NI population in 2030: {total_2030:,}")
```

### 3. Cross-Validate Migration Estimates

```python
from bolster.data_sources.nisra import migration_official, migration

# Load both official and derived data
official_df = migration_official.get_latest_migration_official()
derived_df = migration.get_latest_migration()

# Compare estimates
comparison = migration_official.compare_official_vs_derived(
    official_df,
    derived_df,
    threshold=1000,  # Flag differences > 1000 people
)

# Show discrepancies
print(comparison[comparison["exceeds_threshold"]])
# Output:
#    year  official_net_migration  derived_net_migration  absolute_difference  percent_difference  exceeds_threshold
# 5  2015                   12000                  10500                 1500               12.5%               True

# Calculate overall accuracy
mean_abs_error = comparison["absolute_difference"].mean()
mean_pct_error = comparison["percent_difference"].mean()
print(f"Mean absolute error: {mean_abs_error:,.0f} people")
print(f"Mean percentage error: {mean_pct_error:.1f}%")
```

## Common Use Cases

### Use Case 1: Analyze Migration Trends

```python
from bolster.data_sources.nisra import migration_official
import matplotlib.pyplot as plt

# Get migration data
df = migration_official.get_latest_migration_official()

# Filter to recent decade
df_recent = df[df["year"] >= 2010]

# Plot immigration and emigration flows
plt.figure(figsize=(10, 6))
plt.plot(df_recent["year"], df_recent["immigration"], label="Immigration", marker="o")
plt.plot(df_recent["year"], df_recent["emigration"], label="Emigration", marker="s")
plt.plot(df_recent["year"], df_recent["net_migration"], label="Net Migration", marker="^", linewidth=2)
plt.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
plt.xlabel("Year")
plt.ylabel("People")
plt.title("Northern Ireland Migration Trends")
plt.legend()
plt.grid(alpha=0.3)
plt.tight_layout()
plt.show()
```

### Use Case 2: Forecast Age Distribution

```python
from bolster.data_sources.nisra import population_projections
import pandas as pd

# Get projections for 2030
df_2030 = population_projections.get_latest_projections(area="Northern Ireland", start_year=2030, end_year=2030)

# Filter to totals (All persons)
df_totals = df_2030[df_2030["sex"] == "All persons"]

# Calculate age group percentages
total_pop = df_totals["population"].sum()
df_totals["percentage"] = (df_totals["population"] / total_pop * 100).round(1)

# Show age distribution
print("Projected Age Distribution for NI in 2030:")
print(df_totals[["age_group", "population", "percentage"]].sort_values("age_group"))
```

### Use Case 3: Compare Projections with Historical Data

```python
from bolster.data_sources.nisra import population, population_projections
import pandas as pd

# Get historical population
historical = population.get_latest_population(area="Northern Ireland")
historical = historical[historical["sex"] == "All persons"]
historical_total = historical.groupby("year")["population"].sum().reset_index()

# Get projections
projections = population_projections.get_latest_projections(area="Northern Ireland")
projections = projections[projections["sex"] == "All persons"]
projection_total = projections.groupby("year")["population"].sum().reset_index()

# Combine for continuous timeline
historical_total["source"] = "Historical"
projection_total["source"] = "Projected"
combined = pd.concat([historical_total, projection_total], ignore_index=True)

print(combined.tail(10))
# Shows transition from historical estimates to projections
```

### Use Case 4: Validate Demographic Equation with Official Data

```python
from bolster.data_sources.nisra import migration_official, migration

# Load both datasets
official = migration_official.get_latest_migration_official()
derived = migration.get_latest_migration()

# Compare side-by-side for specific years
comparison = migration_official.compare_official_vs_derived(official, derived)

# Show years where derived estimate was accurate
accurate = comparison[comparison["percent_difference"] < 5.0]
print(f"Years with <5% error: {len(accurate)} / {len(comparison)}")
print(f"Accuracy rate: {len(accurate) / len(comparison) * 100:.1f}%")

# Identify years with large discrepancies for investigation
issues = comparison[comparison["exceeds_threshold"]]
if not issues.empty:
    print("\nYears requiring investigation:")
    print(issues[["year", "official_net_migration", "derived_net_migration", "percent_difference"]])
```

## CLI Usage (Optional Commands)

If CLI commands are implemented, you can use them for quick data exploration:

### Migration Comparison CLI

```bash
# Compare official vs derived migration for recent decade
uv run bolster nisra migration-compare --start-year 2010 --threshold 500

# Output:
# ┌──────┬────────────┬──────────┬────────────┬────────────┐
# │ Year │ Official   │ Derived  │ Difference │ % Error    │
# ├──────┼────────────┼──────────┼────────────┼────────────┤
# │ 2010 │ +5,000     │ +4,800   │ -200       │ 4.0%       │
# │ 2011 │ +8,000     │ +7,500   │ -500       │ 6.3% ⚠️    │
# │ 2012 │ +3,000     │ +4,200   │ +1,200     │ 40.0% ❌   │
# └──────┴────────────┴──────────┴────────────┴────────────┘

# Compare specific year range
uv run bolster nisra migration-compare --start-year 2015 --end-year 2020
```

### Population Projections CLI

```bash
# Query population projections for 2030
uv run bolster nisra projections --year 2030 --area "Northern Ireland"

# Output:
# Northern Ireland Population Projection for 2030:
# ┌───────────┬──────────┬────────┬────────────┐
# │ Age Group │ Male     │ Female │ Total      │
# ├───────────┼──────────┼────────┼────────────┤
# │ 00-04     │ 60,000   │ 57,000 │ 117,000    │
# │ 05-09     │ 62,000   │ 59,000 │ 121,000    │
# │ ...       │ ...      │ ...    │ ...        │
# │ Total     │ 950,000  │ 970,000│ 1,920,000  │
# └───────────┴──────────┴────────┴────────────┘

# Get projections for a range
uv run bolster nisra projections --start-year 2025 --end-year 2035 --area "Northern Ireland"

# Export to CSV for external analysis
uv run bolster nisra projections --year 2030 --format csv > projections_2030.csv
```

## Advanced Usage

### Custom Validation Thresholds

```python
from bolster.data_sources.nisra import migration_official, migration

official = migration_official.get_latest_migration_official()
derived = migration.get_latest_migration()

# Use stricter threshold for high-quality comparison
strict_comparison = migration_official.compare_official_vs_derived(
    official,
    derived,
    threshold=500,  # Flag differences > 500 people
)

# Count discrepancies at different threshold levels
thresholds = [500, 1000, 2000]
for thresh in thresholds:
    count = (strict_comparison["absolute_difference"] > thresh).sum()
    print(f"Discrepancies > {thresh}: {count} years")
```

### Filtering Projections by Multiple Criteria

```python
from bolster.data_sources.nisra import population_projections

# Get projections for working-age population in 2030s
df = population_projections.get_latest_projections(area="Northern Ireland", start_year=2030, end_year=2039)

# Filter to working-age groups (15-64)
working_age_groups = ["15-19", "20-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54", "55-59", "60-64"]
df_working = df[df["age_group"].isin(working_age_groups)]
df_working = df_working[df_working["sex"] == "All persons"]

# Calculate working-age population by year
working_age_by_year = df_working.groupby("year")["population"].sum()
print("Projected Working-Age Population:")
print(working_age_by_year)
```

### Force Refresh Data

```python
from bolster.data_sources.nisra import migration_official, population_projections

# Force download fresh data (bypass cache)
migration_df = migration_official.get_latest_migration_official(force_refresh=True)
projections_df = population_projections.get_latest_projections(force_refresh=True)

print("Data refreshed from NISRA website")
```

## Troubleshooting

### Issue: Data not found

**Error**: `NISRADataNotFoundError: Could not find migration publication`

**Solution**:

- Check internet connection
- Verify NISRA website is accessible: https://www.nisra.gov.uk
- Try with `force_refresh=True` to bypass cache
- Check if NISRA has changed their website structure (file an issue if so)

### Issue: Validation fails

**Error**: `NISRAValidationError: Net migration arithmetic doesn't match`

**Solution**:

- This indicates a data quality issue in the NISRA publication
- Check the raw Excel file for errors
- Report the issue with specific year/values to NISRA
- Use validation to identify problematic years: `validate_migration_arithmetic(df)`

### Issue: Missing years in cross-validation

**Warning**: "Only X years overlap between official and derived data"

**Explanation**:

- Official migration data may not cover the same time period as derived estimates
- Check `official_df['year'].min()` and `derived_df['year'].min()` to see coverage
- This is expected if official data is discontinued or not yet published for recent years

## Next Steps

- Read the full module documentation: `help(migration_official)`, `help(population_projections)`
- Explore related modules: `nisra.population`, `nisra.migration`, `nisra.births`, `nisra.deaths`
- Check the README for full list of available NISRA data sources
- Contribute improvements or report issues on GitHub

## API Reference Summary

### migration_official Module

- `get_latest_migration_official(force_refresh=False) -> pd.DataFrame`
- `validate_migration_arithmetic(df) -> bool`
- `compare_official_vs_derived(official_df, derived_df, threshold=1000) -> pd.DataFrame`

### population_projections Module

- `get_latest_projections(area=None, start_year=None, end_year=None, force_refresh=False) -> pd.DataFrame`
- `validate_projections_totals(df) -> bool`
- `validate_projection_coverage(df) -> bool`

See contracts/ directory for full API specifications.
