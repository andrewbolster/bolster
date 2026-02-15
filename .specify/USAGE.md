# Spec Kit Usage Guide for Bolster Project

This guide explains how to use GitHub Spec Kit for structured, specification-driven development of data source modules in the Bolster project.

## What is Spec Kit?

GitHub Spec Kit is a toolkit that enables **Spec-Driven Development (SDD)** - a structured approach where you define *what* you want to build before defining *how* to build it. This reduces rework, ensures alignment with project standards, and creates documentation as a byproduct.

## Core Workflow

```
/speckit.constitution → /speckit.specify → /speckit.plan → /speckit.tasks → /speckit.implement
```

### Optional Enhancement Commands

- `/speckit.clarify` - Ask structured questions before planning (use when requirements are ambiguous)
- `/speckit.analyze` - Cross-check consistency across artifacts (use before implementing)
- `/speckit.checklist` - Generate quality validation checklists (use after planning)

## Installation

Spec Kit is already installed in this project. Verify with:

```bash
specify version
```

The slash commands are available in Claude Code via the `.claude/commands/` directory.

## File Structure

Spec Kit creates and manages these directories:

```
.specify/
├── memory/
│   └── constitution.md       # Project principles and standards
├── scripts/                   # Automation scripts
│   └── bash/
│       ├── create-new-feature.sh
│       └── setup-plan.sh
└── templates/                 # Templates for specs, plans, tasks
    ├── spec-template.md
    ├── plan-template.md
    └── tasks-template.md

.claude/
└── commands/                  # Slash command definitions
    ├── speckit.constitution.md
    ├── speckit.specify.md
    ├── speckit.plan.md
    ├── speckit.tasks.md
    └── speckit.implement.md
```

## Using Spec Kit for Data Source Development

### Example: Implementing Migration and Population Projection Modules

Let's walk through using Spec Kit to implement two related NISRA data sources: migration estimates and population projections.

______________________________________________________________________

## Step 1: Review Constitution

**Command**: `/speckit.constitution`

**Purpose**: Ensure you understand project principles before starting.

**Prompt**:

```
Review the constitution and summarize the key principles for data source development.
What are the non-negotiable requirements for NISRA modules?
```

**Expected Output**:

- Summary of mother page scraping requirement
- Testing standards (real data, no mocks, scope="class")
- CLI integration requirement
- Validation function requirement
- Shared utilities to use (web.session, \_base.py functions)

**Action**: Read the constitution, confirm understanding. No files created yet.

______________________________________________________________________

## Step 2: Specify Requirements

**Command**: `/speckit.specify`

**Purpose**: Define *what* you want to build in detail.

**Prompt**:

```
I want to implement two NISRA data source modules:

1. **Migration Estimates** (nisra/migration.py)
   - Data: Net migration, immigration, emigration by year
   - Source: https://www.nisra.gov.uk/publications/migration-statistics
   - Format: Excel files with annual estimates
   - Update frequency: Annual
   - Validation: Net migration should equal immigration minus emigration

2. **Population Projections** (nisra/population_projections.py)
   - Data: Projected population by year, age group, sex
   - Source: https://www.nisra.gov.uk/publications/population-projections
   - Format: Excel files with projections to 2050
   - Update frequency: Biennial
   - Validation: Projections should show consistent trends, no negative values

Both modules should:
- Scrape mother pages to find latest publications
- Parse Excel files into pandas DataFrames
- Include comprehensive validation
- Expose CLI commands
- Have data integrity tests

Create a specification for these modules.
```

**Expected Output**: Creates `.specify/memory/specs/migration-and-projections.md` with:

- Functional requirements (what data to fetch, how to parse)
- Non-functional requirements (performance, caching, error handling)
- User stories (as a data analyst, I want to...)
- Acceptance criteria (when is it done?)
- Out of scope (what NOT to build)

**Action**: Review the spec, refine if needed, commit to git.

______________________________________________________________________

## Step 3: Clarify Ambiguities (Optional)

**Command**: `/speckit.clarify`

**Purpose**: Identify and resolve unclear requirements before planning.

**Prompt**:

```
Review the migration and projections spec. What assumptions need to be validated?
Are there any ambiguous requirements that could lead to rework?
```

**Expected Questions**:

- How should we handle multiple projection scenarios (baseline, high, low)?
- Should migration data include components (internal vs external migration)?
- What happens if mother page structure changes?
- Should projections be returned as a single DataFrame or separate DataFrames by scenario?

