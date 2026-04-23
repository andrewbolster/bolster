# Feature Specification: NISRA Migration and Population Projections Data Sources

**Feature Branch**: `001-nisra-migration-projections`\
**Created**: 2026-02-15\
**Status**: Draft\
**Input**: User description: "Implement two related NISRA data source modules: Long-Term International Migration Statistics (migration_official.py) and Population Projections (population_projections.py)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Official Migration Data Access (Priority: P1)

Data analysts and researchers need access to official NISRA long-term international migration statistics to analyze migration patterns without relying on derived calculations from demographic components.

**Why this priority**: This provides the authoritative source for migration data. Currently, users must rely on derived estimates from the demographic equation (population change minus natural change), which introduces measurement error. Official statistics are the foundation for accurate migration analysis and cross-validation of derived estimates.

**Independent Test**: Can be fully tested by requesting official migration data for a specific year (e.g., 2022) and verifying it returns immigration, emigration, and net migration values. Delivers immediate value for migration analysis without requiring population projections.

**Acceptance Scenarios**:

1. **Given** the latest migration data file is available on NISRA, **When** a user requests official migration statistics, **Then** the system returns a dataset with immigration, emigration, and net migration by year
1. **Given** a user has both official and derived migration data, **When** they compare the two datasets for the same year, **Then** they can identify discrepancies and validate the derived calculation approach
1. **Given** migration data spans multiple years, **When** a user requests the full time series, **Then** they receive data for all available years in chronological order

______________________________________________________________________

### User Story 2 - Population Projections Access (Priority: P2)

Data analysts and policy planners need access to official population projections to understand expected demographic changes and plan for future service needs.

**Why this priority**: Complements historical population estimates with forward-looking projections. Essential for planning but less immediately critical than fixing the migration data gap. Projections are typically used for strategic planning while historical data is needed for current analysis.

**Independent Test**: Can be fully tested by requesting population projections for a future year (e.g., 2030) with age/sex breakdown and verifying it returns projected population counts. Delivers standalone value for demographic planning and forecasting.

**Acceptance Scenarios**:

1. **Given** the latest 2022-based population projections are available, **When** a user requests projections for a specific future year, **Then** the system returns projected population by age group and sex
1. **Given** projections cover multiple geographic areas, **When** a user requests projections for Northern Ireland overall, **Then** they receive projections for the entire region aggregated appropriately
1. **Given** projections extend to 2050+, **When** a user requests the full projection period, **Then** they receive data for all projected years from the base year forward

______________________________________________________________________

### User Story 3 - Cross-Validation of Migration Estimates (Priority: P3)

Researchers need to validate derived migration estimates against official migration statistics to assess the accuracy of the demographic equation approach.

**Why this priority**: This is an advanced analytical use case that builds on P1. It provides quality assurance but doesn't deliver new data access—it enhances confidence in existing derived estimates. Only valuable after official migration data (P1) is available.

**Independent Test**: Can be fully tested by loading both official and derived migration data for overlapping years, calculating the difference between them, and generating a validation report showing discrepancies. Delivers value for data quality assessment.

**Acceptance Scenarios**:

1. **Given** both official and derived migration data exist for overlapping years, **When** a user performs cross-validation, **Then** the system reports the average absolute difference and identifies years with significant discrepancies
1. **Given** migration estimates may differ due to methodology, **When** validation results show differences, **Then** the user can determine whether the demographic equation approach is reliable for their use case
1. **Given** validation identifies years with large discrepancies, **When** the user investigates further, **Then** they can access both datasets side-by-side for detailed comparison

______________________________________________________________________

### Edge Cases

- What happens when NISRA publishes a new migration dataset in a different Excel format or structure?
- How does the system handle years where official migration data is available but derived data is not (or vice versa)?
- What happens if population projections are requested for a year beyond the projection horizon (e.g., 2060 when projections only go to 2050)?
- How does the system handle projections when a new base year is published (e.g., 2032-based projections replacing 2022-based)?
- What happens when migration data is requested but the mother page structure has changed?
- How does the system handle partial years or quarterly data if the format changes in future publications?

## Requirements *(mandatory)*

### Functional Requirements

**Migration Official Module (migration_official.py)**:

