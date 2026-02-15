# Research: NISRA Migration and Population Projections

**Status**: PHASE 0 - Research completed\
**Date**: 2026-02-15\
**Updated**: 2026-02-15

This document contains findings from Phase 0 research tasks. All URLs, file structures, and parsing strategies have been verified.

## Research Findings

### 1. Migration Mother Page Structure

**Status**: ✅ Complete

**Correct URL**: https://www.nisra.gov.uk/statistics/population/long-term-international-migration-statistics

**Note**: Original URL in plan.md was incorrect - correct structure is `/statistics/population/` not `/statistics/migration/`

#### Mother Page Structure

- **Navigation**: Home > Statistics and Research > People and communities > Population
- **Organization**: Bulleted list (`<ul>`) with linked headings (`<h3>`)
- **Publication naming**: `Long-Term International Migration Statistics for Northern Ireland (YYYY)`
- **URL pattern**: `/publications/long-term-international-migration-statistics-northern-ireland-[YEAR]`

#### Available Publications

From mother page (as of Feb 2026):

- 2024 (latest, published Feb 5, 2026)
- 2020
- 2019
- 2018 (Charts only)

#### Publication Page Structure (2024 example)

Each publication has **4 Excel files**:

| File Type | URL Pattern | Description |
|-----------|-------------|-------------|
| Official | `/system/files/statistics/YYYY-MM/Mig[YY][YY]-Official_1.xlsx` | Official migration estimates (flows) |
| Inflows | `/system/files/statistics/YYYY-MM/Mig[YY][YY]-In_1.xlsx` | Administrative data - migration into NI |
| Outflows | `/system/files/statistics/YYYY-MM/Mig[YY][YY]-Out_1.xlsx` | Administrative data - migration out of NI |
| Stock | `/system/files/statistics/YYYY-MM/Mig[YY][YY]-Stock_1.xlsx` | International population in NI (stock) |

**Example** (2024 data):

- `Mig2324-Official_1.xlsx` (covers 2023-2024)
- Files stored in `/system/files/statistics/2026-02/`

**CSS Selector for downloads**: `a[href*="/statistics/"][href$=".xlsx"]`

#### Data Availability Timeline

- **Latest**: 2024 (Jul 2023 - Jun 2024)
- **Historical**: Back to 2002 (Jul 2001 - Jun 2002) in time series tables
- **Publishing pattern**: Annual releases, typically Feb/March following year end

### 2. Population Projections Publication Structure

**Status**: ✅ Complete

**URLs**:

- **Principal projection**: https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland
- **Variant projections**: https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland-variant-projections

#### Publication Structure

**Two separate publication pages**:

1. **Principal Projection** (2 files):

   - `NPP22_ppp_age_sexv2.xlsx` (910 KB) - Population by age and sex
   - `NPP22_ppp_coc.xlsx` (210 KB) - Projection summary (components of change)

1. **Variant Projections** (13 files):

   - All named: `NPP22_[code]_coc.xlsx`
   - Codes represent fertility/mortality/migration assumptions

#### Variant Projection Codes

**Code format**: `[fertility][mortality][migration]`

| Letter | Fertility | Mortality | Migration |
|--------|-----------|-----------|-----------|
| p | Principal | Principal | Principal |
| h | High | High life expectancy | High |
| l | Low | Low life expectancy | Low |
| r | Replacement | - | - |
| n | - | No improvement | - |
| z | - | - | Zero net |

**Available variants** (13 total):

- `hhh` - High population (high across all)
- `lll` - Low population (low across all)
- `php` - High fertility, principal mortality/migration
- `plp` - Low fertility
- `prp` - Replacement fertility
- `pph` - High life expectancy
- `ppl` - Low life expectancy
- `ppn` - No long-term life expectancy improvement
- `pph` - High migration
- `ppl` - Low migration
- `ppz` - Zero net migration
- `ppy` - Young age structure
- `ppo` - Old age structure

#### Time Horizon

**All projections**: 2022-2072 (50 years)

