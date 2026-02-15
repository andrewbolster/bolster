# Constitution Enhancement Summary

This document summarizes the changes from the original constitution to the enhanced version installed for Spec Kit.

## What Changed

The enhanced constitution adds **missing critical principles** that were implicit in the codebase but not documented. This makes them explicit and enforceable.

## New Sections Added

### 1. Project Architecture Principles (New Section)

**What was missing**: Documentation of package management standards, testing philosophy, CLI-first design, and mother page scraping.

**Why it matters**: These are **non-negotiable** patterns that every module follows, but weren't written down. New contributors might not discover them until PR review.

**Added principles**:

- **Package Management**: `uv only` - never use pip, poetry, or requirements.txt
- **Testing Philosophy**: Real data only, no mocks, data integrity focus
- **CLI-First Design**: Every user-facing module exposes CLI commands
- **Mother Page Scraping**: Never hardcode URLs to point-in-time files

### 2. Mother Page Scraping Pattern (New Section)

**What was missing**: The core architectural pattern for data discovery wasn't documented.

**Why it matters**: This is what makes Bolster modules **self-updating**. Hardcoded URLs break when publications update. Mother page scraping ensures modules always find the latest data.

**Added**:

- Clear explanation of mother page → publication → file navigation
- Code example showing the pattern
- Rationale: robustness over brittleness

**Example from births.py**:

```python
# Mother page lists all publications
mother_page = "https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/births"

# Find "Monthly Births" publication
pub_link = find_publication_link(soup, "Monthly Births")

# Navigate to publication detail page
# Find latest Excel file
excel_url = find_data_file(pub_response, ".xlsx")
```

### 3. Enhanced Validation Standards (Expanded)

**What changed**: Original had validation function signature, but not validation *types*.

**Added**:

- Arithmetic checks (totals sum correctly)
- Range checks (no negative births, ages \< 150)
- Completeness checks (no missing months in time series)
- Cross-dataset validation (when related data exists)

**Why it matters**: Guides developers on *what* to validate, not just *how* to validate.

### 4. Agent Workflows (New Section)

**What was missing**: AGENTS.md defined agents, but constitution didn't reference them.

**Added**:

- Summary of data-explore, data-build, data-review agents
- How they map to Spec Kit workflow
- Clear division of responsibilities

**Why it matters**: Developers know which agent to invoke for which phase of work.

### 5. Quality Checklist Standards (Expanded)

**What changed**: Original mentioned tests, but not the full QA process.

**Added**:

- Pre-commit enforcement
- Coverage expectations (>90% on new code, pragmatic exemptions for error paths)
- CI verification (`gh pr checks`)
- README coverage table maintenance

**Why it matters**: Prevents "forgot to update README" situations.

### 6. Subpackage Organization (Expanded)

**What changed**: Original mentioned subpackages exist (tourism/), but not *when* to create them.

**Added**:

- Clear criteria: multiple related modules, shared concepts, domain boundary
- Structural example showing flat vs. subpackage

**Why it matters**: Prevents premature abstraction (creating subpackages for one module) or missed abstraction (sprawling flat structure).

### 7. Documentation Standards (New Section)

**What was missing**: Docstring format was shown, but not code comment philosophy.

**Added**:

- Google-style docstrings required
- Comment *why* not *what* (code is self-documenting)
- Comment non-obvious business logic
- Comment mother page navigation steps

### 8. Python Version Support (New Section)

**What was missing**: No documentation of supported versions.

**Added**: Python 3.9-3.13 supported, tested in CI

### 9. Shared Utilities (Expanded)

**What changed**: Original listed utilities, but not *why* to use them.

**Added**:

- Explicit "Always use web.session" with rationale (retry logic)
- "Never use requests.get() directly" with consequences (CI flakiness)
- Exception hierarchy with actionable error messages

**Why it matters**: Prevents reimplementing existing utilities.

## What Stayed the Same

These sections were already excellent and unchanged:

- **Module Docstring Structure** - Clear format with Data Source, Update Frequency, Example
- **Function Naming Conventions** - get_latest\_*, parse\_*, validate\_\* prefixes
- **HTTP Requests** - Use shared session (already explicit)
- **Logging** - logger.getLogger(__name__), no print() statements
- **Exception Hierarchy** - Domain-specific exceptions, never bare Exception
- **Validation Functions** - Always return bool, raise domain-specific errors
- **File Downloads** - Use download_file() from \_base.py with TTL
- **Return Types** - Full type annotations, no untyped Any
- **CLI Integration** - Expose user-facing features via CLI
- **Tests** - test\_<source>\_<module>\_integrity.py, scope="class" fixtures

## Migration Path

