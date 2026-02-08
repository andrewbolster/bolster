# Copilot Instructions for Bolster Project

This is a Python data analysis library for Northern Ireland and UK government data sources. Help developers follow established patterns and maintain consistency across data source modules.

## Project Overview

- **Purpose**: Standardized access to UK/NI government statistics
- **Technology**: Python 3.9+, pandas, uv package manager, pytest testing
- **Architecture**: Modular data source collectors with shared utilities
- **Build**: `uv run pytest`, `uv run pre-commit run --all-files`, `make ready`

## Code Patterns to Follow

### Data Source Module Structure

Every data source module should follow this pattern:

```python
from ._base import download_file, add_date_columns  # Use shared utilities


def get_latest_publication_url() -> str:
    """Scrape/discover latest data URL dynamically."""


def parse_data(file_path: Path) -> pd.DataFrame:
    """Parse downloaded file into standardized DataFrame."""


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Main public API - get latest processed data."""


def validate_data(df: pd.DataFrame) -> bool:
    """Validate data integrity with domain-specific checks."""
```

### HTTP Requests - Critical Pattern

**ALWAYS use shared session for HTTP requests**:

```python
from bolster.utils.web import session  # Has retry logic

response = session.get(url, timeout=30)  # ✓ Correct
# NEVER use: requests.get(url)  # ✗ Wrong - causes CI failures
```

### Testing Patterns

- **Real data tests**: `scope="class"` fixtures, no mocks allowed
- **Integrity validation**: Check data ranges, totals, temporal continuity
- **Cross-validation**: Ensure totals equal sum of parts where applicable

```python
class TestDataIntegrity:
    @pytest.fixture(scope="class")
    def latest_data(self):
        return module.get_latest_data()

    def test_required_columns(self, latest_data):
        assert all(col in latest_data.columns for col in ["date", "value"])
```

## File Organization

### When to Create Subpackages

- **Subpackage**: Multiple related modules (e.g., `nisra/tourism/` for occupancy + visitors)
- **Flat module**: Standalone data sources (e.g., `dva.py`, `eoni.py`)

### Shared Utilities Pattern

Each subpackage has `_base.py` with:

- `download_file()` - file caching with TTL
- `make_absolute_url()` - URL resolution
- `parse_month_year()` - date parsing
- `add_date_columns()` - DataFrame date standardization

## CLI Integration

Add corresponding CLI commands for each data source:

```python
@click.group()
def nisra():
    """NISRA statistics commands."""


@nisra.command("births")
@click.option("--event-type", type=click.Choice(["registration", "occurrence"]))
def get_nisra_births(event_type):
    df = nisra_births.get_latest_births(event_type=event_type)
    console.print_json(df.to_json(orient="records", date_format="iso"))
```

## Quality Standards

### Documentation

- **Type hints**: Required for all public functions
- **Docstrings**: Args, Returns, Example sections in NumPy format
- **README updates**: Add new data sources to coverage table

### Error Handling

- Custom exception hierarchies (`NISRADataError`, `PSNIDataError`)
- Graceful handling of common data issues (missing values, format changes)
- Specific exceptions for different failure modes

### Performance & Caching

- File-based caching in `~/.cache/bolster/<namespace>/`
- Configurable TTL (typically 24-30 days for monthly data)
- Memory-efficient operations for large datasets
- HTTP timeouts and retry logic via shared session

## Security Considerations

- Never hardcode credentials or API keys
- Validate input sanitization for data parsing
- Handle sensitive data appropriately (PII, etc.)
- Use secure URL patterns for data discovery

## Development Workflow

- **Quality**: `uv run pre-commit run --all-files` before commits
- **Testing**: `uv run pytest --cov=bolster` (>90% coverage expected)
- **CLI**: `uv run bolster <command>` for testing commands
- **Ready**: `make ready` runs precommit + tests
