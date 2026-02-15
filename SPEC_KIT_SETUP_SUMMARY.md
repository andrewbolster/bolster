# GitHub Spec Kit Setup Summary

**Date**: 2026-02-15
**Project**: Bolster Python Library
**Completed by**: Claude Sonnet 4.5

______________________________________________________________________

## What Was Done

GitHub Spec Kit has been successfully installed and configured for the Bolster project to enable **specification-driven development** of data source modules.

## Installation Steps Completed

### 1. Installed Spec Kit CLI

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```

**Location**: `/home/bolster/.local/bin/specify`

**Verification**:

```bash
specify --help
# Shows Spec Kit commands: init, check, version, extension
```

### 2. Initialized Spec Kit in Project

```bash
specify init --here --ai claude
```

**Created directories**:

- `.specify/` - Spec Kit workspace
- `.claude/commands/` - Slash command definitions

**Merged with existing**:

- `.claude/` directory already existed with agents and constitution
- Spec Kit commands added alongside existing project structure

### 3. Enhanced Constitution

Created comprehensive constitutional document based on audit of 28+ existing modules.

**Location**: `.specify/memory/constitution.md`

**Also updated**: `.claude/constitution-proposed.md` (for review before replacing original)

**Key additions**:

- Mother page scraping architecture (core principle)
- Data-first testing philosophy
- CLI-first design standards
- Agent workflow integration
- Quality process documentation
- Validation standards with examples
- Governance process

### 4. Created Documentation

Comprehensive guides for using Spec Kit with Bolster workflows:

- `.specify/README.md` - Quick start and reference
- `.specify/USAGE.md` - Step-by-step guide with examples
- `.specify/CONSTITUTION_CHANGES.md` - Explains enhancements to original constitution

### 5. Updated .gitignore

Added Spec Kit guidance (commit specs/plans/tasks, don't ignore .claude/).

______________________________________________________________________

## What Spec Kit Provides

### Slash Commands Available in Claude Code

| Command | Purpose |
|---------|---------|
| `/speckit.constitution` | Review/update project principles |
| `/speckit.specify` | Create feature specification |
| `/speckit.plan` | Create implementation plan |
| `/speckit.tasks` | Generate task breakdown |
| `/speckit.implement` | Execute implementation |
| `/speckit.clarify` | Identify ambiguous requirements (optional) |
| `/speckit.analyze` | Cross-check consistency (optional) |
| `/speckit.checklist` | Generate quality checklist (optional) |

### Directory Structure Created

```
.specify/
├── README.md                    # Quick start guide
├── USAGE.md                     # Comprehensive examples
├── CONSTITUTION_CHANGES.md      # Enhancement summary
├── memory/
│   ├── constitution.md          # Enhanced constitution
│   ├── constitution-template.md # Original template backup
│   ├── specs/                   # Feature specifications (empty, ready for use)
│   ├── plans/                   # Implementation plans (empty)
│   ├── tasks/                   # Task breakdowns (empty)
│   ├── analysis/                # Consistency reports (empty)
│   └── checklists/              # Quality checklists (empty)
├── scripts/
│   └── bash/
│       ├── create-new-feature.sh
│       ├── setup-plan.sh
│       ├── update-agent-context.sh
│       ├── check-prerequisites.sh
│       └── common.sh
└── templates/
    ├── spec-template.md
    ├── plan-template.md
    ├── tasks-template.md
    ├── checklist-template.md
    └── constitution-template.md

.claude/
└── commands/                    # Slash command definitions
    ├── speckit.constitution.md
    ├── speckit.specify.md
    ├── speckit.plan.md
    ├── speckit.tasks.md
    ├── speckit.implement.md
    ├── speckit.clarify.md
    ├── speckit.analyze.md
    ├── speckit.checklist.md
    └── speckit.taskstoissues.md
