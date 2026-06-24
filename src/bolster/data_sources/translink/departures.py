"""Translink scheduled and real-time departure boards.

Provides next-N departure information from any Translink stop using the
undocumented Translink journey planner API (translink.co.uk).

Two-step workflow:

1. Resolve a stop name to a Translink internal StopId via ``find_stop_id()``.
2. Fetch the next N departures from that stop via ``get_departures()``.

Alternatively, use ``get_departures_by_name()`` as a single-call convenience
wrapper that resolves the stop name and returns departures in one step.

Departure times are returned as timezone-aware pandas Timestamps (UTC).
``SysActualDepartureDate`` in the API response is a .NET ``DateTime`` ticks
value (100-nanosecond intervals since 0001-01-01 00:00:00 UTC); these are
decoded via :func:`~bolster.data_sources.translink._base.net_ticks_to_timestamp`.

Example:
    >>> deps = get_departures_by_name("Shankill, Cambria Street", n=3)
    >>> set(deps.columns) >= {"planned_departure", "actual_departure", "service", "destination"}
    True
    >>> len(deps) >= 1
    True
"""

import logging
from datetime import datetime, timezone

import pandas as pd

from bolster.utils.web import session

from ._base import (
    TRANSLINK_BASE_URL,
    TranslinkDataNotFoundError,
    TranslinkValidationError,
    net_ticks_to_timestamp,
)
from .stops import find_stop

logger = logging.getLogger(__name__)

_JOURNEY_RESULTS_URL = f"{TRANSLINK_BASE_URL}/JourneyPlannerApi/GetJourneyResults"
_JOURNEY_RESULTS_NEXT_URL = f"{TRANSLINK_BASE_URL}/JourneyPlannerApi/GetJourneyResultsNext"
_JOURNEY_RESULTS_PREV_URL = f"{TRANSLINK_BASE_URL}/JourneyPlannerApi/GetJourneyResultsPrev"


def find_stop_id(query: str) -> str:
    """Return the Translink internal StopId for the first result matching *query*.

    Args:
        query: Partial or full stop name, e.g. ``"Cambria Street"`` or a
               NaPTAN ATCOCode such as ``"700000014482"``.

    Returns:
        Translink internal StopId string (e.g. ``"10012778"``).

    Raises:
        TranslinkDataNotFoundError: If no stop matches the query.
    """
    results = find_stop(query)
    if not results:
        raise TranslinkDataNotFoundError(f"No stop found matching '{query}'")
    return results[0]["id"]


def _parse_departures(raw: list[dict]) -> pd.DataFrame:
    """Convert the raw Departures list from the API into a clean DataFrame.

    Args:
        raw: List of departure dicts from the ``Result.Departures`` key.

    Returns:
        DataFrame with columns:
        ``planned_departure``, ``actual_departure``, ``service``,
        ``destination``, ``transport_mode``, ``is_real_time``, ``is_cancelled``,
        ``delay_minutes``, ``unique_id``.
    """
    if not raw:
        return pd.DataFrame(
            columns=[
                "planned_departure",
                "actual_departure",
                "service",
                "destination",
                "transport_mode",
                "is_real_time",
                "is_cancelled",
                "delay_minutes",
                "unique_id",
            ]
        )

    rows = []
    for dep in raw:
        planned = net_ticks_to_timestamp(dep["SysPlannedDepartureDate"])
        actual = net_ticks_to_timestamp(dep["SysActualDepartureDate"])
        delay_min = round((actual - planned).total_seconds() / 60, 1)
        rows.append(
            {
                "planned_departure": planned,
                "actual_departure": actual,
                "service": dep.get("ServiceName", ""),
                "destination": dep.get("DestinationName", ""),
                "transport_mode": dep.get("TransportMode", ""),
                "is_real_time": bool(dep.get("IsRealTime", False)),
                "is_cancelled": bool(dep.get("IsCancelled", False)),
                "delay_minutes": delay_min,
                "unique_id": dep.get("UniqueId", ""),
            }
        )

    return pd.DataFrame(rows).sort_values("actual_departure").reset_index(drop=True)


