=============================
Data Source Development Guide
=============================

This guide provides comprehensive instructions for adding new data sources to Bolster. It is based on the patterns established in the NISRA (Northern Ireland Statistics and Research Agency) modules and will help you create consistent, maintainable, and well-tested data source integrations.

.. contents:: Table of Contents
   :local:
   :depth: 3

Overview
========

What is a Data Source Module?
------------------------------

A data source module in Bolster provides programmatic access to external datasets through:

- **Automatic data discovery**: Scraping publication pages to find the latest data files
- **Intelligent caching**: Avoiding unnecessary downloads with configurable TTL
- **Consistent parsing**: Converting raw data (Excel, CSV, etc.) to pandas DataFrames
- **Data validation**: Ensuring data integrity and consistency
- **Convenience functions**: Helper functions for common data analysis tasks
- **CLI integration**: Command-line access for end users

Design Philosophy
-----------------

Bolster data source modules follow these principles:

1. **Zero configuration for common cases**: ``get_latest_X()`` should "just work"
2. **Cache by default**: Respect bandwidth and remote servers
3. **Fail gracefully**: Provide clear error messages when data is unavailable
4. **Document the source**: Always include URLs to the original data
5. **Validate rigorously**: Don't trust external data without verification
6. **Test comprehensively**: Integrity tests ensure modules don't break silently

Getting Started
===============

Directory Structure
-------------------

Data source modules live in ``src/bolster/data_sources/<source_name>/``:

.. code-block:: text

    src/bolster/data_sources/
    └── <source_name>/              # e.g., "nisra", "psni", "doj"
        ├── __init__.py             # Public API exports
        ├── _base.py                # Shared utilities (optional but recommended)
        ├── README.md               # Module-level documentation
        ├── <dataset_1>.py          # Individual dataset module
        ├── <dataset_2>.py          # Individual dataset module
        └── ...

**Example** (NISRA structure):

.. code-block:: text

    src/bolster/data_sources/nisra/
    ├── __init__.py                 # Exports all public functions
    ├── _base.py                    # Common utilities: caching, Excel parsing, errors
    ├── README.md                   # Comprehensive module documentation
    ├── population.py               # Mid-year population estimates
    ├── births.py                   # Birth registrations
    ├── deaths.py                   # Death registrations
    ├── marriages.py                # Marriage registrations
    └── ...                         # 10 total dataset modules

Naming Conventions
------------------

Use these naming patterns for consistency:

- **Module directory**: ``<organization>`` (e.g., ``nisra``, ``psni``, ``doj``)
- **Dataset files**: ``<dataset_topic>.py`` (e.g., ``population.py``, ``crime_statistics.py``)
- **Base utilities**: ``_base.py`` (underscore prefix indicates internal)
- **Tests**: ``tests/test_<source>_<dataset>_integrity.py``

Core Components
===============

The _base.py Module
-------------------

Create ``_base.py`` to share common functionality across dataset modules:

.. code-block:: python

    """Common utilities for <SOURCE> data sources."""

    import hashlib
    import logging
    from datetime import datetime
    from pathlib import Path
    from typing import Dict, List, Optional

    import requests
    from bs4 import BeautifulSoup

    logger = logging.getLogger(__name__)

    # Cache directory
    CACHE_DIR = Path.home() / ".cache" / "bolster" / "<source_name>"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

**Essential Components in _base.py:**

1. **Custom Exceptions**:

   .. code-block:: python

       class SourceDataError(Exception):
           """Base exception for data source errors."""
           pass

       class SourceDataNotFoundError(SourceDataError):
           """Data file not available."""
           pass

       class SourceValidationError(SourceDataError):
           """Data validation failed."""
           pass

2. **Caching Utilities**:

   .. code-block:: python

       def hash_url(url: str) -> str:
           """Generate a safe filename from a URL."""
           return hashlib.md5(url.encode()).hexdigest()

       def get_cached_file(url: str, cache_ttl_hours: int = 24) -> Optional[Path]:
           """Return cached file if exists and fresh, else None."""
           url_hash = hash_url(url)
           ext = Path(url).suffix or ".bin"
           cache_path = CACHE_DIR / f"{url_hash}{ext}"

           if cache_path.exists():
               age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
               if age.total_seconds() < cache_ttl_hours * 3600:
                   logger.info(f"Using cached file: {cache_path}")
                   return cache_path

           return None

       def download_file(url: str, cache_ttl_hours: int = 24,
                        force_refresh: bool = False) -> Path:
           """Download a file with caching support."""
           # Check cache first
           if not force_refresh:
               cached = get_cached_file(url, cache_ttl_hours)
               if cached:
                   return cached

           # Download and cache
           url_hash = hash_url(url)
           ext = Path(url).suffix or ".bin"
           cache_path = CACHE_DIR / f"{url_hash}{ext}"

           try:
               logger.info(f"Downloading {url}")
               response = requests.get(url, timeout=30)
               response.raise_for_status()
               cache_path.write_bytes(response.content)
               logger.info(f"Saved to {cache_path}")
               return cache_path
           except requests.RequestException as e:
               raise SourceDataNotFoundError(f"Failed to download {url}: {e}")

