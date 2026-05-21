# Changelog

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
