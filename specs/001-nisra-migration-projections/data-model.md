# Data Model: NISRA Migration and Population Projections

**Feature**: 001-nisra-migration-projections\
**Date**: 2026-02-15\
**Status**: Phase 1 - Design Complete

## Overview

This feature introduces three primary data entities: Official Migration Estimates, Population Projections, and Migration Validation Results. All entities are represented as pandas DataFrames following the existing bolster project patterns for NISRA data sources.

## Entity Schemas

### Entity 1: Official Migration Estimate

**Purpose**: Annual long-term international migration flows for Northern Ireland from official NISRA statistics

**Data Structure**:

| Column | Type | Description | Constraints |
|--------|------|-------------|-------------|
| `year` | int | Calendar year (e.g., 2022) | >= 2000 |
| `immigration` | int | Number of people immigrating to NI | >= 0 |
| `emigration` | int | Number of people emigrating from NI | >= 0 |
| `net_migration` | int | Net migration (immigration - emigration) | immigration - emigration |
| `date` | pd.Timestamp | Reference date (typically June 30 or Dec 31) | Non-null |

**Validation Rules**:

1. **Arithmetic consistency**: `net_migration` must equal `immigration - emigration` for all rows
1. **Non-negative flows**: `immigration` and `emigration` must be >= 0
1. **Realistic year range**: `year` must be >= 2000 (lower bound for available data)
1. **No missing values**: All columns required (no NaN values)
1. **Unique years**: Each year should appear exactly once

**Sample Data**:

```python
   year  immigration  emigration  net_migration       date
0  2010        20000       15000           5000 2010-12-31
1  2011        22000       14000           8000 2011-12-31
2  2012        19000       16000           3000 2012-12-31
```

**Relationships**:

- **Comparable to**: Derived migration estimates from `migration.py` (same year)
- **Context from**: Population estimates from `population.py` (for calculating migration rates)

**Data Source**: NISRA long-term international migration publications

______________________________________________________________________

### Entity 2: Population Projection

**Purpose**: Forecasted future population for Northern Ireland with demographic breakdowns

**Data Structure**:

| Column | Type | Description | Constraints |
|--------|------|-------------|-------------|
| `year` | int | Projection year (e.g., 2030) | >= base_year, \<= horizon |
| `base_year` | int | Base year for projections (e.g., 2022) | Fixed for publication |
| `age_group` | str | Age band (e.g., "00-04", "05-09", "90+") | Standard format |
| `sex` | str | Sex category | "Male", "Female", "All persons" |
| `area` | str | Geographic area | Valid NI geography |
| `population` | int | Projected population count | >= 0 |
| `variant` | str (optional) | Projection variant | "principal", "high", "low" |

**Validation Rules**:

1. **Year bounds**: `base_year` \<= `year` \<= projection horizon (e.g., 2050)
1. **Non-negative population**: `population` >= 0 for all rows
1. **Sex totals**: For each year/age/area, "All persons" = Male + Female (within rounding tolerance)
1. **Age group format**: Must follow pattern "XX-XX" or "XX+" (e.g., "00-04", "90+")
1. **Valid sex values**: Must normalize to \["Male", "Female", "All persons"\]
1. **Known geographies**: `area` must match recognized NI geographic areas
1. **Complete coverage**: Each projection year should have full age/sex breakdown

**Sample Data**:

```python
   year  base_year age_group     sex              area  population   variant
0  2030       2022     00-04    Male  Northern Ireland       60000 principal
1  2030       2022     00-04  Female  Northern Ireland       57000 principal
2  2030       2022     00-04  All persons Northern Ireland  117000 principal
3  2030       2022     05-09    Male  Northern Ireland       62000 principal
```

**Relationships**:

- **Extends**: Historical population estimates from `population.py` (creates continuous timeline)
- **Consistent with**: Same age_group and area categorizations as population.py
- **Future-looking**: Projections start from base_year and extend forward

**Data Source**: NISRA population projections publications (e.g., 2022-based)

______________________________________________________________________

### Entity 3: Migration Validation Result

**Purpose**: Cross-validation comparison between official and derived migration estimates

**Data Structure**:

| Column | Type | Description | Constraints |
|--------|------|-------------|-------------|
| `year` | int | Year being compared | In both datasets |
| `official_net_migration` | int | Official NISRA estimate | From Entity 1 |
| `derived_net_migration` | int | Derived from demographic equation | From migration.py |
| `absolute_difference` | int | Abs difference between estimates | abs(derived - official) |
| `percent_difference` | float | Percentage difference | abs(derived - official) / official * 100 |
| `exceeds_threshold` | bool | Flags significant discrepancies | abs_diff > threshold |

**Validation Rules**:

1. **Year overlap**: `year` must exist in both official and derived datasets
1. **Percentage calculation**: `percent_difference` = `abs(derived - official) / official * 100`
1. **Threshold flagging**: `exceeds_threshold` = True if `absolute_difference` > user-specified threshold
1. **No missing values**: All columns required (no NaN values)
1. **Sorted by year**: Results typically sorted chronologically

**Sample Data**:

```python
   year  official_net_migration  derived_net_migration  absolute_difference  percent_difference  exceeds_threshold
0  2010                    5000                   4800                  200                 4.0              False
1  2011                    8000                   7500                  500                 6.3              False
2  2012                    3000                   4200                 1200                40.0               True
```

