# Changelog

## [0.6.1] - 2026-05-24

- fix(readme): correct CI badge workflow filename (test.yml → pytest.yml) (#1842)
- feat(nisra/disease_prevalence): add GP-practice-level data from Table 5 sheets (#1839)
- feat(psni): add PACE stop & search and arrests statistics module (#1832) (#1838)
- feat(psni): add stop_and_search module — PSNI stop & search 2017/18–2024/25 (#1837)
- feat(nisra): add disease_prevalence module — NI raw disease register statistics (#1836)
- feat(nisra/public_confidence): add PCOS module with awareness and trust time-series (#1835)
- fix: pre-0.6.0 audit fixes — init exports, CLI gaps, CHANGELOG, README (#1840)
- feat(psni): add Police Ombudsman complaint statistics module (#1834)
- feat(nisra): add claimant_count module — monthly UC+JSA claimant statistics (#1833)
- feat(nisra): add child protection statistics module (#1772) (#1828)
- feat(nisra): add elective/outpatient waiting times module (#1802) (#1830)
- feat: add CLI commands for baby names, work quality, education suspensions (#1827)
- fix(psni/crime_statistics): raise PSNIDataStaleError; add get_historical_crime_statistics() (#1823)
- feat(daera): add NI LAC municipal waste statistics module (#1734) (#1825)
- feat(nisra/population_projections): add LGD sub-area projections (2022-based, 2022–2047) (#1822)
- feat(ashe): add Figures 2, 3, 6, 7, 8, 11, 12 (real earnings, occupation/industry, pay distribution) (#1789)
- refactor(nisra): consolidate economic indicators into dedicated modules (#1819)
- fix(ci): fix YAML syntax error in auto-release workflow (#1813)
- fix(population_projections): auto-discover latest projection series URL (#1812)
- fix(composite_index): update stale URL path to /economic-output/ (#1809)
- fix(ci+cli): codecov ignore cli.py, serialise matrix, drop ceremonial --latest (#1796)
- fix(docs): correct structural and content issues (#1782)
- fix(cli): standardise data-selection flag to --dimension across nisra commands
- fix(ci): exclude .claude/agents/ from mdformat
- feat(nisra): add NI Planning Activity Statistics module
- Revert "fix(docs): use uv export | pip install for RTD instead of uv sync"
- fix(docs): use uv export | pip install for RTD instead of uv sync
- fix(docs): install docs group on RTD instead of --all-extras
- feat: add NISRA Quarterly Employment Survey module
- feat: add NISRA Index of Production and Index of Services modules
- Merge branch 'main' into dependabot/uv/boto3-1.42.97
- Merge branch 'main' into dependabot/uv/ruff-0.15.12
- Merge branch 'main' into dependabot/uv/requests-cache-1.3.1
- feat: build and deploy Sphinx docs to bolster.help via GitHub Pages (#1740)
- feat(nisra): add stillbirths module and update population projections to 2024-based (#1762)
- fix(nisra): fix population scraper broken by NISRA site restructure (#1758)
- Merge branch 'main' into dependabot/uv/boto3-1.42.97
- Merge branch 'main' into dependabot/uv/ruff-0.15.12
- Merge branch 'main' into dependabot/uv/requests-cache-1.3.1
- fix(release): use bump-my-version show to extract version after bump (#1739)
- Merge branch 'main' into dependabot/uv/requests-cache-1.3.1
- Merge branch 'main' into dependabot/uv/ruff-0.15.12
- Merge branch 'main' into dependabot/uv/boto3-1.42.97
- fix(ci): allow manual dispatch of rebase workflow to update all BEHIND PRs
- Merge branch 'main' into dependabot/uv/boto3-1.42.97
- Merge branch 'main' into dependabot/uv/ruff-0.15.12
- Merge branch 'main' into dependabot/uv/requests-cache-1.3.1
- fix(web): cap retry backoff to prevent CI hangs on blocked IPs
- Merge branch 'main' into dependabot/uv/boto3-1.42.97
- Merge branch 'main' into dependabot/uv/ruff-0.15.12
- Merge branch 'main' into dependabot/uv/requests-cache-1.3.1
- fix(web): cap retry backoff to prevent CI hangs on blocked IPs
- Merge branch 'main' into dependabot/uv/requests-cache-1.3.1
- fix(ci): include BEHIND PRs in auto-rebase workflow
- feat(ashe): refactor linked-tables parsing to content-fingerprint detection (#1748)
- feat(data): UK Gender Pay Gap reporting data source (#217) (#1741)
- feat(ashe): implement Figures 14-18 gender earnings analysis (#1747)
- fix(web): add tqdm progress bar to download_extract_zip (#314)
- fix(drift-detection): bump artifact actions to Node.js 24, fix speciesName trailing punctuation
- feat: weekly NISRA feed drift detection via TF-IDF (#1732)


All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## \[0.6.0\] - 2026-05-23

### Added

- `nisra.claimant_count` — monthly UC+JSA claimant count statistics from DfC/ONS; NI headline back to April 1997, with LGD and SOA breakdowns (#1833)
- `psni.police_ombudsman` — annual and quarterly Police Ombudsman complaint statistics; complaints by district, allegation type, and outcome back to 2000/01 (#1834)
- `nisra.public_confidence` — Public Confidence in Official Statistics (PCOS) survey; awareness and trust indicators back to 2009 from annual ODS file (#1835)
- `nisra.disease_prevalence` — NI disease prevalence registers from DoH/PHA; Table 1 registered patients and Table 2 prevalence per 1,000 patients across 17 disease categories (#1836)
- `psni.stop_and_search` — PSNI stop & search records from OpenDataNI; 199,661 records covering 2017/18–2024/25 with PACE reason flags, legislation, and demographic breakdowns (#1837)
- `psni.pace` — annual PSNI PACE statistics; monthly stop & search by reason and quarterly PACE arrests by gender/category back to 2013/14 (#1838)
- `nisra.disease_prevalence.get_latest_gp_prevalence` — GP-practice-level disease prevalence from 17 Table 5 sheets with practice lookup from Table 4 (359 practices) (#1839)

### Fixed

- `nisra/__init__.py` now correctly exports `elective_waiting_times` (was omitted despite module existing since #1830)
- `psni/__init__.py` now exports `PSNIDataStaleError` and `get_historical_crime_statistics`; docstring example updated to use `get_historical_crime_statistics()` instead of the now-raising `get_latest_crime_statistics()`
- `bolster nisra labour-market --dimension all` no longer hardcodes `year=2025, quarter="Jul-Sep"`; now calls `get_latest_employment` and `get_latest_economic_inactivity` to auto-detect the current quarter
- `bolster dva` no longer requires `--latest` flag (was `required=True`; changed to `default=True`)

### Added (CLI)

- `bolster psni crime` — historical crime statistics subcommand with clear stale-data messaging
- `bolster nisra quarterly-employment-survey` — QES employee jobs by sector with `--adjusted/--unadjusted` flag
- `bolster nisra emergency-care` now accepts `--force-refresh` flag
- `bolster nisra feed --check-coverage` keyword map expanded with 11 additional module mappings

______________________________________________________________________

## \[0.6.0\] - 2026-05-21

### Added

- `nisra.population_projections` now includes LGD sub-area projections (2022-based, 2022–2047) (#1822)
- `daera_waste` — NI LAC municipal waste statistics from DAERA; waste collected, landfilled, and recycled by Local Authority (#1825)
- `nisra.elective_waiting_times` — elective and outpatient waiting times (inpatient/day-case/outpatient queues); data from DoH NI (#1830)
- CLI commands for `baby-names`, `work-quality`, and `education suspensions` (#1827)

### Fixed

- `psni.crime_statistics.get_latest_crime_statistics()` now raises `PSNIDataStaleError` with guidance; historical data available via `get_historical_crime_statistics()` (#1823)

______________________________________________________________________

## \[0.5.0\] - 2026-05-20

### Added

- `nisra.stillbirths` — monthly stillbirth registrations (#1762)
- `nisra.population_projections` updated to 2024-based NI-level series (#1762)
- `nisra.index_of_production` — quarterly Index of Production (IOP) (#1763)
- `nisra.index_of_services` — quarterly Index of Services (IOS) (#1763)
- `nisra.quarterly_employment_survey` — employee jobs by sector, Q1 1998 to present (#1764)
- `nisra.planning_statistics` — NI planning applications by council (quarterly) (#1784)
- `nisra.ashe` extended with real earnings, occupation/industry change, and pay distribution dimensions — Figures 2, 3, 6, 7, 8, 11, 12 (#1789)
- `gender_pay_gap` — UK Gender Pay Gap Reporting service data source (#1741)
- Sphinx documentation deployed to bolster.help via GitHub Pages (#1740)
- Weekly NISRA feed drift detection via TF-IDF (#1732)

### Changed

- `nisra` economic indicator modules consolidated into dedicated files — `composite_index`, `index_of_production`, `index_of_services` refactored out of monolithic module (#1819)
- All NISRA CLI commands standardised to use `--dimension` flag (deprecated `--table`) (#1788)

### Fixed

- `nisra.population` scraper fixed after NISRA site restructure broke URL discovery (#1758)
- `nisra.composite_index` URL updated to new `/economic-output/` path (#1809)
- `nisra.population_projections` URL auto-discovery updated for 2024-based series (#1812)
- CI retry backoff capped to prevent 2-hour hangs when NISRA servers rate-limit CI runners (#1796)
- `ashe` linked-tables parsing refactored to content-fingerprint detection for resilience (#1748)

______________________________________________________________________

## \[0.4.0\] - 2024-11-26

### Added

- PSNI Road Traffic Collision statistics module
- Data source info helper for crime statistics
- NISRA feed command for RSS discovery

### Changed

- Moved occupancy to tourism subpackage
- Updated agent specifications based on tourism PR learnings

______________________________________________________________________

*Previous versions - see git history for details*

## Version Numbering

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** version when you make incompatible API changes
- **MINOR** version when you add functionality in a backwards compatible manner
- **PATCH** version when you make backwards compatible bug fixes

Version bumps are automatically determined from:

1. Conventional commit messages in merged PRs
1. PR labels (`version:major`, `version:minor`, `version:patch`, `version:skip`)
1. Detection of breaking changes in code or documentation
