# Spec Kit Integration for Bolster Project

This directory contains GitHub Spec Kit configuration for specification-driven development of data source modules.

## Quick Start

### Using Spec Kit Slash Commands in Claude Code

1. **Review the constitution**:

   ```
   /speckit.constitution
   ```

   Summarizes project principles before starting any work.

1. **Create a specification**:

   ```
   /speckit.specify

   I want to implement a NISRA migration statistics module...
   ```

   Documents what you want to build (requirements, user stories).

1. **Create a plan**:

   ```
   /speckit.plan
   ```

   Defines how to build it (architecture, tech stack, data contracts).

1. **Generate tasks**:

   ```
   /speckit.tasks
   ```

   Breaks the plan into actionable, phased work items.

1. **Implement**:

   ```
   /speckit.implement
   ```

   Executes all tasks systematically.

## Directory Structure

```
.specify/
├── README.md                    # This file
├── USAGE.md                     # Comprehensive usage guide with examples
├── CONSTITUTION_CHANGES.md      # Explains constitution enhancements
├── memory/
│   ├── constitution.md          # Project constitutional principles
│   ├── constitution-template.md # Backup of original template
│   ├── specs/                   # Feature specifications
│   ├── plans/                   # Implementation plans
│   ├── tasks/                   # Task breakdowns
│   ├── analysis/                # Consistency analysis reports
│   └── checklists/              # Quality validation checklists
├── scripts/
│   └── bash/
│       ├── create-new-feature.sh
│       ├── setup-plan.sh
│       └── update-agent-context.sh
└── templates/
    ├── spec-template.md
    ├── plan-template.md
    ├── tasks-template.md
    ├── checklist-template.md
    └── constitution-template.md
```

## What is Spec Kit?

GitHub Spec Kit enables **Spec-Driven Development (SDD)** - a structured workflow where:

1. **Constitution** defines non-negotiable project principles
1. **Specifications** document *what* to build (requirements, acceptance criteria)
1. **Plans** define *how* to build it (architecture, tech stack, data contracts)
1. **Tasks** break it down into actionable work
1. **Implementation** executes systematically following the plan

Benefits:

- Reduces rework by clarifying requirements upfront
- Ensures consistency with project standards (constitution enforced)
- Creates documentation as a byproduct
- Enables structured AI-assisted development

## Available Slash Commands

### Core Workflow

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `/speckit.constitution` | Review/update project principles | Start of every feature |
| `/speckit.specify` | Create specification | Define what to build |
| `/speckit.plan` | Create implementation plan | Define how to build it |
| `/speckit.tasks` | Generate task breakdown | Plan the work |
| `/speckit.implement` | Execute tasks | Build the feature |

### Optional Enhancements

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `/speckit.clarify` | Identify ambiguous requirements | Before planning if unclear |
| `/speckit.analyze` | Cross-check consistency | Before implementation |
| `/speckit.checklist` | Generate quality checklist | After planning |

## Constitutional Principles

The Bolster project constitution defines these non-negotiable standards:

### 1. Data-First Development

Every module must retrieve real, current data from authoritative sources. No synthetic data. No hardcoded URLs to point-in-time files.

### 2. Mother Page Scraping

Modules scrape "mother pages" (publication listings) to discover the latest publication automatically. This ensures self-updating modules.

### 3. Real Data Testing

Tests download and validate current published data. No mocks for integration tests. `scope="class"` fixtures minimize network calls.

### 4. CLI-First Design

User-facing features expose CLI commands. Internal utilities exempt.

### 5. Package Management

`uv` only - never use pip, poetry, or requirements.txt.

### 6. Type Annotations

All public functions fully type-annotated. No untyped `Any`.

### 7. Validation Functions

Every data source module has at least one `validate_*()` function with domain-specific integrity checks.

### 8. Shared Utilities