```

______________________________________________________________________

## Constitutional Principles Documented

The enhanced constitution makes these implicit practices **explicit**:

### 1. Data-First Development

Every module retrieves real, current data from authoritative sources. No synthetic data. No hardcoded URLs.

### 2. Mother Page Scraping

Modules scrape publication listing pages ("mother pages") to discover the latest file automatically. This ensures self-updating modules that don't break when new publications are released.

**Pattern**:

```python
# Mother page → Publication detail → Data file
mother_page = "https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/births"
pub_link = find_publication_link(soup, "Monthly Births")
excel_url = find_data_file(pub_response, ".xlsx")
```

### 3. Real Data Testing

Tests download and validate current published data. No mocks for integration tests. Use `scope="class"` fixtures to minimize network calls.

### 4. CLI-First Design

User-facing features expose CLI commands. Internal utilities exempt.

### 5. Validation Functions Required

Every data source module has at least one `validate_*()` function with domain-specific integrity checks (arithmetic, ranges, completeness).

### 6. Package Management

`uv` only - never use pip, poetry, or requirements.txt.

### 7. Shared Utilities

Always use `web.session` for HTTP (has retry logic). Use utilities from `_base.py`.

### 8. Type Annotations

All public functions fully type-annotated. No untyped `Any`.

______________________________________________________________________

## How to Use Spec Kit

### Example: Implementing Migration Statistics Module

```
# 1. Review constitution
/speckit.constitution

# 2. Create specification
/speckit.specify

I want to implement a NISRA migration statistics module that:
- Scrapes https://www.nisra.gov.uk/publications/migration-statistics
- Parses Excel files with immigration, emigration, net migration
- Validates: immigration - emigration = net migration
- Exposes CLI command: `uv run bolster migration`
- Includes data integrity tests with real data

# 3. Create implementation plan
/speckit.plan

Use:
- Python 3.9+, pandas, openpyxl, BeautifulSoup
- Shared utilities from nisra/_base.py
- Follow births.py pattern

# 4. Generate task breakdown
/speckit.tasks

# 5. Implement systematically
/speckit.implement

Implement the migration module following the task list.
```

**Output**:

- `.specify/memory/specs/migration.md` - Specification
- `.specify/memory/plans/migration.md` - Technical plan
- `.specify/memory/tasks/migration.md` - Task breakdown
- `src/bolster/data_sources/nisra/migration.py` - Implementation
- `tests/test_nisra_migration_integrity.py` - Tests
- Updated CLI, README, exports

______________________________________________________________________

## Integration with Existing Agent Workflows

The Bolster project has three specialized agents (see `AGENTS.md`):

| Agent | Role | Spec Kit Integration |
|-------|------|---------------------|
| **data-explore** | Discover and evaluate new data sources | `/speckit.specify` - Document findings as spec |
| **data-build** | Build production modules | `/speckit.plan`, `/speckit.tasks`, `/speckit.implement` |
| **data-review** | Review PRs for quality | `/speckit.analyze` - Validate implementation |

**Workflow enhancement**:

- **Before Spec Kit**: Developers learned patterns by reading code, discovered standards through PR feedback
- **After Spec Kit**: Constitution guides from the start, specs document decisions, plans ensure consistency

______________________________________________________________________

## Constitution Review and Approval

### Current Status

- **Enhanced constitution**: `.specify/memory/constitution.md` (installed and ready)
- **Proposed for review**: `.claude/constitution-proposed.md` (same content, for comparison)
- **Original constitution**: `.claude/constitution.md` (still in place)

### Recommendation: Replace Original Constitution

**Action**:

```bash
# Review the proposed constitution
cat .claude/constitution-proposed.md

# If approved, replace original
cp .specify/memory/constitution.md .claude/constitution.md

# Commit both
git add .claude/constitution.md .specify/memory/constitution.md
git commit -m "docs: enhance constitution with Spec Kit integration

- Add mother page scraping architecture
- Document data-first testing philosophy
- Clarify CLI-first design principles
- Integrate agent workflows
- Add validation standards
- Document quality process"
```

### What Changed

The enhanced constitution **doesn't change practices**, it **documents implicit knowledge**:

- Mother page scraping (was implicit, now explicit)
- Real data testing rationale (was implicit, now explained)
- CLI-first design (was followed, now required)
- Validation standards (examples → categories)
- Agent workflows (documented integration)
- Quality process (comprehensive checklist)

**See**: `.specify/CONSTITUTION_CHANGES.md` for detailed comparison.

______________________________________________________________________

## Next Steps

### Immediate Actions

1. **Review the enhanced constitution**:

   ```bash
   cat .specify/memory/constitution.md
   # or
   cat .claude/constitution-proposed.md
   ```

1. **Read the usage guide**:

   ```bash
   cat .specify/USAGE.md
   ```

1. **Decide on constitution**:

   - If approved: `cp .specify/memory/constitution.md .claude/constitution.md`
   - If amendments needed: Edit `.specify/memory/constitution.md`, then copy

1. **Commit Spec Kit setup**:

   ```bash
   git add .specify/ .claude/commands/ .gitignore
   git commit -m "feat: add GitHub Spec Kit for specification-driven development"
   ```

### Using Spec Kit for Next Data Source Module

**Scenario**: You want to implement migration statistics and population projections modules.

**Workflow**:

```
# Start with constitution review
/speckit.constitution

