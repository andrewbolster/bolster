# Spec Kit Workflow for Bolster Data Sources

## Visual Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SPEC-DRIVEN DATA SOURCE DEVELOPMENT                  │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐
│ /speckit         │  Read and understand project principles
│ .constitution    │  - Mother page scraping required
│                  │  - Real data tests (no mocks)
└────────┬─────────┘  - CLI-first design
         │            - uv only, type hints, validation functions
         ▼
┌──────────────────┐
│ /speckit         │  Document WHAT to build
│ .specify         │  - Functional requirements
│                  │  - User stories
└────────┬─────────┘  - Acceptance criteria
         │            - Out of scope
         │
         ▼ (optional if requirements unclear)
┌──────────────────┐
│ /speckit         │  Identify ambiguous requirements
│ .clarify         │  - Ask structured questions
│                  │  - Resolve assumptions
└────────┬─────────┘  - Update spec accordingly
         │
         ▼
┌──────────────────┐
│ /speckit         │  Define HOW to build it
│ .plan            │  - Architecture (functions, modules)
│                  │  - Tech stack (pandas, openpyxl, BeautifulSoup)
└────────┬─────────┘  - Data contracts (DataFrame schemas)
         │            - Testing strategy
         │            - CLI design
         │
         ▼ (optional for quality assurance)
┌──────────────────┐
│ /speckit         │  Generate quality validation checklist
│ .checklist       │  - Pre-implementation checks
│                  │  - Implementation checks
└────────┬─────────┘  - Testing checks
         │            - Quality checks
         │
         ▼
┌──────────────────┐
│ /speckit         │  Break down into actionable tasks
│ .tasks           │  - Phase 1: Core implementation
│                  │  - Phase 2: Testing
└────────┬─────────┘  - Phase 3: Integration (CLI, exports, README)
         │            - Phase 4: Quality assurance
         │
         ▼ (optional before implementation)
┌──────────────────┐
│ /speckit         │  Cross-check consistency
│ .analyze         │  - Spec requirements → Plan coverage
│                  │  - Plan → Task completeness
└────────┬─────────┘  - Constitution compliance
         │
         ▼
┌──────────────────┐
│ /speckit         │  Execute implementation
│ .implement       │  - Create module (migration.py)
│                  │  - Create tests (test_nisra_migration_integrity.py)
└────────┬─────────┘  - Add CLI command
         │            - Update exports, README
         │            - Run quality checks
         │
         ▼
┌──────────────────┐
│ Create PR        │  Submit for review
│ gh pr create     │  - Include 2-3 data insights
│                  │  - Python and CLI usage examples
└────────┬─────────┘  - Verify CI passes (gh pr checks)
         │
         ▼