**Relationships**:

- **Compares**: Official migration (Entity 1) with derived migration (`migration.py`)
- **Quality assessment**: Helps users understand reliability of demographic equation approach
- **Diagnostic tool**: Identifies years with measurement issues or data quality concerns

**Data Source**: Computed by merging official and derived migration DataFrames

______________________________________________________________________

## Data Flow Diagram

```
┌─────────────────────────────┐
│  NISRA Mother Pages         │
│  (Web Scraping)             │
└─────────┬───────────────────┘
          │
          ├──────────────────────────────────┐
          │                                  │
          ▼                                  ▼
┌─────────────────────┐          ┌─────────────────────┐
│ Migration Excel     │          │ Projections Excel   │
│ File Download       │          │ File Download       │
└─────────┬───────────┘          └──────────┬──────────┘
          │                                  │
          ▼                                  ▼
┌─────────────────────┐          ┌─────────────────────┐
│ parse_migration_    │          │ parse_projections_  │
│ file()              │          │ file()              │
└─────────┬───────────┘          └──────────┬──────────┘
          │                                  │
          ▼                                  ▼
┌─────────────────────┐          ┌─────────────────────┐
│ Entity 1:           │          │ Entity 2:           │
│ Official Migration  │          │ Population          │
│ DataFrame           │          │ Projections         │
└─────────┬───────────┘          │ DataFrame           │
          │                      └─────────────────────┘
          │
          ├──────────────────┐
          │                  │
          ▼                  ▼
┌─────────────────┐   ┌─────────────────────┐
│ validation      │   │ Derived Migration   │
│ functions       │   │ (migration.py)      │
└─────────────────┘   └──────────┬──────────┘
                                 │
                                 │
          ┌──────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│ compare_official_vs_derived()   │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│ Entity 3:                       │
│ Migration Validation Result     │
│ DataFrame                       │
└─────────────────────────────────┘
```

## Validation Strategy

### Entity 1 Validation (Official Migration)

**Function**: `validate_migration_arithmetic(df) -> bool`

**Checks**:

- Net migration arithmetic: `net_migration == immigration - emigration`
- Non-negative values: `immigration >= 0` and `emigration >= 0`
- No missing values in required columns
- Year range is realistic (>= 2000)

**Raises**: `NISRAValidationError` if any check fails

______________________________________________________________________

### Entity 2 Validation (Population Projections)

**Function 1**: `validate_projections_totals(df) -> bool`

**Checks**:

- Sex totals: For each year/age/area, "All persons" == Male + Female
- Tolerance: Allow small rounding differences (\< 5 people)

**Function 2**: `validate_projection_coverage(df) -> bool`

**Checks**:

- Year range: Projections cover base_year to horizon year
- Completeness: All expected age groups present for each year
- No missing demographics: Each year has full sex breakdown

**Raises**: `NISRAValidationError` if any check fails

______________________________________________________________________

### Entity 3 Validation (Cross-Validation Results)

**Function**: `compare_official_vs_derived(official_df, derived_df, threshold) -> pd.DataFrame`

**Checks**:

- Year alignment: Only compares years present in both datasets
- Calculation accuracy: Differences computed correctly
- Threshold application: Flags applied consistently

**Returns**: DataFrame (Entity 3) rather than bool

______________________________________________________________________

## Data Transformation Notes

### Migration Data Transformations

1. **Date parsing**: Convert Excel date columns to `pd.Timestamp`
1. **Integer conversion**: Ensure immigration/emigration/net_migration are int64
1. **Year extraction**: If not present, extract from date column
1. **Sorting**: Sort by year chronologically

### Projection Data Transformations

1. **Wide to long format**: If projections are in wide format (years as columns), melt to long format
1. **Sex normalization**: Standardize "Persons" → "All persons"
1. **Age group standardization**: Ensure consistent format ("00-04" not "0-4")
1. **Base year addition**: Add `base_year` column if not present in source data
1. **Filtering**: Apply area/year filters as requested by user

### Cross-Validation Transformations

1. **Year-based merge**: Inner join on year column
1. **Difference calculations**: Absolute and percentage differences
1. **Threshold flagging**: Boolean column for exceeds_threshold
1. **Sorting**: Sort by year for readability

______________________________________________________________________

## Extension Points

### Future Enhancements

1. **Migration breakdowns**: If NISRA publishes migration by age/sex, extend Entity 1 schema
1. **Projection variants**: Support multiple scenarios (high/low fertility/mortality)
1. **Geographic variants**: Support projections for constituencies, health trusts
1. **Confidence intervals**: If projection files include uncertainty bounds, add CI columns
1. **Time series validation**: Check for unexpectedly large year-over-year changes

### Backward Compatibility

- Schema additions should be additive (new optional columns)
- Existing column names and types should remain stable
- Validation functions should gracefully handle missing optional columns
- Breaking changes require major version bump and migration guide

______________________________________________________________________

## Summary

This data model provides three complementary views of Northern Ireland demographic data:

1. **Official Migration**: Authoritative source for migration flows
1. **Population Projections**: Forward-looking demographic forecasts
1. **Cross-Validation**: Quality assessment tool for derived estimates

All entities follow bolster project conventions:

- pandas DataFrame representation
- Type-annotated schemas
- Validation functions that raise exceptions on failure
- Integration with existing NISRA modules (migration.py, population.py)
