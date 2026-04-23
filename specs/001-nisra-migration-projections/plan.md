# Implementation Plan: NISRA Migration and Population Projections Data Sources

**Branch**: `001-nisra-migration-projections` | **Date**: 2026-02-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-nisra-migration-projections/spec.md`

## Summary

Implement two new NISRA data source modules (`migration_official.py` and `population_projections.py`) to provide access to official long-term international migration statistics and population projections. The migration official module will enable cross-validation with existing derived migration estimates (from `migration.py`), while population projections will extend historical population data into the future for demographic planning. Both modules follow the established mother page scraping pattern, use shared utilities from `_base.py`, and include comprehensive data integrity tests using real NISRA data.

## Technical Context

**Language/Version**: Python 3.11+ (compatible with 3.11, 3.12, 3.13)\
**Primary Dependencies**: pandas, BeautifulSoup4 (HTML parsing), openpyxl (Excel parsing), requests (via shared session)\
**Storage**: File-based caching via `download_file()` utility (TTL: 24h for migration, 168h for projections)\
**Testing**: pytest with real data integration tests (scope="class" fixtures), no mocks for external data sources\
**Target Platform**: Cross-platform Python library (Linux, macOS, Windows)\
**Project Type**: Single library project with data source modules\
**Performance Goals**: Downloads complete within 30 seconds, cross-validation completes in \<5 seconds for 20 years of data\
**Constraints**: Must scrape mother pages (no hardcoded URLs), must use shared HTTP session with retry logic\
**Scale/Scope**: Two new modules (~300-400 lines each), 4-6 new test classes, 2 optional CLI commands

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### ✅ PASS: Core Philosophy Alignment

- **Data-first development**: Both modules retrieve real, current NISRA data
- **No synthetic data**: All tests use actual published data
- **Mother page scraping**: Both modules discover latest publications automatically
- **No hardcoded URLs**: Publication URLs discovered via scraping mother pages

### ✅ PASS: Package Management

- **uv only**: All operations via `uv run` (pytest, pre-commit, CLI)
- **Dependencies**: pandas and beautifulsoup4 already in pyproject.toml
- **No new dependencies required**: Uses existing project stack

### ✅ PASS: Testing Philosophy

- **Real data only**: Integration tests download current NISRA publications
- **No mocking**: Tests use `scope="class"` fixtures to download once per test class
- **Data integrity focus**: Tests validate column presence, value ranges, arithmetic relationships
- **Coverage target**: 80% on new data paths (validation function unit tests boost coverage)

### ✅ PASS: HTTP Requests

- **Shared session**: Must use `from bolster.utils.web import session`
- **Retry logic**: session.get() retries on 500/502/503/504 errors
- **Never raw requests**: No direct use of `requests.get()`

### ✅ PASS: Logging

- **Standard logger**: `logger = logging.getLogger(__name__)` in both modules
- **No print()**: All output via logger.info(), logger.warning(), logger.error()
- **Progress logging**: Log publication discovery, data range, key statistics

### ✅ PASS: Exception Hierarchy

- **NISRA exceptions**: Use `NISRADataNotFoundError`, `NISRAValidationError` from `_base.py`
- **Actionable messages**: Include context about what failed (e.g., "Could not find migration publication on mother page")

### ✅ PASS: Validation Functions

- **Migration**: Validate net_migration = immigration - emigration
- **Projections**: Validate total population = sum of age groups, check year coverage
- **Returns bool**: All validation functions return True or raise exception
- **Cross-validation**: New function to compare official vs derived migration

### ✅ PASS: File Downloads

- **Use download_file()**: From `nisra/_base.py` with appropriate TTL
- **Cache TTL**: 24 hours for migration (annual updates), 168 hours for projections (biennial updates)
- **Force refresh support**: Both modules support `force_refresh` parameter

### ✅ PASS: Type Annotations

- **All public functions**: Fully type-annotated
- **Standard return types**: `pd.DataFrame` for data access, `str` for URL discovery, `bool` for validation
- **No untyped Any**: All parameters and returns explicitly typed

### ✅ PASS: CLI Integration

- **Optional CLI commands**: Evaluate if standalone utility exists
- **Migration**: Cross-validation CLI command likely useful (`bolster nisra migration-compare`)
- **Projections**: Projection query CLI may be useful for planning scenarios
- **Click framework**: All CLI commands use click for argument parsing
- **Rich output**: Use rich.console for formatted tables

### ✅ PASS: Testing Standards

- **File naming**: `test_nisra_migration_official_integrity.py`, `test_nisra_population_projections_integrity.py`
- **Test classes**: `TestDataIntegrity` (real data) + `TestValidation` (unit tests for edge cases)
- **Fixtures**: `scope="class"` for one download per test class
- **Coverage**: Unit tests for validation edge cases (empty DataFrame, missing columns, invalid values)

### ✅ PASS: Module Structure

- **Flat modules**: migration_official.py and population_projections.py are standalone (not subpackage)
- **Mother page pattern**: Both use get_latest\_*_publication_url() → parse_*_file() → get_latest_\*()
- **Shared utilities**: Use download_file(), make_absolute_url(), web.session from \_base.py

### ✅ PASS: Pre-commit Enforcement

- **All checks must pass**: ruff linting/formatting, trailing whitespace, YAML validation
- **Line length**: 120 characters
- **Before commit**: Run `uv run pre-commit run --all-files`

### ✅ PASS: Documentation

- **Module docstrings**: Include Data Source section with mother page URL, update frequency, geographic coverage
- **Function docstrings**: Args, Returns, Raises, Example sections (Google style)
- **Code comments**: Explain mother page navigation, non-obvious business logic

### ✅ PASS: README Update

- **Coverage table**: Add two rows:
  - `Long-Term International Migration | nisra.migration_official | ✅`
  - `Population Projections | nisra.population_projections | ✅`
- **Update migration.py entry**: Note that official data now available for cross-validation

### ✅ PASS: Shared Utilities

- **No duplication**: Use existing utilities from `_base.py`:
  - `download_file()` for caching
  - `make_absolute_url()` for relative URLs
  - `scrape_download_links()` if applicable
  - `safe_int()` for robust parsing
  - `add_date_columns()` if time series columns needed

## Project Structure

### Documentation (this feature)

```text
specs/001-nisra-migration-projections/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output: Mother page analysis, Excel format research
├── data-model.md        # Phase 1 output: Migration and projection data schemas
├── quickstart.md        # Phase 1 output: Usage examples for both modules
├── contracts/           # Phase 1 output: Data schemas and validation contracts
└── checklists/
    └── requirements.md  # Spec quality checklist (already created)
