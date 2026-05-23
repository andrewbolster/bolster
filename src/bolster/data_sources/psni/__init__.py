"""PSNI (Police Service of Northern Ireland) Data Sources.

This module provides access to PSNI open data including:
- Crime Statistics: Police recorded crime data with monthly updates
- Road Traffic Collisions: Injury collision, casualty, and vehicle data
- Police Ombudsman: Complaint statistics from 2000/01 to present

Data is sourced from OpenDataNI and the Police Ombudsman's Office under the
Open Government Licence v3.0.
Geographic breakdowns use the 11 Policing Districts which align with
Northern Ireland's Local Government Districts (LGDs), enabling integration
with other NISRA datasets.

Example:
    >>> from bolster.data_sources.psni import crime_statistics, road_traffic_collisions
    >>> df = crime_statistics.get_historical_crime_statistics()
    >>> 'lgd_code' in df.columns
    True
    >>> lgd_code = crime_statistics.get_lgd_code("Belfast City")
    >>> lgd_code
    'N09000003'
    >>> casualties = road_traffic_collisions.get_casualties()
    >>> 'severity' in casualties.columns
    True

See individual module docstrings for detailed documentation.
"""

from ._base import (
    PSNIDataError,
    PSNIDataNotFoundError,
    PSNIDataStaleError,
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
    get_data_source_info,
    get_historical_crime_statistics,
    get_latest_crime_statistics,
    get_lgd_code,
    get_nuts3_code,
    get_nuts_region_name,
    get_outcome_rates_by_district,
    get_total_crimes_by_district,
    parse_crime_statistics_file,
    validate_crime_statistics,
)
from .police_ombudsman import (
    get_annual_publication_url,
    get_latest_complaints,
    get_quarterly_publication_url,
    parse_annual,
    parse_quarterly,
    validate_complaints,
)
from .road_traffic_collisions import (
    get_annual_summary as get_rtc_annual_summary,
)
from .road_traffic_collisions import (
    get_available_years as get_rtc_available_years,
)
from .road_traffic_collisions import (
    get_casualties,
    get_casualties_by_district,
    get_casualties_by_road_user,
    get_casualties_with_collision_details,
    get_collisions,
    get_vehicles,
)
from .road_traffic_collisions import (
    validate_data as validate_rtc_data,
)

__all__ = [
    # Crime Statistics - Main functions
    "get_historical_crime_statistics",
    "get_latest_crime_statistics",
    "parse_crime_statistics_file",
    "validate_crime_statistics",
    # Crime Statistics - Filtering functions
    "filter_by_district",
    "filter_by_crime_type",
    "filter_by_date_range",
    # Crime Statistics - Analysis functions
    "get_total_crimes_by_district",
    "get_crime_trends",
    "get_outcome_rates_by_district",
    # Crime Statistics - Helper functions
    "get_available_crime_types",
    "get_available_districts",
    "get_data_source_info",
    # Road Traffic Collisions - Main functions
    "get_collisions",
    "get_casualties",
    "get_vehicles",
    "get_casualties_with_collision_details",
    "validate_rtc_data",
    # Road Traffic Collisions - Analysis functions
    "get_rtc_annual_summary",
    "get_casualties_by_district",
    "get_casualties_by_road_user",
    # Road Traffic Collisions - Helper functions
    "get_rtc_available_years",
    # Geographic utilities
    "get_lgd_code",
    "get_nuts3_code",
    "get_nuts_region_name",
    # Police Ombudsman
    "get_annual_publication_url",
    "get_quarterly_publication_url",
    "get_latest_complaints",
    "parse_annual",
    "parse_quarterly",
    "validate_complaints",
    # Cache management
    "clear_cache",
    # Exceptions
    "PSNIDataError",
    "PSNIDataNotFoundError",
    "PSNIDataStaleError",
    "PSNIValidationError",
]
