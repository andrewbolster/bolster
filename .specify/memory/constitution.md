# Bolster Project Constitution

This document establishes the inviolable principles and constraints for AI-assisted development of the Bolster Python package. These constitutional requirements supersede all other considerations and must be enforced at every level of development.

## Core Principles (MUST Level - Non-negotiable)

### 1. Security by Construction

- **No CWE Top 25 vulnerabilities** shall be introduced into the codebase
- **Input validation** must be implemented for all external data sources
- **Safe HTTP practices** using the shared `web.session` with retry logic
- **No hardcoded credentials** or sensitive data in source code

### 2. Test-First Development

- **All new modules require tests** before implementation
- **Real data tests only** - no mocks for integration tests (use `scope="class"` fixtures)
- **Test coverage >90%** for all new code (enforced by codecov/patch)
- **All tests must pass** before any release

### 3. Shared Utility Adherence

- **MUST use shared utilities** from `_base.py` modules (no reinventing wheels)
- **MUST use `web.session`** for all HTTP requests (never raw `requests.get()`)
- **MUST use `uv run`** for all Python command execution (never raw `python`)
- **MUST follow existing patterns** in similar modules before writing new code
- **MUST use `CachedDownloader`** for file downloads with appropriate TTL

### 4. Data Source Integrity

- **Data validation functions required** for all modules that process external data
- **Comprehensive error handling** for network failures and data corruption
- **Consistent data schema** using pandas DataFrames with documented column types
- **Cross-validation** with related datasets where applicable

### 5. Logging Standards

- **MUST include logger setup** in every data source module: `logger = logging.getLogger(__name__)`
- **MUST use structured logging** with appropriate levels (info/warning/error)
- **MUST NOT use `print()`** for operational messages (use logger instead)
- **SHOULD include context** in log messages (module, function, operation)

### 6. Error Handling Hierarchy

- **MUST use domain-specific exceptions** inherited from base classes:
  - `DataSourceError` (base class for all data source errors)
  - `DataNotFoundError` (for missing publications/URLs)
  - `ValidationError` (for data integrity failures)
  - `ParseError` (for file format/parsing issues)
- **MUST NOT use generic `Exception`** for domain-specific issues
- **SHOULD provide actionable error messages** with troubleshooting guidance

### 7. Function Naming Conventions

- **MUST follow naming hierarchy**:
  - `get_latest_X()` - Retrieve most recent published data
  - `parse_X_file(file_path)` - Parse downloaded files into DataFrames
  - `validate_X_data(df)` - Validate parsed data integrity
  - `get_X_summary()` - Generate analytical summaries
- **MUST use consistent parameter names** across similar functions
- **SHOULD include data type in function name** when ambiguous

### 8. Module Structure Standards

- **MUST create subpackages** when:
  - 3+ related modules share domain concepts (e.g., `nisra/tourism/`)
  - Modules will likely grow together over time
  - Clear domain boundary exists with shared utilities
- **MUST use flat modules** for standalone data sources
- **MUST follow import patterns**: `from .._base import shared_function`

### 9. Data Source Documentation

- **MUST include comprehensive module docstring** with:
  - **Data Source**: Mother page URL and official publication details
  - **Update Frequency**: Publication schedule (daily/weekly/monthly/annual)
  - **Geographic Coverage**: Spatial scope and administrative boundaries
  - **Reference Period**: Historical coverage and data availability
  - **Example**: Code snippet demonstrating basic usage
- **MUST include function docstrings** with Args, Returns, and Examples
- **SHOULD include data quality notes** and known limitations

### 10. CLI Integration Standards

- **MUST expose at least one CLI command** per data source module
- **MUST follow command pattern**: `bolster <source> <action>` (e.g., `bolster nisra deaths`)
- **MUST include comprehensive `--help`** with data source context
- **SHOULD include common options**: `--output`, `--format`, `--cache-refresh`
- **MUST provide meaningful output** for direct CLI usage (not just raw DataFrames)

## Architectural Guidelines (SHOULD Level - Strong preference)

### 1. Library-First Architecture

- Every feature should be implementable as a reusable library function
- CLI commands should be thin wrappers around library functions
- Module APIs should be consistent across all data sources

### 2. Observability Over Opacity

- Everything must be inspectable via CLI commands
- Progress indicators for long-running operations using `tqdm`
- Comprehensive logging with appropriate levels
- Clear error messages with actionable guidance

### 3. Simplicity Over Cleverness

- Start with simple implementations, add complexity only when proven necessary
- Avoid premature abstractions - three similar pieces of code before generalizing
- Prefer explicit imports over wildcard imports
- Clear variable and function names over clever abbreviations

### 4. Integration Over Isolation

- Test against real data sources in CI when possible
- Use caching to balance test reliability with performance
- Cross-validate between related datasets (births, deaths, population, migration)
- Prefer integration tests over isolated unit tests for data accuracy

