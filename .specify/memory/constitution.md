# Bolster Project Constitution

Derived from audit of 28+ existing data source modules. These conventions describe what the codebase actually does and therefore what new contributions must follow.

**Purpose**: This library provides standardized, reliable access to Northern Ireland and UK government data sources for data science, policy research, and civic analysis.

**Core Philosophy**: Data-first development. Every module must retrieve real, current data from authoritative sources. No synthetic data. No hardcoded URLs to point-in-time files. Modules scrape "mother pages" to discover the latest publication automatically.

## 1. Project Architecture Principles

### Package Management

- **uv only**: All Python operations use `uv run` (never `python`, `pip`, or `poetry`)
- **No legacy tools**: Do not use `requirements.txt`, `setup.py`, or `setup.cfg`
- **Single source of truth**: All dependencies in `pyproject.toml`

### Testing Philosophy

- **Real data only**: Tests download and validate current published data
- **Avoid mocking data sources**: Never mock external data sources; mocking specific in-module utilities is permissible in extreme cases
- **Data integrity focus**: Tests validate data quality, not just code paths
- **Coverage target**: 80% on new data paths, with pragmatic exemptions for error handling

### CLI Design

- **Useful and well-scoped CLIs**: Expose CLI commands when they provide clear standalone utility
- **Interface consolidation**: Look for opportunities to consolidate related commands rather than proliferating single-purpose commands
- **Rich output**: Use `rich` library for formatted tables and progress indicators
- **Not a hard requirement**: CLIs are encouraged but not mandatory for every module

### Mother Page Scraping

- **Never hardcode URLs to data files**: URLs change when publications update
- **Always scrape publication listings**: Find "mother pages" that list all publications for a topic
- **Navigate publication structure**: Mother page → publication detail page → Excel/CSV file
- **Fail explicitly**: Raise `*DataNotFoundError` if scraping fails, with context about what broke
- **No unstable sources**: If stable mother pages cannot be identified, we should not implement the data source - we are not a "source of truth" for unreliable or one-off datasets
- **Exception**: Extremely canonical and reliable hardcoded sources may be considered on a case-by-case basis

**Mother Page Pattern**:

```python
def get_latest_publication_url() -> str:
    """Scrape mother page to find latest data file.

    Navigates:
    1. Mother page (lists all publications)
    2. Publication detail page (links to files)
    3. Data file (Excel/CSV)
    """
    # Scrape mother page for publication link
    response = session.get(MOTHER_PAGE_URL, timeout=30)
    soup = BeautifulSoup(response.content, "html.parser")

    # Find specific publication
    pub_link = find_publication_link(soup, "Monthly Births")

    # Scrape publication page for data file
    pub_response = session.get(pub_link, timeout=30)
    excel_url = find_data_file(pub_response, ".xlsx")

    return excel_url
```

## 2. Module Docstring Structure

Every data source module opens with a docstring containing these sections, in order:

```python
"""Brief description of what the data source provides.

More detail about what the data includes, breakdowns available, and methodological notes.

Data Source:
    **Mother Page**: <URL to publication listing page>

    Explanation of navigation structure (mother → publication → file).
    Note about automatic scraping and why this ensures currency.

Update Frequency: How often the data is published (e.g., Monthly, Quarterly)
Geographic Coverage: Spatial scope (e.g., "Northern Ireland")

Example:
    >>> from bolster.data_sources.nisra import births
    >>> df = births.get_latest_births()
    >>> print(df.head())
"""
```

**Exemptions**: Utility modules (`validation.py`, `migration.py`) and `_base.py` describe computations, not data sources.

## 3. Function Naming Conventions

All public functions follow these prefixes:

| Prefix | Purpose | Example | Returns |
|--------|---------|---------|---------|
| `get_latest_*()` | Fetch most recent published data | `get_latest_births()` | `pd.DataFrame` or `Dict[str, pd.DataFrame]` |
| `get_latest_*_publication_url()` | Discover/scrape URL of latest file | `get_latest_births_publication_url()` | `str` (URL) |
| `parse_*_file(file_path)` | Parse a downloaded file into DataFrame | `parse_births_file(path)` | `pd.DataFrame` |
| `validate_*()` | Check data integrity | `validate_births_totals(df)` | `bool` (always) |