**Action**: Answer the questions, update the spec accordingly.

______________________________________________________________________

## Step 4: Create Implementation Plan

**Command**: `/speckit.plan`

**Purpose**: Define *how* to build it - technical decisions, architecture, tech stack.

**Prompt**:

```
Create an implementation plan for the migration and projections modules.

Use:
- Python 3.9+ (project requirement)
- pandas for DataFrames
- openpyxl for Excel parsing
- BeautifulSoup for web scraping
- Shared utilities from nisra/_base.py

Follow the established module pattern (see births.py as reference).

Include:
- Module structure (functions needed)
- Data flow (scraping → downloading → parsing → validation)
- Error handling strategy
- Testing approach
- CLI commands
```

**Expected Output**: Creates `.specify/memory/plans/migration-and-projections.md` with:

- **Architecture**: Module structure, function responsibilities
- **Tech Stack**: Libraries and versions to use
- **Data Contracts**: DataFrame schemas (columns, dtypes)
- **Implementation Phases**: What to build in what order
- **Testing Strategy**: Integration tests, unit tests, fixtures
- **CLI Design**: Command structure, arguments, output format
- **Research**: Links to example mother pages, Excel file formats

**Action**: Review the plan for consistency with constitution, commit to git.

______________________________________________________________________

## Step 5: Generate Quality Checklist (Optional)

**Command**: `/speckit.checklist`

**Purpose**: Create a validation checklist to ensure nothing is forgotten.

**Prompt**:

```
Generate a quality checklist for the migration and projections implementation.
```

**Expected Output**: Creates `.specify/memory/checklists/migration-and-projections.md` with:

```markdown
## Pre-Implementation Checklist
- [ ] Constitution reviewed and understood
- [ ] Spec covers all functional requirements
- [ ] Plan addresses all spec requirements
- [ ] Tech stack approved and available
- [ ] Similar modules reviewed for patterns

## Implementation Checklist
- [ ] Core module created (migration.py)
- [ ] Mother page scraping implemented
- [ ] Excel parsing implemented with robust error handling
- [ ] Validation functions with domain-specific checks
- [ ] Shared utilities used (web.session, download_file)
- [ ] Type hints on all public functions
- [ ] Docstrings with Data Source, Update Frequency, Example
- [ ] Logging with appropriate levels

## Testing Checklist
- [ ] Integration test class with scope="class" fixture
- [ ] Real data downloaded and validated
- [ ] Column presence tests
- [ ] Value range tests
- [ ] Arithmetic validation tests (immigration - emigration = net migration)
- [ ] Unit tests for validation edge cases
- [ ] All tests pass (`uv run pytest tests/ -v`)
- [ ] Coverage >90% (`uv run pytest --cov=src/bolster`)

## Quality Checklist
- [ ] Pre-commit checks pass (`uv run pre-commit run --all-files`)
- [ ] CLI command added to cli.py
- [ ] CLI command tested manually
- [ ] README coverage table updated
- [ ] __init__.py exports added
- [ ] No regression in existing tests

## PR Checklist
- [ ] Branch created (`git checkout -b feature/migration-projections`)
- [ ] Commits have clear messages
- [ ] PR includes 2-3 example insights from data
- [ ] PR includes Python and CLI usage examples
- [ ] CI checks pass (`gh pr checks`)
```

**Action**: Use this checklist during implementation to track progress.

______________________________________________________________________

## Step 6: Generate Actionable Tasks

**Command**: `/speckit.tasks`

**Purpose**: Break down the plan into specific, implementable tasks.

**Prompt**:

```
Generate a task list for implementing migration and projections modules.
Organize into phases and include acceptance criteria for each task.
```

**Expected Output**: Creates `.specify/memory/tasks/migration-and-projections.md` with:

```markdown
## Phase 1: Migration Module - Core Implementation

### Task 1.1: Create migration.py skeleton
**Description**: Create the basic module structure following the births.py pattern.
**Acceptance**:
- [ ] File created at src/bolster/data_sources/nisra/migration.py
- [ ] Module docstring with Data Source, Update Frequency, Geographic Coverage, Example
- [ ] Import statements (logging, pandas, openpyxl, BeautifulSoup, _base utilities)
- [ ] Logger configured
- [ ] Constants defined (MIGRATION_BASE_URL)

**Estimated Effort**: 15 minutes

### Task 1.2: Implement get_latest_migration_publication_url()
**Description**: Scrape mother page to find latest migration estimates file.
**Acceptance**:
- [ ] Function scrapes https://www.nisra.gov.uk/publications/migration-statistics
- [ ] Finds "Migration Estimates" publication link
- [ ] Navigates to publication page
- [ ] Finds latest Excel file (.xlsx)
- [ ] Returns absolute URL
- [ ] Raises NISRADataNotFoundError if scraping fails with clear error message
- [ ] Logs publication discovery at INFO level

**Estimated Effort**: 45 minutes

### Task 1.3: Implement parse_migration_file()
**Description**: Parse downloaded Excel file into DataFrame.
**Acceptance**:
- [ ] Function takes file_path parameter
- [ ] Loads Excel with openpyxl
- [ ] Identifies correct sheet (typically "Table 1" or similar)
- [ ] Parses data into DataFrame with columns: year, immigration, emigration, net_migration
- [ ] Handles header rows appropriately
- [ ] Converts values to appropriate dtypes (int for counts, datetime for year)
- [ ] Returns cleaned DataFrame

**Estimated Effort**: 60 minutes

### Task 1.4: Implement validate_migration_totals()
**Description**: Validate arithmetic consistency of migration data.
**Acceptance**:
- [ ] Function takes DataFrame parameter
- [ ] Checks: immigration - emigration = net_migration for each year
- [ ] Allows small floating point tolerance (< 0.01)
- [ ] Raises NISRAValidationError with specific year/values if validation fails
- [ ] Logs successful validation at INFO level
- [ ] Returns True on success

**Estimated Effort**: 30 minutes

### Task 1.5: Implement get_latest_migration()
**Description**: High-level function that orchestrates URL discovery, download, parse, validate.
**Acceptance**:
- [ ] Function has force_refresh parameter (default False)
- [ ] Calls get_latest_migration_publication_url()
- [ ] Calls download_file() with appropriate cache TTL (720 hours for monthly)
- [ ] Calls parse_migration_file()
- [ ] Calls validate_migration_totals()
- [ ] Returns validated DataFrame
- [ ] Type hints: -> pd.DataFrame

**Estimated Effort**: 15 minutes

## Phase 2: Migration Module - Testing

### Task 2.1: Create test_nisra_migration_integrity.py
**Description**: Write integration tests using real data.
**Acceptance**:
- [ ] File created at tests/test_nisra_migration_integrity.py
- [ ] TestDataIntegrity class with scope="class" fixture
- [ ] test_required_columns() - checks year, immigration, emigration, net_migration present
- [ ] test_value_ranges() - checks all counts >= 0
- [ ] test_historical_coverage() - checks at least 10 years of data
- [ ] test_arithmetic_consistency() - validates immigration - emigration = net_migration

**Estimated Effort**: 45 minutes

### Task 2.2: Create validation unit tests
**Description**: Test validation edge cases without network calls.
**Acceptance**:
- [ ] TestValidation class created
- [ ] test_validate_empty_dataframe() - raises NISRAValidationError
- [ ] test_validate_missing_columns() - raises NISRAValidationError
- [ ] test_validate_arithmetic_mismatch() - raises NISRAValidationError with clear message

**Estimated Effort**: 30 minutes

## Phase 3: Migration Module - Integration

### Task 3.1: Add CLI command
**Description**: Expose migration data via CLI.
**Acceptance**:
- [ ] Command added to src/bolster/cli.py
- [ ] Command name: `migration`
- [ ] Uses rich for formatted output
- [ ] Displays latest 10 rows by default
- [ ] Option: --all to show full dataset
- [ ] Help text explains what data is retrieved

**Estimated Effort**: 20 minutes

### Task 3.2: Update exports and README
**Description**: Make module discoverable.
**Acceptance**:
- [ ] migration added to src/bolster/data_sources/nisra/__init__.py
- [ ] README.md coverage table updated with ✅ for Migration Estimates
- [ ] Example usage added to README if appropriate

**Estimated Effort**: 10 minutes

## Phase 4: Population Projections Module - Core Implementation

### Task 4.1: Create population_projections.py skeleton
[Similar structure to Task 1.1, adapted for projections]

### Task 4.2: Implement get_latest_projections_publication_url()
[Similar structure to Task 1.2, adapted for projections]

### Task 4.3: Implement parse_projections_file()
**Description**: Parse Excel file with projection scenarios.
**Acceptance**:
- [ ] Handles multiple sheets (baseline, high, low scenarios)
- [ ] Returns Dict[str, pd.DataFrame] mapping scenario → DataFrame
- [ ] Each DataFrame has columns: year, age_group, sex, population
- [ ] Year range validated (should project to ~2050)

**Estimated Effort**: 90 minutes

### Task 4.4: Implement validate_projections()
**Acceptance**:
- [ ] Checks all population values >= 0
- [ ] Checks year range is continuous (no gaps)
- [ ] Checks baseline scenario exists
- [ ] Validates age groups are standard NISRA groupings

**Estimated Effort**: 45 minutes

### Task 4.5: Implement get_latest_projections()
**Acceptance**:
- [ ] Optional parameter: scenario (baseline, high, low, all)
- [ ] If scenario specified, returns single DataFrame
- [ ] If scenario='all', returns Dict[str, pd.DataFrame]
- [ ] Type hint: Union[pd.DataFrame, Dict[str, pd.DataFrame]]

**Estimated Effort**: 30 minutes

## Phase 5: Population Projections - Testing

[Similar structure to Phase 2, adapted for projections]

## Phase 6: Population Projections - Integration

[Similar structure to Phase 3, adapted for projections]

## Phase 7: Quality Assurance

### Task 7.1: Run full test suite
**Acceptance**:
- [ ] `uv run pytest tests/ -v` - all tests pass
- [ ] `uv run pytest --cov=src/bolster` - coverage >90% on new code
- [ ] No regressions in existing tests

**Estimated Effort**: 10 minutes + debugging time

### Task 7.2: Run pre-commit checks
**Acceptance**:
- [ ] `uv run pre-commit run --all-files` - no errors
- [ ] All code formatted with ruff
- [ ] No linting issues

**Estimated Effort**: 5 minutes

### Task 7.3: Manual CLI testing
**Acceptance**:
- [ ] `uv run bolster migration` - displays migration data correctly
- [ ] `uv run bolster projections` - displays projections correctly
- [ ] Help text clear and accurate

**Estimated Effort**: 10 minutes

## Phase 8: Pull Request

### Task 8.1: Create PR with insights
**Acceptance**:
- [ ] Branch created (`feature/migration-projections`)
- [ ] Commits have clear messages
- [ ] PR description includes:
  - Summary of what modules provide
  - 2-3 example insights from data (e.g., "Net migration peaked in 2008 at X")
  - Python usage examples
  - CLI usage examples
- [ ] CI checks pass (`gh pr checks`)

**Estimated Effort**: 30 minutes
```