## Implementation Standards (MAY Level - Best practices)

### 1. Code Quality

- Type hints for all public functions using Python 3.9+ syntax
- Docstrings with Args, Returns, and Example sections
- Pre-commit hooks must pass (ruff, formatting, YAML validation)
- Function complexity should remain low (prefer composition over complex logic)

### 2. Performance Guidelines

- Cache downloads with appropriate TTL (default 24 hours for data sources)
- Use pandas vectorized operations over explicit loops where possible
- Profile data processing functions for datasets >10MB
- Implement progress indicators for operations >5 seconds

### 3. Documentation Requirements

- All modules must have comprehensive docstrings
- Example usage in module docstrings
- CLI help text for all commands
- README coverage table updates for new data sources

### 4. Development Workflow

- Conventional commits for semantic versioning
- Feature branches with descriptive names
- PR descriptions must include data insights and usage examples
- No direct commits to main branch

## Constitutional Enforcement

### Version Control Gates

These checks are enforced before any version increment:

```python
def constitutional_pre_check():
    """Validate constitutional compliance before version bump."""
    checks = [
        verify_test_coverage_above_90_percent(),
        verify_no_security_vulnerabilities(),
        verify_all_tests_passing(),
        verify_shared_utilities_usage(),
        verify_data_validation_functions(),
        verify_logging_standards(),
        verify_error_handling_hierarchy(),
        verify_function_naming_conventions(),
        verify_data_source_documentation(),
        verify_cli_integration(),
        verify_conventional_commit_format(),
    ]
    return all(checks)
```

### AI Development Constraints

When working with AI assistants (Claude Code, Copilot, etc.):

#### MUST Constraints for AI-Generated Code

1. **Never bypass shared utilities** - AI must use existing `_base.py` functions
1. **Never skip validation functions** - all data processing must include validation
1. **Never use raw HTTP requests** - must use the configured `web.session`
1. **Never commit without tests** - AI-generated modules require test coverage

#### SHOULD Guidelines for AI Assistance

1. **Study existing patterns** before implementing new functionality
1. **Request clarification** on data source specifics before implementation
1. **Generate comprehensive docstrings** with practical examples
1. **Suggest cross-validation opportunities** with related datasets

#### Constitutional Violations - Immediate Failure

If any MUST-level requirement is violated:

1. **Halt development** immediately
1. **Flag constitutional violation** in PR/commit message
1. **Require human review** before proceeding
1. **Document exception** if violation is justified (rare)

## Agent-Specific Constitutional Requirements

### Data-Explore Agent

- **MUST NOT create production code** (only disposable scripts in `/tmp/`)
- **MUST evaluate data accessibility** before recommending implementation
- **SHOULD score complexity** and warn about integration challenges
- **MAY suggest related datasets** for cross-validation opportunities

### Data-Build Agent

- **MUST follow the module template** defined in `AGENTS.md`
- **MUST run all tests locally** before creating PR
- **MUST include data insights** in PR description
- **SHOULD suggest performance optimizations** for large datasets

### Data-Review Agent

- **MUST verify constitutional compliance** in all reviews
- **MUST check shared utility usage** in code changes
- **SHOULD identify cross-validation opportunities** in reviews
- **MAY suggest architectural improvements** aligned with constitutional principles

## Version Control Integration

### Semantic Versioning Constitutional Impact

- **PATCH**: Bug fixes, documentation, minor improvements (constitutional compliance maintained)
- **MINOR**: New data sources, features (constitutional compliance maintained + expanded)
- **MAJOR**: Breaking changes, architectural changes (constitutional review required)

### Release Gates

All releases must pass constitutional validation:

```yaml
constitutional_release_checks:
  - security_scan_clean: true
  - test_coverage_minimum: 0.90
  - all_tests_passing: true
  - shared_utilities_compliance: true
  - data_validation_present: true
  - documentation_complete: true
```

## Compliance Monitoring

### Automated Enforcement

- Pre-commit hooks enforce code quality requirements
- CI/CD pipelines validate constitutional compliance
- Version bump scripts include constitutional checks
- PR templates remind reviewers of constitutional requirements

### Manual Review Triggers

These changes require human constitutional review:

- Breaking changes to shared utilities
- New dependency additions
- Security-related modifications
- Architecture pattern changes

### Exception Process

Constitutional violations may be approved only when:

1. **Documented justification** explains why violation is necessary
1. **Technical debt ticket** created to address violation in future
1. **Security review completed** if violation affects security posture
1. **Stakeholder approval** obtained for architectural changes

______________________________________________________________________

*This constitution is living document that evolves with the project but maintains backward compatibility in constitutional requirements. Changes to MUST-level requirements require unanimous agreement from maintainers.*

**Last Updated**: 2025-02-06
**Version**: 1.0.0
**Next Review**: 2025-05-06
