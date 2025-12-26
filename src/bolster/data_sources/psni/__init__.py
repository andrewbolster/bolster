"""PSNI (Police Service of Northern Ireland) Data Sources.

This module provides access to PSNI open data including:
- Crime Statistics: Police recorded crime data with monthly updates

Data is sourced from OpenDataNI under the Open Government Licence v3.0.
Geographic breakdowns use the 11 Policing Districts which align with
Northern Ireland's Local Government Districts (LGDs), enabling integration
with other NISRA datasets.

Example:
    >>> from bolster.data_sources.psni import crime_statistics
    >>> # Get latest crime data
    >>> df = crime_statistics.get_latest_crime_statistics()
    >>>
    >>> # Filter to Belfast
    >>> belfast = crime_statistics.filter_by_district(df, "Belfast City")
    >>>
    >>> # Get LGD code for cross-referencing
    >>> lgd_code = crime_statistics.get_lgd_code("Belfast City")
    >>> print(f"Belfast LGD: {lgd_code}")  # N09000003

See individual module docstrings for detailed documentation.
"""

from ._base import (
    PSNIDataError,
    PSNIDataNotFoundError,
    PSNIValidationError,
    clear_cache,
)
from .crime_statistics import (
    filter_by_crime_type,
    filter_by_date_range,
    filter_by_district,
    get_available_crime_types,
    get_available_districts,
    get_crime_trends,
    get_latest_crime_statistics,
    get_lgd_code,
    get_nuts3_code,
    get_nuts_region_name,
    get_outcome_rates_by_district,
    get_total_crimes_by_district,
    parse_crime_statistics_file,
    validate_crime_statistics,
)

__all__ = [
    # Main functions
    "get_latest_crime_statistics",
    "parse_crime_statistics_file",
    "validate_crime_statistics",
    # Filtering functions
    "filter_by_district",
    "filter_by_crime_type",
    "filter_by_date_range",
    # Analysis functions
    "get_total_crimes_by_district",
    "get_crime_trends",
    "get_outcome_rates_by_district",
    # Helper functions
    "get_available_crime_types",
    "get_available_districts",
    # Geographic utilities
    "get_lgd_code",
    "get_nuts3_code",
    "get_nuts_region_name",
    # Cache management
    "clear_cache",
    # Exceptions
    "PSNIDataError",
    "PSNIDataNotFoundError",
    "PSNIValidationError",
]
