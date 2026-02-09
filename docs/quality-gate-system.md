# Quality Gate System

This document describes the comprehensive pre-merge quality gate system that replaces the legacy `constitutional_check.py` with a modern, standards-based validation system.

## Overview

The quality gate system leverages existing mature tools instead of custom validation code:

- **ruff**: For code style, import organization, and docstring validation
- **pytest-cov**: For test coverage analysis with 80% threshold
- **Custom checks**: For domain-specific patterns that can't be expressed in standard tools

## Architecture

### Core Components

1. **Enhanced ruff configuration** (`pyproject.toml`)

   - Expanded rule set including docstring validation (D), print detection (T20), and bug detection (B)
   - Per-file rule exceptions for different module types
   - Google-style docstring convention

1. **Coverage configuration** (`pyproject.toml`)

   - 80% coverage threshold requirement
   - Detailed reporting with missing line information
   - Excludes common patterns that don't need coverage

1. **Quality gate orchestrator** (`scripts/quality_gate.py`)

   - Aggregates results from multiple quality tools
   - Generates unified reports with actionable feedback
   - Supports multiple output formats (text, JSON, GitHub Actions)
   - Operates in advisory mode by default (non-blocking)

### Quality Dimensions Validated

#### 1. Code Style & Quality (via ruff)

- **Pycodestyle errors/warnings** (E, W): Standard Python style issues
- **Pyflakes** (F): Unused imports, undefined variables
- **Import organization** (I): Proper import sorting and grouping
- **Docstring quality** (D): Presence and format of documentation
- **Modern Python patterns** (UP): Use of current Python idioms
- **Bug detection** (B): Common programming errors
- **Print statement detection** (T20): Prevents print() in library code

#### 2. Test Coverage (via pytest-cov)

- **80% minimum coverage** threshold
- **Line-by-line reporting** of missing coverage
- **Excludes appropriate patterns** (test files, __init__.py, etc.)

#### 3. Domain-Specific Patterns (custom checks)

- **Shared utilities usage**: Enforces `bolster.utils.web.session` instead of raw `requests`
- **Download patterns**: Requires `download_file()` from `_base` modules instead of direct HTTP calls
- **Additional patterns**: Extensible system for project-specific requirements

## Usage

### Command Line

```bash
# Run full quality gate analysis
uv run scripts/quality_gate.py

# Generate JSON report for tool integration
uv run scripts/quality_gate.py --format json

# Run in blocking mode (for CI/CD gates)
uv run scripts/quality_gate.py --fail-on-issues

# Quick demo on subset of files
uv run scripts/quality_gate_demo.py
```

### CI/CD Integration

The system is integrated into the GitHub Actions workflow (`auto-release.yml`):

```yaml
- name: Quality gate validation
  run: |
    echo "🏗️  Running quality gate validation before release..."
    uv run scripts/quality_gate.py --format github
```

### Pre-commit Integration

Quality checks run automatically via pre-commit hooks:

```bash
# Manual run of all pre-commit checks
uv run pre-commit run --all-files
```

## Configuration

### Ruff Configuration

The enhanced ruff configuration in `pyproject.toml` includes:

```toml
[tool.ruff]
lint.select = [
    "E", "F", "I",  # Basic style and errors
    "W",            # Warnings
    "D",            # Docstring validation
    "UP",           # Modern Python patterns
    "B",            # Bug detection
    "T20",          # Print detection
    # ... additional rules
]

# Per-file exceptions
[tool.ruff.lint.per-file-ignores]
"src/bolster/cli.py" = ["T20"]        # Allow print() in CLI
"scripts/**/*.py" = ["T20"]           # Allow print() in scripts
"tests/**/*.py" = ["D", "T20"]        # Relax rules in tests
```

### Coverage Configuration

```toml
[tool.coverage.report]
fail_under = 80          # 80% threshold
show_missing = true      # Show uncovered lines
sort = "Miss"           # Sort by missing coverage
```

## Migration from Constitutional Checker

### What Changed

| Before (constitutional_check.py) | After (quality gate system) |
|----------------------------------|----------------------------|
| Custom AST parsing | Standard ruff rules |
| Hardcoded file patterns | Configurable ruff exceptions |
| String-based pattern matching | Semantic code analysis |
| Single custom script | Orchestrated mature tools |
| Ad-hoc violation reporting | Standardized quality reports |

### Preserved Patterns

All original validation patterns are preserved but implemented through standard tools:

1. **Shared utilities usage** → Custom checks + ruff import rules
1. **Logging standards** → Ruff print detection (T20) + custom logger checks
1. **Documentation requirements** → Ruff docstring validation (D rules)
1. **Function naming** → Can be added as ruff custom rules if needed
1. **Exception hierarchy** → Ruff bug detection (B rules)

### Benefits of New System

1. **Standards-based**: Uses mature, well-tested linting tools
1. **Configurable**: Rules can be modified without code changes
1. **Extensible**: Easy to add new quality dimensions
1. **Maintainable**: Leverages community-maintained rule sets
1. **Advisory mode**: Reports issues without blocking builds initially
1. **Comprehensive reporting**: Detailed file/line-level feedback

## Examples

### Sample Quality Report

```
🏗️  Bolster Quality Gate Report
==================================================
❌ Code Quality (ruff): 15 violations found
   📂 documentation: 8 issues
      src/bolster/data_sources/births.py:1 - Missing docstring in public module
      src/bolster/utils/cache.py:45 - Missing function docstring
   📂 print_statements: 2 issues
      src/bolster/experimental/debug.py:23 - print() call found

✅ Test Coverage: 82.4% (≥80% required)

❌ Domain-Specific Rules: 1 violation found
   src/bolster/experimental/fetcher.py:15 - Use bolster.utils.web.session instead of raw requests

==================================================
⚠️  Quality issues found: 16 total violations
Review the issues above and address them to improve code quality.
(Note: This is running in advisory mode - builds are not blocked)
```

### Integration with Development Workflow

1. **Pre-commit hooks** catch issues before commit
1. **Quality gate** provides comprehensive pre-merge validation
1. **Advisory mode** allows gradual improvement without blocking development
1. **Detailed reports** give actionable guidance for fixes

## Future Enhancements

The quality gate system is designed to be extensible:

1. **Additional ruff rules** can be enabled as the codebase matures
1. **Custom domain checks** can be added to `quality_gate.py`
1. **Blocking mode** can be enabled when quality debt is reduced
1. **Tool integration** with IDEs and other development tools
1. **Metrics tracking** over time to measure quality improvements

## Troubleshooting

### Common Issues

**"Ruff configuration error"**: Check `pyproject.toml` syntax and rule names
**"Coverage too low"**: Review uncovered lines and add tests or exclusions
**"Quality gate timeout"**: Use demo version or increase timeout limits
**"Custom check failures"**: Review shared utilities imports and usage patterns

### Getting Help

1. Check configuration in `pyproject.toml`
1. Run demo version: `uv run scripts/quality_gate_demo.py`
1. Review individual tool outputs: `uv run ruff check src/`
1. Check coverage details: `uv run pytest --cov=src/bolster --cov-report=term-missing`
