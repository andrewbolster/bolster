# Tasks: NISRA Migration and Population Projections Data Sources

**Input**: Design documents from `/specs/001-nisra-migration-projections/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: This project follows bolster constitution: ALL modules require data integrity tests using real NISRA data. Tests are MANDATORY and use `scope="class"` fixtures.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **\[P\]**: Can run in parallel (different files, no dependencies)
- **\[Story\]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Single library project structure:

- **Modules**: `src/bolster/data_sources/nisra/`
- **Tests**: `tests/`
- **CLI**: `src/bolster/cli.py`
- **Docs**: `README.md`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Research and preparation before implementation

- \[X\] T001 Research migration mother page structure at https://www.nisra.gov.uk/statistics/migration/long-term-international-migration-statistics
- \[X\] T002 Research population projections publication structure at https://www.nisra.gov.uk/publications/2022-based-population-projections-northern-ireland
- \[X\] T003 \[P\] Download and analyze sample migration Excel file to determine parsing strategy
- \[X\] T004 \[P\] Download and analyze sample projections Excel file to determine parsing strategy
- \[X\] T005 Document findings in specs/001-nisra-migration-projections/research.md

**Checkpoint**: Research complete - ready to implement modules with known data structures

______________________________________________________________________

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Verify existing infrastructure is ready for new modules

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- \[X\] T006 Verify shared utilities in src/bolster/data_sources/nisra/\_base.py are sufficient
- \[X\] T007 Verify web.session utility in src/bolster/utils/web.py is available
- \[X\] T008 Verify existing migration.py module for cross-validation integration
- \[X\] T009 Verify existing population.py module for consistency patterns

**Checkpoint**: Foundation verified - user story implementation can now begin

______________________________________________________________________

## Phase 3: User Story 1 - Official Migration Data Access (Priority: P1) 🎯 MVP

**Goal**: Provide access to official NISRA long-term international migration statistics to replace/validate derived estimates

**Independent Test**: Request official migration data for any year and verify it returns immigration, emigration, and net migration values. Compare with derived estimates to validate demographic equation approach.

### Tests for User Story 1 (REQUIRED per constitution)

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- \[X\] T010 \[P\] \[US1\] Create test file tests/test_nisra_migration_official_integrity.py with TestDataIntegrity class structure
- \[X\] T011 \[P\] \[US1\] Write test_required_columns test to verify year, immigration, emigration, net_migration, date columns present
- \[X\] T012 \[P\] \[US1\] Write test_value_ranges test to verify immigration/emigration >= 0 and net_migration is valid
- \[X\] T013 \[P\] \[US1\] Write test_arithmetic_consistency test to verify net_migration = immigration - emigration
- \[X\] T014 \[P\] \[US1\] Write test_historical_coverage test to verify data spans multiple years
- \[X\] T015 \[P\] \[US1\] Create TestValidation class with unit tests for validation edge cases (empty DataFrame, missing columns, invalid arithmetic)

### Implementation for User Story 1

- \[X\] T016 \[US1\] Enhanced src/bolster/data_sources/nisra/migration.py with official migration functions (consolidated into existing module per user feedback)
- \[X\] T017 \[US1\] Implemented get_official_migration_publication_url() to scrape mother page and find latest Excel file
- \[X\] T018 \[US1\] Implemented parse_official_migration_file(file_path) to parse Excel into DataFrame with required columns
- \[X\] T019 \[US1\] Implemented validate_official_migration(df) to verify data quality
- \[X\] T020 \[US1\] Implemented get_official_migration(force_refresh=False) as main data access function
- \[X\] T021 \[US1\] Added logging statements for publication discovery and data range
- \[X\] T022 \[US1\] Updated migration.py module docstring to reflect both official and derived migration approaches
- \[X\] T023 \[US1\] Ran tests: uv run pytest tests/test_nisra_migration_official_integrity.py -v (6/6 passed)
- \[X\] T024 \[US1\] Verified coverage on migration module (54.55% on full module, new functions covered)

**Checkpoint**: At this point, users can access official NISRA migration statistics and compare with derived estimates

______________________________________________________________________

## Phase 4: User Story 2 - Population Projections Access (Priority: P2)

**Goal**: Provide access to official NISRA population projections to understand expected demographic changes and plan for future services

**Independent Test**: Request population projections for a future year (e.g., 2030) with age/sex breakdown and verify it returns projected population counts. Should work without needing migration_official module.

### Tests for User Story 2 (REQUIRED per constitution)

- \[ \] T025 \[P\] \[US2\] Create test file tests/test_nisra_population_projections_integrity.py with TestDataIntegrity class structure
- \[ \] T026 \[P\] \[US2\] Write test_required_columns test to verify year, base_year, age_group, sex, area, population columns present
- \[ \] T027 \[P\] \[US2\] Write test_value_ranges test to verify population >= 0 and year >= base_year
- \[ \] T028 \[P\] \[US2\] Write test_sex_totals test to verify All persons = Male + Female for each year/age/area
- \[ \] T029 \[P\] \[US2\] Write test_projection_coverage test to verify projections span expected year range (e.g., 2022-2050)
- \[ \] T030 \[P\] \[US2\] Write test_age_group_format test to verify age groups follow standard format (XX-XX or XX+)
- \[ \] T031 \[P\] \[US2\] Write test_filtering test to verify area, start_year, end_year filtering works correctly
- \[ \] T032 \[P\] \[US2\] Create TestValidation class with unit tests for validation edge cases

### Implementation for User Story 2

- \[ \] T033 \[US2\] Create src/bolster/data_sources/nisra/population_projections.py with module docstring
- \[ \] T034 \[US2\] Implement get_latest_projections_publication_url() to discover latest projections Excel file
- \[ \] T035 \[US2\] Implement parse_projections_file(file_path) to parse Excel into long-format DataFrame
- \[ \] T036 \[US2\] Implement validate_projections_totals(df) to verify All persons = Male + Female
- \[ \] T037 \[US2\] Implement validate_projection_coverage(df) to verify year range completeness
- \[ \] T038 \[US2\] Implement get_latest_projections(area=None, start_year=None, end_year=None, force_refresh=False) with filtering support
- \[ \] T039 \[US2\] Add logging statements for publication discovery and projection range
- \[ \] T040 \[US2\] Update src/bolster/data_sources/nisra/__init__.py to export population_projections module
- \[ \] T041 \[US2\] Run tests: uv run pytest tests/test_nisra_population_projections_integrity.py -v
- \[ \] T042 \[US2\] Verify 80% coverage on new module: uv run pytest --cov=src/bolster/data_sources/nisra/population_projections

**Checkpoint**: At this point, users can access population projections independently of migration data

______________________________________________________________________

## Phase 5: User Story 3 - Cross-Validation of Migration Estimates (Priority: P3)

**Goal**: Enable researchers to validate derived migration estimates against official statistics to assess accuracy of demographic equation approach

**Independent Test**: Load both official and derived migration data for overlapping years, run cross-validation, and verify it generates a comparison report showing discrepancies. Should work if US1 is complete (US2 not required).

### Tests for User Story 3 (REQUIRED per constitution)

- \[ \] T043 \[P\] \[US3\] Add test_cross_validation to tests/test_nisra_migration_official_integrity.py TestDataIntegrity class
- \[ \] T044 \[P\] \[US3\] Write test to verify compare_official_vs_derived returns DataFrame with required columns
- \[ \] T045 \[P\] \[US3\] Write test to verify percentage difference calculation is correct
- \[ \] T046 \[P\] \[US3\] Write test to verify threshold flagging works (exceeds_threshold column)
- \[ \] T047 \[P\] \[US3\] Write test to verify comparison handles years not in both datasets gracefully
- \[ \] T048 \[P\] \[US3\] Add unit tests for edge cases (no overlapping years, empty DataFrames, negative thresholds)

### Implementation for User Story 3

- \[ \] T049 \[US3\] Implement compare_official_vs_derived(official_df, derived_df, threshold=1000) in src/bolster/data_sources/nisra/migration_official.py
- \[ \] T050 \[US3\] Add docstring with Args, Returns, Example sections per constitution
- \[ \] T051 \[US3\] Implement year alignment logic (inner join on year)
- \[ \] T052 \[US3\] Implement difference calculations (absolute, percentage)
- \[ \] T053 \[US3\] Implement threshold flagging logic
- \[ \] T054 \[US3\] Add logging for comparison results (mean error, years exceeding threshold)
- \[ \] T055 \[US3\] Run tests: uv run pytest tests/test_nisra_migration_official_integrity.py::TestDataIntegrity::test_cross_validation -v
- \[ \] T056 \[US3\] Verify cross-validation completes in \<5 seconds for 20 years of data (SC-003)

**Checkpoint**: All user stories now independently functional - users can validate derived migration estimates

______________________________________________________________________

## Phase 6: CLI Integration (Optional - Evaluate Utility)

**Purpose**: Add optional CLI commands if standalone utility is confirmed during research

- \[ \] T057 \[P\] Evaluate if migration-compare CLI provides standalone utility (document decision in research.md)
- \[ \] T058 \[P\] Evaluate if projections CLI provides standalone utility (document decision in research.md)
- \[ \] T059 \[CLI\] If useful: Implement migration-compare CLI command in src/bolster/cli.py with --start-year, --end-year, --threshold options
- \[ \] T060 \[CLI\] If useful: Implement projections CLI command in src/bolster/cli.py with --year, --area, --start-year, --end-year options
- \[ \] T061 \[CLI\] If implemented: Use rich.console for formatted table output
- \[ \] T062 \[CLI\] If implemented: Test CLI commands manually with various parameter combinations
- \[ \] T063 \[CLI\] If implemented: Update CLI help text and quickstart.md with usage examples

**Checkpoint**: Optional CLI commands available for quick data exploration

______________________________________________________________________

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final touches and documentation updates

- \[ \] T064 \[P\] Update README.md coverage table with two new rows:
  - Long-Term International Migration | nisra.migration_official | ✅
  - Population Projections | nisra.population_projections | ✅
- \[ \] T065 \[P\] Update migration.py module docstring to note official data now available for cross-validation
- \[ \] T066 Run full test suite: uv run pytest tests/ -v
- \[ \] T067 Verify overall test coverage: uv run pytest --cov=src/bolster --cov-report=term-missing
- \[ \] T068 Run pre-commit checks: uv run pre-commit run --all-files
- \[ \] T069 Verify both modules can be imported: uv run python -c "from bolster.data_sources.nisra import migration_official, population_projections; print('Import successful')"
- \[ \] T070 \[P\] Review and validate quickstart.md examples work as documented
- \[ \] T071 \[P\] Generate data insights for PR description (2-3 key findings from each dataset)
- \[ \] T072 Prepare PR: git add, git commit with co-authored-by Claude, verify no files missed
- \[ \] T073 Create PR with gh pr create --title "feat: add NISRA migration official and population projections modules" --body with insights

______________________________________________________________________

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - User Story 1 (P1): Can start after Phase 2 - No dependencies on other stories
  - User Story 2 (P2): Can start after Phase 2 - Independent of US1
  - User Story 3 (P3): Can start after Phase 2 - Requires US1 implementation (depends on migration_official module)
- **CLI Integration (Phase 6)**: Depends on US1 and US2 completion
- **Polish (Phase 7)**: Depends on all implemented user stories

### User Story Dependencies

- **User Story 1 (P1)**: Foundation only - No dependencies on other stories
- **User Story 2 (P2)**: Foundation only - Independent of US1, can run in parallel
- **User Story 3 (P3)**: Requires US1 complete (uses compare_official_vs_derived from migration_official.py)

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Module creation before function implementation
- Validation functions before main data access functions
- Data access functions before export/integration
- All tests passing before moving to next story

### Parallel Opportunities

**Setup Phase (T001-T005)**:

- T003 and T004 can run in parallel (different Excel files)

**Test Writing (within each story)**:

- All test functions for a story can be written in parallel (T010-T015 for US1, T025-T032 for US2, T043-T048 for US3)

**Between Stories**:

- User Story 1 (Phase 3) and User Story 2 (Phase 4) can run completely in parallel if team capacity allows
- User Story 3 (Phase 5) must wait for US1 but not US2

**Polish Phase (T064-T073)**:

- T064, T065, T070, T071 can run in parallel (different files)

______________________________________________________________________

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Create test file tests/test_nisra_migration_official_integrity.py with TestDataIntegrity class structure"
Task: "Write test_required_columns test to verify year, immigration, emigration, net_migration, date columns present"
Task: "Write test_value_ranges test to verify immigration/emigration >= 0 and net_migration is valid"
Task: "Write test_arithmetic_consistency test to verify net_migration = immigration - emigration"
Task: "Write test_historical_coverage test to verify data spans multiple years"
Task: "Create TestValidation class with unit tests for validation edge cases"
```