def get_departures(
    stop_id: str,
    n: int = 5,
    dt: datetime | None = None,
) -> pd.DataFrame:
    """Return the next *n* departures from a stop identified by Translink StopId.

    The API returns up to 8 departures per call.  If more are needed, subsequent
    calls advance the ``DepartureOrArrivalDate`` to fetch additional pages.

    Args:
        stop_id: Translink internal StopId (e.g. ``"10012778"``).  Obtain via
                 :func:`find_stop_id`.
        n: Number of departures to return (default 5).  The API returns at most
           8 per call; additional pages are fetched automatically if needed.
        dt: Reference datetime for the first departure (default: now, UTC).

    Returns:
        DataFrame with columns:
        ``planned_departure`` (Timestamp[UTC]), ``actual_departure`` (Timestamp[UTC]),
        ``service`` (str), ``destination`` (str), ``transport_mode`` (str),
        ``is_real_time`` (bool), ``is_cancelled`` (bool), ``delay_minutes`` (float),
        ``unique_id`` (str).

    Raises:
        TranslinkDataNotFoundError: If the API request fails.
        TranslinkValidationError: If the API returns an unexpected response.
    """
    if dt is None:
        dt = datetime.now(tz=timezone.utc)

    all_deps: list[pd.DataFrame] = []
    current_dt = dt

    while sum(len(d) for d in all_deps) < n:
        payload = {
            "OriginId": stop_id,
            "DepartureOrArrivalDate": current_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        try:
            resp = session.post(_JOURNEY_RESULTS_URL, json=payload, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            raise TranslinkDataNotFoundError(f"Departures request failed for stop {stop_id!r}: {e}") from e

        body = resp.json()
        if body.get("ResponseCode") not in (200, None) and body.get("ResponseCode") != 200:
            raise TranslinkValidationError(f"API returned ResponseCode {body.get('ResponseCode')}: {body}")

        result = body.get("Result") or {}
        raw_deps = result.get("Departures") or []

        if not raw_deps:
            break  # No more departures (end of service / outside hours)

        batch = _parse_departures(raw_deps)
        all_deps.append(batch)

        # Advance past the last departure in this batch for the next page
        last_dt = batch["actual_departure"].max()
        if last_dt <= current_dt:
            break
        current_dt = last_dt.to_pydatetime()

    if not all_deps:
        return _parse_departures([])

    combined = pd.concat(all_deps, ignore_index=True)
    combined = combined.drop_duplicates("unique_id").sort_values("actual_departure").reset_index(drop=True)
    return combined.head(n)


def get_departures_by_name(
    stop_name: str,
    n: int = 5,
    dt: datetime | None = None,
) -> pd.DataFrame:
    """Return the next *n* departures from a stop resolved by name.

    Convenience wrapper that calls :func:`find_stop_id` then :func:`get_departures`.

    Args:
        stop_name: Stop name or NaPTAN ATCOCode to search for.
        n: Number of departures to return (default 5).
        dt: Reference datetime (default: now, UTC).

    Returns:
        DataFrame as returned by :func:`get_departures`, with an additional
        ``stop_name`` column showing the resolved stop name.

    Raises:
        TranslinkDataNotFoundError: If the stop cannot be found or the API fails.
    """
    results = find_stop(stop_name)
    if not results:
        raise TranslinkDataNotFoundError(f"No stop found matching '{stop_name}'")

    stop = results[0]
    df = get_departures(stop["id"], n=n, dt=dt)
    df.insert(0, "stop_name", stop["name"])
    return df


def validate_departures(df: pd.DataFrame) -> bool:
    """Validate that a departures DataFrame has the expected schema and values.

    Args:
        df: DataFrame as returned by :func:`get_departures`.

    Returns:
        True if validation passes.

    Raises:
        TranslinkValidationError: If required columns are missing or values are invalid.
    """
    required = {"planned_departure", "actual_departure", "service", "destination", "is_real_time", "is_cancelled"}
    missing = required - set(df.columns)
    if missing:
        raise TranslinkValidationError(f"Departures DataFrame missing columns: {missing}")

    if len(df) == 0:
        return True  # Empty is valid (outside service hours)

    if not pd.api.types.is_datetime64_any_dtype(df["planned_departure"]):
        raise TranslinkValidationError("planned_departure must be a datetime column")

    if df["is_real_time"].dtype != bool:
        raise TranslinkValidationError("is_real_time must be bool")

    if df["is_cancelled"].dtype != bool:
        raise TranslinkValidationError("is_cancelled must be bool")

    return True
