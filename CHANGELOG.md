# Changelog

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
