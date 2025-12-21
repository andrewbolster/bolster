# NISRA Data Sources

This module provides programmatic access to Northern Ireland Statistics and Research Agency (NISRA) official statistics.

## Available Data Sources

### 1. Monthly Birth Registrations (`births.py`)

- **Update Frequency**: Monthly (published 12th of following month at 9:30 AM)
- **Mother Page**: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/births
- **Data Dimensions**:
  - Event type (Registration vs Occurrence)
  - Sex (Persons, Male, Female)
  - Monthly time series (2006-present)
- **Key Functions**:
  - `get_latest_births()` - Automatically fetches most recent monthly data
  - `parse_births_file()` - Parse specific Excel file
  - `validate_births_totals()` - Verify Male + Female = Persons
- **Data Format**: Monthly time series files with complete history
- **Notes**:
  - Registration: When births were officially registered
  - Occurrence: When births actually occurred
  - Most births registered within 42 days
  - COVID-19 anomaly: April-May 2020 registration data disrupted by lockdown (offices closed), but occurrence data remains normal

### 2. Weekly Death Registrations (`deaths.py`)

- **Update Frequency**: Weekly (published Fridays)
- **Mother Page**: https://www.nisra.gov.uk/statistics/death-statistics/weekly-death-registrations-northern-ireland
- **Data Dimensions**:
  - Demographics (age, sex)
  - Geography (Local Government Districts)
  - Place of death (hospital, home, care home, etc.)
  - Totals with historic averages
- **Key Functions**:
  - `get_latest_deaths()` - Automatically fetches most recent weekly data
  - `parse_deaths_file()` - Parse specific Excel file
- **Data Format**: Cumulative weekly files (year-to-date)

### 3. Labour Force Survey (`labour_market.py`)

- **Update Frequency**: Quarterly (published ~2 months after quarter end)
- **Mother Page**: https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare
- **Data Tables**:
  - Employment by age band and sex (Table 2.15)
  - Employment by industry sector (Table 2.17)
  - Employment by occupation (Table 2.18)
  - Employment by Local Government District (Table 2.19 - annual only)
  - Economic inactivity (Table 2.21)
  - Unemployment rates (Table 2.22)
- **Key Functions**:
  - `get_latest_employment()` - Automatically fetches latest quarterly employment data
  - `get_latest_economic_inactivity()` - Fetches economic inactivity statistics
  - `get_quarterly_data()` - Retrieve specific quarter's data
- **Data Format**: Quarterly rolling 3-month periods (e.g., "Jul-Sep 2025")

## Design Philosophy

### Mother Page Scraping Approach

All NISRA data sources follow a robust, future-proof architecture for discovering the latest publications:

#### 1. Two-Step Web Scraping

Instead of hardcoding dates or file URLs, modules scrape NISRA's official statistics pages:

```
Mother Page (listing all publications)
    ↓ Find latest publication link
Publication Detail Page
    ↓ Extract Excel file URL
Excel File Download
    ↓ Parse and validate
Structured DataFrame
```

#### 2. Date Parsing for Validation

Modules extract dates from filenames and publication titles to:

- Verify they've found the truly latest publication (not just first link)
- Warn if data appears stale (e.g., > 6 months old)
- Support chronological sorting when multiple files exist

#### 3. Fallback Mechanisms

Each module implements graceful degradation:

- Primary: Parse dates from filenames
- Secondary: Parse from link text
- Tertiary: Use first link (reverse chronological page order)
- All failures: Raise descriptive `NISRADataNotFoundError`

### Why This Approach?

**Problem**: NISRA publishes new data regularly with varying filenames and URLs. Hardcoded dates/URLs break when new data is released.

**Solution**: Scrape the authoritative source (mother page) that NISRA maintains in reverse chronological order.

**Benefits**:

- ✅ Automatically picks up new publications without code changes
- ✅ Self-documenting (mother page URLs in docstrings)
- ✅ Transparent (logs what it finds)
- ✅ Robust (multiple fallback strategies)
- ✅ Testable (can validate against real NISRA website)

### Example: Labour Market Latest Detection

