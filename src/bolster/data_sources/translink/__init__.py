"""Translink (NI) Data Sources.

Provides access to live and scheduled transport data for Northern Ireland's
Translink-operated services (Ulsterbus, Metro, Glider, NI Railways).

Data sources:
- Live vehicle positions: undocumented VMI feed (vpos.translinkniplanner.co.uk)
- Scheduled departures: Translink journey planner API (translink.co.uk)
- Stop metadata: Open Data NI ATCO-CIF timetable zips (admin.opendatani.gov.uk)

Example:
    >>> from bolster.data_sources import translink
    >>> deps = translink.get_departures_by_name("Shankill, Cambria Street", n=3)
    >>> "planned_departure" in deps.columns
    True
"""

from ._base import (
    TranslinkDataError,
    TranslinkDataNotFoundError,
    TranslinkValidationError,
    clear_cache,
)
from .departures import (
    find_stop_id,
    get_departures,
    get_departures_by_name,
    get_departures_with_vehicles,
    validate_departures,
)
from .stops import (
    find_stop,
    get_stop_dataframe,
    get_stop_lookup,
    resolve_stop_name,
)
from .vehicles import (
    get_live_vehicles,
    validate_vehicles,
)

__all__ = [
    "TranslinkDataError",
    "TranslinkDataNotFoundError",
    "TranslinkValidationError",
    "clear_cache",
    "find_stop_id",
    "get_departures",
    "get_departures_by_name",
    "get_departures_with_vehicles",
    "validate_departures",
    "find_stop",
    "get_stop_dataframe",
    "get_stop_lookup",
    "resolve_stop_name",
    "get_live_vehicles",
    "validate_vehicles",
]