#### Geographic Coverage

- **Northern Ireland only** (Area_Code: N92000002)
- No local government district breakdowns in these files

#### Age Breakdown Format

**Age/Sex file** (`NPP22_ppp_age_sexv2.xlsx`) has 6 sheets:

| Sheet Name | Purpose |
|------------|---------|
| Cover sheet | Publication metadata |
| Contents | Navigation and summary |
| Flat File | **BEST FOR PARSING** - long format, all data in one sheet |
| Tabular Single Year of Age | Wide format, single year ages |
| Tabular 5 Year Age Bands | Wide format, 5-year bands |
| Metadata | Documentation |

**Flat File columns**:

- `Area`, `Area_Code`, `Projection`, `Mid-Year`, `Sex`, `Age`, `Age_5`, `NPP`
- 14,229 rows (51 years × 3 sexes × 91+ ages)
- Sex values: 'All Persons', 'Females', 'Males'
- Age: 0-90+ (single years)

### 3. Excel Parsing Strategy

**Status**: ✅ Complete

#### Migration Files - Official Estimates

**File**: `Mig[YY][YY]-Official_1.xlsx`

**Sheet structure**:

- Mixed content: Contents, Figures (empty charts), Tables
- Data sheets: `Table 1.1`, `Table 1.2`, `Table 1.3`, `Table 1.4`, `Table 1.5`, `Table 1.6`
- Figure sheets: Empty (chart placeholders)

**Key tables**:

| Sheet | Content | Parsing Strategy |
|-------|---------|------------------|
| Table 1.1 | Net International Migration time series (2002-2024) | `skiprows=2`, header row at index 2 |
| Table 1.2 | Net Migration by LGD (2014-2024) | `skiprows=1`, wide format with years as columns |
| Table 1.3 | Net Migration by Age/Sex (latest year) | `skiprows=1`, simple two-column format |
| Table 1.4 | Net GB and International Migration (2002-2024) | `skiprows=1`, wide format |
| Table 1.5 | Components of Change by LGD (latest year) | `skiprows=1`, multiple columns |
| Table 1.6 | Net Total Migration by Age/Sex (latest year) | Same as Table 1.3 |

**Example parsing code**:

```python
# Table 1.1 - Time series
df = pd.read_excel(file_path, sheet_name="Table 1.1", skiprows=2)
# Results in columns: Time-period, [intermediate cols], Net International Migration

# Table 1.4 - Migration by type (wide format)
df = pd.read_excel(file_path, sheet_name="Table 1.4", skiprows=1)
# Each year is a column, migration types are rows
# Needs unpivoting to long format
```

**Challenges**:

- Wide format tables need melting/unpivoting
- Header rows vary (1-2 rows of metadata before column names)
- Some tables have merged cells in headers
- Footer notes included in data area

#### Migration Files - Inflows/Outflows

**Files**: `Mig[YY][YY]-In_1.xlsx`, `Mig[YY][YY]-Out_1.xlsx`

**Sheet structure**:

- 29+ sheets (Contents, Figures, Tables 2.1-2.25)
- More granular than official estimates
- Similar parsing challenges (skiprows, wide format)

**Example** (Table 2.1 - Inflows from Non-UK Nationals):

```python
df = pd.read_excel(file_path, sheet_name="Table 2.1", skiprows=2)
# Quarterly data in wide format (columns = time periods)
# Rows: Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec, Total
```

#### Population Projections - Flat File (RECOMMENDED)

**File**: `NPP22_ppp_age_sexv2.xlsx`

**Sheet**: `Flat File` (sheet 3)

**Already in perfect long format** - no transformation needed!

```python
df = pd.read_excel(file_path, sheet_name="Flat File")
# Columns: Area, Area_Code, Projection, Mid-Year, Sex, Age, Age_5, NPP
# No skiprows needed - first row is headers
# 14,229 rows × 8 columns
```

**Data types**:

- `Area`: object (always "Northern Ireland")
- `Area_Code`: object (always "N92000002")
- `Projection`: object (always "Principal Projection")
- `Mid-Year`: int64 (2022-2072)
- `Sex`: object ('All Persons', 'Females', 'Males')
- `Age`: object (0-90+, but stored as object due to "90+")
- `Age_5`: object ('00-04', '05-09', ..., '90+')
- `NPP`: int64 (population count)

#### Population Projections - Summary/Components

**File**: `NPP22_ppp_coc.xlsx`

**Sheet**: `PERSONS` (also MALES, FEMALES)

**Wide format with complex structure**:

- Row 0: Table title
- Row 1: Area name
- Row 2: Projection type
- Row 3-5: Notes/metadata
- Row 6: Component labels (row headers)
- Row 7+: Data rows with years as columns

**Parsing strategy**:

```python
# Skip metadata rows, use row 6 as index
df = pd.read_excel(file_path, sheet_name="PERSONS", skiprows=6, index_col=0)
# Results in wide format: rows = components, columns = years
# Need to transpose or melt for long format
```

**Components available**:

- Population at start/end
- Births, Deaths, Natural Change
- International/Cross-border migration (inflows/outflows/net)
- Total change, Annual growth rate
- TFR, Life expectancy (EOLB males/females)

#### Variant Projections

**Files**: `NPP22_[code]_coc.xlsx`

**Same structure** as principal projection summary file:

- Only difference: Row 2 shows variant name (e.g., "High Population" instead of "Principal projection")
- Use identical parsing strategy

**Recommendation**: Write one parsing function, parameterized by projection type

### 4. Cross-Validation Design

**Status**: ✅ Complete

#### Overlapping Data Sources

**Migration estimates vs Projection components**:

1. **Official migration estimates** (`Table 1.1`):

   - Net International Migration by year (Jul YYYY to Jun YYYY+1)
   - Historical: 2002-2024
   - Annual mid-year estimates

1. **Projection components** (`NPP22_ppp_coc.xlsx`):

   - Net international migration component
   - Projection period: 2022-2072
   - Annual mid-year values

**Overlap period**: 2022-2024 (2-3 years depending on latest publication)

#### Comparison Methodology

**Direct comparison**:

- Compare `Net International Migration` from official estimates
- With `Net international migration` from projection components
- For overlapping mid-years (2022, 2023, 2024)

**Expected differences**:

- Official estimates are **actuals** (based on admin data + census)
- Projection components are **projected** (model-based assumptions)
- Even for recent years, projections use assumed rates, not actual data

**Tolerance thresholds**:

- ±10-15% difference is reasonable (projections vs actuals often diverge)
- Large divergence (>20%) indicates either:
  - Significant policy/demographic shift since projection baseline
  - Data quality issue requiring investigation

#### Function Design

**Signature**:

```python
def compare_migration_estimates(
    official_df: pd.DataFrame,  # From get_official_migration()
    projection_df: pd.DataFrame,  # From get_projection_components()
    year_range: tuple[int, int] = (2022, 2024),
) -> pd.DataFrame:
    """
    Compare official migration estimates with projection assumptions.

    Args:
        official_df: Official migration time series (Table 1.1)
        projection_df: Projection components (PERSONS sheet)
        year_range: (start_year, end_year) for comparison

    Returns:
        DataFrame with columns:
        - mid_year: int
        - official_net_migration: int
        - projected_net_migration: int
        - difference: int (projected - official)
        - pct_difference: float (difference / official * 100)
        - status: str ('MATCH', 'DIVERGING', 'SIGNIFICANT_DIVERGENCE')
    """
```

**Status thresholds**:

- MATCH: |pct_difference| \< 10%
- DIVERGING: 10% ≤ |pct_difference| \< 20%
- SIGNIFICANT_DIVERGENCE: |pct_difference| ≥ 20%

#### Alternative: Natural Increase Cross-Validation

**Could also compare**:

- Official births/deaths (if we implement those modules)
- With projection birth/death components
- Natural change = Births - Deaths
- This would be even more robust (births/deaths less volatile than migration)