# Create specification
/speckit.specify
[Describe what you want to build]

# Create implementation plan
/speckit.plan

# Generate tasks
/speckit.tasks

# Implement systematically
/speckit.implement
```

**See**: `.specify/USAGE.md` for complete step-by-step example.

### Integration with Development Workflow

**Before (without Spec Kit)**:

1. Read AGENTS.md → understand workflow
1. Read existing modules → learn patterns
1. Implement → discover standards through PR feedback
1. 3-4 rounds of review → align with implicit practices

**After (with Spec Kit)**:

1. `/speckit.constitution` → understand standards upfront
1. `/speckit.specify` → document requirements
1. `/speckit.plan` → technical decisions respecting constitution
1. `/speckit.implement` → constitution-compliant code from start
1. 1 round of review → only domain-specific feedback

______________________________________________________________________

## Files Created/Modified

### Created

- `.specify/README.md` - Quick start guide
- `.specify/USAGE.md` - Comprehensive usage examples
- `.specify/CONSTITUTION_CHANGES.md` - Enhancement summary
- `.specify/memory/constitution.md` - Enhanced constitution
- `.specify/memory/constitution-template.md` - Original template backup
- `.specify/scripts/bash/*.sh` - Automation scripts
- `.specify/templates/*.md` - Spec/plan/task templates
- `.claude/commands/speckit.*.md` - Slash command definitions (9 commands)
- `.claude/constitution-proposed.md` - Enhanced constitution for review
- `SPEC_KIT_SETUP_SUMMARY.md` - This document

### Modified

- `.gitignore` - Added Spec Kit guidance

### Existing (Preserved)

- `.claude/constitution.md` - Original constitution (still in place)
- `.claude/agents/` - Existing agent configurations (unchanged)
- `.claude/rules/` - Existing rules (unchanged)

______________________________________________________________________

## Resources

### Documentation

- **Quick Start**: `.specify/README.md`
- **Usage Guide**: `.specify/USAGE.md`
- **Constitution**: `.specify/memory/constitution.md`
- **Changes Summary**: `.specify/CONSTITUTION_CHANGES.md`

### GitHub Spec Kit

- **Repository**: https://github.com/github/spec-kit
- **Blog Post**: https://developer.microsoft.com/blog/spec-driven-development-spec-kit
- **CLI Help**: `specify --help`

### Bolster Project

- **Constitution**: `.claude/constitution.md` (original) or `.specify/memory/constitution.md` (enhanced)
- **Agent Workflows**: `AGENTS.md`
- **Project Guide**: `CLAUDE.md`

______________________________________________________________________

## Verification

### Test Spec Kit Installation

```bash
# Check CLI available
specify version

# Check slash commands installed
ls .claude/commands/speckit.*
# Should show 9 .md files

# Check constitution exists
cat .specify/memory/constitution.md | head -20
```

### Test Slash Commands

In Claude Code:

```
/speckit.constitution
```

Should trigger the constitution review command.

______________________________________________________________________

## Summary

GitHub Spec Kit is now fully integrated with the Bolster project:

✅ CLI installed (`specify` command available)
✅ Project initialized (`.specify/` and `.claude/commands/` created)
✅ Constitution enhanced (mother page scraping, data-first testing, CLI-first documented)
✅ Documentation created (README, USAGE, CONSTITUTION_CHANGES)
✅ Slash commands available (9 commands for spec-driven workflow)
✅ Integration with existing agents (data-explore, data-build, data-review)
✅ .gitignore updated (specs/plans/tasks should be committed)

**Ready to use**: Start with `/speckit.constitution` in your next data source development task.

______________________________________________________________________

**Questions or Issues?**

- Read `.specify/USAGE.md` for detailed examples
- Read `.specify/CONSTITUTION_CHANGES.md` to understand enhancements
- Check `.specify/README.md` for quick reference

**Next Feature to Implement?**
Try the Spec Kit workflow with migration statistics or population projections (see usage guide for complete example).

______________________________________________________________________

**Version**: 1.0.0 | **Date**: 2026-02-15 | **Author**: Andrew Bolster (via Claude Sonnet 4.5)