**Naming rules**:

- Internal helpers: prefix with `_`
- Compound names allowed: `get_latest_hotel_occupancy()` and `get_latest_ssa_occupancy()` in same module
- Be specific: `get_latest_births()` not `get_data()`

## 4. HTTP Requests

**Always use the shared session** — it has retry logic for transient failures:

```python
from bolster.utils.web import session

response = session.get(url, timeout=30)  # Retries on 500/502/503/504
```

**Never use `requests.get()` directly** — it lacks retry logic and causes CI flakiness.

**Exemptions**: Modules that don't make HTTP calls (`migration.py`, `validation.py`)

## 5. Logging

Every module that contains functions has:

```python
import logging

logger = logging.getLogger(__name__)
```

**No `print()` calls in library code** — use `logger.info()`, `logger.warning()`, `logger.error()` appropriately.

**Log levels**:

- `INFO`: Progress updates, data discovery (e.g., "Found publication: Monthly Births")
- `WARNING`: Unexpected but recoverable situations
- `ERROR`: Failures that will raise exceptions

## 6. Exception Hierarchy

Raise domain-specific exceptions, never bare `Exception`:

- **NISRA modules**: `NISRADataNotFoundError`, `NISRAValidationError` (from `nisra/_base.py`)
- **PSNI modules**: `PSNIDataNotFoundError`, `PSNIValidationError` (from `psni/_base.py`)
- **Standalone modules**: Use appropriate base exception for domain

**Exception messages must be actionable**:

```python
# Good: tells user what went wrong
raise NISRADataNotFoundError("Could not find 'Monthly Births' publication on mother page")

# Bad: generic, no context
raise Exception("Error occurred")
```

## 7. Validation Functions

Validation functions are encouraged to help derive insights for PR review and guide later usage, but are not a hard requirement:

```python
def validate_births_totals(df: pd.DataFrame) -> bool:
    """Validate that Male + Female births equal Persons for each month.

    Args:
        df: DataFrame from parse_births_file.

    Returns:
        True if validation passes.

    Raises:
        NISRAValidationError: If totals do not match.
    """
    for month in df["month"].unique():
        subset = df[df["month"] == month]
        male = subset[subset["sex"] == "Male"]["count"].sum()
        female = subset[subset["sex"] == "Female"]["count"].sum()
        persons = subset[subset["sex"] == "Persons"]["count"].sum()

        if abs((male + female) - persons) > 0.01:
            raise NISRAValidationError(f"Month {month}: Male ({male}) + Female ({female}) != Persons ({persons})")

    logger.info("Validation passed: Male + Female = Persons for all months")
    return True
```

**Validation types**:

- **Arithmetic checks**: Totals sum correctly, percentages add to 100
- **Range checks**: Values are plausible (no negative births, ages \< 150, etc.)
- **Completeness checks**: Expected time periods present (no missing months in time series)
- **Cross-dataset validation**: When multiple related datasets exist, check consistency

**When to include validation**:

- Domain-specific integrity checks exist (arithmetic relationships, known ranges)
- Validation helps document expected data properties
- Cross-dataset consistency can be verified

**When validation may be omitted**:

- No meaningful domain-specific checks beyond basic sanity
- Data is purely descriptive with no mathematical relationships

## 8. File Downloads

Use `download_file()` from the appropriate `_base.py`, not raw HTTP writes:

```python
from ._base import download_file

file_path = download_file(url, cache_ttl_hours=24, force_refresh=False)
```

**Cache TTL guidelines**:

- Daily/weekly data: 24 hours
- Monthly publications: `30 * 24` (720 hours)
- Annual/static data: `365 * 24` (8760 hours)

**Why caching matters**: Reduces load on NISRA/government servers, speeds up tests, enables offline development

## 9. Type Annotations

All public functions are fully type-annotated. Common return types:

| Return Type | When to Use | Example |
|-------------|-------------|---------|
| `pd.DataFrame` | Standard for single dataset | `get_latest_births()` |
| `Dict[str, pd.DataFrame]` | Multiple related datasets | `get_latest_occupancy()` returns `{"hotel": df1, "ssa": df2}` |
| `Union[pd.DataFrame, Dict[str, pd.DataFrame]]` | Parameter controls which | `get_latest_data(separate=True)` |
| `str` | URL discovery functions | `get_latest_publication_url()` |
| `bool` | Validation functions (always) | `validate_births_totals()` |

