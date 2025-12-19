# Bolster Package - Developer's Guide

**Version**: 0.4.0
**Updated**: 2024-12-19
**Status**: Development Status 2 - Pre-Alpha

## Quick Start for Development

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/andrewbolster/bolster.git
cd bolster

# Install UV package manager (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=bolster --cov-report=html

# Run specific test file
uv run pytest tests/test_bolster.py

# Run tests for specific Python version
uv run --python 3.9 pytest
```

### Code Quality Checks

```bash
# Run linting
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .

# Format code
uv run ruff format .

# Run all pre-commit hooks
pre-commit run --all-files
```

## Package Architecture

### Core Structure

```
src/bolster/
├── __init__.py          # Core utilities (concurrency, data processing, tree navigation)
├── cli.py              # Command-line interface
├── data_sources/       # Northern Ireland and UK data source modules
│   ├── companies_house.py
│   ├── eoni.py         # Electoral Office NI
│   ├── metoffice.py
│   ├── ni_house_price_index.py
│   ├── ni_water.py
│   └── wikipedia.py
├── aws.py              # AWS service integrations
├── azure.py            # Azure service integrations
├── statistics.py       # Statistical functions
├── utils.py            # General utilities
└── web.py              # Web scraping and HTTP utilities
```

### Key Module Purposes

- **`__init__.py`**: Core utility functions for concurrency, data transformation, and tree/dict navigation
- **`data_sources/`**: Specialized modules for accessing Northern Ireland and UK public data
- **`cli.py`**: Command-line tools built with Click framework
- **Cloud integrations**: AWS and Azure service handlers with best practices
- **`web.py`**: Robust HTTP request handling and web scraping utilities

## Development Workflow

### Making Changes

1. **Create a feature branch**:

   ```bash
   git checkout -b feature/your-feature-name
   ```

1. **Make your changes**:

   - Write code following existing patterns
   - Add/update tests for new functionality
   - Update docstrings and documentation

1. **Test your changes**:

   ```bash
   # Run tests
   uv run pytest

   # Check code quality
   uv run ruff check .
   ```

1. **Commit with pre-commit hooks**:

   ```bash
   git add .
   git commit -m "Brief description of changes"
   # Pre-commit hooks will run automatically
   ```

1. **Push and create PR**:

   ```bash
   git push origin feature/your-feature-name
   # Create PR on GitHub
   ```

### Pre-commit Hooks

The project uses pre-commit hooks for code quality:

- **mdformat**: Markdown formatting
- **ruff**: Python linting and formatting
- **pre-commit-hooks**: Standard checks (trailing whitespace, merge conflicts, etc.)

If pre-commit fails, fix the issues and commit again. Many issues are auto-fixed.

### Testing Strategy

#### Unit Tests

- Located in `tests/` directory
- Test individual functions and modules
- Mock external API calls to avoid network dependencies
- Use pytest fixtures for common test data

#### Python Version Compatibility

- **Supported versions**: Python 3.9, 3.10, 3.11, 3.12, 3.13
- **Note**: Click CLI behavior differs between Python 3.9 and 3.10+
- Use `@pytest.mark.skipif` for version-specific tests

#### Coverage Goals

- **Overall target**: 70%+
- **Core modules**: 80%+
- Current coverage: Check latest CI run or run `pytest --cov`

#### Notebook Testing

- Jupyter notebooks in `notebooks/` are tested with nbmake
- Ensures examples stay working

## Release Process

### Version Numbering

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (X.0.0): Breaking changes
- **MINOR** (0.X.0): New features, backwards compatible
- **PATCH** (0.0.X): Bug fixes, backwards compatible

### Creating a Release

1. **Ensure main is clean and tests pass**:

   ```bash
   git checkout main
   git pull origin main
   uv run pytest
   ```

1. **Bump version** (using bump2version):

   ```bash
   # For a minor version (0.3.4 → 0.4.0)
   bump2version minor

   # For a patch version (0.3.4 → 0.3.5)
   bump2version patch

   # For a major version (0.3.4 → 1.0.0)
   bump2version major
   ```

   This automatically:

   - Updates `pyproject.toml`
   - Creates a git commit
   - Creates a signed git tag (`v0.4.0`)

1. **Push the tag to trigger release**:

   ```bash
   git push origin main
   git push origin v0.4.0  # Replace with your version
   ```

1. **GitHub Actions will**:

   - Run full test suite
   - Check code coverage (must be ≥5%)
   - Build the package with `uv build`
   - Publish to PyPI with `uv publish`
   - Upload coverage to Codecov

### Release Workflow Details

**Trigger**: Git tags matching `v*.*.*` pattern
**Platform**: GitHub Actions (`.github/workflows/publish.yml`)
**Python Version**: 3.13 (for building)
**Publishing**: Trusted publishing to PyPI (no token needed)

## Code Quality Standards

### Linting Configuration

**Tool**: Ruff (replaces flake8, isort, black)
**Line length**: 120 characters
**Selected rules**: E (pycodestyle errors), F (pyflakes), I (isort)
**Ignored**: E501 (line too long - using 120 instead)

### Type Hints

- Use type annotations for all public functions
- Version is dynamically loaded: `importlib.metadata.version("bolster")`
- Import types from `typing` module

### Docstring Style

- Use Google or NumPy style docstrings
- Include usage examples where helpful
- Doctests are executed during test runs

### Code Organization Principles

1. **Core utilities** in `__init__.py` should be broadly useful
1. **Data sources** should be self-contained modules
1. **Mock external APIs** in tests - don't rely on network calls
1. **CLI commands** should have comprehensive help text
1. **Error handling** should be robust with clear error messages

## Common Tasks

### Adding a New Data Source

1. Create module in `src/bolster/data_sources/your_source.py`
1. Implement data retrieval functions
1. Add tests in `tests/test_your_source.py`
1. Mock external API calls in tests
1. Document the data source in README.md
1. Add CLI command if appropriate

### Adding a CLI Command

1. Add command to `src/bolster/cli.py` using Click decorators
1. Add comprehensive help text
1. Add tests in `tests/test_cli.py`
1. Update README.md with usage examples

### Updating Dependencies

```bash
# Add a new dependency
uv add package-name