┌──────────────────┐
│ Merge & Deploy   │  Feature complete!
└──────────────────┘
```

## Workflow States and Artifacts

```
┌─────────────────────────────────────────────────────────────────────┐
│                          ARTIFACTS CREATED                          │
├─────────────────────────────────────────────────────────────────────┤
│ Constitution   │ .specify/memory/constitution.md                    │
│                │ (Read-only: project principles)                    │
├────────────────┼────────────────────────────────────────────────────┤
│ Specification  │ .specify/memory/specs/migration.md                 │
│                │ - Requirements                                      │
│                │ - User stories                                      │
│                │ - Acceptance criteria                               │
├────────────────┼────────────────────────────────────────────────────┤
│ Plan           │ .specify/memory/plans/migration.md                 │
│                │ - Architecture                                      │
│                │ - Tech stack                                        │
│                │ - Data contracts                                    │
│                │ - Testing strategy                                  │
├────────────────┼────────────────────────────────────────────────────┤
│ Tasks          │ .specify/memory/tasks/migration.md                 │
│                │ - Phase 1: Core implementation                      │
│                │ - Phase 2: Testing                                  │
│                │ - Phase 3: Integration                              │
│                │ - Phase 4: QA                                       │
├────────────────┼────────────────────────────────────────────────────┤
│ Checklist      │ .specify/memory/checklists/migration.md (optional) │
│ (optional)     │ - Pre-implementation checks                         │
│                │ - Implementation checks                             │
│                │ - Testing checks                                    │
│                │ - Quality checks                                    │
├────────────────┼────────────────────────────────────────────────────┤
│ Analysis       │ .specify/memory/analysis/migration.md (optional)   │
│ (optional)     │ - Consistency matrix                                │
│                │ - Constitution compliance                           │
│                │ - Deviations identified                             │
├────────────────┼────────────────────────────────────────────────────┤
│ Implementation │ src/bolster/data_sources/nisra/migration.py        │
│                │ tests/test_nisra_migration_integrity.py             │
│                │ src/bolster/cli.py (updated)                        │
│                │ README.md (updated)                                 │
│                │ __init__.py (updated exports)                       │
└────────────────┴────────────────────────────────────────────────────┘
```

## Decision Points

```
                    ┌─────────────────────────┐
                    │ Is Spec Kit needed for  │
                    │ this feature?           │
                    └──────────┬──────────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
        ┌───────────────┐             ┌──────────────┐
        │ YES           │             │ NO           │
        │ - New module  │             │ - Bug fix    │
        │ - Complex     │             │ - Typo       │
        │ - Unclear     │             │ - One-liner  │
        └───────┬───────┘             └──────────────┘
                │
                ▼
        ┌───────────────────────┐
        │ Are requirements      │
        │ clear and complete?   │
        └───────┬───────────────┘
                │
        ┌───────┴────────┐
        │                │
        ▼                ▼
   ┌────────┐      ┌──────────────┐
   │ YES    │      │ NO           │
   │ Skip   │      │ Use          │
   │ clarify│      │ /clarify     │
   └────┬───┘      └──────┬───────┘
        │                 │
        └────────┬────────┘
                 ▼
        ┌────────────────────┐
        │ Is implementation  │
        │ straightforward?   │
        └────────┬───────────┘
                 │
        ┌────────┴─────────┐
        │                  │
        ▼                  ▼
   ┌────────┐        ┌──────────────┐
   │ YES    │        │ NO           │
   │ Skip   │        │ Use          │
   │ analyze│        │ /analyze     │
   └────┬───┘        └──────┬───────┘
        │                   │
        └────────┬──────────┘
                 ▼
        ┌────────────────┐
        │ Proceed to     │
        │ /implement     │
        └────────────────┘
```

## Integration with Agent Workflows

```
┌────────────────────────────────────────────────────────────────┐
│              BOLSTER AGENTS + SPEC KIT WORKFLOW                │
└────────────────────────────────────────────────────────────────┘

┌──────────────────┐
│ data-explore     │  Discover new data sources
│                  │  - Scan RSS feeds
│                  │  - Research accessibility
└────────┬─────────┘  - Evaluate format, history
         │            - Rate: accessibility, stability, usefulness
         │
         ▼
    ┌─────────────────────┐
    │ /speckit.specify    │  Document exploration findings
    │                     │  - What data is available?
    └─────────┬───────────┘  - Why is it useful?
              │              - How is it published?
              │
              ▼
┌──────────────────┐
│ data-build       │  Build production module
│                  │  1. /speckit.plan (technical decisions)
└────────┬─────────┘  2. /speckit.tasks (break down work)
         │            3. /speckit.implement (execute)
         │            4. Quality checks (tests, pre-commit, CI)
         │
         ▼
┌──────────────────┐
│ data-review      │  Review PR
│                  │  - /speckit.analyze (consistency check)
└────────┬─────────┘  - Review against constitution
         │            - Verify: tests, CLI, README, exports
         │
         ▼