**No untyped `Any` in public function signatures** unless genuinely unavoidable.

## 10. CLI Integration

Data source modules that produce standalone-useful output expose at least one CLI command in `cli.py`:

```python
@cli.command()
@click.option(
    "--event-type",
    type=click.Choice(["registration", "occurrence"]),
    default="registration",
    help="Event type to retrieve",
)
def births(event_type):
    """Fetch latest NISRA birth registrations."""
    from bolster.data_sources.nisra import births

    df = births.get_latest_births(event_type=event_type)
    console.print(df.head(10))
```

**CLI design principles**:

- Use `click` for argument parsing
- Use `rich` for formatted output
- Provide helpful `--help` text
- Default to sensible options (e.g., most recent data)

**Exemptions**: Internal utility modules (`validation.py`, `migration.py`, `_base.py`)

## 11. Testing Standards

### Test File Naming

`test_<source>_<module>_integrity.py` (e.g., `test_nisra_births_integrity.py`)

### Test Structure

```python
class TestDataIntegrity:
    """Integration tests using real data — run once per class."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        """Download real data once for all tests in this class."""
        return module.get_latest_data()

    def test_required_columns(self, latest_data):
        """Verify expected columns present."""
        assert "month" in latest_data.columns

    def test_value_ranges(self, latest_data):
        """Check values are plausible."""
        assert (latest_data["count"] >= 0).all()


class TestValidation:
    """Unit tests for validation edge cases — no network calls needed."""

    def test_validate_empty_dataframe(self):
        """Validation should fail on empty DataFrame."""
        with pytest.raises(NISRAValidationError):
            validate_births_totals(pd.DataFrame())

    def test_validate_missing_columns(self):
        """Validation should fail if required columns missing."""
        df = pd.DataFrame({"wrong": [1, 2, 3]})
        with pytest.raises(NISRAValidationError):
            validate_births_totals(df)
```

### Testing Principles

- **Real data only**: No mocks for integration tests
- **`scope="class"` fixtures**: One network call per test class
- **Data integrity focus**: Tests validate data quality, not just code paths
- **Unit tests for validation**: Edge cases don't need network calls
- **Coverage pragmatism**: Error handling paths (try/except) acceptable to leave uncovered if mocking required

### Coverage Tips

- `codecov/patch` checks coverage on new/changed lines specifically
- Validation functions have easy-to-test edge cases (empty data, bad values, missing columns)
- Add unit tests for validation branches — they don't need network calls
- Error handling paths are harder to cover without mocks — acceptable to mark `# pragma: no cover`

## 12. Subpackage Organization

Create a subpackage (e.g., `nisra/tourism/`) when:

- Multiple related modules share common concepts (tourism has occupancy + visitors)
- Modules will likely grow together over time
- There's a clear domain boundary

Keep flat modules when the data source is standalone.

**Subpackage structure**:

```
nisra/
├── _base.py           # Shared utilities for all NISRA modules
├── births.py          # Standalone module
├── deaths.py          # Standalone module
└── tourism/           # Subpackage for related modules
    ├── __init__.py    # Exports for subpackage
    ├── occupancy.py   # Hotel and SSA occupancy
    └── visitor_statistics.py
```

## 13. Pre-commit Enforcement

All code must pass pre-commit checks before commit:

```bash
uv run pre-commit run --all-files
```

**Pre-commit hooks**:

- `ruff`: Linting and formatting (E, F, I rules)
- `trailing-whitespace`: Remove trailing whitespace
- `end-of-file-fixer`: Ensure files end with newline
- `check-yaml`: Validate YAML syntax

**Line length**: 120 characters (not 80 or 88)

## 14. Agent Workflows

This project defines three specialized agents for data source development:

### data-explore Agent

**Purpose**: Discover and evaluate new data sources before building.

**Workflow**:

1. Discover via RSS feed (`uv run bolster nisra feed --limit 20`)
1. Gap analysis (compare feed vs README coverage table)
1. Research accessibility, format, history
1. Validate assumptions with disposable scripts in `/tmp/`
1. Score on accessibility, stability, usefulness, complexity
1. Recommend with structured evaluation