- **FR-001**: System MUST scrape the NISRA migration mother page to automatically discover the latest long-term international migration publication
- **FR-002**: System MUST download and parse Excel files containing immigration, emigration, and net migration statistics
- **FR-003**: System MUST return migration data in a long-format DataFrame with columns for year, immigration count, emigration count, and net migration
- **FR-004**: System MUST cache downloaded migration files with a default TTL of 24 hours to minimize repeated downloads
- **FR-005**: System MUST provide a function to retrieve official migration data for the full available time series
- **FR-006**: System MUST validate that net migration equals immigration minus emigration for each year

**Population Projections Module (population_projections.py)**:

- **FR-007**: System MUST access NISRA population projections publications (currently 2022-based)
- **FR-008**: System MUST parse Excel files containing projected population by year, age group, sex, and geography
- **FR-009**: System MUST return projection data in a long-format DataFrame consistent with the historical population module structure
- **FR-010**: System MUST support filtering projections by geographic area (Northern Ireland overall, Parliamentary Constituencies, Health and Social Care Trusts)
- **FR-011**: System MUST support filtering projections by year range (e.g., 2025-2035)
- **FR-012**: System MUST cache downloaded projection files with a default TTL of 168 hours (7 days) since projections update biennially

**Cross-Validation Support**:

- **FR-013**: System MUST provide a function to compare official migration data with derived migration estimates for overlapping years
- **FR-014**: Validation function MUST calculate absolute and percentage differences between official and derived estimates
- **FR-015**: Validation function MUST identify years where differences exceed a specified threshold

**Integration Requirements**:

- **FR-016**: Migration official module MUST use shared utilities from `_base.py` (download_file, web.session, add_date_columns)
- **FR-017**: Population projections module MUST use shared utilities from `_base.py` for consistency with population.py
- **FR-018**: Both modules MUST follow the existing NISRA module patterns for scraping mother pages and parsing Excel files
- **FR-019**: Both modules MUST include docstrings with Args, Returns, and Example sections
- **FR-020**: Both modules MUST export their main data access functions in the nisra package `__init__.py`

**CLI Requirements**:

- **FR-021**: System SHOULD provide CLI commands for migration official data access (if standalone utility is needed beyond cross-validation)
- **FR-022**: System SHOULD provide CLI commands for population projections access (if standalone utility for planning scenarios exists)

### Key Entities *(include if feature involves data)*

- **Official Migration Estimate**: Represents annual long-term international migration flows for Northern Ireland

  - Attributes: year, immigration count, emigration count, net migration, data source publication date
  - Relationships: Comparable to derived migration estimates (from migration.py) for the same year

- **Population Projection**: Represents forecasted future population for a specific year

  - Attributes: projection year, base year, age group, sex, geographic area, projected population count, projection variant (if applicable - e.g., principal, high, low)
  - Relationships: Extends historical population estimates (from population.py) into the future; based on assumptions about future births, deaths, and migration

- **Migration Validation Result**: Represents comparison between official and derived migration estimates

  - Attributes: year, official estimate, derived estimate, absolute difference, percentage difference, discrepancy flag
  - Relationships: Links official migration data with derived migration data for quality assessment

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can access official NISRA migration statistics for all available years with a single function call
- **SC-002**: Users can retrieve population projections for any future year within the projection horizon (2022-2050+) with age and sex breakdowns
- **SC-003**: Cross-validation between official and derived migration estimates completes in under 5 seconds for 20 years of overlapping data
- **SC-004**: Migration and projection data downloads succeed on first attempt for 95% of requests (excluding network failures)
- **SC-005**: Data integrity tests verify that all required columns are present and contain valid values for 100% of retrieved datasets
- **SC-006**: Module documentation enables a new user to access migration or projection data with zero prior knowledge of NISRA data structures
- **SC-007**: Caching reduces redundant NISRA website requests by 90% for repeated data access within TTL window
- **SC-008**: Cross-validation identifies discrepancies between official and derived estimates with a mean absolute error calculation accurate to within 1 person

### Non-Functional Success Criteria

- **SC-009**: Both modules achieve minimum 80% test coverage on data retrieval and parsing paths
- **SC-010**: All tests use real NISRA data with class-scoped fixtures (no mocks)
- **SC-011**: Pre-commit hooks (ruff linting/formatting) pass for all new code before PR submission
- **SC-012**: README coverage table updated to reflect availability of official migration and population projection modules