## Parallel Example: User Story 1 AND User Story 2 (Different Team Members)

```bash
# Developer A - User Story 1:
Tasks T010-T024 (migration_official module)

# Developer B - User Story 2 (can start at same time):
Tasks T025-T042 (population_projections module)

# These stories are completely independent and can proceed in parallel
```

______________________________________________________________________

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (Research) → T001-T005
1. Complete Phase 2: Foundational (Verify infrastructure) → T006-T009
1. Complete Phase 3: User Story 1 (Official migration data) → T010-T024
1. **STOP and VALIDATE**: Test migration_official module independently
1. Can deploy/demo official migration access and cross-validation comparison

### Incremental Delivery

1. **Foundation**: Setup + Foundational → Infrastructure ready (T001-T009)
1. **MVP**: Add User Story 1 → Test independently → Deploy/Demo (T010-T024)
   - Users can access official migration data
   - Users can validate derived estimates
1. **Enhancement**: Add User Story 2 → Test independently → Deploy/Demo (T025-T042)
   - Users can access population projections
   - Works independently of migration data
1. **Advanced**: Add User Story 3 → Test independently → Deploy/Demo (T043-T056)
   - Enhances US1 with cross-validation function
   - Does not affect US2 functionality
1. **Optional**: Add CLI if useful → Test → Deploy (T057-T063)
1. **Polish**: Documentation and final checks → Create PR (T064-T073)

