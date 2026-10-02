# Bolster Style Guide

The project's coding conventions — derived from auditing 28+ existing data
source modules, and the one canonical place to add a new one when a pattern
repeats across PRs. `AGENTS.md` covers workflow (the data-source agent
lifecycle, shared-utility catalog, release mechanics); this file covers code.

## Package Management

- `uv` only for all Python operations (`uv run`, `uv sync`) — never `python`,
  `pip`, or `poetry` directly.
- No `requirements.txt`, `setup.py`, or `setup.cfg`. All dependencies live in
  `pyproject.toml`.

## Module Docstring Structure

Every data source module opens with a docstring containing these sections,
in order:

```python
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

Utility modules (e.g. `validation.py`, `migration.py`) and `_base.py` are
exempt — they describe what they compute, not a data source.

### Mother-page discovery

Never hardcode a URL to a specific data file — publishers rename and
re-publish. Scrape the "mother page" that lists all publications for a topic
to find the latest one, every call:

```python
def get_latest_publication_url() -> str:
    """Scrape the mother page to find the latest data file."""
    response = session.get(MOTHER_PAGE_URL, timeout=30)
    soup = BeautifulSoup(response.content, "html.parser")
    pub_link = find_publication_link(soup, "Monthly Births")
    return make_absolute_url(pub_link, MOTHER_PAGE_URL)
```

If a source has no stable mother page to discover from, that's a reason not
to build the module at all, not a reason to hardcode a point-in-time URL.

## Function Naming

All public functions follow these prefixes:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `get_latest_*()` | Fetch most recent published data | `get_latest_births()` |
| `get_latest_*_publication_url()` | Discover/scrape URL of latest file | `get_latest_births_publication_url()` |
| `parse_*_file(file_path)` | Parse a downloaded file into a DataFrame | `parse_births_file(path)` |
| `validate_*()` | Check data integrity | `validate_births_totals(df)` |

Internal helpers are prefixed with `_`. Compound names are acceptable when a
single module covers multiple related datasets (e.g. `get_latest_hotel_occupancy()`
and `get_latest_ssa_occupancy()` in `occupancy.py`).

## Comments and Docstrings

Comments and docstrings describe **current reality only**. Three concrete
rules, in order of how often they actually come up:

1. **No narrative or history.** Never write what a function used to do, what
   was tried and found wrong, or a specific debugging example from the
   session that found a bug (a particular vehicle ID, a particular score
   comparison, "~22 min late"). That belongs in the git log and the PR
   description, where it stays attributable and doesn't rot the moment the
   next change lands — a reader can't tell which sentence in a docstring is
   still true once it starts narrating. This is easy to let slip during a
   long, live/iterative debugging session (that's the only place it's ever
   actually happened in this codebase) — when fixing something found live,
   write the *current* behavior and *why* it's correct, not the story of how
   you got there.
2. **No comments that just restate the next line in English.** `# Parse
   date` above `df["date"] = pd.to_datetime(...)` adds nothing a reasonably
   named variable doesn't already say. Only comment a genuinely non-obvious
   *why* — a hidden constraint, a workaround for a specific upstream quirk,
   an invariant that would surprise a reader.
3. **No fixed numbers presented as proof of a one-off finding.** "Tested
   against 8 vehicles" or "0.93 vs. the next candidate's 0.85" is evidence
   from one debugging session, not a fact about the code — if it matters,
   it belongs in a test assertion or the PR description, not narrated inline.
   This is **not** a ban on numbers in general: a stable cross-reference to a
   tracking issue as a pointer (e.g. "several modules independently
   reimplemented this, see issue #2176" in `utils/text.py`) is fine and
   common here — it doesn't rot the way a narrated measurement does.

**Exception**: a rare, deliberate decision-record comment in infra/config
(not application code) that exists specifically to stop a setting from being
re-litigated after it already thrashed back and forth in practice (see
`.github/workflows/pytest.yml`'s "Concurrency design" comment) is not a
violation of rule 1 — it's guarding against a real, demonstrated regression,
not narrating a function's behavior. Keep these rare.

## HTTP Requests

All HTTP calls go through the shared session:

```python
from bolster.utils.web import session

response = session.get(url, timeout=30)
```

Never use `requests.get()` directly — the shared session has retry logic for
transient failures. Modules that don't make HTTP calls (e.g. `migration.py`,
`validation.py`) are exempt.

### URL / hostname validation

When checking whether a scraped link belongs to a known, trusted domain,
compare the parsed hostname — never substring-contain the raw URL string:

```python
from bolster.utils.web import is_url_host

if is_url_host(href, "datavis.nisra.gov.uk"):
    ...
```

`"datavis.nisra.gov.uk" in href` also matches an attacker-controlled host
like `datavis.nisra.gov.uk.evil.com`, or the string appearing anywhere in a
path or query — CodeQL flags this, and it has been found and fixed in more
than one module independently. `is_url_host()` already exists in
`utils/web.py`; use it rather than re-deriving a check inline.

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

Exception messages are actionable (say what went wrong and where), not
generic.

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

Covers arithmetic checks (totals/percentages add up), range checks (plausible
values), completeness checks (no missing time periods), and cross-dataset
checks where related datasets exist. Utility modules (`validation.py`,
`_base.py`) are exempt.

## File Downloads

Use `download_file()` from the appropriate `_base.py`, not raw HTTP writes:

```python
from ._base import download_file

file_path = download_file(url, cache_ttl_hours=24, force_refresh=False)
```

Typical TTLs: 24 hours for daily/weekly data, `30 * 24` for monthly
publications, `365 * 24` for annual/static data.

## Return Types and Typing

All public functions are fully type-annotated. Common return types:

- `pd.DataFrame` — standard for data retrieval
- `Dict[str, pd.DataFrame]` — when returning multiple related datasets
- `Union[pd.DataFrame, Dict[str, pd.DataFrame]]` — when a parameter controls which
- `str` — URL discovery functions
- `bool` — validation functions (always)

No untyped `Any` in public function signatures.

## CLI Integration

Data source modules that produce standalone-useful output expose at least one
CLI command in `cli.py`, using `click` for arguments and `rich` for formatted
output. Internal utility modules (`validation.py`, `migration.py`,
`_base.py`) do not need CLI commands.

## Formatting and Supported Versions

- Line length 120 characters (`ruff` enforced — not 80 or 88).
- `uv run pre-commit run --all-files` must be clean before every push.
- Python 3.11, 3.12, 3.13 (`pyproject.toml`'s `requires-python`) — all three
  are in the CI matrix; don't rely on syntax newer than 3.11 supports.

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

- `scope="class"` fixtures (one network call per class).
- Real data only — no mocks for integration tests.
- Tests check data integrity, not just code paths.
- New code reaches >90% coverage (`codecov/patch`) — error-handling paths
  that would need a mock to exercise are a pragmatic exception.