```python
def get_latest_lfs_publication_url() -> tuple[str, str, str]:
    """Find the latest Labour Force Survey quarterly tables publication.

    Returns:
        Tuple of (excel_file_url, year, quarter)
    """
    # Step 1: Scrape mother page
    mother_page = "https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare"
    soup = BeautifulSoup(requests.get(mother_page).content, "html.parser")

    # Step 2: Find latest "Quarterly Labour Force Survey Tables" link
    lfs_links = [
        link
        for link in soup.find_all("a", href=True)
        if "Quarterly Labour Force Survey Tables" in link.get_text(strip=True)
    ]
    latest_pub_url = lfs_links[0]["href"]  # First = newest (reverse chronological)

    # Step 3: Scrape publication page for Excel file
    pub_soup = BeautifulSoup(requests.get(latest_pub_url).content, "html.parser")
    excel_url = find_excel_link(pub_soup)

    # Step 4: Extract quarter and year from filename
    # e.g., "lmr-labour-force-survey-quarterly-tables-July-September-25.xlsx"
    quarter, year = parse_quarter_from_filename(excel_url)

    return excel_url, year, quarter
```

## Testing Approach

### Data Integrity Testing (Not Unit Testing)

All NISRA modules follow a **data integrity testing** philosophy:

#### Core Principles

1. **Use Real Data, Not Mocks**

   - Tests download actual NISRA data files
   - Validates against real-world edge cases
   - Catches format changes immediately

1. **Test Mathematical Consistency**

   - Male + Female = Total
   - Sum of all geographies = Total
   - Sum of age bands = Total
   - Cross-dimensional consistency

1. **Test Data Quality**

   - No negative values where impossible
   - Realistic ranges (e.g., employment rates 0-100%)
   - No missing required columns
   - Proper data types

1. **Test Temporal Patterns**

   - Chronological ordering
   - No missing weeks/quarters
   - Historical patterns hold (e.g., female inactivity > male historically)

#### Example Test Structure

```python
class TestDeathsDataIntegrity:
    """Test suite for validating internal consistency of deaths data."""

    @pytest.fixture(scope="class")
    def latest_all_dimensions(self):
        """Fetch latest data once for all tests (efficient)."""
        return deaths.get_latest_deaths(dimension="all", force_refresh=False)

    def test_demographics_sum_to_total(self, latest_all_dimensions):
        """Test that male + female deaths equal total deaths for each week."""
        demographics = latest_all_dimensions["demographics"]

        for week in demographics["week_ending"].unique():
            week_data = demographics[demographics["week_ending"] == week]
            all_ages = week_data[week_data["age_range"] == "All"]

            total = all_ages[all_ages["sex"].str.contains("Total")]["deaths"].sum()
            male = all_ages[all_ages["sex"].str.contains("Male") & ~all_ages["sex"].str.contains("Female")][
                "deaths"
            ].sum()
            female = all_ages[all_ages["sex"].str.contains("Female")]["deaths"].sum()

            assert total == male + female, f"Week {week}: Total ({total}) != Male ({male}) + Female ({female})"
```

#### Test Coverage

- **Births Statistics**: 15 integrity tests, 85% code coverage
- **Deaths Statistics**: 15 integrity tests, 87% code coverage
- **Labour Market Statistics**: 21 integrity tests, 86% code coverage

#### Why This Approach?

**Traditional unit testing** mocks external dependencies and tests logic in isolation.

**Data integrity testing** validates that:

- We correctly understand the data structure
- Our parsing logic handles real-world data
- Mathematical relationships hold
- Data quality meets expectations

This catches issues that unit tests miss:

- NISRA changes Excel format
- New categories appear
- Edge cases in real data
- Mathematical relationships we assumed don't actually hold

## Architecture Patterns

### 1. Module-First, CLI-Second

All functionality is implemented as importable Python modules **first**, with CLI as a thin wrapper:

```python
# As a module (for analysis/scripting)
from bolster.data_sources.nisra import labour_market
df = labour_market.get_latest_employment()
print(df[df["age_range"] == "16-24"]["employment_thousands"].mean())

# As CLI (for quick checks)
$ bolster nisra labour-market --latest --table employment
```