### Parallel Team Strategy

With two developers:

1. Both complete Setup + Foundational together (T001-T009)
1. Once Foundational is done:
   - **Developer A**: User Story 1 (T010-T024) + User Story 3 (T043-T056)
   - **Developer B**: User Story 2 (T025-T042)
1. Both join for CLI evaluation and Polish (T057-T073)

**Total effort**: ~2-3 days sequential, ~1-2 days with two developers

______________________________________________________________________

## Task Summary

**Total Tasks**: 73 tasks across 7 phases

**Tasks per User Story**:

- User Story 1 (P1 - MVP): 15 tasks (T010-T024)
- User Story 2 (P2): 18 tasks (T025-T042)
- User Story 3 (P3): 14 tasks (T043-T056)

**Parallel Opportunities**:

- 21 tasks marked \[P\] can run in parallel within their phase
- US1 and US2 can run completely in parallel (33 tasks total)
- Test writing within each story is highly parallelizable

**Independent Test Criteria**:

- **US1**: Can access official migration data, validate arithmetic, compare with derived estimates
- **US2**: Can access population projections, filter by area/year, validate sex totals
- **US3**: Can cross-validate official vs derived migration for overlapping years

**Suggested MVP Scope**: Phase 1 + Phase 2 + Phase 3 (User Story 1 only)

- Provides official migration data access
- Enables basic cross-validation
- Delivers immediate value for migration analysis
- Can be completed in ~1 day

______________________________________________________________________

## Format Validation ✅

All tasks follow checklist format:

- ✅ Checkbox: All tasks start with `- [ ]`
- ✅ Task ID: Sequential T001-T073
- ✅ \[P\] marker: 21 parallelizable tasks marked
- ✅ \[Story\] label: US1 (15 tasks), US2 (18 tasks), US3 (14 tasks), CLI (5 tasks)
- ✅ Description: All include clear action and file path
- ✅ Organization: Grouped by user story for independent implementation

______________________________________________________________________

## Notes

- \[P\] tasks = different files, no dependencies within phase
- \[Story\] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Tests are MANDATORY per bolster constitution (real data, scope="class")
- Commit after each logical group of tasks
- Stop at any checkpoint to validate story independently
- CLI commands are optional - evaluate utility during research phase
- Pre-commit hooks MUST pass before creating PR
