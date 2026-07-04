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
uv run pytest tests/ -q --no-cov                     # Quick local run (no coverage)
uv run pytest tests/ -q --cov=src/bolster --cov-report=xml:cov.xml  # Full run with coverage (required before push)
make test                                            # Same as above via Makefile
uv run pre-commit run --all-files                    # Lint/format
uv run bolster --help                                # CLI
```

**Coverage gate**: always run the full coverage suite before pushing. The `pre-push` hook in `.pre-commit-config.yaml` enforces this automatically when using `git push`. `cli.py` is omitted from coverage by design — confirm it's absent from `cov.xml` with `grep cli cov.xml` (should return nothing).

## Tool Preferences

- Use `uv run` for all Python commands (not `python` or `pip`)
- Use `gh` CLI for GitHub operations

## Git Workflow — IMPORTANT

**Never commit directly to `main`.** All changes must go through a PR:

1. `git checkout -b fix/<name>` (or `feat/<name>`)
1. Commit changes on the branch
1. `gh pr create` — include summary and any relevant issue references
1. Wait for CI to pass before merging

This applies even to small fixes. The only exception is post-merge follow-up commits already agreed with the user in the same session.

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

### NISRA PxStat API (`src/bolster/data_sources/nisra/pxstat.py`)

**Always check PxStat first for NISRA data** — it has no rate limits, no auth, and no CI flakiness.

```python
from bolster.data_sources.nisra.pxstat import read_dataset

df = read_dataset("WDTHS")  # Returns tidy DataFrame, UTF-8 BOM handled automatically
```

API endpoint: `https://ws-data.nisra.gov.uk/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{MATRIX}/CSV/1.0/en`

Discover available matrices at `https://data.nisra.gov.uk/` — 1116 datasets as of 2026-06.

**Prefer PxStat over Excel scraping** for any new NISRA module. Only fall back to Excel scraping when:

- The dataset is not in PxStat (check first with a quick GET)
- The required granularity (e.g. monthly births) is not available via the API
- The data is only published as PDF

### NISRA Excel scraping utilities (`src/bolster/data_sources/nisra/_base.py`)

Only use these when PxStat is not available for the dataset:

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

**Trigger**: Automatically on any open `data-source-candidate` issue that has no evaluation comment yet. Also invokable manually: "Use the data-explore agent to evaluate issue #NNN" or "evaluate all unevaluated data-source-candidate issues". Optionally, run `/nisra-feed-review` first to discover and create new `data-source-candidate` issues before evaluating.

**Workflow**:

1. **Find scope** - Run `gh issue list --label "data-source-candidate" --state open` to find candidate issues. If directed at a specific issue, use that; otherwise process all with no evaluation comment.
1. **Gap analysis** - Compare against README coverage table and existing modules in `src/bolster/data_sources/`
1. **Research** - For each candidate, evaluate accessibility, format, history. Check PxStat first (`https://data.nisra.gov.uk/`).
1. **Validate** - Write disposable scripts in `/tmp/` to test assumptions. Never commit these.
1. **Score** - Rate on accessibility, stability, usefulness, complexity
1. **Output** - Post evaluation as a comment on the `data-source-candidate` issue. Do not create new issues or modify `src/`.

**Key behaviors**:

- Do NOT write production code
- Do NOT create files in `src/`
- Disposable scripts only — never commit exploration code
- Be honest about integration complexity
- Always post output as a comment on the originating `data-source-candidate` issue

**Output format** (post as issue comment):

```markdown
## Data Source Evaluation: [Name]
- **Source**: [URL]
- **Format**: [Excel/CSV/API]
- **PxStat matrix**: [matrix code if available, e.g. WDTHS — or "not in PxStat"]
- **Accessibility**: X/5 (5 = PxStat API; 4 = direct file URL; 3 = scrape needed; 1-2 = Cloudflare/auth blocked)
- **Recommendation**: RECOMMENDED / MAYBE / NOT RECOMMENDED
- **Next steps**: [for data-build agent — use PxStat if available]
```

## Agent: data-build

**Purpose**: Build production-quality data source modules with tests and CLI.

**Trigger**: Invoked manually after a `data-explore` evaluation is marked RECOMMENDED on a `data-source-candidate` issue. "Use the data-build agent to implement issue #NNN" or "build the data source from issue #NNN".

**Workflow**:

1. **Find spec** - If directed at a specific issue, read it. Otherwise run `gh issue list --label "data-source-candidate" --state open` and find issues with a RECOMMENDED `data-explore` evaluation comment. Confirm with the user before proceeding if ambiguous.
1. **Check CI status** - Run `gh pr list` and `gh run list --limit 5` to confirm no failing tests on `main` before starting.
1. **Branch** - `git checkout -b feat/<name>` from a clean `main`.
1. **Study patterns** - Read 2-3 similar existing modules before writing any code.
1. **Implement in phases** — commit after each phase to enable safe rollback:
   - **Phase 1**: Core module in `src/bolster/data_sources/<source>/` + `__init__.py` exports. Commit: `feat(<name>): add core module`
   - **Phase 2**: Data integrity tests in `tests/test_<source>_<name>_integrity.py`. Run `uv run pytest tests/test_<source>_<name>_integrity.py -v` — must pass. Commit: `test(<name>): add integrity tests`
   - **Phase 3**: CLI command in `src/bolster/cli.py` + README coverage table update. Commit: `feat(<name>): add CLI command and update README`
   - **Phase 4** (if applicable): Cross-validation tests against related datasets. Commit: `test(<name>): add cross-validation`
