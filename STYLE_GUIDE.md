# Bolster Style Guide

This is the one canonical style guide for this project — the place to look
before asking "how do we do X here," and the place to add a rule when a
pattern repeats across PRs instead of restating it in a comment each time.

It has two parts: general Python conventions (aligned with current,
widely-used practice — not invented here), and this project's own
idiosyncrasies on top of them (derived from auditing 28+ existing data
source modules).

## General Python Conventions

These aren't Bolster-specific opinions — they're current, broadly-adopted
practice, included so the rationale is on record rather than assumed.

- **Docstrings follow [PEP 257](https://peps.python.org/pep-0257/)'s shape**
  (summary line, blank line, details) **in [Google's style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)**
  — `Args:`/`Returns:`/`Raises:` sections, not NumPy-style's wider tables.
  Google's is the more compact convention and what Sphinx's `napoleon`
  extension (used by this repo's docs build) is built to render.
- **Comments explain *why*, not *what*.** This is a named section of the
  Google Style Guide (§3.8), not a Bolster invention: "come as close to
  explaining the code as documenting it" is the failure mode it calls out —
  a comment that just narrates the next line in different words adds
  nothing a reasonably named variable doesn't already say. Comment the
  non-obvious: a hidden constraint, a workaround for a specific upstream
  quirk, an invariant that would surprise a reader.
- **[`ruff`](https://docs.astral.sh/ruff/) is the formatter and linter** —
  the current de facto standard, built as a single drop-in replacement for
  Flake8 + plugins, Black, isort, and pyupgrade. One tool, one config block
  in `pyproject.toml`, no separate `.flake8`/`.isort.cfg`/`setup.cfg`.
- **`src/` layout**, per the
  [Python Packaging User Guide](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/):
  it forces an installed/editable install to actually be importable, rather
  than accidentally working only because the working directory shadows it.
- **`pyproject.toml` is the single source of configuration** (PEP 518/621)
  — no `requirements.txt`, `setup.py`, or `setup.cfg`.
- **[Conventional Commits](https://www.conventionalcommits.org/) drive
  [SemVer](https://semver.org/)** releases automatically (see
  `CONTRIBUTING.rst`'s "Deploying" section for this repo's exact mapping).
- A few specific, checkable habits worth naming directly: no mutable
  default arguments (`def f(x=[])` — evaluated once at def-time, not per
  call; Ruff's `B006` flags this); `pathlib.Path` over string paths and
  `os.path`; f-strings over `.format()`/`%`; `raise NewError(...) from e`
  to chain an exception rather than losing the original traceback; type
  hints on every public function.

## Bolster-Specific Conventions

### Package management

- `uv` only for all Python operations (`uv run`, `uv sync`) — never
  `python`, `pip`, or `poetry` directly.

### Module docstring structure

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
re-publish. Scrape the "mother page" that lists all publications for a
topic to find the latest one, every call:

```python
def get_latest_publication_url() -> str:
    """Scrape the mother page to find the latest data file."""
    response = session.get(MOTHER_PAGE_URL, timeout=30)
    soup = BeautifulSoup(response.content, "html.parser")
    pub_link = find_publication_link(soup, "Monthly Births")
    return make_absolute_url(pub_link, MOTHER_PAGE_URL)
```

If a source has no stable mother page to discover from, that's a reason
not to build the module at all, not a reason to hardcode a point-in-time
URL.

### Function naming

All public functions follow these prefixes:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `get_latest_*()` | Fetch most recent published data | `get_latest_births()` |
| `get_latest_*_publication_url()` | Discover/scrape URL of latest file | `get_latest_births_publication_url()` |
| `parse_*_file(file_path)` | Parse a downloaded file into a DataFrame | `parse_births_file(path)` |
| `validate_*()` | Check data integrity | `validate_births_totals(df)` |

Internal helpers are prefixed with `_`. Compound names are acceptable when
a single module covers multiple related datasets (e.g.
`get_latest_hotel_occupancy()` and `get_latest_ssa_occupancy()` in
`occupancy.py`).

### Comments and docstrings: no narrative, no fixed proof-numbers

This extends the "why, not what" convention above with two project-specific
rules, both found necessary the hard way during a long live-debugging
session:

1. **No narrative or history.** Never write what a function used to do,
   what was tried and found wrong, or a specific debugging example from the
   session that found a bug (a particular vehicle ID, a particular score
   comparison, "~22 min late"). That belongs in the git log and the PR
   description, where it stays attributable and doesn't rot the moment the
   next change lands — a reader can't tell which sentence in a docstring is
   still true once it starts narrating. This is easy to let slip during a
   long, live/iterative debugging session (that's the only place it's ever
   actually happened in this codebase) — when fixing something found live,
   write the *current* behavior and *why* it's correct, not the story of
   how you got there.
1. **No fixed numbers presented as proof of a one-off finding.** "Tested
   against 8 vehicles" or "0.93 vs. the next candidate's 0.85" is evidence
   from one debugging session, not a fact about the code — if it matters,
   it belongs in a test assertion or the PR description, not narrated
   inline. This is **not** a ban on numbers in general: a stable
   cross-reference to a tracking issue as a pointer (e.g. "several modules
   independently reimplemented this, see issue #2176" in `utils/text.py`)
   is fine and common here — it doesn't rot the way a narrated measurement
   does.

**Exception**: a rare, deliberate decision-record comment in infra/config
(not application code) that exists specifically to stop a setting from
being re-litigated after it already thrashed back and forth in practice
(see `.github/workflows/pytest.yml`'s "Concurrency design" comment) is not
a violation of rule 1 — it's guarding against a real, demonstrated
regression, not narrating a function's behavior. Keep these rare.

### HTTP requests

All HTTP calls go through the shared session:

```python
from bolster.utils.web import session

response = session.get(url, timeout=30)
```

Never use `requests.get()` directly — the shared session has retry logic
for transient failures. Modules that don't make HTTP calls (e.g.
`migration.py`, `validation.py`) are exempt.

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

### Logging

Every module that contains functions has:

```python
import logging

logger = logging.getLogger(__name__)
```

No `print()` calls in library code — use `logger.info()`,
`logger.warning()`, `logger.error()` appropriately.

### Exception hierarchy

Raise domain-specific exceptions, never bare `Exception`:

- NISRA modules: `NISRADataNotFoundError`, `NISRAValidationError` (from `nisra/_base.py`)
- PSNI modules: `PSNIDataNotFoundError`, `PSNIValidationError` (from `psni/_base.py`)
- Standalone modules (e.g. `wikipedia.py`, `cineworld.py`) may use the most
  appropriate base exception for their domain.

Exception messages are actionable (say what went wrong and where), not
generic.

### Validation functions

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

Covers arithmetic checks (totals/percentages add up), range checks
(plausible values), completeness checks (no missing time periods), and
cross-dataset checks where related datasets exist. Utility modules
(`validation.py`, `_base.py`) are exempt.

### File downloads

Use `download_file()` from the appropriate `_base.py`, not raw HTTP writes:

```python
from ._base import download_file

file_path = download_file(url, cache_ttl_hours=24, force_refresh=False)
```

Typical TTLs: 24 hours for daily/weekly data, `30 * 24` for monthly
publications, `365 * 24` for annual/static data.

### Return types and typing

Common return types:

- `pd.DataFrame` — standard for data retrieval
- `Dict[str, pd.DataFrame]` — when returning multiple related datasets
- `Union[pd.DataFrame, Dict[str, pd.DataFrame]]` — when a parameter controls which
- `str` — URL discovery functions
- `bool` — validation functions (always)

No untyped `Any` in public function signatures.

### CLI integration

Data source modules that produce standalone-useful output expose at least
one CLI command in `cli.py`, using `click` for arguments and `rich` for
formatted output. Internal utility modules (`validation.py`,
`migration.py`, `_base.py`) do not need CLI commands.

### Formatting and supported versions

- Line length 120 characters (`ruff` enforced — not 80 or 88).
- `uv run pre-commit run --all-files` must be clean before every push.
- Python 3.11, 3.12, 3.13 (`pyproject.toml`'s `requires-python`) — all
  three are in the CI matrix; don't rely on syntax newer than 3.11
  supports.

### Tests

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
- Coverage: locally, `pytest-cov`'s `fail_under = 80` (`pyproject.toml`)
  gates `make test`. On a PR, Codecov's `patch`/`project` checks aren't a
  fixed percentage — they fail only if coverage drops by more than 1%
  from the current baseline (`codecov.yml`, `target: auto`). Error-handling
  paths that would need a mock to exercise are a pragmatic exception either
  way.
