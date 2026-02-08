# Bolster Project Constitution

Derived from audit of 28 existing data source modules. These conventions describe
what the codebase actually does and therefore what new contributions must follow.

## Module Docstring Structure

Every data source module opens with a docstring containing these sections, in order:

```
"""Brief description of what the data source provides.

More detail about what the data includes.

Data Source:
    URL and explanation of how/where data is sourced.

Update Frequency: How often the data is published.

Geographic Coverage: Spatial scope (e.g., "Northern Ireland").

Example:
    >>> from bolster.data_sources.nisra import births
    >>> df = births.get_latest_births()
"""
```

Utility modules (e.g. `validation.py`, `migration.py`) and `_base.py` are exempt —
they describe what they compute, not a data source.

## Function Naming

All public functions follow these prefixes:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `get_latest_*()` | Fetch most recent published data | `get_latest_births()` |
| `get_latest_*_publication_url()` | Discover/scrape URL of latest file | `get_latest_births_publication_url()` |
| `parse_*_file(file_path)` | Parse a downloaded file into a DataFrame | `parse_births_file(path)` |
| `validate_*()` | Check data integrity | `validate_births_totals(df)` |

Internal helpers are prefixed with `_`. Compound names are acceptable when a single
module covers multiple related datasets (e.g. `get_latest_hotel_occupancy()` and
`get_latest_ssa_occupancy()` in `occupancy.py`).

## HTTP Requests

All HTTP calls go through the shared session:

```python
from bolster.utils.web import session

response = session.get(url, timeout=30)
```

Never use `requests.get()` directly — the shared session has retry logic for
transient failures. Modules that don't make HTTP calls (e.g. `migration.py`,
`validation.py`) are exempt.

## Logging

Every module that contains functions has:

```python
import logging

logger = logging.getLogger(__name__)
```

No `print()` calls in library code — use `logger.info()`, `logger.warning()`,
`logger.error()` appropriately.

## Exception Hierarchy

Raise domain-specific exceptions, never bare `Exception`:

- NISRA modules: `NISRADataNotFoundError`, `NISRAValidationError` (from `nisra/_base.py`)
- PSNI modules: `PSNIDataNotFoundError`, `PSNIValidationError` (from `psni/_base.py`)
- Standalone modules (e.g. `wikipedia.py`, `cineworld.py`) may use the most
  appropriate base exception for their domain.

## Validation Functions

Every data source module has at least one `validate_*()` function:

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
        ...
    logger.info("Validation passed: ...")
    return True
```

Utility modules (`validation.py`, `_base.py`) are exempt.

## File Downloads

Use `download_file()` from the appropriate `_base.py`, not raw HTTP writes:

```python
from ._base import download_file

file_path = download_file(url, cache_ttl_hours=24, force_refresh=False)
```

TTL is typically 24 hours for daily/weekly data, `30 * 24` for monthly publications.

## Return Types

All public functions are fully type-annotated. Common return types:

- `pd.DataFrame` — standard for data retrieval
- `Dict[str, pd.DataFrame]` — when returning multiple related datasets
- `Union[pd.DataFrame, Dict[str, pd.DataFrame]]` — when a parameter controls which
- `str` — URL discovery functions
- `bool` — validation functions (always)

No untyped `Any` in public function signatures.

## CLI Integration

Data source modules that produce standalone-useful output expose at least one CLI
command in `cli.py`. Internal utility modules (`validation.py`, `migration.py`,
`_base.py`) do not need CLI commands.

## Tests

Test files are named `test_<source>_<module>_integrity.py` and follow:

```python
class TestDataIntegrity:
    @pytest.fixture(scope="class")
    def latest_data(self):
        return module.get_latest_data()

    def test_required_columns(self, latest_data): ...
    def test_value_ranges(self, latest_data): ...
```

- `scope="class"` fixtures (one network call per class)
- Real data only — no mocks for integration tests
- Tests check data integrity, not just code paths