```

### Source Code (repository root)

```text
src/bolster/
├── data_sources/
│   └── nisra/
│       ├── _base.py                       # Shared utilities (existing)
│       ├── migration.py                   # Derived migration (existing)
│       ├── population.py                  # Historical population (existing)
│       ├── migration_official.py          # NEW: Official migration statistics
│       ├── population_projections.py      # NEW: Population projections
│       └── __init__.py                    # Update exports for new modules
├── utils/
│   └── web.py                             # Shared HTTP session (existing)
└── cli.py                                 # Update with optional CLI commands

tests/
├── test_nisra_migration_official_integrity.py    # NEW: Migration official tests
└── test_nisra_population_projections_integrity.py # NEW: Projections tests

README.md                                  # Update coverage table
```

**Structure Decision**: Single library project with flat NISRA modules. Migration official and population projections are standalone modules (not subpackage) because they don't share domain-specific concepts beyond the standard NISRA utilities in `_base.py`. Follows existing pattern of births.py, deaths.py, population.py as peer modules.

## Complexity Tracking

> **No constitution violations** - This feature fully complies with all project standards. No complexity justification required.

## Phase 0: Research & Discovery

### Research Tasks

#### 1. Migration Mother Page Structure

**Task**: Analyze NISRA migration statistics mother page to understand publication structure

**URL to investigate**: https://www.nisra.gov.uk/statistics/migration/long-term-international-migration-statistics

**Questions to answer**:

- What is the mother page HTML structure?
- How are publications listed? (reverse chronological? table? links?)
- What is the link pattern to publication detail pages?
- What is the Excel file naming pattern?
- How many years of data are available?
- What is the most recent publication date?
- Are there multiple Excel files per publication or one consolidated file?

**Method**: Use Task tool with Explore agent or manual WebFetch to:

1. Fetch mother page HTML
1. Parse with BeautifulSoup to find publication links
1. Follow link to latest publication detail page
1. Identify Excel download links
1. Document link patterns and CSS selectors

**Output**: Document in research.md with example HTML snippets and link patterns

#### 2. Population Projections Publication Structure

**Task**: Analyze NISRA population projections publication to understand file structure

**URL to investigate**: https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland

**Questions to answer**:

- Is there a mother page listing all projection publications, or is it a single page?
- What Excel files are available? (variants: principal, high, low?)
- What is the sheet structure within Excel files?
- What geographic breakdowns are included? (NI overall, constituencies, health trusts?)
- What is the projection time horizon? (2022 to what year?)
- What age breakdowns are provided? (single year? 5-year bands?)
- How are projections organized? (separate files per geography? one consolidated file?)

**Method**: Use WebFetch to:

1. Fetch publication page
1. List all Excel file links
1. Download sample file and inspect sheets/structure
1. Document column names, data format, multi-sheet organization

**Output**: Document in research.md with file structure diagram and column mappings

#### 3. Excel Parsing Strategy

**Task**: Determine optimal approach for parsing migration and projection Excel files

**Questions to answer**:

- Which pandas read_excel() parameters are needed? (sheet_name, skiprows, usecols?)
- Are there header rows to skip?
- Are there footer notes to exclude?
- What is the data orientation? (wide format requiring melt? already long format?)
- Are there merged cells or formatting issues?
- What data types need conversion? (dates, integers, floats?)

**Method**:

1. Download sample Excel files for both data sources
1. Open in Python and test `pd.read_excel()` with different parameters
1. Identify any quirks (merged cells, multiple tables per sheet, etc.)
1. Document working parameters

**Output**: Document in research.md with working code snippets

#### 4. Cross-Validation Design

**Task**: Design cross-validation approach for comparing official vs derived migration

**Questions to answer**:

- What years overlap between official and derived data?
- What metrics should be compared? (net migration only? or immigration/emigration separately if available?)
- What tolerance is reasonable for discrepancies? (demographic equation has measurement error)
- What output format is most useful? (DataFrame? summary dict? plot?)
- Should cross-validation be a standalone function or integrated into migration_official module?

**Method**:

1. Load existing derived migration data from migration.py
1. Check what year range is available
1. Design function signature: `compare_official_vs_derived(official_df, derived_df) -> pd.DataFrame`
1. Define output schema with columns: year, official_net, derived_net, absolute_diff, percent_diff

**Output**: Document in research.md with function design and expected output format

#### 5. CLI Command Evaluation

**Task**: Determine if CLI commands provide standalone utility

**Questions to answer**:

- **Migration official**: Is there utility beyond just viewing data? (Cross-validation comparison is likely useful)
- **Population projections**: Would users query specific years/scenarios via CLI? (Planning use case)
- What parameters would CLI commands accept?
- What output format is most useful? (rich table? summary statistics? CSV export?)

**Decision criteria**:

- CLI is useful if it enables quick data exploration without writing Python
- Cross-validation CLI likely valuable: `uv run bolster nisra migration-compare --start-year 2010`
- Projections CLI may be valuable: `uv run bolster nisra projections --year 2030 --area "Northern Ireland"`

**Output**: Document in research.md with CLI command designs and usage examples

### Research Consolidation (research.md)

After completing all research tasks, create `research.md` with these sections:

1. **Migration Mother Page Analysis**

   - Mother page URL structure
   - Publication link patterns
   - Excel file naming conventions
   - Data availability timeline

1. **Population Projections Publication Analysis**

   - Publication URL (single page or mother page?)
   - Excel file structure and variants
   - Geographic and temporal coverage
   - Projection scenarios (principal/high/low)

1. **Excel Parsing Strategy**

   - Migration file parsing approach (sheet names, skiprows, etc.)
   - Projections file parsing approach
   - Data transformation requirements (wide to long format?)
   - Column name standardization

1. **Cross-Validation Design**

   - Function signature and return type
   - Comparison metrics and tolerance thresholds
   - Output format and user-facing interpretation

1. **CLI Command Decisions**

   - Migration CLI: `bolster nisra migration-compare` with parameters
   - Projections CLI: `bolster nisra projections` with filtering options
   - Rationale for inclusion or exclusion of each command

## Phase 1: Design & Contracts

### Data Model (data-model.md)

#### Entity 1: Official Migration Estimate

**Description**: Annual long-term international migration flows for Northern Ireland from official NISRA statistics

**Schema**:

```python
{
    "year": int,  # Calendar year (e.g., 2022)
    "immigration": int,  # Number of people immigrating to NI
    "emigration": int,  # Number of people emigrating from NI
    "net_migration": int,  # Net migration (immigration - emigration)
    "date": pd.Timestamp,  # Reference date (typically June 30 or December 31)
}
```

**Validation Rules**:

- `year` must be >= 2000 (realistic lower bound for available data)
- `immigration` must be >= 0
- `emigration` must be >= 0
- `net_migration` must equal `immigration - emigration`
- No missing values in required columns

**Relationships**:

- Comparable to derived migration data from `migration.py` for overlapping years
- Can be merged with population data from `population.py` for context

**Data Source**: Scraped from NISRA long-term international migration publications

#### Entity 2: Population Projection

**Description**: Forecasted future population for Northern Ireland with age, sex, and geographic breakdowns

**Schema**:

```python
{
    "year": int,  # Projection year (e.g., 2030)
    "base_year": int,  # Base year for projections (e.g., 2022)
    "age_group": str,  # Age band (e.g., "00-04", "05-09", ..., "90+")
    "sex": str,  # "Male", "Female", "All persons"
    "area": str,  # Geographic area (e.g., "Northern Ireland", "Belfast East")
    "population": int,  # Projected population count
    "variant": str,  # Projection variant ("principal", "high", "low") if applicable
}
```

**Validation Rules**:

- `year` must be >= `base_year`
- `year` must be \<= projection horizon (e.g., 2050 for 2022-based projections)
- `population` must be >= 0
- `age_group` must follow standard format (e.g., "00-04", "05-09", "90+")
- `sex` must be in \["Male", "Female", "All persons", "Persons"\] (normalize to standard)
- `area` must match known geographic areas
- For "All persons", population should equal sum of Male + Female for same year/age/area

**Relationships**:

- Extends historical population data from `population.py` into the future
- Can be combined with historical data for full time series (past + future)

**Data Source**: Scraped from NISRA population projections publications (e.g., 2022-based)

#### Entity 3: Migration Validation Result

**Description**: Comparison between official and derived migration estimates for quality assessment

**Schema**:

```python
{
    "year": int,  # Year being compared
    "official_net_migration": int,  # Official NISRA estimate
    "derived_net_migration": int,  # Derived from demographic equation
    "absolute_difference": int,  # Absolute difference between estimates
    "percent_difference": float,  # Percentage difference (absolute_diff / official * 100)
    "exceeds_threshold": bool,  # Whether difference exceeds configured threshold
}
```

**Validation Rules**:

- `year` must exist in both official and derived datasets
- `percent_difference` calculated as: `abs(derived - official) / official * 100`
- `exceeds_threshold` compares `absolute_difference` to user-specified threshold (default: 1000)

**Relationships**:

- Links official migration data (Entity 1) with derived migration data (from `migration.py`)
- Enables quality assessment of demographic equation approach

**Data Source**: Computed from official and derived migration DataFrames

### API Contracts (contracts/)

#### Contract 1: migration_official.py Public API

```python
# contracts/migration_official_api.py

