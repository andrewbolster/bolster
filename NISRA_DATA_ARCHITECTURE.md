# NISRA Data Sources - Architecture Guidelines

**Version**: 1.0
**Created**: 2024-12-19
**Purpose**: Document consistent patterns for parsing and storing NISRA statistical data

______________________________________________________________________

## Core Principles

### 1. Flat Data Philosophy

- **Goal**: Create maximally granular, flat datasets where each row is a single observation
- **Rationale**: Enables flexible querying, aggregation, and analysis
- **Validation**: Use aggregated sheets/totals to validate disaggregated data

### 2. Separate Dimension Tables (Non-Crossed Dimensions)

When source data presents **independent dimensional breakdowns** (not cross-tabulated):

- Create **separate tables per dimension**
- Share common temporal/geographic key
- Each table validates independently against totals

**Example**: Weekly Deaths Statistics

- Demographics table: `week_ending | sex | age_range | deaths`
- Geography table: `week_ending | lgd | deaths`
- Place table: `week_ending | place_of_death | deaths`

**Rationale**:

- Source data doesn't cross dimensions (can't get "males aged 65 in Belfast")
- Separate tables avoid sparse matrices with many nulls
- Each dimension can be queried/validated independently

### 3. Preserve Hierarchical Aggregations

Include both totals and breakdowns in flat tables:

```python
# Example: Include "Total" sex alongside "Male"/"Female"
week_ending | sex    | age_range | deaths
2025-01-03  | Total  | All       | 416      # <- Keep this
2025-01-03  | Total  | 0-14      | 2        # <- And this
2025-01-03  | Male   | All       | 215      # <- And this
2025-01-03  | Male   | 0-14      | 2        # <- And this
```

**Rationale**:

- Enables validation: `df[df.sex=='Total'].sum() == df[df.sex!='Total'].sum()`
- Users can filter out totals if unwanted: `df[df.sex != 'Total']`
- Preserves all information from source

### 4. Data Validation Strategy

Every parser must validate against published aggregates:

```python
# Validate that disaggregated data matches published totals
def validate_totals(parsed_df, expected_total_col, expected_total_value):
    actual = parsed_df[parsed_df.is_total_row == True]["count"].sum()
    assert actual == expected_total_value, f"Validation failed: {actual} != {expected_total_value}"
```

### 5. Date Semantics

- **Always document**: Registration date vs. occurrence date vs. reporting date
- **Use consistent column naming**:
  - `week_ending` for weekly data
  - `month_ending` / `month` for monthly
  - `quarter` for quarterly
  - `year` for annual
- **Store as date/datetime**, not strings

______________________________________________________________________

## Standard Table Schema Patterns

### Weekly Time Series

```python
{
    "week_ending": datetime,  # Friday of reporting week
    "dimension_1": str,  # Primary dimension (e.g., 'sex', 'lgd', 'place')
    "dimension_2": str,  # Optional secondary (if crossed in source)
    "value": int / float,  # The measured value
    "is_total": bool,  # Flag for aggregated rows
    "data_source": str,  # 'nisra_weekly_deaths_2025-12-12'
}
```

### Monthly Time Series

```python
{
    "month": datetime,  # First or last day of month
    "dimension_1": str,
    "value": int / float,
    "is_total": bool,
    "data_source": str,
}
```

### Geographic Data

```python
{
    "date": datetime,
    "lgd": str,  # Local Government District (standardized names)
    "dimension": str,  # What's being measured
    "value": int / float,
    "data_source": str,
}
```

______________________________________________________________________

## File Naming and Organization

### Module Structure

```
src/bolster/data_sources/nisra/
├── __init__.py              # Package exports
├── _base.py                 # Common functionality (URL patterns, caching, validation)
├── deaths.py                # Deaths statistics
├── labour_market.py         # Labour market statistics
├── crime.py                 # Crime statistics
└── ...
```

### Function Naming Convention

```python
# Discovery functions
get_latest_{dataset}_url() -> str
list_available_{dataset}_files() -> List[Dict]

# Download functions
download_{dataset}(url: str, cache_dir: Optional[Path]) -> Path

# Parsing functions
parse_{dataset}_{dimension}(file_path: Path) -> pd.DataFrame
parse_{dataset}_all_dimensions(file_path: Path) -> Dict[str, pd.DataFrame]

# Validation functions
validate_{dataset}_totals(df: pd.DataFrame, expected: Dict) -> bool

# High-level convenience functions
get_latest_{dataset}(dimension: str, format: str = 'dataframe') -> Union[pd.DataFrame, Dict]
```

______________________________________________________________________

## URL Pattern Documentation

