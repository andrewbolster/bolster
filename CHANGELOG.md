# Changelog

## [0.5.1] - 2026-05-21

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


## [0.5.0] - 2026-05-20

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

## \[Unreleased\]

### Added

- Automated semantic versioning and release workflow
- Conventional commit parsing for intelligent version bumping
- Automatic changelog generation
- PR labeling system for version control override

### Changed

- Enhanced CI/CD pipeline with automated releases
- Improved documentation validation

### Fixed

- N/A

### Breaking Changes

- N/A

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