from typing import Tuple
import pandas as pd


def get_latest_migration_publication_url() -> str:
    """Scrape NISRA migration mother page to find latest publication.

    Returns:
        URL to latest migration Excel file

    Raises:
        NISRADataNotFoundError: If mother page or publication cannot be found
    """
    ...


def parse_migration_file(file_path: str) -> pd.DataFrame:
    """Parse downloaded migration Excel file into DataFrame.

    Args:
        file_path: Path to downloaded Excel file

    Returns:
        DataFrame with columns: year, immigration, emigration, net_migration, date

    Raises:
        NISRAValidationError: If file format is unexpected or data is invalid
    """
    ...


def get_latest_migration_official(force_refresh: bool = False) -> pd.DataFrame:
    """Get latest official NISRA migration statistics.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with migration statistics for all available years

    Raises:
        NISRADataNotFoundError: If publication cannot be found
        NISRAValidationError: If data fails integrity checks
    """
    ...


def validate_migration_arithmetic(df: pd.DataFrame) -> bool:
    """Validate that net_migration = immigration - emigration.

    Args:
        df: DataFrame from parse_migration_file() or get_latest_migration_official()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If arithmetic relationship doesn't hold
    """
    ...


def compare_official_vs_derived(
    official_df: pd.DataFrame, derived_df: pd.DataFrame, threshold: int = 1000
) -> pd.DataFrame:
    """Compare official migration data with derived estimates.

    Args:
        official_df: DataFrame from get_latest_migration_official()
        derived_df: DataFrame from migration.get_latest_migration()
        threshold: Absolute difference threshold for flagging discrepancies

    Returns:
        DataFrame with columns: year, official_net_migration, derived_net_migration,
                                absolute_difference, percent_difference, exceeds_threshold
    """
    ...