Document URL patterns for programmatic access:

### Weekly Deaths Example

```python
WEEKLY_DEATHS_URL_PATTERN = (
    "https://www.nisra.gov.uk/system/files/statistics/"
    "{year:04d}-{month:02d}/"
    "Weekly_Deaths%20-%20w%20e%20{day:02d}%20{month_name}%20{year:04d}.xlsx"
)

WEEKLY_DEATHS_LANDING_PAGE = "https://www.nisra.gov.uk/publications/weekly-death-registrations-northern-ireland-{year}"
```

### Discovery Strategy

Prefer (in order):

1. **Scraping landing page** for download links (most reliable)
1. **RSS feed** for latest publication announcements
1. **URL construction** from known patterns (fragile, use as fallback)

______________________________________________________________________

## Caching Strategy

### Local File Caching

```python
CACHE_DIR = Path.home() / ".cache" / "bolster" / "nisra"


def get_cached_file(url: str, cache_ttl_hours: int = 24) -> Optional[Path]:
    """Return cached file if exists and fresh, else None"""
    cache_path = CACHE_DIR / hash_url(url)
    if cache_path.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if age.total_seconds() < cache_ttl_hours * 3600:
            return cache_path
    return None
```

### Cache Invalidation

- Weekly data: Cache for 7 days
- Monthly data: Cache for 30 days
- Annual data: Cache for 365 days
- Use `--force-refresh` flag in CLI to bypass cache

______________________________________________________________________

## Excel Parsing Best Practices

### 1. Sheet Navigation

```python
# Always check sheet names first
wb = openpyxl.load_workbook(path, data_only=True)
print(f"Available sheets: {wb.sheetnames}")

# Use explicit sheet names, not indices
data_sheet = wb["Table 2"]  # NOT wb.worksheets[3]
```

### 2. Find Data Start Row

Don't assume fixed row numbers:

```python
def find_header_row(sheet, expected_columns: List[str]) -> int:
    """Search for row containing expected column headers"""
    for row_idx, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if any(expected_columns[0] in str(cell) for cell in row if cell):
            return row_idx
    raise ValueError(f"Could not find header row with {expected_columns[0]}")
```

### 3. Clean Column Names

```python
def clean_column_name(col: str) -> str:
    """Standardize column names from Excel headers"""
    if col is None:
        return None
    # Remove newlines, extra spaces, normalize
    col = str(col).replace("\n", " ").strip()
    col = " ".join(col.split())  # Collapse multiple spaces
    return col
```

### 4. Handle Merged Cells

```python
# Read with data_only=True to get values, not formulas
wb = openpyxl.load_workbook(path, data_only=True)

# For merged cells, openpyxl returns None for non-top-left cells
# Forward-fill to populate merged regions
df = pd.read_excel(path, sheet_name="Table 2")
df["dimension"].fillna(method="ffill", inplace=True)
```

______________________________________________________________________

## Testing Requirements

### 1. Unit Tests (Mocked Data)

```python
def test_parse_deaths_demographics():
    """Test parsing with mocked Excel data"""
    mock_excel = create_mock_deaths_file()
    df = parse_deaths_demographics(mock_excel)

    assert "week_ending" in df.columns
    assert df["week_ending"].dtype == "datetime64[ns]"
    assert set(df["sex"].unique()) == {"Total", "Male", "Female"}


def test_validate_totals():
    """Test validation catches discrepancies"""
    df = pd.DataFrame(
        {
            "week_ending": ["2025-01-03"] * 3,
            "sex": ["Total", "Male", "Female"],
            "deaths": [100, 60, 50],  # Intentional mismatch
        }
    )
    with pytest.raises(ValidationError):
        validate_deaths_totals(df)
```

### 2. Integration Tests (Real Data - Optional)

```python
@pytest.mark.integration
@pytest.mark.skipif(not NISRA_TESTS_ENABLED, reason="Integration tests disabled")
def test_download_latest_deaths():
    """Test with real NISRA website (slow, can fail)"""
    url = get_latest_weekly_deaths_url()
    assert "nisra.gov.uk" in url
    assert ".xlsx" in url
```

### 3. Validation Tests

```python
def test_deaths_sum_validation():
    """Ensure disaggregated data sums to totals"""
    df = parse_deaths_demographics("/path/to/real/file.xlsx")

    # Test 1: Sex breakdown sums to total
    for week in df["week_ending"].unique():
        week_data = df[df["week_ending"] == week]
        total = week_data[week_data["sex"] == "Total"]["deaths"].sum()
        male_female = week_data[week_data["sex"].isin(["Male", "Female"])]["deaths"].sum()
        assert total == male_female, f"Week {week}: {total} != {male_female}"
```