1. **Quality checks** — before pushing:
   - `uv run pytest tests/ -q --no-cov` — ALL tests must pass, not just new ones
   - `make test` — >90% coverage on new code
   - `uv run pre-commit run --all-files` — must be clean
1. **PR** - Only push and `gh pr create` once all quality checks pass locally. Include 2-3 example insights from the data and link the originating `data-source-candidate` issue with `Closes #NNN`.
1. **Verify CI** - After PR, run `gh pr checks` to confirm CI passes. Do not merge until green.

**Module template (PxStat — preferred for NISRA)**:

```python
from .pxstat import read_dataset, PxStatError  # noqa: F401


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    # force_refresh ignored — PxStat always returns current data
    df = read_dataset("MATRIX_CODE")
    ...


def validate_data(df: pd.DataFrame) -> bool: ...
```

**Module template (Excel scraping — only when PxStat unavailable)**:

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

**Purpose**: Review open PRs that implement a `data-source-candidate` for consistency, shared utilities, and quality.

**Trigger**: Invoked manually against a specific PR: "Use the data-review agent to review PR #NNN". Also invokable as a batch: "review all open data-source PRs". Only review PRs that touch `src/bolster/data_sources/` — skip dependency bumps, CI changes, and documentation-only PRs.

**Before reviewing**:

1. Confirm the PR implements or modifies a data source (touches `src/bolster/data_sources/`). If not, skip.
1. Run `gh pr checks <PR#>` to check CI status — if checks are still running, wait; if failing, identify the root cause before proceeding.
1. Read the linked `data-source-candidate` issue (if any) to understand the intended scope.

**Checklist**:

### CI Status

- \[ \] `gh pr checks` shows all checks passing
- \[ \] If checks fail, identify root cause before proceeding

### Code Quality

- \[ \] Follows existing module patterns (compare to a similar module in `src/bolster/data_sources/`)
- \[ \] Uses shared utilities from `_base.py` or `pxstat.py` (no reinventing)
- \[ \] For NISRA data: uses `pxstat.read_dataset()` if the matrix exists; falls back to `_base.download_file()` only if not in PxStat
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
- \[ \] `data-source-candidate` issue referenced with `Closes #NNN`

### Opportunities

- \[ \] Any repeated code that should be a shared utility?
- \[ \] Any patterns that could be generalized?
- \[ \] Cross-validation with related datasets?

**Output**: Post a structured review as a PR review comment with specific file:line references. Use GitHub's review API via `gh pr review <PR#> --comment --body "..."`. Do not approve or request changes — comment only.

## Agent: data-maintenance

**Purpose**: Review recently merged PRs to keep documentation current and surface emerging shared utility candidates as actionable issues.

**Trigger**: Runs on a monthly schedule (first Monday of each month). Also invokable manually: "Use the data-maintenance agent to review last month's merges".

**Workflow**:

1. **Find scope** - Run `gh pr list --state merged --base main --limit 50 --json number,title,mergedAt,labels` and filter to PRs merged in the last 30 days. Skip PRs labelled `version:skip`, `dependencies`, or `documentation`.
1. **README audit** - For each merged PR that touches `src/bolster/data_sources/`, verify:
   - The new module appears in the README coverage table
   - The CLI command is documented (`uv run bolster --help` output matches)
   - `docs/data_sources.rst` references the new module
     If any are missing, open a single `gh issue create --label "documentation"` issue listing all gaps found.
1. **Shared utility scan** - Read the diff of each qualifying PR (`gh pr diff <PR#>`). Look for:
   - Repeated patterns across ≥2 PRs (URL construction, date parsing, Excel sheet discovery, pagination)
   - Code in a module that duplicates something already in `_base.py`, `pxstat.py`, `utils/web.py`, or `utils/cache.py`
   - New helper functions defined inline that belong in a shared utility
     For each identified pattern, open a `gh issue create --label "enhancement"` issue describing the candidate utility, which PRs introduced the pattern, and a sketch of the proposed API.
1. **Summary** - Open a single `gh issue create --label "maintenance"` issue titled "Monthly Maintenance Review — <Month Year>" linking all issues raised (or noting "nothing to report" if clean).

**Key behaviors**:

- Read-only on code — do NOT open PRs or modify `src/`
- Open the minimum number of issues needed — batch documentation gaps into one issue, not one per module
- Be conservative on shared utility candidates — only flag patterns seen in ≥2 separate PRs
- Do not re-raise issues that are already open with the same label and similar title

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