### For Existing Modules

**No action required**. All existing modules already follow the enhanced constitution. The new version simply documents what was implicit.

### For New Modules

**Use Spec Kit**:

1. `/speckit.constitution` - Review before starting
1. `/speckit.specify` - Define requirements
1. `/speckit.plan` - Technical decisions
1. `/speckit.tasks` - Break down work
1. `/speckit.implement` - Execute systematically

### For Constitution Amendments

**Propose via PR**:

1. Identify a pattern that should be universal (not one-off)
1. Verify pattern exists in at least 3 existing modules
1. Write clear rationale grounded in actual codebase
1. PR with amendment to .specify/memory/constitution.md
1. Update .claude/constitution.md to match after approval

## Spec Kit Integration

The enhanced constitution is stored in two locations:

1. **`.specify/memory/constitution.md`** - Used by Spec Kit slash commands
1. **`.claude/constitution.md`** - Used by Claude Code project context

These should be kept in sync. When updating one, update the other.

## Key Principles Emphasized

The enhanced constitution makes these implicit principles **explicit**:

### 1. Data-First Development

"Every module must retrieve real, current data from authoritative sources. No synthetic data. No hardcoded URLs to point-in-time files."

### 2. Self-Updating Architecture

"Modules scrape 'mother pages' to discover the latest publication automatically."

### 3. Real Data Testing

"Tests download and validate current published data. No mocks for integration tests."

### 4. CLI-First Design

"User-facing features expose CLI commands. Internal utilities exempt."

### 5. Validation is Non-Negotiable

"Every data source module has at least one validate\_\*() function with domain-specific checks."

## Impact on Development Workflow

### Before Enhanced Constitution

- Developers learned patterns by reading existing code
- Implicit knowledge shared via PR review
- "Why do we do it this way?" answered case-by-case

### After Enhanced Constitution

- Developers read constitution before starting
- Spec Kit enforces constitutional principles during planning
- Rationale documented: self-updating, robustness, data integrity

## Constitution Governance

From the new Governance section:

> **This constitution is living documentation**: It evolves as patterns emerge, but changes require consensus. Propose amendments via PR with rationale grounded in actual codebase patterns.

### Amendment Process

1. Identify pattern worth codifying
1. Verify prevalence (3+ existing modules)
1. Document rationale
1. PR with amendment
1. Review by project maintainers
1. Merge if consensus reached
1. Update both .specify/ and .claude/ copies

## Comparison: Old vs. New

| Aspect | Original Constitution | Enhanced Constitution |
|--------|----------------------|----------------------|
| **Length** | 154 lines | 650+ lines |
| **Scope** | Code patterns | Code + philosophy + workflow |
| **Mother Page Scraping** | Not mentioned | Core architectural principle |
| **Testing Philosophy** | Mentioned | Detailed rationale |
| **CLI Standards** | Mentioned | Design principles added |
| **Validation Types** | Example only | Comprehensive categories |
| **Agent Workflows** | Not mentioned | Integrated with Spec Kit |
| **Quality Process** | Tests only | Full QA checklist |
| **Rationale** | Minimal | Explicit "why" for each rule |
| **Spec Kit Integration** | N/A | Native support |

## Example: How Constitution Guides Development

### Scenario: Implementing Security Statistics Module

**Without Enhanced Constitution**:

1. Read AGENTS.md → see data-build workflow
1. Look at similar modules (births.py) for patterns
1. Implement, discover mother page pattern through PR feedback
1. Add CLI after PR review suggests it
1. Update README after PR review reminds you
1. Three rounds of review to align with implicit standards

**With Enhanced Constitution + Spec Kit**:

1. `/speckit.constitution` → understand mother page pattern upfront
1. `/speckit.specify` → define requirements, constitution auto-referenced
1. `/speckit.plan` → plan respects constitutional standards
1. `/speckit.tasks` → task list includes CLI, README, validation
1. `/speckit.implement` → execute with constitution-compliant code
1. One round of review, only for domain-specific feedback

**Result**: Faster development, fewer surprises, documented decisions.

## Conclusion

The enhanced constitution makes **implicit knowledge explicit**. It doesn't change what we do - it documents *why* we do it and *how* to do it consistently.

Key additions:

- Mother page scraping architecture
- Data-first testing philosophy
- CLI-first design principles
- Agent workflow integration
- Quality process documentation
- Validation standards
- Governance process

This creates a **constitutional AI** approach: the AI agent reads the constitution before every feature, ensuring consistency without manual enforcement.

______________________________________________________________________

**Version**: 1.0.0 | **Comparison Date**: 2026-02-15 | **Author**: Andrew Bolster (via Claude Sonnet 4.5)