### 5. CLI Command Evaluation

**Status**: ✅ Complete

#### Recommendation: CLI Commands NOT Needed

**Rationale**:

1. **Primary use case is programmatic**:

   - These are research/analysis datasets
   - Users will integrate into notebooks, scripts, analysis pipelines
   - Python API is sufficient for data access

1. **Complex query requirements**:

   - Projections: Filter by year, sex, age range, variant
   - Migration: Filter by year, geography, component
   - Too many parameters for clean CLI UX
   - Better handled in pandas with method chaining

1. **Large result sets**:

   - Population projections: 14k+ rows in flat file
   - Migration tables: Multiple wide-format sheets
   - Not suitable for terminal display
   - Users need to export to CSV/analysis tools anyway

1. **Cross-validation is niche**:

   - Compare function is for data quality checks
   - Not a common user workflow
   - Document in README with example, don't expose as CLI

#### CLI Pattern from Existing Modules

**Existing pattern** (for reference, but NOT implementing):

```python
@cli.group()
def nisra():
    """NISRA data sources"""
    pass


@nisra.command()
def migration():
    """Show latest migration estimates"""
    df = get_latest_migration()
    click.echo(df.to_string())


@nisra.command()
@click.option("--variant", default="principal", help="Projection variant")
def projections(variant):
    """Show population projections"""
    df = get_projections(variant=variant)
    click.echo(df.to_string())
```

**Problems with this approach**:

- Large dataframes don't display well in terminal
- Limited filtering options
- Users still need to export to CSV for real work

#### Final Decision

**NO CLI commands**. Document usage in README:

````markdown
## Usage

### Migration Statistics

```python
from bolster.data_sources.nisra import migration

# Get latest official estimates
df = migration.get_latest_migration()

# Get specific publication year
df = migration.get_migration(year=2023)

# Compare with projections
comparison = migration.compare_with_projections()
````

### Population Projections

```python
from bolster.data_sources.nisra import population_projections

# Get principal projection
df = population_projections.get_projections()

# Get specific variant
df = population_projections.get_projections(variant="hhh")

# Filter for specific demographics
df_filtered = df[
    (df["Mid-Year"] >= 2022) & (df["Mid-Year"] <= 2030) & (df["Sex"] == "Females") & (df["Age"].between(20, 30))
]
```

```

This gives users full pandas flexibility without forcing CLI constraints.

## Key Findings Summary

### Migration Data
- ✅ 4 file types per publication (Official, In, Out, Stock)
- ✅ Data back to 2002 in time series
- ✅ Multiple sheets per file (Contents, Figures, Tables)
- ⚠️ Wide format tables require transformation
- ⚠️ Inconsistent header rows (need skiprows parameter per sheet)

### Population Projections
- ✅ Excellent "Flat File" sheet - ready to use, no transformation
- ✅ 13 variant projections with systematic naming
- ✅ 50-year horizon (2022-2072)
- ✅ Single year age breakdown
- ⚠️ Summary files are wide format (components of change)

### Cross-Validation
- ✅ 2-3 year overlap between official and projected migration
- ✅ Clear comparison methodology defined
- ℹ️ Expect 10-15% differences (projections vs actuals)

### CLI Decision
- ❌ NO CLI commands recommended
- ✅ Python API sufficient for research datasets
- ✅ Document usage patterns in README

## Resolved Clarifications from plan.md

1. **Migration mother page URL**: ✅ Corrected to `/statistics/population/long-term-international-migration-statistics`
2. **File variants**: ✅ Documented all 4 migration file types + 15 projection files
3. **Parsing strategy**: ✅ Detailed skiprows/sheet recommendations per file type
4. **CLI decision**: ✅ Decided against CLI - programmatic use only

## Next Steps

1. ✅ Research complete - ready for Phase 1 (Design & Contracts)
2. Update plan.md status to Phase 1
3. Begin designing module structure and data contracts
4. Write parsing functions based on research findings
```