______________________________________________________________________

## CLI Design Patterns

### Standard Command Structure

```bash
# Pattern: bolster nisra <dataset> <action> [options]

# Get latest data
bolster nisra deaths --latest --dimension demographics

# Get specific week/month/year
bolster nisra deaths --week 2025-01-03 --dimension all

# Export formats
bolster nisra deaths --latest --format csv
bolster nisra deaths --latest --format json
bolster nisra deaths --latest --format excel

# Cache control
bolster nisra deaths --latest --force-refresh
bolster nisra deaths --clear-cache
```

### Help Text Standards

```python
@click.command()
@click.option("--latest", is_flag=True, help="Get most recent data available")
@click.option(
    "--dimension",
    type=click.Choice(["demographics", "geography", "place", "all"]),
    default="all",
    help="Which dimension to retrieve",
)
@click.option("--format", type=click.Choice(["dataframe", "csv", "json", "excel"]), default="csv", help="Output format")
def nisra_deaths(latest, dimension, format):
    """
    NISRA Weekly Deaths Statistics

    Retrieves weekly death registrations in Northern Ireland with breakdowns by:
    - Demographics (age, sex)
    - Geography (Local Government Districts)
    - Place of death (hospital, home, care home, etc.)

    \b
    EXAMPLES:
        # Get latest demographics breakdown as CSV
        bolster nisra deaths --latest --dimension demographics

        # Get all dimensions as JSON
        bolster nisra deaths --latest --dimension all --format json

    \b
    DATA NOTES:
        - Based on registration date, not death occurrence date
        - Most deaths registered within 5 days
        - Weekly files are provisional and subject to revision
        - Dimensions are NOT cross-tabulated in source data

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/death-statistics/weekly-death-registrations-northern-ireland
    """
```

______________________________________________________________________

## Error Handling

### Graceful Degradation

```python
class NISRADataError(Exception):
    """Base exception for NISRA data errors"""

    pass


class NISRADataNotFoundError(NISRADataError):
    """Data file not available"""

    pass


class NISRAValidationError(NISRADataError):
    """Data validation failed"""

    pass


# Usage
try:
    df = get_latest_weekly_deaths()
except NISRADataNotFoundError as e:
    logger.error(f"Latest data not available: {e}")
    # Fall back to cached data
    df = get_cached_weekly_deaths()
except NISRAValidationError as e:
    logger.warning(f"Data validation failed: {e}")
    # Still return data but flag it
    df["_validation_warning"] = True
```

______________________________________________________________________

## Documentation Requirements

Each data source module must include:

1. **Module docstring** with:

   - Brief description of dataset
   - Update frequency
   - Geographic coverage
   - Available dimensions
   - Data source URL
   - Example usage

1. **Function docstrings** with:

   - Args and return types (with type hints)
   - Example code
   - Notes on data semantics (registration vs occurrence dates, etc.)

1. **README entry** with:

   - CLI examples
   - Python API examples
   - Link to official NISRA page
   - Known limitations

______________________________________________________________________

## Future Considerations

### Cross-Dataset Joining

When multiple datasets share common dimensions:

```python
# Join deaths geography with crime geography
deaths_geo = get_latest_deaths(dimension="geography")
crime_geo = get_latest_crime(dimension="geography")

# Both have 'lgd' column - can join on this
combined = deaths_geo.merge(crime_geo, on=["week_ending", "lgd"], how="outer")
```

Maintain **consistent naming** across datasets:

- LGD names (standardize formatting: "Derry City & Strabane" not "Derry City and Strabane")
- Date columns (`week_ending`, `month`, etc.)
- Age ranges (if different datasets use different breakpoints, document clearly)

### Time Series Alignment

Different datasets publish on different schedules:

- Deaths: Weekly
- Crime: Monthly
- Labour Market: Monthly
- Economic Indices: Quarterly

Consider helper functions for temporal alignment:

```python
def align_to_monthly(weekly_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate weekly data to monthly for comparison"""
    return weekly_df.resample("M", on="week_ending").sum()
```

______________________________________________________________________

## Checklist for New Data Source

- \[ \] Module created in `data_sources/nisra/`
- \[ \] URL pattern documented
- \[ \] Landing page scraper implemented
- \[ \] Download function with caching
- \[ \] Parser for each dimension
- \[ \] Validation against published totals
- \[ \] Unit tests with mocked data
- \[ \] CLI command added
- \[ \] Help text written
- \[ \] README examples added
- \[ \] Integration test (optional, can be skipped in CI)

______________________________________________________________________

**This document is living** - update as patterns emerge from implementing additional data sources.
