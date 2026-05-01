# Changelog

## [0.5.0] - 2026-05-01

- feat(nisra): add stillbirths module and update population projections to 2024-based (#1762)
- fix(nisra): fix population scraper broken by NISRA site restructure (#1758)
- fix(release): use bump-my-version show to extract version after bump (#1739)
- fix(ci): allow manual dispatch of rebase workflow to update all BEHIND PRs
- fix(web): cap retry backoff to prevent CI hangs on blocked IPs
- fix(web): cap retry backoff to prevent CI hangs on blocked IPs
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