3. **Scraping Utilities**:

   .. code-block:: python

       def scrape_download_links(page_url: str,
                                file_extension: str = ".xlsx") -> List[dict]:
           """Scrape download links from a page.

           Returns:
               List of dicts with 'url' and 'text' keys
           """
           try:
               response = requests.get(page_url, timeout=30)
               response.raise_for_status()
           except requests.RequestException as e:
               raise SourceDataError(f"Failed to fetch page {page_url}: {e}")

           soup = BeautifulSoup(response.content, "html.parser")
           links = []

           for a_tag in soup.find_all("a", href=True):
               href = a_tag["href"]
               if file_extension in href.lower():
                   # Make absolute URL
                   if href.startswith("/"):
                       url = f"https://www.example.gov.uk{href}"
                   elif not href.startswith("http"):
                       url = f"https://www.example.gov.uk/{href}"
                   else:
                       url = href

                   links.append({"url": url, "text": a_tag.get_text(strip=True)})

           return links

4. **Excel Parsing Utilities** (if working with Excel files):

   .. code-block:: python

       def safe_int(val) -> Optional[int]:
           """Safely convert value to integer, handling placeholders."""
           if val is None or val == "" or val == "-":
               return None
           try:
               return int(val)
           except (ValueError, TypeError):
               return None

       def safe_float(val) -> Optional[float]:
           """Safely convert value to float, handling placeholders."""
           if val is None or val == "" or val == "-":
               return None
           try:
               return float(val)
           except (ValueError, TypeError):
               return None

       def find_header_row(sheet, expected_columns: List[str],
                          max_rows: int = 20) -> Optional[int]:
           """Find the row number containing expected column headers.

           Args:
               sheet: openpyxl worksheet object
               expected_columns: Column names to search for (case-insensitive)
               max_rows: Maximum rows to search

           Returns:
               1-based row number where headers are found, or None
           """
           for row_idx, row in enumerate(sheet.iter_rows(
               min_row=1, max_row=max_rows, values_only=True), 1):
               row_str = [str(cell).lower() if cell else "" for cell in row]

               matches = sum(1 for expected in expected_columns
                           if any(expected.lower() in cell for cell in row_str))

               if matches == len(expected_columns):
                   logger.debug(f"Found header row at row {row_idx}")
                   return row_idx

           logger.warning(f"Could not find header row with columns: {expected_columns}")
           return None

Individual Dataset Modules
---------------------------

Each dataset gets its own module file (e.g., ``population.py``, ``crime_statistics.py``).

**Module Template:**

.. code-block:: python

    """<Dataset Name> Data Source.

    <Brief description of the dataset>

    Data includes:
    - <Key feature 1>
    - <Key feature 2>
    - <Key feature 3>

    Data Source:
        **Mother Page**: <URL to main listings page>

        <Description of how data is discovered and accessed>

    Update Frequency: <e.g., Monthly, Annual, Quarterly>
    Geographic Coverage: <e.g., Northern Ireland, UK>
    Reference Date: <What the dates in the data represent>

    Example:
        >>> from bolster.data_sources.<source> import <dataset>
        >>> # Get latest data
        >>> df = <dataset>.get_latest_<dataset>()
        >>> print(df.head())
    """

    import logging
    from pathlib import Path
    from typing import Tuple, Union

    import pandas as pd

    from ._base import (
        SourceDataNotFoundError,
        SourceValidationError,
        download_file
    )

    logger = logging.getLogger(__name__)

    # Base URL for this dataset
    BASE_URL = "https://www.example.gov.uk/statistics/<topic>"

**Required Functions:**

1. **get_latest_<dataset>_publication_url() -> Tuple[str, ...]**

   Scrapes the source website to find the most recent data file.

   .. code-block:: python

       def get_latest_<dataset>_publication_url() -> Tuple[str, int]:
           """Scrape source to find the latest data file.

           Returns:
               Tuple of (excel_file_url, year)

           Raises:
               SourceDataNotFoundError: If publication or file not found
           """
           import requests
           from bs4 import BeautifulSoup

           try:
               response = requests.get(BASE_URL, timeout=30)
               response.raise_for_status()
           except requests.RequestException as e:
               raise SourceDataNotFoundError(f"Failed to fetch page: {e}")

           soup = BeautifulSoup(response.content, "html.parser")

           # Find the latest publication link
           # (Customize this for your source's HTML structure)
           for link in soup.find_all("a", href=True):
               link_text = link.get_text(strip=True)

               # Look for patterns in link text
               if "Latest Report" in link_text:
                   href = link["href"]
                   if href.startswith("/"):
                       href = f"https://www.example.gov.uk{href}"

                   # Extract year or other metadata
                   year = 2024  # Parse from link_text or URL

                   return href, year

           raise SourceDataNotFoundError("Could not find latest publication")

2. **parse_<dataset>_file(file_path: Union[str, Path], ...) -> pd.DataFrame**

   Parses the downloaded file into a pandas DataFrame.

   .. code-block:: python

       def parse_<dataset>_file(
           file_path: Union[str, Path],
           # Add optional parameters for filtering/customization
       ) -> pd.DataFrame:
           """Parse data file into DataFrame.

           Args:
               file_path: Path to the data file

           Returns:
               DataFrame with columns:
                   - column1: Description
                   - column2: Description
                   ...

           Raises:
               SourceValidationError: If file structure is unexpected
           """
           file_path = Path(file_path)

           try:
               # Read the file (adjust for Excel, CSV, etc.)
               df = pd.read_excel(file_path, sheet_name="Data")
           except Exception as e:
               raise SourceValidationError(f"Failed to read file: {e}")

           # Validate expected columns
           expected_cols = {"col1", "col2", "col3"}
           if not expected_cols.issubset(df.columns):
               missing = expected_cols - set(df.columns)
               raise SourceValidationError(f"Missing columns: {missing}")

           # Clean and transform data
           df = df.rename(columns={"old_name": "new_name"})
           df["date"] = pd.to_datetime(df["date"])
           df = df.sort_values("date").reset_index(drop=True)

           # Log summary
           logger.info(f"Parsed {len(df)} records from {file_path.name}")

           return df

