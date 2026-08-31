# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## \[Unreleased\]

## \[0.7.1\] - 2026-08-31

### Added

- `health_ni` — new top-level data source package for Department of Health NI statistics;
  six modules migrated from `nisra/` where DoH is the canonical publisher (#1963)
  - `health_ni.cancer_waiting_times` — cancer referral and treatment waiting times (PxStat)
  - `health_ni.child_protection` — child protection registrations and case conferences
  - `health_ni.diagnostic_waiting_times` — diagnostic waiting times by test type (PxStat)
  - `health_ni.disease_prevalence` — NI disease register statistics at NI, LGD, HSCT, and GP-practice level
  - `health_ni.elective_waiting_times` — inpatient/day-case and outpatient waiting times
  - `health_ni.emergency_care_waiting_times` — A&E 4-hour target performance by Trust
- `health_ni.disease_prevalence.get_latest_gp_prevalence()` — GP-practice-level disease
  prevalence restored from DoH Excel workbook Table 4/5 sheets; ~17 financial years,
  ~360 practices, 17 disease registers (#1963)
- `translink` — live departure boards and vehicle positions (#1917)
  - `get_departures_by_name()` / `get_departures()` — next-N departures from any Translink stop
  - `get_live_vehicles()` — live vehicle snapshot from Translink VMI feed
  - `get_departures_with_vehicles()` — departure boards enriched with VMI vehicle positions
  - Stop metadata from Open Data NI ATCO-CIF zips (12,700+ stops, ING→WGS84 conversion)
  - CLI: `bolster translink departures <stop>` and `bolster translink vehicles`
- `nisra.deprivation` — NI Multiple Deprivation Measure 2017 (NIMDM); SOA-level overall
  and domain deprivation ranks via PxStat (#1933)
- `nisra.business_register` — NI Business Register (IDBR); annual VAT/PAYE business counts
  by industry, legal status, and LGD via PxStat (#1934)
- `nisra.housing_stock` — NI Housing Stock Statistics (DoF/LPS); annual property counts
  by type and district (#1898)
- `nisra.diagnostic_waiting_times` — NI Diagnostic Waiting Times via PxStat DWT matrix (#1899)
- `niassembly` — NI Assembly AIMS data source; MLAs, oral/written questions, and votes (#1897)

### Changed

- `nisra.cancer_waiting_times`, `nisra.child_protection`, `nisra.diagnostic_waiting_times`,
  `nisra.disease_prevalence`, `nisra.elective_waiting_times`, `nisra.emergency_care_waiting_times`
  are now at `health_ni.*`; the old paths are removed (#1963)
- Dropped Python 3.10 support; minimum is now Python 3.11 (#1935)
- Eight NISRA modules migrated from Excel scraping to the PxStat API, eliminating CI
  rate-limit errors and improving reliability (#1895)

### Fixed

- `_parse_numeric_col` comma-stripping guard now uses `pd.api.types.is_string_dtype()`
  instead of `dtype == object`; was silently skipping PyArrow-backed strings under
  pandas 3.0, leaving comma-formatted numbers unparsed (#1962)
- `wikipedia` scraper now raises `ParseError` on pages with no HTML tables instead of
  swallowing `ImportError` from missing `html5lib` (#1960)
- `ni_water` CSV fetch now uses the shared retry session instead of bypassing it via
  `pd.read_csv(url)` (#1953)
- HTTP retry logic: added jitter backoff and caching for `application/json` and
  `rss+xml` responses to reduce CI flakiness (#1958)
- `metoffice` module: added explicit timeout to all `session.get()` calls (#1942)
- CI: PyTest concurrency scoped per-ref to prevent cross-branch job starvation (#1950)
- Web integration tests replaced with local server fixtures to avoid third-party
  rate-limiting in CI (#1961)

### Also in this release

Merging main into this long-open branch pulled in two months of work landed
after the curated summary above was written. Listed as-is rather than
recategorised/rewritten, to stay accurate without re-editorialising history:

- fix(release): auto-merge patch release PRs directly (#2087)
- Fix CSV output corruption from Rich Console word-wrapping (#2085)
- fix(release-logic): handle repos with no existing tags (#2082)
- Release bolster.help; the domain now serves the chat interface (#2080)
- fix(health_ni): find turnover in the bulletin that carries it (#2081)
- Fix doctest rot and enforce doctests in CI (#2060)
- refactor(web): shared link-scraping helpers + fix list-sources coverage (#2057)
- refactor(cli): introspect list-sources from the Click command tree (#2059)
- fix(health-ni): repair disease prevalence source resolution (#2040)
- feat(psni): add motoring offences statistics module (#2029)
- feat(neet): add NISRA Young People NEET statistics (#2030)
- feat(nisra): add working and workless households (LFS) data source (#2028)
- feat: Family Resources Survey Report NI (DfC) (#2026)
- feat(health_ni): add HSC workforce and active recruitment statistics (#2024)
- feat(justice): add court prosecutions, convictions and out of court disposals (#2017)
- feat(dfi): add YPBAS travel to/from school data source (#2015)
- feat: add PPS Statistical Bulletin data source (#2014)
- feat(nisra): add NI Housing Bulletin data source (#2027)
- feat(teacher-workforce): add NISRA teacher workforce statistics module (#2013)
- feat(justice): add DoJ first time entrants to the criminal justice system (#2012)
- feat(daera): add NI Greenhouse Gas Inventory data source (#2035)
- feat(psni): add NI Road Safety Partnership safety camera detections (#2034)
- fix(ci): stop .codecov.yaml shadowing the cli.py coverage ignore (#2025)
- Stabilise the test suite: skip WAF-blocked source, fix ruff violations in tests/ (#2016)
- feat: add Child Maintenance Service statistics (DfC) (#2011)
- fix(health-ni): resolve disease prevalence via article page, not site search (#2044)
- feat(school-leavers): NI School Leavers Survey via PxStat (#2007)
- feat: add PBNI caseload statistics (annual + quarterly) (#2008)
- feat(justice): NICTS quarterly court business figures (#2009)
- refactor: consolidate \_hash_url duplicates onto bolster.utils.cache.hash_url (#2003)
- refactor(nisra): extract shared two-hop URL discovery into \_base.py (#2002)
- feat(electricity-renewables): NI Electricity Consumption and Renewable Generation (#1992)
- feat(homelessness): NI Homelessness Bulletin module (DfC/NIHE) (#1991)
- fix(labour_market): add monthly LMR track + fix force_refresh propagation (#1999)
- fix(ni_water): dynamic CKAN API lookup for resource URLs (#2000)
- fix(ci): restore write permissions in release-logic.yml (#1982)
- fix(ci): use --group fuzz flag for atheris install (#1981)
- fix(ci): address Scorecards findings — permissions, fuzzing, continue-on-error (#1980)
- feat(security): OpenSSF Best Practices compliance + Scorecards (#1970)
- fix(dva): handle sheet name format change and datetime date values (#1975)
- feat(agents): clarify agent triggers/scope, add data-maintenance agent, auto-retry timed-out CI (#1964)
- Update concurrency group format in pytest.yml
- Update concurrency group name in pytest workflow
- ci+fix(web): restore PyTest concurrency throttle, widen page cache to text/\* and skip params (#1948)
- fix(release): refresh open release PR's changelog on every main push (#1947)
- revert(ci): remove global pytest-all concurrency group (#1946)
- feat(cache): report file-download cache hit/miss counts after tests (#1945)
- fix(rebase): skip PRs with a pending PyTest run already queued (#1943)
- revert(ci): back to single global pytest-all concurrency group (#1941)
- fix(ci): scope pytest concurrency to workflow level, not job level (#1940)
- fix: only auto-release patch versions; minor and major require manual dispatch (#1894)
- fix: rebase workflow skips PRs due to UNKNOWN mergeStateStatus (#1892)
- fix: use BOLSTER_TOKEN PAT for auto-merge to trigger downstream workflows (#1891)
- fix: resolve 4 CLI bugs (#1867, #1868, #1869, #1870) (#1889)
- feat: dispatch bolster-release event to mcp.bolster.online on release (#1872)
- feat(boe): add Bank of England base rate data source (#1860)
- feat(ons): add ONS CPI/CPIH/RPI inflation data source (#1859)
- feat(nisra): add drug-related and drug misuse deaths data source (#1855)
- feat(justice): add NICTS mortgages actions for possession module (#1852)

## \[0.7.0\] - 2026-05-28

### Added

- `nisra.disease_prevalence` — NI raw disease register statistics; Table 1 registered
  patients and Table 2 prevalence per 1,000 patients across 17 disease categories (#1836)
- `nisra.disease_prevalence.get_latest_gp_prevalence` — GP-practice-level prevalence
  from 17 Table 5 sheets with practice lookup from Table 4 (359 practices) (#1839)
- `nisra.public_confidence` — Public Confidence in Official Statistics (PCOS) survey;
  awareness and trust indicators back to 2009 (#1835)
- `nisra.claimant_count` — monthly UC+JSA claimant count statistics from DfC/ONS;
  NI headline back to April 1997, with LGD and SOA breakdowns (#1833)
- `nisra.child_protection` — child protection registrations and case conferences (#1828)
- `nisra.elective_waiting_times` — elective and outpatient waiting times; inpatient/day-case
  and outpatient queues from DoH NI (#1830)
- `psni.stop_and_search` — PSNI stop & search records from OpenDataNI; 199,661 records
  covering 2017/18–2024/25 with PACE reason flags, legislation, and demographic breakdowns (#1837)
- `psni.pace` — annual PSNI PACE statistics; monthly stop & search by reason and quarterly
  arrests by gender/category back to 2013/14 (#1838)
- `psni.police_ombudsman` — annual and quarterly Police Ombudsman complaint statistics;
  complaints by district, allegation type, and outcome back to 2000/01 (#1834)
- CLI commands for `baby-names`, `work-quality`, and `education-suspensions` (#1827)
- `bolster nisra quarterly-employment-survey` — QES employee jobs by sector (#1840)

### Fixed

- `nisra/__init__.py` now correctly exports `elective_waiting_times` (was omitted despite
  module existing since #1830) (#1840)
- `psni/__init__.py` now exports `PSNIDataStaleError` and `get_historical_crime_statistics` (#1840)
- `bolster nisra labour-market --dimension all` no longer hardcodes the current quarter (#1840)
- `bolster dva` no longer requires `--latest` flag (#1840)
- `psni.crime_statistics.get_latest_crime_statistics()` now raises `PSNIDataStaleError`
  with guidance; historical data available via `get_historical_crime_statistics()` (#1823)

## \[0.6.0\] - 2026-05-21

### Added

- `nisra.population_projections` now includes LGD sub-area projections (2022-based, 2022–2047) (#1822)
- `daera_waste` — NI LAC municipal waste statistics from DAERA; waste collected, landfilled,
  and recycled by Local Authority (#1825)

## \[0.5.0\] - 2026-05-20

### Added

- `nisra.stillbirths` — monthly stillbirth registrations (#1762)
- `nisra.population_projections` updated to 2024-based NI-level series (#1762)
- `nisra.index_of_production` — quarterly Index of Production (IOP) (#1763)
- `nisra.index_of_services` — quarterly Index of Services (IOS) (#1763)
- `nisra.quarterly_employment_survey` — employee jobs by sector, Q1 1998 to present (#1764)
- `nisra.planning_statistics` — NI planning applications by council (quarterly) (#1784)
- `nisra.ashe` extended with real earnings, occupation/industry change, and pay distribution
  dimensions — Figures 2, 3, 6, 7, 8, 11, 12 (#1789)
- `gender_pay_gap` — UK Gender Pay Gap Reporting service data source (#1741)
- Sphinx documentation deployed to bolster.help via GitHub Pages (#1740)
- Weekly NISRA feed drift detection via TF-IDF (#1732)

### Changed

- `nisra` economic indicator modules consolidated into dedicated files —
  `composite_index`, `index_of_production`, `index_of_services` refactored out of
  monolithic module (#1819)
- All NISRA CLI commands standardised to use `--dimension` flag (deprecated `--table`) (#1788)

### Fixed

- `nisra.population` scraper fixed after NISRA site restructure broke URL discovery (#1758)
- `nisra.composite_index` URL updated to new `/economic-output/` path (#1809)
- `nisra.population_projections` URL auto-discovery updated for 2024-based series (#1812)
- CI retry backoff capped to prevent 2-hour hangs when NISRA servers rate-limit CI runners (#1796)
- `ashe` linked-tables parsing refactored to content-fingerprint detection for resilience (#1748)

## \[0.4.0\] - 2024-11-26

### Added

- PSNI Road Traffic Collision statistics module
- Data source info helper for crime statistics
- NISRA feed command for RSS discovery

### Changed

- Moved occupancy to tourism subpackage

______________________________________________________________________

## Version Numbering

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** version when you make incompatible API changes
- **MINOR** version when you add functionality in a backwards compatible manner
- **PATCH** version when you make backwards compatible bug fixes