```

#### Contract 2: population_projections.py Public API

```python
# contracts/population_projections_api.py

from typing import Optional, Literal
import pandas as pd


def get_latest_projections_publication_url() -> str:
    """Discover latest population projections publication URL.

    Returns:
        URL to latest projections Excel file

    Raises:
        NISRADataNotFoundError: If publication cannot be found
    """
    ...


def parse_projections_file(file_path: str) -> pd.DataFrame:
    """Parse downloaded projections Excel file into long-format DataFrame.

    Args:
        file_path: Path to downloaded Excel file

    Returns:
        DataFrame with columns: year, base_year, age_group, sex, area,
                                population, variant (if applicable)

    Raises:
        NISRAValidationError: If file format unexpected or data invalid
    """
    ...


def get_latest_projections(
    area: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get latest NISRA population projections with optional filtering.

    Args:
        area: Filter to specific geographic area (e.g., "Northern Ireland")
        start_year: Filter projections >= this year
        end_year: Filter projections <= this year
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with population projections

    Raises:
        NISRADataNotFoundError: If publication cannot be found
        NISRAValidationError: If data fails integrity checks
    """
    ...


def validate_projections_totals(df: pd.DataFrame) -> bool:
    """Validate that All persons = Male + Female for each year/age/area.

    Args:
        df: DataFrame from get_latest_projections()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If totals don't match
    """
    ...


def validate_projection_coverage(df: pd.DataFrame) -> bool:
    """Validate that projections cover expected year range.

    Args:
        df: DataFrame from get_latest_projections()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If year range is incomplete or suspicious
    """
    ...
```

#### Contract 3: CLI Commands (if implemented)

```python
# contracts/cli_commands.py

# Command: bolster nisra migration-compare
@cli.command("migration-compare")
@click.option("--start-year", type=int, help="Start year for comparison")
@click.option("--end-year", type=int, help="End year for comparison")
@click.option("--threshold", type=int, default=1000, help="Threshold for flagging discrepancies")
def migration_compare(start_year, end_year, threshold):
    """Compare official and derived migration estimates.

    Displays side-by-side comparison with discrepancies highlighted.
    """
    ...


# Command: bolster nisra projections
@cli.command("projections")
@click.option("--year", type=int, help="Specific projection year to query")
@click.option("--area", type=str, default="Northern Ireland", help="Geographic area")
@click.option("--start-year", type=int, help="Start year for range")
@click.option("--end-year", type=int, help="End year for range")
def projections(year, area, start_year, end_year):
    """Query NISRA population projections.

    Displays projected population with age/sex breakdown.
    """
    ...
```

### Quickstart (quickstart.md)

#### Migration Official - Basic Usage

```python
from bolster.data_sources.nisra import migration_official

# Get all official migration data
df = migration_official.get_latest_migration_official()
print(df.head())

# Output:
#    year  immigration  emigration  net_migration       date
# 0  2010        20000       15000           5000 2010-12-31
# 1  2011        22000       14000           8000 2011-12-31
# ...

# Validate data integrity
is_valid = migration_official.validate_migration_arithmetic(df)
print(f"Data validation: {'PASS' if is_valid else 'FAIL'}")
```

#### Population Projections - Basic Usage

```python
from bolster.data_sources.nisra import population_projections

# Get all projections
df = population_projections.get_latest_projections()
print(df.head())

# Get projections for specific year
df_2030 = population_projections.get_latest_projections(area="Northern Ireland", start_year=2030, end_year=2030)
print(df_2030)

# Get projections for next decade
df_decade = population_projections.get_latest_projections(start_year=2026, end_year=2035)
```

#### Cross-Validation Example

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

print(comparison[comparison["exceeds_threshold"]])

# Output:
#    year  official_net_migration  derived_net_migration  absolute_difference  percent_difference  exceeds_threshold
# 5  2015                   12000                  10500                 1500               12.5%               True
```

#### CLI Usage (if implemented)

```bash
# Compare migration estimates for recent decade
uv run bolster nisra migration-compare --start-year 2010 --threshold 500

# Query population projections for 2030
uv run bolster nisra projections --year 2030 --area "Northern Ireland"

# Get projections for range
uv run bolster nisra projections --start-year 2025 --end-year 2035
```

### Agent Context Update

After Phase 1 completion, run:

```bash
.specify/scripts/bash/update-agent-context.sh claude
```

This updates `.specify/memory/agent-context.claude.md` with:

- New modules added: `migration_official.py`, `population_projections.py`
- Testing patterns: Real data with `scope="class"` fixtures
- Cross-validation patterns for comparing official vs derived data

## Phase 2: Implementation Readiness

**Output from Phase 0 and Phase 1**:

- ✅ research.md: Mother page analysis, Excel parsing strategy, cross-validation design
- ✅ data-model.md: Three entities with schemas and validation rules
- ✅ contracts/: Public API contracts for both modules and optional CLI
- ✅ quickstart.md: Usage examples for common scenarios
- ✅ Updated agent context with new modules

**Next Steps**:

1. Run `/speckit.tasks` to break implementation into atomic tasks
1. Assign tasks to implementation agent or developer
1. Follow test-driven development: write tests first, then implementation
1. Ensure 80% coverage on new data paths (use validation unit tests to boost coverage)
1. Update README coverage table before creating PR

**Implementation Order** (recommended):

1. **Task 1**: Implement `migration_official.py` core (get_latest\_*, parse\_*, validate\_\*)
1. **Task 2**: Implement migration_official tests (TestDataIntegrity + TestValidation classes)
1. **Task 3**: Implement cross-validation function `compare_official_vs_derived()`
1. **Task 4**: Implement `population_projections.py` core (get_latest\_*, parse\_*, validate\_\*)
1. **Task 5**: Implement population_projections tests
1. **Task 6**: Update `__init__.py` exports for both modules
1. **Task 7**: Implement optional CLI commands (migration-compare, projections)
1. **Task 8**: Update README coverage table
1. **Task 9**: Run full test suite, pre-commit checks, verify 80% coverage
1. **Task 10**: Create PR with data insights

**Estimated Complexity**:

- **Migration official**: Medium (similar to existing births/deaths modules)
- **Population projections**: Medium-High (more complex filtering, multiple breakdowns)
- **Cross-validation**: Low (straightforward DataFrame merge and comparison)
- **Tests**: Medium (real data tests + validation edge case unit tests)
- **Total effort**: ~2-3 days for experienced developer familiar with codebase patterns

**Risk Areas**:

- Excel file structure may vary between publications (mitigate: flexible parsing with error handling)
- Mother page HTML structure may change (mitigate: clear error messages, fallback strategies)
- Cross-validation may reveal unexpected discrepancies (mitigate: document in PR, adjust thresholds)
- Projection files may have multiple sheets/variants (mitigate: research phase identifies structure)

**Success Metrics** (from spec.md):

- ✅ SC-001: Users can access official migration with single function call
- ✅ SC-002: Users can retrieve projections for any future year with breakdowns
- ✅ SC-003: Cross-validation completes in \<5 seconds
- ✅ SC-004: Downloads succeed 95% of time (exclude network failures)
- ✅ SC-005: Data integrity tests verify 100% of datasets
- ✅ SC-009: Minimum 80% test coverage
- ✅ SC-010: All tests use real NISRA data
- ✅ SC-011: Pre-commit hooks pass
- ✅ SC-012: README coverage table updated