3. **get_latest_<dataset>(force_refresh: bool = False, ...) -> pd.DataFrame**

   Convenience function that discovers, downloads, and parses in one call.

   .. code-block:: python

       def get_latest_<dataset>(
           force_refresh: bool = False,
       ) -> pd.DataFrame:
           """Get the latest data with automatic discovery and caching.

           Args:
               force_refresh: If True, bypass cache and download fresh data

           Returns:
               DataFrame with parsed data

           Raises:
               SourceDataNotFoundError: If latest publication cannot be found
               SourceValidationError: If file structure is unexpected

           Example:
               >>> df = get_latest_<dataset>()
               >>> print(df.shape)
               >>> # Filter and analyze
               >>> df_2024 = df[df['year'] == 2024]
           """
           # Discover latest publication
           excel_url, year = get_latest_<dataset>_publication_url()

           logger.info(f"Downloading {year} data from: {excel_url}")

           # Download with appropriate cache TTL
           # Use longer TTL for annual data, shorter for frequent updates
           cache_ttl_hours = 180 * 24  # 180 days for annual data
           file_path = download_file(
               excel_url,
               cache_ttl_hours=cache_ttl_hours,
               force_refresh=force_refresh
           )

           # Parse and return
           return parse_<dataset>_file(file_path)

**Optional but Recommended Functions:**

4. **Validation Functions**:

   .. code-block:: python

       def validate_<dataset>_<check>(df: pd.DataFrame) -> bool:
           """Validate data integrity.

           Args:
               df: DataFrame from parse_<dataset>_file or get_latest_<dataset>

           Returns:
               True if validation passes

           Raises:
               SourceValidationError: If validation fails
           """
           # Perform validation checks
           # Example: Check totals add up
           for group_key, group_data in df.groupby("category"):
               total = group_data["total"].iloc[0]
               parts_sum = group_data["part1"].sum() + group_data["part2"].sum()

               if total != parts_sum:
                   raise SourceValidationError(
                       f"{group_key}: Total ({total}) != Sum of parts ({parts_sum})"
                   )

           logger.info(f"Validation passed: {len(df)} records checked")
           return True

5. **Helper/Filter Functions**:

   .. code-block:: python

       def get_<dataset>_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
           """Filter data for a specific year."""
           return df[df["year"] == year].reset_index(drop=True)

       def get_<dataset>_summary(df: pd.DataFrame) -> pd.DataFrame:
           """Calculate summary statistics."""
           return df.groupby("category").agg({
               "value": ["sum", "mean", "count"]
           }).reset_index()

The __init__.py File
--------------------

Export the public API from ``__init__.py``:

.. code-block:: python

    """<Source Name> Data Sources.

    This module provides access to <organization> open data including:
    - <Dataset 1>: <Brief description>
    - <Dataset 2>: <Brief description>
    - ...

    Example:
        >>> from bolster.data_sources.<source> import <dataset>
        >>> df = <dataset>.get_latest_<dataset>()

    See individual module docstrings for detailed documentation.
    """

    # Import key functions from each module
    from .<dataset_1> import (
        get_latest_<dataset_1>,
        parse_<dataset_1>_file,
        validate_<dataset_1>,
    )

    from .<dataset_2> import (
        get_latest_<dataset_2>,
        parse_<dataset_2>_file,
    )

    # Import exceptions for users
    from ._base import (
        SourceDataError,
        SourceDataNotFoundError,
        SourceValidationError,
    )

    __all__ = [
        # Dataset 1
        "get_latest_<dataset_1>",
        "parse_<dataset_1>_file",
        "validate_<dataset_1>",
        # Dataset 2
        "get_latest_<dataset_2>",
        "parse_<dataset_2>_file",
        # Exceptions
        "SourceDataError",
        "SourceDataNotFoundError",
        "SourceValidationError",
    ]

Documentation Standards
=======================

Module-Level Documentation
--------------------------

Every dataset module must have comprehensive docstrings:

1. **First paragraph**: Brief description (1-2 sentences)
2. **"Data includes:" section**: Bullet list of key features
3. **"Data Source:" section**:
   - **Mother Page**: URL to main listings/publications page
   - Description of how data is discovered
4. **Metadata**:
   - **Update Frequency**: How often data is published
   - **Geographic Coverage**: Region covered
   - **Reference Date**: What dates in the data represent
5. **Example**: Short code snippet showing basic usage

**Example** (from NISRA population.py):

.. code-block:: python

    """NISRA Mid-Year Population Estimates Data Source.

    Provides access to mid-year population estimates for Northern Ireland with breakdowns by:
    - Geography (Northern Ireland, Parliamentary Constituencies, Health and Social Care Trusts)
    - Sex (All persons, Males, Females)
    - Age (5-year age bands: 00-04, 05-09, ..., 85-89, 90+)
    - Year (1971-present for NI overall, 2021-present for sub-geographies)

    Mid-year estimates are referenced to June 30th of each year.

    Data Source:
        **Mother Page**: https://www.nisra.gov.uk/statistics/people-and-communities/population

        This page lists all population statistics publications in reverse chronological order
        (newest first). The module automatically scrapes this page to find the latest
        "Mid-Year Population Estimates for Small Geographical Areas" publication, then downloads
        the age bands Excel file from that publication's detail page.

    Update Frequency: Annual (published ~6 months after reference date)
    Geographic Coverage: Northern Ireland
    Reference Date: June 30th of each year

    Example:
        >>> from bolster.data_sources.nisra import population
        >>> # Get latest population estimates
        >>> df = population.get_latest_population()
        >>> print(df.head())
    """