**Benefits**:

- Enables rapid analysis in Jupyter notebooks
- Supports programmatic integration
- Makes testing easier (test modules, not CLI)
- CLI stays simple (just argument parsing)

### 2. Long-Format DataFrames

All functions return [tidy/long-format](https://vita.had.co.nz/papers/tidy-data.pdf) DataFrames:

```python
# Long format (preferred)
| week_ending | sex    | age_range | deaths |
|-------------|--------|-----------|--------|
| 2025-12-12  | Male   | 0-4       | 3      |
| 2025-12-12  | Male   | 5-14      | 1      |
| 2025-12-12  | Female | 0-4       | 2      |

# NOT wide format (harder to work with)
| week_ending | Male_0-4 | Male_5-14 | Female_0-4 | ... |
```

**Benefits**:

- Easy filtering: `df[df["sex"] == "Male"]`
- Easy grouping: `df.groupby(["sex", "age_range"]).sum()`
- Handles varying categories across years
- Works well with seaborn/plotly
- Standard format for pandas operations

### 3. Shared Utilities (`_base.py`)

Common functionality extracted to avoid duplication:

- `download_file()` - HTTP downloads with caching
- `scrape_download_links()` - BeautifulSoup link extraction
- `safe_int()`, `safe_float()` - Robust type conversion from Excel
- `NISRADataNotFoundError`, `NISRAValidationError` - Custom exceptions

### 4. Comprehensive Logging

All modules use Python's `logging` module:

```python
logger.info("Found latest LFS publication: Jul-Sep 2025")
logger.warning("Latest deaths file is 180 days old - NISRA may not have published recent data")
```

Users can control verbosity:

```python
import logging

logging.basicConfig(level=logging.INFO)  # See what's happening
logging.basicConfig(level=logging.WARNING)  # Quiet mode
```

## Usage Examples

### Quick Start

```python
from bolster.data_sources.nisra import births, deaths, labour_market

# Get latest monthly births by registration date
births_df = births.get_latest_births(event_type="registration")
print(f"Latest month: {births_df['month'].max()}")
print(f"Total births: {births_df[births_df['sex'] == 'Persons']['births'].sum()}")

# Get latest weekly deaths by demographics
deaths_df = deaths.get_latest_deaths(dimension="demographics")
print(f"Latest week: {deaths_df['week_ending'].max()}")
print(f"Total deaths: {deaths_df['deaths'].sum()}")

# Get latest quarterly employment by age/sex
employment_df = labour_market.get_latest_employment()
print(
    f"Youth (16-24) employment: {employment_df[employment_df['age_range'] == '16-24']['employment_thousands'].sum():.1f}k"
)
```

### Analysis Example

```python
import pandas as pd
from bolster.data_sources.nisra import labour_market

# Get latest employment data
df = labour_market.get_latest_employment()

# Calculate employment by sex
by_sex = df.groupby("sex")["employment_thousands"].sum()
print(f"Male employment: {by_sex['Male']:.1f}k")
print(f"Female employment: {by_sex['Female']:.1f}k")

# Calculate youth (16-24) unemployment rate
youth_data = df[df["age_range"] == "16-24"]
youth_employment = youth_data["employment_thousands"].sum()
print(f"Youth employment: {youth_employment:.1f}k")
```

### CLI Examples

```bash
# Get latest births by registration date
bolster nisra births --latest --event-type registration

# Get both registration and occurrence data
bolster nisra births --latest --event-type both --save births.csv

# Get latest deaths statistics as CSV
bolster nisra deaths --latest --dimension all --format csv --save deaths_latest.csv

# Get latest labour market employment data
bolster nisra labour-market --latest --table employment

# Get economic inactivity breakdown
bolster nisra labour-market --latest --table economic_inactivity --format json
```

## Development Guidelines

### Adding New NISRA Data Sources

When adding a new NISRA dataset, follow these patterns:

1. **Find the Mother Page**

   - Navigate NISRA website: https://www.nisra.gov.uk/statistics
   - Find the topic-specific statistics page
   - Document URL in module docstring

1. **Implement Latest Detection**

   ```python
   def get_latest_DATASET_url() -> str:
       """Scrape mother page to find latest publication.

       Returns:
           URL of latest Excel file
       """
       # Scrape mother page
       # Find latest publication link
       # Follow to publication page
       # Extract Excel file URL
       # Parse and validate date
       return excel_url
   ```

1. **Implement Parsing Functions**

   - Use `openpyxl` for Excel parsing
   - Return long-format DataFrames
   - Use `safe_int()`, `safe_float()` for type conversion
   - Handle missing/sparse data gracefully

1. **Write Integrity Tests**

   ```python
   class TestDATASETDataIntegrity:
       @pytest.fixture(scope="class")
       def latest_data(self):
           return get_latest_DATASET()

       def test_mathematical_consistency(self, latest_data):
           # Test that totals = sum of parts
           pass

       def test_data_quality(self, latest_data):
           # No negatives, realistic ranges, etc.
           pass
   ```

1. **Add CLI Integration**

   - Add command group to `cli.py`
   - Keep as thin wrapper around module functions
   - Support `--latest`, `--format`, `--save` flags

1. **Update Exports**

   ```python
   # In __init__.py
   from . import deaths, labour_market, NEW_MODULE
   ```

### Code Quality Standards

- **Type Hints**: Use Python 3.10+ type hints (`str | None`, not `Optional[str]`)
- **Docstrings**: Google-style docstrings for all public functions
- **Logging**: Use `logger.info()`, `logger.warning()` appropriately
- **Error Handling**: Raise custom exceptions (`NISRADataNotFoundError`, `NISRAValidationError`)
- **Testing**: Aim for >80% code coverage with integrity tests
- **Formatting**: Use `ruff` for linting/formatting

## Troubleshooting

### "Latest" Detection Not Working

**Symptoms**: Module returns old data or raises `NISRADataNotFoundError`

**Debugging**:

1. Check if NISRA changed mother page URL (navigate manually)
1. Check if publication naming changed ("Quarterly Labour Force Survey Tables" → different title)
1. Enable debug logging: `logging.basicConfig(level=logging.DEBUG)`
1. Check if Excel file structure changed (NISRA sometimes reorganizes)

**Fix**: Update scraping logic in `get_latest_*_url()` function

### Test Failures After NISRA Update

**Symptoms**: Integrity tests fail after new data published

**Common Causes**:

- NISRA added new categories (e.g., new age band)
- NISRA changed column names
- NISRA changed sheet names

**Debugging**:

1. Download latest Excel file manually
1. Compare structure to what code expects
1. Check test assumptions still hold

**Fix**: Update parsing logic to handle new structure, update tests if assumptions changed

### Excel Parsing Errors

**Symptoms**: `ValueError`, `KeyError`, or malformed DataFrames

**Common Causes**:

- NISRA changed sheet structure
- Unexpected merged cells
- Missing headers

**Fix**: Inspect Excel file manually, update cell references in parsing code

## Future Enhancements

Potential additional NISRA data sources to add:

- \[ \] **Crime Statistics** - Monthly police recorded crime
- \[ \] **House Prices** - Quarterly NI house price index (may overlap with existing `ni_house_price_index.py`)
- \[ \] **Birth Statistics** - Quarterly birth registrations
- \[ \] **Education Statistics** - Annual school census data
- \[ \] **Tourism Statistics** - Quarterly visitor numbers
- \[ \] **Business Statistics** - Quarterly economic indicators

## References

- **NISRA Statistics Portal**: https://www.nisra.gov.uk/statistics
- **Labour Market Statistics**: https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare
- **Death Statistics**: https://www.nisra.gov.uk/statistics/death-statistics
- **NISRA Data Quality**: https://www.nisra.gov.uk/statistics/data-quality

## License

This module interfaces with publicly available NISRA data under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

When using NISRA data, please cite:

> Northern Ireland Statistics and Research Agency (NISRA). \[Dataset Name\]. Retrieved from https://www.nisra.gov.uk/