# Add a development dependency
uv add --dev package-name

# Update all dependencies
uv lock --upgrade

# Sync environment
uv sync
```

## CI/CD Workflows

### Active Workflows

- **pytest.yml**: Run tests on all supported Python versions
- **notebooks.yml**: Test Jupyter notebooks
- **publish.yml**: Build and publish to PyPI on version tags
- **lint.yml**: Code quality checks
- **codeql-analysis.yml**: Security analysis

### Workflow Triggers

- **Push to main**: Tests, linting, notebooks
- **Pull requests**: Tests, linting, notebooks
- **Tags (v\*.\*.\*)**: Full test suite + PyPI publish

## External Dependencies

### Data Sources

Many data source modules depend on external APIs:

- **NI Water**: Northern Ireland Water quality data
- **EONI**: Electoral Office for Northern Ireland (some historical data unavailable)
- **Met Office**: UK weather data
- **Companies House**: UK company information
- **NIHPI**: Northern Ireland house price index

**Important**: Always mock these in tests to avoid:

- Network dependency failures in CI
- Rate limiting issues
- Data source availability issues

### Cloud Services

- **AWS**: boto3 integration for S3, DynamoDB, etc.
- **Azure**: Azure SDK integration for Blob Storage

## Documentation

### ReadTheDocs Integration

Documentation is built and hosted on ReadTheDocs:

- **URL**: https://bolster.readthedocs.io
- **Builder**: Sphinx
- **Theme**: sphinx-rtd-theme
- **Source**: `docs/` directory

### Building Documentation Locally

```bash
cd docs
uv run make html
# Open docs/_build/html/index.html
```

### Documentation Structure

- **API Reference**: Auto-generated from docstrings
- **CLI Documentation**: Generated from Click commands
- **Examples**: Jupyter notebooks in `notebooks/`

## Contributing Guidelines

### Before Submitting a PR

1. ✅ All tests pass locally
1. ✅ Pre-commit hooks pass
1. ✅ Code is documented (docstrings, type hints)
1. ✅ New features have tests
1. ✅ README updated if adding user-facing features

### PR Review Process

1. CI checks must pass
1. Code coverage should not decrease significantly
1. Code should follow existing patterns
1. Documentation should be clear and complete

## Troubleshooting

### Pre-commit Hook Failures

```bash
# Install/update hooks
pre-commit install
pre-commit autoupdate

# Run manually
pre-commit run --all-files
```

### Test Failures

```bash
# Run with verbose output
uv run pytest -v

# Run specific failing test
uv run pytest tests/test_file.py::test_function -v

# Skip slow tests
uv run pytest -m "not slow"
```

### Python Version Issues

```bash
# Test with specific Python version
uv run --python 3.9 pytest

# Check available Python versions
uv python list
```

### UV Issues

```bash
# Clear UV cache
uv cache clean

# Reinstall dependencies
rm uv.lock
uv sync
```

## Project Contacts

- **Maintainer**: Andrew Bolster
- **Email**: andrew.bolster@gmail.com
- **GitHub**: https://github.com/andrewbolster/bolster
- **Issues**: https://github.com/andrewbolster/bolster/issues
- **PyPI**: https://pypi.org/project/bolster/

## License

GNU General Public License v3 (GPLv3) - See LICENSE file for details.