Function Documentation
----------------------

All public functions must have complete docstrings with:

1. **Brief description**: One-line summary
2. **Args**: Type-annotated parameters with descriptions
3. **Returns**: Description of return value with column details for DataFrames
4. **Raises**: Exception types and conditions
5. **Example**: Usage example with realistic code

**Example**:

.. code-block:: python

    def get_latest_population(
        area: Optional[
            Literal[
                "all",
                "Northern Ireland",
                "Parliamentary Constituencies (2024)",
                "Health and Social Care Trusts",
            ]
        ] = "all",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Get the latest mid-year population estimates.

        Automatically discovers and downloads the most recent population estimates
        from the NISRA website.

        Args:
            area: Which geographic area(s) to return (default: "all")
            force_refresh: If True, bypass cache and download fresh data

        Returns:
            DataFrame with columns:
                - area, area_code, area_name: Geographic identifiers
                - year: Reference year
                - sex: "All persons", "Males", or "Females"
                - age_5: 5-year age band
                - age_band, age_broad: Alternative age groupings
                - population: Mid-year estimate

        Raises:
            NISRADataNotFoundError: If latest publication cannot be found
            NISRAValidationError: If file structure is unexpected

        Example:
            >>> # Get all data
            >>> df = get_latest_population()

            >>> # Get only Northern Ireland overall
            >>> ni_df = get_latest_population(area='Northern Ireland')

            >>> # Calculate total NI population in latest year
            >>> ni_2024 = ni_df[(ni_df['year'] == 2024) & (ni_df['sex'] == 'All persons')]
            >>> total = ni_2024['population'].sum()
        """

Module README
-------------

Create ``README.md`` in the module directory with:

1. **Overview**: What data is available
2. **Quick Start**: Basic usage examples
3. **Available Datasets**: Table of all dataset modules
4. **Common Patterns**: Frequently used analysis patterns
5. **Data Quality**: Notes on validation and limitations
6. **License/Attribution**: Data source licenses and attribution requirements

See ``src/bolster/data_sources/nisra/README.md`` for a complete example.

Testing
=======

Integrity Tests
---------------

Create comprehensive integrity tests in ``tests/test_<source>_<dataset>_integrity.py``:

.. code-block:: python

    """Integrity tests for <source> <dataset> data source."""

    import pytest
    import pandas as pd

    from bolster.data_sources.<source> import <dataset>


    @pytest.fixture(scope="module")
    def data():
        """Load data once for all tests."""
        return <dataset>.get_latest_<dataset>()


    class TestDataStructure:
        """Test data structure and format."""

        def test_returns_dataframe(self, data):
            """Should return a pandas DataFrame."""
            assert isinstance(data, pd.DataFrame)

        def test_not_empty(self, data):
            """Should contain data."""
            assert len(data) > 0

        def test_has_expected_columns(self, data):
            """Should have all expected columns."""
            expected = {"column1", "column2", "column3"}
            assert expected.issubset(set(data.columns))

        def test_no_duplicate_keys(self, data):
            """Should have no duplicate keys."""
            key_cols = ["col1", "col2"]
            assert not data.duplicated(subset=key_cols).any()


    class TestDataQuality:
        """Test data quality and integrity."""

        def test_no_null_in_required_columns(self, data):
            """Required columns should have no null values."""
            required = ["column1", "column2"]
            for col in required:
                assert data[col].notna().all(), f"{col} has null values"

        def test_valid_date_range(self, data):
            """Dates should be within reasonable range."""
            assert data["date"].min() >= pd.Timestamp("2000-01-01")
            assert data["date"].max() <= pd.Timestamp.now()

        def test_numeric_columns_positive(self, data):
            """Numeric values should be non-negative."""
            numeric_cols = ["value1", "value2"]
            for col in numeric_cols:
                assert (data[col] >= 0).all(), f"{col} has negative values"


    class TestDataValidation:
        """Test data validation functions."""

        def test_validation_passes(self, data):
            """Data validation should pass."""
            assert <dataset>.validate_<dataset>(data)

        def test_totals_match_sum_of_parts(self, data):
            """Total columns should equal sum of constituent parts."""
            for _, row in data.iterrows():
                total = row["total"]
                parts_sum = row["part1"] + row["part2"]
                assert abs(total - parts_sum) < 0.01, \
                    f"Total {total} != Parts sum {parts_sum}"


    class TestHelperFunctions:
        """Test helper and filter functions."""

        def test_filter_by_year(self, data):
            """Should filter to specific year."""
            years = data["year"].unique()
            test_year = years[0]

            filtered = <dataset>.get_<dataset>_by_year(data, test_year)

            assert (filtered["year"] == test_year).all()
            assert len(filtered) > 0

        def test_summary_statistics(self, data):
            """Should calculate summary statistics."""
            summary = <dataset>.get_<dataset>_summary(data)

            assert isinstance(summary, pd.DataFrame)
            assert len(summary) > 0


**Test Coverage Requirements:**

- Aim for >90% code coverage
- Test all public functions
- Test error conditions (invalid inputs, missing files, etc.)
- Test data validation logic
- Mock network calls where appropriate to avoid flakiness

CLI Integration
===============

Adding CLI Commands
-------------------

If your data source would benefit from CLI access, add commands to ``src/bolster/cli.py``:

.. code-block:: python

    @cli.command("get-<dataset>")
    @click.option(
        "--output",
        "-o",
        type=click.Path(),
        default="<dataset>.csv",
        help="Output CSV file path",
    )
    @click.option(
        "--year",
        type=int,
        help="Filter to specific year",
    )
    @click.option(
        "--force-refresh",
        is_flag=True,
        help="Force download fresh data (bypass cache)",
    )
    def get_<dataset>_cli(output, year, force_refresh):
        """Download <dataset> data from <source>.

        Examples:

            # Download latest data to default file
            bolster get-<dataset>

            # Download data for specific year
            bolster get-<dataset> --year 2024

            # Force fresh download
            bolster get-<dataset> --force-refresh
        """
        try:
            click.echo(f"Fetching <dataset> data...")

            # Get data
            df = get_latest_<dataset>(force_refresh=force_refresh)

            # Apply filters
            if year:
                df = df[df["year"] == year]
                click.echo(f"Filtered to year {year}: {len(df)} records")

            # Save to file
            df.to_csv(output, index=False)
            click.echo(f"✓ Saved {len(df)} records to {output}")

        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            raise click.Abort()

Python Compatibility
====================

Python 3.9+ Type Hints
----------------------

**CRITICAL**: All type hints must be compatible with Python 3.9+.

**DO NOT USE** (Python 3.10+ only):

.. code-block:: python

    # ❌ WRONG - PEP 604 union syntax not in Python 3.9
    def parse_file(file_path: str | Path) -> pd.DataFrame:
        ...

    # ❌ WRONG - Lowercase generics not in Python 3.9
    def get_links(page_url: str) -> list[dict]:
        ...

    def get_mapping() -> dict[str, int]:
        ...

    def get_url() -> tuple[str, int]:
        ...

**USE INSTEAD** (Python 3.9+ compatible):

.. code-block:: python

    # ✓ CORRECT - Use typing module
    from typing import Dict, List, Optional, Tuple, Union

    def parse_file(file_path: Union[str, Path]) -> pd.DataFrame:
        ...

    def get_links(page_url: str) -> List[dict]:
        ...

    def get_mapping() -> Dict[str, int]:
        ...

    def get_url() -> Tuple[str, int]:
        ...

    # For optional union types
    def get_optional_area(area: Optional[str] = None) -> Optional[pd.DataFrame]:
        ...

**Common Patterns:**

.. code-block:: python

    from typing import Dict, List, Literal, Optional, Tuple, Union
    from pathlib import Path
    import pandas as pd

    # Union types
    def parse(file_path: Union[str, Path]) -> pd.DataFrame:
        ...

    # Optional parameters
    def get_data(year: Optional[int] = None) -> pd.DataFrame:
        ...

    # List/Dict/Tuple generics
    def scrape() -> List[dict]:
        ...

    def map_columns() -> Dict[str, int]:
        ...

    def discover() -> Tuple[str, int]:
        ...

    # Complex Optional[Literal[...]]
    def parse_file(
        file_path: Union[str, Path],
        area: Optional[Literal["all", "Northern Ireland", "Regions"]] = "all",
    ) -> pd.DataFrame:
        ...

Common Patterns and Best Practices
===================================

Caching Strategy
----------------

Choose appropriate cache TTL based on update frequency:

.. code-block:: python

    # Annual data (population, census): 180 days
    cache_ttl_hours = 180 * 24

    # Quarterly data (economic indicators): 60 days
    cache_ttl_hours = 60 * 24

    # Monthly data (births, marriages): 30 days
    cache_ttl_hours = 30 * 24

    # Weekly data (provisional stats): 7 days
    cache_ttl_hours = 7 * 24

    # Daily data (real-time feeds): 1 day
    cache_ttl_hours = 24

Error Handling
--------------

Use specific exception types for different failure modes:

.. code-block:: python

    try:
        # Network request
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise SourceDataNotFoundError(f"Failed to fetch page: {e}")

    try:
        # File parsing
        df = pd.read_excel(file_path)
    except Exception as e:
        raise SourceValidationError(f"Failed to parse file: {e}")

    # Data validation
    if expected_cols not in df.columns:
        raise SourceValidationError(f"Missing columns: {expected_cols}")

Logging
-------

Use appropriate log levels:

.. code-block:: python

    import logging
    logger = logging.getLogger(__name__)

    # Info: Normal operations
    logger.info(f"Downloading {year} data from {url}")
    logger.info(f"Parsed {len(df)} records")
    logger.info("Validation passed")

    # Debug: Detailed information for troubleshooting
    logger.debug(f"Found header row at row {row_idx}")
    logger.debug(f"Cache hit: {cache_path}")

    # Warning: Potential issues that don't stop execution
    logger.warning(f"Could not find column: {col_name}, using default")
    logger.warning(f"{missing_count} records have missing data")

RSS Feed Discovery
------------------

For sources with RSS feeds, use ``bolster.utils.rss`` for automatic discovery:

.. code-block:: python

    from bolster.utils.rss import find_feed, parse_feed

    # Find RSS feed for a page
    feed_url = find_feed("https://www.example.gov.uk/statistics")

    if feed_url:
        # Parse feed entries
        entries = parse_feed(feed_url)

        # Find latest publication
        for entry in entries:
            if "Latest Report" in entry.title:
                publication_url = entry.link
                publication_date = entry.published_parsed
                break

Excel Parsing Tips
------------------

Common patterns for handling messy Excel files:

.. code-block:: python

    import openpyxl

    # Skip header rows
    df = pd.read_excel(file_path, sheet_name="Data", skiprows=3)

    # Read specific range
    wb = openpyxl.load_workbook(file_path)
    sheet = wb["Table 1"]

    # Find header row dynamically
    header_row = find_header_row(sheet, ["Year", "Total", "Male", "Female"])

    # Extract column mapping
    col_map = extract_column_mapping(sheet, header_row, ["Year", "Total"])

    # Read data starting from header
    data = []
    for row in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        if row[col_map["Year"]]:  # Skip empty rows
            data.append({
                "year": safe_int(row[col_map["Year"]]),
                "total": safe_int(row[col_map["Total"]]),
            })

    df = pd.DataFrame(data)

    # Handle merged cells
    # Openpyxl returns None for merged cells except the top-left
    # Use forward-fill for category columns
    df["category"] = df["category"].ffill()

Example Walkthrough: PSNI Crime Statistics
===========================================

Let's walk through creating a new data source for PSNI (Police Service of Northern Ireland) crime statistics.

Step 1: Research the Data Source
---------------------------------

1. **Find the data page**: https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics
2. **Identify patterns**:
   - Monthly Excel files
   - Files named like "Police Recorded Crime Apr 2024.xlsx"
   - Contains sheets: "Summary", "Offence Type", "Geographic Area"
3. **Determine update frequency**: Monthly (published ~15th of following month)
4. **Check if RSS available**: Yes, https://www.psni.police.uk/rss/official-statistics

Step 2: Create Directory Structure
-----------------------------------

.. code-block:: bash

    mkdir -p src/bolster/data_sources/psni
    touch src/bolster/data_sources/psni/__init__.py
    touch src/bolster/data_sources/psni/_base.py
    touch src/bolster/data_sources/psni/crime_statistics.py
    touch src/bolster/data_sources/psni/README.md

Step 3: Create _base.py
------------------------

.. code-block:: python

    """Common utilities for PSNI data sources."""

    import hashlib
    import logging
    from datetime import datetime
    from pathlib import Path
    from typing import List, Optional

    import requests
    from bs4 import BeautifulSoup

    logger = logging.getLogger(__name__)

    # Cache directory
    CACHE_DIR = Path.home() / ".cache" / "bolster" / "psni"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


    class PSNIDataError(Exception):
        """Base exception for PSNI data errors."""
        pass


    class PSNIDataNotFoundError(PSNIDataError):
        """Data file not available."""
        pass


    class PSNIValidationError(PSNIDataError):
        """Data validation failed."""
        pass


    def hash_url(url: str) -> str:
        """Generate a safe filename from a URL."""
        return hashlib.md5(url.encode()).hexdigest()


    def get_cached_file(url: str, cache_ttl_hours: int = 24) -> Optional[Path]:
        """Return cached file if exists and fresh, else None."""
        url_hash = hash_url(url)
        ext = Path(url).suffix or ".bin"
        cache_path = CACHE_DIR / f"{url_hash}{ext}"

        if cache_path.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
            if age.total_seconds() < cache_ttl_hours * 3600:
                logger.info(f"Using cached file: {cache_path}")
                return cache_path

        return None


    def download_file(url: str, cache_ttl_hours: int = 24,
                     force_refresh: bool = False) -> Path:
        """Download a file with caching support."""
        if not force_refresh:
            cached = get_cached_file(url, cache_ttl_hours)
            if cached:
                return cached

        url_hash = hash_url(url)
        ext = Path(url).suffix or ".bin"
        cache_path = CACHE_DIR / f"{url_hash}{ext}"

        try:
            logger.info(f"Downloading {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            cache_path.write_bytes(response.content)
            logger.info(f"Saved to {cache_path}")
            return cache_path
        except requests.RequestException as e:
            raise PSNIDataNotFoundError(f"Failed to download {url}: {e}")

Step 4: Create crime_statistics.py
-----------------------------------

.. code-block:: python

    """PSNI Police Recorded Crime Statistics.

    Provides access to monthly police recorded crime statistics for Northern Ireland.

    Data includes:
    - Monthly crime counts by offence type
    - Geographic breakdown by policing district
    - Outcome classifications (detected, undetected, etc.)
    - Historical trends from 2000 onwards

    Data Source:
        **Mother Page**: https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics

        The module uses PSNI's RSS feed to discover the latest monthly crime statistics
        publication, then downloads the Excel file.

    Update Frequency: Monthly (published ~15th of following month)
    Geographic Coverage: Northern Ireland (by policing district)
    Reference Date: Month of crime occurrence

    Example:
        >>> from bolster.data_sources.psni import crime_statistics
        >>> # Get latest crime data
        >>> df = crime_statistics.get_latest_crime_statistics()
        >>> print(df.head())
    """

    import logging
    import re
    from datetime import datetime
    from pathlib import Path
    from typing import Tuple, Union

    import pandas as pd

    from bolster.utils.rss import find_feed, parse_feed
    from ._base import PSNIDataNotFoundError, PSNIValidationError, download_file

    logger = logging.getLogger(__name__)

    BASE_URL = "https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics"


    def get_latest_crime_statistics_publication_url() -> Tuple[str, datetime]:
        """Find the latest crime statistics file via RSS feed.

        Returns:
            Tuple of (excel_file_url, publication_date)

        Raises:
            PSNIDataNotFoundError: If publication not found
        """
        # Find RSS feed for the page
        feed_url = find_feed(BASE_URL)

        if not feed_url:
            raise PSNIDataNotFoundError("Could not find RSS feed for PSNI statistics")

        # Parse feed entries
        entries = parse_feed(feed_url)

        # Look for latest "Police Recorded Crime" publication
        for entry in entries:
            if "Police Recorded Crime" in entry.title:
                # Entry has link to detail page, need to scrape for Excel file
                import requests
                from bs4 import BeautifulSoup

                try:
                    response = requests.get(entry.link, timeout=30)
                    response.raise_for_status()
                except requests.RequestException as e:
                    continue

                soup = BeautifulSoup(response.content, "html.parser")

                # Find Excel file link
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    if href.endswith(".xlsx") or href.endswith(".xls"):
                        if href.startswith("/"):
                            href = f"https://www.psni.police.uk{href}"

                        pub_date = datetime(*entry.published_parsed[:6])
                        logger.info(f"Found crime statistics: {entry.title}")
                        return href, pub_date

        raise PSNIDataNotFoundError("Could not find crime statistics publication in RSS feed")


    def parse_crime_statistics_file(file_path: Union[str, Path]) -> pd.DataFrame:
        """Parse PSNI crime statistics Excel file.

        Args:
            file_path: Path to the Excel file

        Returns:
            DataFrame with columns:
                - month: datetime (first day of month)
                - offence_type: str (crime category)
                - district: str (policing district)
                - count: int (number of recorded crimes)
                - detected: int (crimes with outcome)

        Raises:
            PSNIValidationError: If file structure is unexpected
        """
        file_path = Path(file_path)

        try:
            # Read the main data sheet
            df = pd.read_excel(file_path, sheet_name="Offence Type", skiprows=2)
        except Exception as e:
            raise PSNIValidationError(f"Failed to read file: {e}")

        # Validate expected columns
        expected_cols = {"Month", "Offence Type", "Total"}
        if not expected_cols.issubset(df.columns):
            missing = expected_cols - set(df.columns)
            raise PSNIValidationError(f"Missing columns: {missing}")

        # Clean and transform
        df = df.rename(columns={
            "Month": "month",
            "Offence Type": "offence_type",
            "Total": "count",
        })

        df["month"] = pd.to_datetime(df["month"])
        df = df.sort_values(["month", "offence_type"]).reset_index(drop=True)

        logger.info(f"Parsed {len(df)} crime records from {file_path.name}")

        return df


    def get_latest_crime_statistics(force_refresh: bool = False) -> pd.DataFrame:
        """Get the latest police recorded crime statistics.

        Args:
            force_refresh: If True, bypass cache and download fresh data

        Returns:
            DataFrame with monthly crime statistics

        Raises:
            PSNIDataNotFoundError: If latest publication cannot be found
            PSNIValidationError: If file structure is unexpected

        Example:
            >>> df = get_latest_crime_statistics()
            >>> # Filter to latest year
            >>> latest_year = df["month"].max().year
            >>> df_2024 = df[df["month"].dt.year == latest_year]
            >>> print(f"Total crimes in {latest_year}: {df_2024['count'].sum():,}")
        """
        # Discover via RSS
        excel_url, pub_date = get_latest_crime_statistics_publication_url()

        logger.info(f"Downloading crime statistics ({pub_date.strftime('%B %Y')}) from: {excel_url}")

        # Monthly data, cache for 30 days
        cache_ttl_hours = 30 * 24
        file_path = download_file(excel_url, cache_ttl_hours=cache_ttl_hours,
                                  force_refresh=force_refresh)

        return parse_crime_statistics_file(file_path)


    def validate_crime_statistics(df: pd.DataFrame) -> bool:
        """Validate crime statistics data integrity.

        Args:
            df: DataFrame from parse_crime_statistics_file or get_latest_crime_statistics

        Returns:
            True if validation passes

        Raises:
            PSNIValidationError: If validation fails
        """
        # Check for reasonable crime counts (no negative, not absurdly high)
        if (df["count"] < 0).any():
            raise PSNIValidationError("Found negative crime counts")

        if (df["count"] > 100000).any():
            logger.warning("Found suspiciously high crime count")

        # Check temporal continuity
        month_counts = df.groupby("month").size()
        if month_counts.min() < 5:
            raise PSNIValidationError("Some months have too few offence types")

        logger.info(f"Validation passed: {len(df)} records checked")
        return True


    def get_crime_statistics_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
        """Filter crime statistics for a specific year."""
        return df[df["month"].dt.year == year].reset_index(drop=True)


    def get_crime_summary_by_type(df: pd.DataFrame) -> pd.DataFrame:
        """Calculate summary statistics by offence type."""
        return df.groupby("offence_type").agg({
            "count": ["sum", "mean", "count"]
        }).reset_index()

Step 5: Create __init__.py
---------------------------

.. code-block:: python

    """PSNI (Police Service of Northern Ireland) Data Sources.

    This module provides access to PSNI open data including:
    - Crime Statistics: Monthly police recorded crime data

    Example:
        >>> from bolster.data_sources.psni import crime_statistics
        >>> df = crime_statistics.get_latest_crime_statistics()

    See individual module docstrings for detailed documentation.
    """

    from .crime_statistics import (
        get_latest_crime_statistics,
        parse_crime_statistics_file,
        validate_crime_statistics,
        get_crime_statistics_by_year,
        get_crime_summary_by_type,
    )

    from ._base import (
        PSNIDataError,
        PSNIDataNotFoundError,
        PSNIValidationError,
    )

    __all__ = [
        # Crime statistics
        "get_latest_crime_statistics",
        "parse_crime_statistics_file",
        "validate_crime_statistics",
        "get_crime_statistics_by_year",
        "get_crime_summary_by_type",
        # Exceptions
        "PSNIDataError",
        "PSNIDataNotFoundError",
        "PSNIValidationError",
    ]

Step 6: Create Tests
--------------------

Create ``tests/test_psni_crime_statistics_integrity.py``:

.. code-block:: python

    """Integrity tests for PSNI crime statistics data source."""

    import pytest
    import pandas as pd

    from bolster.data_sources.psni import crime_statistics


    @pytest.fixture(scope="module")
    def data():
        """Load data once for all tests."""
        return crime_statistics.get_latest_crime_statistics()


    class TestDataStructure:
        """Test data structure and format."""

        def test_returns_dataframe(self, data):
            assert isinstance(data, pd.DataFrame)

        def test_not_empty(self, data):
            assert len(data) > 0

        def test_has_expected_columns(self, data):
            expected = {"month", "offence_type", "count"}
            assert expected.issubset(set(data.columns))


    class TestDataQuality:
        """Test data quality and integrity."""

        def test_no_null_in_required_columns(self, data):
            required = ["month", "offence_type", "count"]
            for col in required:
                assert data[col].notna().all()

        def test_valid_date_range(self, data):
            assert data["month"].min() >= pd.Timestamp("2000-01-01")
            assert data["month"].max() <= pd.Timestamp.now()

        def test_crime_counts_positive(self, data):
            assert (data["count"] >= 0).all()


    class TestDataValidation:
        """Test data validation functions."""

        def test_validation_passes(self, data):
            assert crime_statistics.validate_crime_statistics(data)


    class TestHelperFunctions:
        """Test helper functions."""

        def test_filter_by_year(self, data):
            years = data["month"].dt.year.unique()
            test_year = years[0]

            filtered = crime_statistics.get_crime_statistics_by_year(data, test_year)

            assert (filtered["month"].dt.year == test_year).all()
            assert len(filtered) > 0

        def test_summary_by_type(self, data):
            summary = crime_statistics.get_crime_summary_by_type(data)

            assert isinstance(summary, pd.DataFrame)
            assert len(summary) > 0

Step 7: Create README
---------------------

Create ``src/bolster/data_sources/psni/README.md`` with comprehensive documentation.

Step 8: Test and Submit
------------------------

.. code-block:: bash

    # Run tests
    pytest tests/test_psni_crime_statistics_integrity.py -v

    # Run linting
    make pre-commit

    # Commit and push
    git add src/bolster/data_sources/psni/
    git add tests/test_psni_crime_statistics_integrity.py
    git commit -m "feat: Add PSNI crime statistics data source"
    git push origin feature/psni-crime-statistics

Checklist
=========

Before Submitting a PR
----------------------

Use this checklist to ensure your data source is complete:

**Code:**

- [ ] Created ``src/bolster/data_sources/<source>/`` directory
- [ ] Created ``_base.py`` with custom exceptions and utilities
- [ ] Created individual dataset module(s) with required functions:
  - [ ] ``get_latest_<dataset>_publication_url()``
  - [ ] ``parse_<dataset>_file()``
  - [ ] ``get_latest_<dataset>()``
  - [ ] At least one validation function
  - [ ] At least one helper/filter function
- [ ] Created ``__init__.py`` with public API exports
- [ ] All type hints are Python 3.9+ compatible (no ``X | Y``, no ``list[X]``)

**Documentation:**

- [ ] Module docstrings include:
  - [ ] Brief description
  - [ ] Data source URL (mother page)
  - [ ] Update frequency, geographic coverage, reference date
  - [ ] Usage example
- [ ] All public functions have complete docstrings with Args/Returns/Raises/Example
- [ ] Created comprehensive ``README.md`` in module directory

**Testing:**

- [ ] Created ``tests/test_<source>_<dataset>_integrity.py``
- [ ] Tests cover:
  - [ ] Data structure (DataFrame, columns, types)
  - [ ] Data quality (no nulls, valid ranges)
  - [ ] Validation functions
  - [ ] Helper functions
- [ ] All tests pass locally
- [ ] Code coverage >90%

**Integration:**

- [ ] Added CLI command to ``src/bolster/cli.py`` (if applicable)
- [ ] Tested CLI command locally
- [ ] Updated ``docs/usage.rst`` with usage examples (if significant)

**Quality:**

- [ ] Code passes ``make pre-commit`` (ruff linting and formatting)
- [ ] No hardcoded credentials or API keys
- [ ] Appropriate cache TTL for update frequency
- [ ] Clear error messages for common failure modes
- [ ] Logging at appropriate levels (info for major operations, debug for details)

Getting Help
============

If you have questions while developing a data source:

1. **Check existing modules**: The NISRA modules (``src/bolster/data_sources/nisra/``) provide comprehensive examples
2. **Read the tests**: Integrity tests show expected usage patterns
3. **File an issue**: https://github.com/andrewbolster/bolster/issues with questions
4. **Start a discussion**: For design questions, open a GitHub Discussion

Contributing
============

We welcome data source contributions! Follow these steps:

1. **Open an issue** describing the data source you want to add
2. **Get feedback** on approach before writing significant code
3. **Follow this guide** for implementation
4. **Submit a PR** with complete code, tests, and documentation
5. **Iterate** based on review feedback

Your contribution helps make Northern Ireland's open data more accessible!