Always use `web.session` for HTTP (has retry logic). Use utilities from `_base.py` (don't reinvent).

See `.specify/memory/constitution.md` for complete details.

## Integration with Bolster Agent Workflows

The Bolster project defines three specialized agents (see `AGENTS.md`):

- **data-explore**: Discover and evaluate new data sources
- **data-build**: Build production modules with tests and CLI
- **data-review**: Review PRs for consistency and quality

Spec Kit complements these workflows:

| Agent | Spec Kit Commands | Purpose |
|-------|-------------------|---------|
| data-explore | `/speckit.specify` | Document exploration findings as spec |
| data-build | `/speckit.plan`, `/speckit.tasks`, `/speckit.implement` | Structured implementation |
| data-review | `/speckit.analyze` | Validate implementation vs spec |

## Example Workflow: Implementing Migration Module

```
# 1. Review constitution
/speckit.constitution

# 2. Create specification
/speckit.specify

I want to implement a NISRA migration statistics module that:
- Scrapes https://www.nisra.gov.uk/publications/migration-statistics
- Parses Excel files with immigration, emigration, net migration
- Validates: immigration - emigration = net migration
- Exposes CLI command
- Includes data integrity tests

# 3. Create plan
/speckit.plan

Use:
- Python 3.9+
- pandas for DataFrames
- openpyxl for Excel
- BeautifulSoup for scraping
- Shared utilities from nisra/_base.py

Follow births.py pattern.

# 4. Generate tasks
/speckit.tasks

# 5. Implement
/speckit.implement

Implement the migration module following the task list.
Start with core module, then tests, then CLI.
```

This produces:

- `.specify/memory/specs/migration.md` (specification)
- `.specify/memory/plans/migration.md` (technical plan)
- `.specify/memory/tasks/migration.md` (task breakdown)
- `src/bolster/data_sources/nisra/migration.py` (implementation)
- `tests/test_nisra_migration_integrity.py` (tests)
- Updated CLI, README, exports

## Files to Commit

**Always commit**:

- `.specify/memory/constitution.md` (if updated)
- `.specify/memory/specs/*.md` (specifications are documentation)
- `.specify/memory/plans/*.md` (plans document decisions)
- `.specify/memory/tasks/*.md` (task lists show work breakdown)
- `.claude/commands/` (slash command definitions)

**Optionally commit**:

- `.specify/memory/analysis/*.md` (consistency reports, useful for audit)
- `.specify/memory/checklists/*.md` (quality checklists, useful for process)

**Do NOT commit**:

- Nothing - Spec Kit doesn't generate temp files

## Updating the Constitution

The constitution evolves as patterns emerge, but changes require consensus.

**Amendment Process**:

1. Identify a pattern worth codifying (not one-off)
1. Verify prevalence (exists in 3+ modules)
1. Document rationale grounded in actual codebase
1. Create PR updating `.specify/memory/constitution.md`
1. Also update `.claude/constitution.md` to match
1. Review by project maintainers
1. Merge if consensus reached

**Important**: Keep `.specify/memory/constitution.md` and `.claude/constitution.md` in sync.

## Documentation

- **USAGE.md**: Comprehensive guide with step-by-step examples
- **CONSTITUTION_CHANGES.md**: Explains enhancements to original constitution
- **memory/constitution.md**: The actual constitutional document
- **.claude/commands/speckit.\*.md**: Slash command definitions

## CLI Tool

Spec Kit includes a CLI for setup and management:

```bash
# Check installation
specify version

# Initialize new project (already done for this project)
specify init --here --ai claude

# Check prerequisites
specify check
```

## Best Practices

### 1. Constitution First

Always run `/speckit.constitution` before starting a new feature.

### 2. Spec Before Code

Write the spec even for "small" features. It clarifies thinking and creates documentation.

### 3. Validate Assumptions Early

Use `/speckit.clarify` when requirements are ambiguous. Rework is expensive.

### 4. Commit Spec Artifacts

Specs, plans, and tasks are as important as code. They document the *why*.

### 5. Use Checklists

Quality checklists prevent forgotten steps (validation functions, CLI commands, README updates).

### 6. Analyze Before Merging

Run `/speckit.analyze` before creating a PR. Catch constitution violations early.

## Common Issues

### Slash Commands Not Working

**Symptom**: `/speckit.specify` doesn't trigger anything.
**Fix**: Ensure `.claude/commands/` directory exists and contains `speckit.specify.md`.

### Constitution Not Respected

**Symptom**: Agent generates code violating constitution.
**Fix**: Explicitly reference: "Review the constitution first, then generate code."

### Spec Too Vague

**Symptom**: Plan asks clarifying questions instead of generating a plan.
**Fix**: Use `/speckit.clarify` to identify gaps, update spec with details.

## Resources

- **GitHub Spec Kit Repo**: https://github.com/github/spec-kit
- **Spec-Driven Development Blog**: https://developer.microsoft.com/blog/spec-driven-development-spec-kit
- **Bolster Constitution**: `.specify/memory/constitution.md`
- **Usage Guide**: `.specify/USAGE.md`

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────┐
│ Spec Kit Commands for Bolster Data Source Development      │
├─────────────────────────────────────────────────────────────┤
│ /speckit.constitution  │ Review project principles          │
│ /speckit.specify       │ Define what to build               │
│ /speckit.clarify       │ Identify ambiguities (optional)    │
│ /speckit.plan          │ Define how to build it             │
│ /speckit.checklist     │ Generate QA checklist (optional)   │
│ /speckit.tasks         │ Break down into tasks              │
│ /speckit.analyze       │ Check consistency (optional)       │
│ /speckit.implement     │ Execute implementation             │
└─────────────────────────────────────────────────────────────┘

Constitution Highlights:
  ✓ Mother page scraping (never hardcode URLs)
  ✓ Real data tests (no mocks, scope="class")
  ✓ CLI-first design (expose user-facing features)
  ✓ uv only (no pip, poetry)
  ✓ Validation functions required
  ✓ web.session for HTTP (retry logic)

Data Source Module Pattern:
  1. get_latest_*_publication_url() → scrape mother page
  2. parse_*_file(path) → parse Excel to DataFrame
  3. validate_*() → check data integrity
  4. get_latest_*() → orchestrate download + parse + validate

Testing Pattern:
  class TestDataIntegrity:
      @pytest.fixture(scope="class")
      def latest_data(self):
          return module.get_latest_data()

      def test_required_columns(self, latest_data): ...
      def test_value_ranges(self, latest_data): ...

  class TestValidation:
      def test_validate_empty_dataframe(self): ...
      def test_validate_missing_columns(self): ...
```

______________________________________________________________________

**Version**: 1.0.0 | **Created**: 2026-02-15 | **Updated**: 2026-02-15