**Action**: Use this task list to implement systematically, checking off items as you complete them.

______________________________________________________________________

## Step 7: Implement

**Command**: `/speckit.implement`

**Purpose**: Execute all tasks to build the feature.

**Prompt**:

```
Implement the migration and projections modules following the task list.
Work through Phase 1 first (migration core), then Phase 2 (migration tests),
then proceed to population projections phases.

After each phase, run tests to ensure no regressions.
```

**Expected Behavior**:
The agent will:

1. Create migration.py with all required functions
1. Create test file with integration and unit tests
1. Add CLI command
1. Update exports and README
1. Repeat for population projections
1. Run quality checks
1. Create PR with insights

**Action**: Review each file as it's created, run tests frequently, provide feedback if deviations occur.

______________________________________________________________________

## Step 8: Analyze Consistency (Optional)

**Command**: `/speckit.analyze`

**Purpose**: Validate that implementation matches spec and plan.

**Prompt**:

```
Analyze the migration and projections implementation for consistency.
Do the modules match the spec? Does the code follow the plan?
Are there any deviations from the constitution?
```

**Expected Output**: Creates `.specify/memory/analysis/migration-and-projections.md` with:

- Compliance matrix (spec requirement → implementation status)
- Constitution adherence check
- Deviations identified with severity
- Recommendations for fixes

**Action**: Address any high-severity deviations before merging.

______________________________________________________________________

## Advanced Spec Kit Usage

### Working with Multiple Features

Spec Kit supports organizing specs/plans/tasks by feature:

```bash
.specify/memory/
├── constitution.md
├── specs/
│   ├── migration-and-projections.md
│   ├── security-statistics.md
│   └── road-safety-dashboard.md
├── plans/
│   ├── migration-and-projections.md
│   └── security-statistics.md
└── tasks/
    ├── migration-and-projections.md
    └── security-statistics.md
```

**Naming convention**: Use descriptive, hyphenated names matching the feature branch.

### Spec Kit Scripts

Spec Kit includes automation scripts in `.specify/scripts/bash/`:

- **create-new-feature.sh**: Scaffold a new feature spec
- **setup-plan.sh**: Initialize planning workspace
- **update-agent-context.sh**: Refresh agent with latest specs

Usage:

```bash
.specify/scripts/bash/create-new-feature.sh security-statistics
```

### Integration with Git

Spec Kit artifacts are version-controlled alongside code:

```bash
git add .specify/memory/specs/migration-and-projections.md
git commit -m "spec: define migration and projections modules"
```

This creates a traceable history of requirements and decisions.

### Using Spec Kit with Existing Agent Workflows

The Bolster project has three specialized agents (data-explore, data-build, data-review).
Spec Kit complements these workflows:

**data-explore** → `/speckit.specify`

- Exploration findings feed into the specification
- Spec documents the "why build this" rationale

**data-build** → `/speckit.plan` + `/speckit.tasks` + `/speckit.implement`

- Plan captures technical decisions
- Tasks break down the build work
- Implementation follows the plan

**data-review** → `/speckit.analyze`

- Analysis validates the implementation against spec
- Catches deviations early

## Best Practices

### 1. Constitution First

Always review the constitution before starting a new feature. It defines non-negotiable standards.

### 2. Spec Before Code

Write the spec even for "small" features. It clarifies thinking and creates documentation.

### 3. Validate Assumptions Early

Use `/speckit.clarify` when requirements are ambiguous. Rework is expensive.

### 4. Commit Spec Artifacts

Specs, plans, and tasks are as important as code. Commit them to git.

### 5. Update Constitution Sparingly

Only update the constitution when you discover a pattern that should be universal. Propose amendments via PR.

### 6. Use Checklists

Quality checklists prevent forgotten steps (especially validation functions, CLI commands, README updates).

### 7. Analyze Before Merging

Run `/speckit.analyze` before creating a PR. Catch constitution violations early.

## Common Pitfalls

### Skipping Specification

**Problem**: Jumping straight to `/speckit.plan` without a spec.
**Fix**: Always create a spec first. Plans without specs lack context.

### Over-Specifying

**Problem**: 10-page specs for a 50-line module.
**Fix**: Keep specs focused. "What" not "how". Save technical details for the plan.

### Ignoring Constitution

**Problem**: Implementing without reviewing constitution, causing rework.
**Fix**: Start every feature with `/speckit.constitution`.

### Not Updating Tasks

**Problem**: Task list becomes stale as implementation evolves.
**Fix**: Update the task list when you discover missing tasks or complete tasks out of order.

## Troubleshooting

### Slash Commands Not Working

**Symptom**: `/speckit.specify` doesn't trigger anything in Claude Code.
**Fix**: Ensure `.claude/commands/` directory exists and contains `speckit.specify.md`.

### Constitution Not Respected

**Symptom**: Agent generates code that violates constitution.
**Fix**: Explicitly reference the constitution in your prompt: "Review the constitution first, then generate code."

### Spec Too Vague

**Symptom**: Plan asks clarifying questions instead of generating a plan.
**Fix**: Use `/speckit.clarify` to identify gaps, then update the spec with missing details.

## Summary

Spec Kit enables **specification-driven development** for the Bolster project:

1. **Constitution** - Non-negotiable project principles (mother page scraping, real data tests, CLI-first)
1. **Specify** - Define *what* to build (requirements, user stories, acceptance criteria)
1. **Plan** - Define *how* to build it (architecture, tech stack, data contracts)
1. **Tasks** - Break it down (actionable, phased work items)
1. **Implement** - Execute systematically (following plan, checking off tasks)

This workflow reduces rework, ensures consistency with project standards, and creates documentation as a natural byproduct.

**Next Steps**:

- Use `/speckit.specify` to define your next data source module
- Reference this guide when you need workflow reminders
- Update this guide if you discover better practices

______________________________________________________________________

**Version**: 1.0.0 | **Created**: 2026-02-15 | **Last Updated**: 2026-02-15
