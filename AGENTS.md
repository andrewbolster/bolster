# Bolster Project

A Python utility library for Northern Ireland and UK data sources, providing standardized access to government statistics and public data.

## Project Structure

```
src/bolster/
├── data_sources/
│   ├── nisra/          # NI Statistics and Research Agency
│   │   ├── _base.py    # Shared utilities (download, parse, validate)
│   │   ├── tourism/    # Subpackage for related data (occupancy, visitors)
│   │   ├── deaths.py, births.py, marriages.py, ...
│   │   └── cancer_waiting_times.py
│   ├── psni/           # Police Service of NI
│   │   ├── _base.py    # PSNI shared utilities
│   │   └── road_traffic_collisions.py, crime_statistics.py
│   └── dva.py          # Driver and Vehicle Agency
├── utils/
│   ├── cache.py        # CachedDownloader (uses web.session)
│   ├── rss.py          # get_nisra_statistics_feed()
│   └── web.py          # HTTP session with retry logic
└── cli.py              # Click-based CLI
```

### When to create subpackages

Create a subpackage (e.g., `nisra/tourism/`) when:

- Multiple related modules share common concepts (e.g., tourism has occupancy + visitors)
- Modules will likely grow together over time
- There's a clear domain boundary

Keep flat modules when the data source is standalone.

## Commands

```bash
uv run pytest tests/ -v                              # Run tests
uv run pytest tests/ --cov=src/bolster               # With coverage
uv run pre-commit run --all-files                    # Lint/format
uv run bolster --help                                # CLI
```

## Standards

- **No mocks** - tests use real data with `scope="class"` fixtures
- **Pre-commit required** - ruff linting/formatting enforced
- **Type hints** - required for public functions
- **Docstrings** - Args, Returns, Example sections

## Shared Utilities

### HTTP utilities (`src/bolster/utils/web.py`)

**Always use the shared session for HTTP requests** - it has retry logic for transient failures:

```python
from bolster.utils.web import session

response = session.get(url, timeout=30)  # Retries on 500/502/503/504
```

Do NOT use raw `requests.get()` - it lacks retry logic and causes CI flakiness.

### NISRA utilities (`src/bolster/data_sources/nisra/_base.py`)

| Function | Purpose |
|----------|---------|
| `download_file(url, cache_ttl_hours=24)` | Download with caching (uses shared session) |
| `make_absolute_url(url, base_url)` | Convert relative URLs |
| `parse_month_year(str, format="%B %Y")` | Parse "April 2008" → Timestamp |
| `add_date_columns(df, source_col)` | Add date/year/month columns |
| `scrape_download_links(page_url)` | Find Excel links on a page |

______________________________________________________________________

# Data Source Agents

Three specialized agents for the data source development lifecycle.

## Agent: data-explore

**Purpose**: Discover and evaluate potential new data sources before building.

**Workflow**:

1. **Discover** - Use `uv run bolster nisra feed --limit 20` to see recent publications, check README coverage table
1. **Gap analysis** - Compare feed entries vs implemented modules
1. **Research** - For each candidate, evaluate accessibility, format, history
1. **Validate** - Write disposable scripts in `/tmp/` to test assumptions
1. **Score** - Rate on accessibility, stability, usefulness, complexity
1. **Recommend** - Output structured evaluation with next steps

**Key behaviors**:

- Do NOT write production code
- Do NOT create files in `src/`
- Disposable scripts only - never commit exploration code
- Be honest about integration complexity

**Output format**:

```markdown
## Data Source Evaluation: [Name]
- **Source**: [URL]
- **Format**: [Excel/CSV/API]
- **Accessibility**: X/5
- **Recommendation**: RECOMMENDED / MAYBE / NOT RECOMMENDED
- **Next steps**: [for data-build agent]
```

## Agent: data-build

**Purpose**: Build production-quality data source modules with tests and CLI.

**Workflow**:

1. **Check CI status** - Before starting, run `gh pr list` and `gh run list` to check for failing tests
1. **Branch** - `git checkout -b feature/<name>` (or use existing feature branch)
1. **Study patterns** - Read similar modules before writing
1. **Implement** in order:
   - Core module in `src/bolster/data_sources/<source>/`
   - Update `__init__.py` exports
   - Data integrity tests in `tests/test_<source>_<name>_integrity.py`
   - Cross-validation tests if related data exists
   - CLI command in `src/bolster/cli.py`
   - README coverage table update
1. **Quality checks**:
   - Run `uv run pytest tests/ -v` - ALL tests must pass (not just new ones)
   - Run `uv run pytest --cov=src/bolster` - >90% coverage on new code
   - Run `uv run pre-commit run --all-files` - must be clean
1. **PR** - Create with `gh pr create`, include insights from the data
1. **Verify CI** - After PR, run `gh pr checks` to confirm CI passes

**Module template**:

```python
from ._base import download_file, add_date_columns


def get_latest_publication_url() -> str: ...
def parse_data(file_path) -> pd.DataFrame: ...
def get_latest_data(force_refresh=False) -> pd.DataFrame: ...
def validate_data(df) -> bool: ...
```

**Test template**:

```python
class TestDataIntegrity:
    @pytest.fixture(scope="class")
    def latest_data(self):
        return module.get_latest_data()

    def test_required_columns(self, latest_data): ...
    def test_value_ranges(self, latest_data): ...
    def test_historical_coverage(self, latest_data): ...


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def test_validate_empty_dataframe(self): ...
    def test_validate_missing_columns(self): ...
    def test_validate_negative_values(self): ...
    def test_validate_too_few_records(self): ...
```

**Coverage tips**:

- `codecov/patch` checks coverage on new/changed lines specifically
- Validation functions have easy-to-test edge cases (empty data, bad values)
- Add unit tests for validation branches - they don't need network calls
- Error handling paths (try/except) are harder to cover without mocks - acceptable to leave uncovered

**PR must include**:

- Summary of what the module provides
- 2-3 example insights from the data
- Usage examples (Python and CLI)

## Agent: data-review

**Purpose**: Review PRs for consistency, shared utilities, and quality.

**Before reviewing**:

1. Run `gh pr list` to see open PRs
1. Run `gh pr checks <PR#>` to check CI status
1. If CI is failing, identify the failing tests before reviewing code

**Checklist**:

### CI Status

- \[ \] `gh pr checks` shows all checks passing
- \[ \] If checks fail, identify root cause before proceeding

### Code Quality

- \[ \] Follows existing module patterns
- \[ \] Uses shared utilities from `_base.py` (no reinventing)
- \[ \] Uses `web.session` for HTTP requests (not raw `requests.get()`)
- \[ \] Type hints on public functions
- \[ \] Docstrings with examples

### Testing

- \[ \] Real data tests (no mocks)
- \[ \] Uses `scope="class"` fixtures
- \[ \] Tests data integrity, not just code paths
- \[ \] >90% coverage on new code
- \[ \] ALL existing tests still pass (no regressions)

### Integration

- \[ \] CLI command added and documented
- \[ \] README coverage table updated
- \[ \] Pre-commit checks pass

### Opportunities

- \[ \] Any repeated code that should be a shared utility?
- \[ \] Any patterns that could be generalized?
- \[ \] Cross-validation with related datasets?

**Output**: Structured review with specific line references and suggestions.

______________________________________________________________________

# RSS Feed Discovery

## CLI Approach (Recommended)

```bash
# Show recent NISRA publications with formatted table
uv run bolster nisra feed --limit 20

# Alternative: use the RSS command directly
uv run bolster rss nisra-statistics --limit 20
```

## Module Approach (For Programmatic Use)

```python
from bolster.utils.rss import get_nisra_statistics_feed

feed = get_nisra_statistics_feed()
for entry in feed.entries:
    print(entry.title)
```

Current NISRA sources tracked in README.md coverage table.
