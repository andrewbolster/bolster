"""Translink (NI) Data Sources.

Provides access to live and scheduled transport data for Northern Ireland's
Translink-operated services (Ulsterbus, Metro, Glider, NI Railways).

Data sources:
- Live vehicle positions: undocumented VMI feed (vpos.translinkniplanner.co.uk)
- Scheduled departures: Translink journey planner API (translink.co.uk)
- Stop metadata: Open Data NI ATCO-CIF timetable zips (admin.opendatani.gov.uk)

Example:
    >>> from bolster.data_sources import translink
    >>> deps = translink.get_departures("Shankill, Cambria Street", n=5)
    >>> "planned_departure" in deps.columns
    True
"""

from ._base import (
    TranslinkDataError,
    TranslinkDataNotFoundError,
    TranslinkValidationError,
    clear_cache,
)

__all__ = [
    "TranslinkDataError",
    "TranslinkDataNotFoundError",
    "TranslinkValidationError",
    "clear_cache",
]