**Key constraints**:

- Do NOT write production code
- Do NOT create files in `src/`
- Be honest about integration complexity

### data-build Agent

**Purpose**: Build production-quality modules with tests and CLI.

**Workflow**:

1. Check CI status (`gh pr list`, `gh run list`)
1. Branch (`git checkout -b feature/<name>`)
1. Study similar modules before writing
1. Implement: core module → exports → tests → CLI → README update
1. Quality checks: all tests pass, 80% coverage on new data paths, pre-commit clean
1. PR with insights from data (`gh pr create`)
1. Verify CI (`gh pr checks`)

**PR must include**:

- Summary of module functionality
- 2-3 example insights from the data
- Usage examples (Python and CLI)

### data-review Agent

**Purpose**: Review PRs for consistency, shared utilities, quality.

**Checklist**:

- CI passes (`gh pr checks`)
- Follows existing module patterns
- Uses shared utilities from `_base.py`
- Uses `web.session` for HTTP (not raw `requests.get()`)
- Type hints on public functions
- Real data tests (no mocks), `scope="class"` fixtures
- 80% coverage on new data paths
- ALL existing tests still pass
- CLI command added and documented
- README coverage table updated
- Pre-commit checks pass

**Opportunities**:

- Any repeated code that should be a shared utility?
- Any patterns that could be generalized?
- Cross-validation with related datasets?

## 15. Shared Utilities

### HTTP (`src/bolster/utils/web.py`)

- `session`: Shared HTTP session with retry logic

### NISRA (`src/bolster/data_sources/nisra/_base.py`)

- `download_file(url, cache_ttl_hours=24)`: Download with caching
- `make_absolute_url(url, base_url)`: Convert relative URLs
- `parse_month_year(str, format="%B %Y")`: Parse "April 2008" → Timestamp
- `add_date_columns(df, source_col)`: Add date/year/month columns
- `scrape_download_links(page_url)`: Find Excel links on a page
- `safe_int(value)`: Safely convert values to int, handling NaN/errors

### Exceptions

- `NISRADataNotFoundError`: Raised when scraping fails
- `NISRAValidationError`: Raised when data integrity checks fail
- `PSNIDataNotFoundError`, `PSNIValidationError`: PSNI equivalents

## 16. README Coverage Tracking

Maintain the "NISRA RSS Feed Coverage" table in README.md:

```markdown
| Publication | Module | Status |
|-------------|--------|--------|
| Labour Market Statistics | `nisra.labour_market` | ✅ |
| Weekly/Monthly Deaths | `nisra.deaths` | ✅ |
| Monthly Births/Stillbirths | `nisra.births` | ✅ |
| Security Situation Statistics | - | Planned |
```

Update this table whenever:

- A new module is added (✅)
- A new publication is discovered (Planned)
- A module is deprecated or removed

## 17. Python Version Support

**Supported versions**: Python 3.11+

**CI testing**: Python 3.11, 3.12, 3.13 tested in GitHub Actions

**Dependencies**: Must be compatible with all supported versions (avoid cutting-edge syntax from 3.14+)

## 18. Documentation Standards

### Docstrings

Follow Google style:

```python
def get_latest_births(event_type: Literal["registration", "occurrence"] = "registration") -> pd.DataFrame:
    """Fetch latest NISRA birth registrations.

    Args:
        event_type: Whether to return births by registration date or occurrence date.
            Defaults to 'registration'.

    Returns:
        DataFrame with columns: month, sex, event_type, count, date, year

    Raises:
        NISRADataNotFoundError: If latest publication cannot be found or downloaded.
        NISRAValidationError: If downloaded data fails integrity checks.

    Example:
        >>> from bolster.data_sources.nisra import births
        >>> df = births.get_latest_births(event_type='registration')
        >>> print(df.head())
    """
```

### Code Comments

- Explain *why*, not *what* (code should be self-documenting for *what*)
- Comment non-obvious business logic
- Comment mother page navigation steps
- Comment regex patterns for URL extraction

______________________________________________________________________

**This constitution is living documentation**: It evolves as patterns emerge, but changes require consensus. Propose amendments via PR with rationale grounded in actual codebase patterns.
