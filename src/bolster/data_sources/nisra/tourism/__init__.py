"""NISRA Tourism Statistics Data Sources.

This module provides access to Northern Ireland tourism data including:

- **Occupancy Surveys**: Hotel and SSA (B&B/guest house) occupancy rates
- **Visitor Statistics**: Trips, expenditure, demographics (coming soon)
- **Air Passenger Flow**: Airport throughput data (coming soon)

All data is sourced from NISRA (Northern Ireland Statistics and Research Agency)
and published under the Open Government Licence.

Example:
    >>> from bolster.data_sources.nisra.tourism import occupancy
    >>> # Get hotel occupancy rates
    >>> df = occupancy.get_latest_hotel_occupancy()
    >>> print(df.head())
    >>>
    >>> # Get combined hotel + SSA data
    >>> df_combined = occupancy.get_combined_occupancy()
    >>> comparison = occupancy.compare_accommodation_types(df_combined)
    >>> print(comparison)

See individual module docstrings for detailed documentation.
"""

from .occupancy import (
    compare_accommodation_types,
    get_combined_occupancy,
    get_latest_hotel_occupancy,
    get_latest_hotel_occupancy_publication_url,
    get_latest_rooms_beds_sold,
    get_latest_ssa_occupancy,
    get_latest_ssa_occupancy_publication_url,
    get_latest_ssa_rooms_beds_sold,
    get_occupancy_by_year,
    get_occupancy_summary_by_year,
    get_seasonal_patterns,
)

__all__ = [
    # Hotel occupancy
    "get_latest_hotel_occupancy",
    "get_latest_hotel_occupancy_publication_url",
    "get_latest_rooms_beds_sold",
    # SSA occupancy
    "get_latest_ssa_occupancy",
    "get_latest_ssa_occupancy_publication_url",
    "get_latest_ssa_rooms_beds_sold",
    # Combined/comparison
    "get_combined_occupancy",
    "compare_accommodation_types",
    # Analysis helpers
    "get_occupancy_by_year",
    "get_occupancy_summary_by_year",
    "get_seasonal_patterns",
]