┌──────────────────┐
│ Merge            │
└──────────────────┘
```

## Typical Timeline

```
┌─────────────────────────────────────────────────────────────┐
│                      ESTIMATED TIMELINE                     │
├─────────────────────────────────────────────────────────────┤
│ Constitution review    │ 5 min   │ Understand principles   │
│ Specification          │ 15 min  │ Document requirements   │
│ Clarification (opt)    │ 10 min  │ Resolve ambiguities     │
│ Planning               │ 20 min  │ Technical decisions     │
│ Checklist (opt)        │ 5 min   │ Generate QA checklist   │
│ Task generation        │ 10 min  │ Break down work         │
│ Analysis (opt)         │ 10 min  │ Consistency check       │
│ Implementation         │ 2-4 hrs │ Code + tests + CLI      │
│ Quality checks         │ 15 min  │ Tests, pre-commit, CI   │
│ PR creation            │ 10 min  │ Write description       │
├─────────────────────────────────────────────────────────────┤
│ Total (with optional)  │ ~3-5 hrs│ For typical module      │
│ Total (core workflow)  │ ~2-4 hrs│ Skip clarify/analyze    │
└─────────────────────────────────────────────────────────────┘

Note: Time savings come from:
- Fewer rounds of PR feedback (standards understood upfront)
- Less rework (clear requirements before coding)
- Faster debugging (comprehensive tests from start)
```

## When to Use Each Command

```
┌──────────────────────────────────────────────────────────────┐
│                    COMMAND USAGE GUIDE                       │
├──────────────────┬───────────────────────────────────────────┤
│ /constitution    │ ALWAYS - Start every feature             │
├──────────────────┼───────────────────────────────────────────┤
│ /specify         │ ALWAYS - Document requirements           │
├──────────────────┼───────────────────────────────────────────┤
│ /clarify         │ SOMETIMES - Use when:                    │
│                  │ - Requirements are vague                  │
│                  │ - Multiple interpretations possible       │
│                  │ - Stakeholder input needed                │
│                  │ - Data format unclear                     │
├──────────────────┼───────────────────────────────────────────┤
│ /plan            │ ALWAYS - Define implementation approach  │
├──────────────────┼───────────────────────────────────────────┤
│ /checklist       │ SOMETIMES - Use when:                    │
│                  │ - Complex feature with many parts         │
│                  │ - First time contributor                  │
│                  │ - Want structured QA process              │
├──────────────────┼───────────────────────────────────────────┤
│ /tasks           │ ALWAYS - Break down implementation       │
├──────────────────┼───────────────────────────────────────────┤
│ /analyze         │ SOMETIMES - Use when:                    │
│                  │ - Large/complex implementation            │
│                  │ - Multiple modules involved               │
│                  │ - Want pre-PR validation                  │
├──────────────────┼───────────────────────────────────────────┤
│ /implement       │ ALWAYS - Execute systematically          │
└──────────────────┴───────────────────────────────────────────┘

Recommended workflow for typical NISRA module:
  constitution → specify → plan → tasks → implement

Recommended workflow for complex feature:
  constitution → specify → clarify → plan → checklist → tasks → analyze → implement
```

## Best Practices

### Do's

- ✅ Run `/speckit.constitution` before every new feature
- ✅ Commit spec/plan/task artifacts to git (they're documentation)
- ✅ Use specific, descriptive names (migration.md not feature1.md)
- ✅ Include data insights in PR (show value of the module)
- ✅ Update README coverage table
- ✅ Run quality checks before PR (tests, pre-commit, CI)

### Don'ts

- ❌ Skip specification ("I'll just code it quickly")
- ❌ Ignore constitution ("I know a better way")
- ❌ Use generic names (task.md, plan.md)
- ❌ Forget CLI command for user-facing features
- ❌ Forget validation functions
- ❌ Hardcode URLs to data files (use mother page scraping)

______________________________________________________________________

**See also**:

- `.specify/README.md` - Quick start guide
- `.specify/USAGE.md` - Detailed examples
- `.specify/memory/constitution.md` - Project principles
