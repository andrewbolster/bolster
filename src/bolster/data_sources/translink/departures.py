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
from datetime import UTC, datetime

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
        dt = datetime.now(tz=UTC)

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


def get_departures_with_vehicles(
    stop_name: str,
    n: int = 5,
    dt: datetime | None = None,
    enrich_stops: bool = False,
) -> pd.DataFrame:
    """Return next-N departures enriched with live vehicle positions where available.

    Fetches departures and live VMI vehicles in parallel (two API calls), then
    joins on line + direction + journey time proximity (±60 minute window).

    VMI vehicles are matched to departures by:
    1. Line number (case-insensitive).
    2. Inferred direction (inbound = destination contains "Belfast"/"CastleCourt"/
       "Royal Avenue"/"City Centre"; outbound = everything else).
    3. Journey ID (HHMM) within ±60 minutes of the actual departure time.

    Not all departures will have a matched vehicle — buses that have not yet
    started their journey are not yet in the VMI feed.

    Args:
        stop_name: Stop name to search for (resolved via :func:`find_stop_id`).
        n: Number of departures to return (default 5).
        dt: Reference datetime (default: now, UTC).
        enrich_stops: If True, include ``current_stop_name`` and ``next_stop_name``
                      for matched vehicles.

    Returns:
        DataFrame with all departure columns plus optional vehicle columns:
        ``vehicle_id``, ``vehicle_lat``, ``vehicle_lon``, ``vehicle_delay_s``,
        ``current_stop``, ``next_stop``, and (if enrich_stops) ``current_stop_name``,
        ``next_stop_name``.  Vehicle columns are ``None`` / ``NaN`` where no match.
    """
    from .vehicles import get_live_vehicles

    deps = get_departures_by_name(stop_name, n=n, dt=dt)
    if deps.empty:
        return deps

    # Collect lines present in departures to reduce VMI filtering work
    dep_lines = {_extract_line(s) for s in deps["service"].unique()}

    all_vehicles = []
    for line in dep_lines:
        vdf = get_live_vehicles(line=line, enrich_stops=enrich_stops)
        all_vehicles.append(vdf)

    if not all_vehicles or all(v.empty for v in all_vehicles):
        # No live vehicles on any line — return departures as-is with empty vehicle cols
        for col in ("vehicle_id", "vehicle_lat", "vehicle_lon", "vehicle_delay_s", "current_stop", "next_stop"):
            deps[col] = None
        return deps

    vehicles = pd.concat([v for v in all_vehicles if not v.empty], ignore_index=True)

    _INBOUND_KEYWORDS = {"belfast", "castlecourt", "royal avenue", "city centre", "great victoria"}

    def _dep_direction(destination: str) -> str:
        return "inbound" if any(kw in destination.lower() for kw in _INBOUND_KEYWORDS) else "outbound"

    def _vmi_direction(direction_text: str) -> str:
        return "inbound" if any(kw in direction_text.lower() for kw in _INBOUND_KEYWORDS) else "outbound"

    def _journey_dt(hhmm: str, ref: "pd.Timestamp") -> "pd.Timestamp | None":
        """Convert a VMI HHMM journey ID to a UTC Timestamp comparable to ref.

        VMI journey IDs are in local Belfast time (Europe/London).  Convert to
        UTC before comparing against departure times (which are in UTC).
        """
        try:
            h, m = int(hhmm[:2]), int(hhmm[2:])
            # Build naive local datetime on same calendar date as ref (in local tz)
            ref_local = ref.tz_convert("Europe/London")
            local_dt = ref_local.normalize() + pd.Timedelta(hours=h, minutes=m)
            # localise and convert to UTC
            return local_dt.tz_localize(None).tz_localize("Europe/London").tz_convert("UTC")
        except (ValueError, IndexError, Exception):
            return None

    vehicle_cols = {
        "vehicle_id": None,
        "vehicle_lat": None,
        "vehicle_lon": None,
        "vehicle_delay_s": None,
        "current_stop": None,
        "next_stop": None,
    }
    if enrich_stops:
        vehicle_cols["current_stop_name"] = None
        vehicle_cols["next_stop_name"] = None

    matched_rows = []
    for _, dep in deps.iterrows():
        line = _extract_line(dep["service"])
        direction = _dep_direction(dep["destination"])
        dep_dt = dep["actual_departure"]

        candidates = vehicles[
            (vehicles["line"].str.upper() == line.upper()) & (vehicles["direction"].apply(_vmi_direction) == direction)
        ]

        best_match = None
        best_delta = pd.Timedelta(minutes=60)

        for _, v in candidates.iterrows():
            jdt = _journey_dt(v["journey_id"], dep_dt)
            if jdt is None:
                continue
            if jdt.tzinfo is None:
                jdt = jdt.tz_localize("UTC")
            delta = abs(dep_dt - jdt)
            if delta < best_delta:
                best_delta = delta
                best_match = v

        row = dep.to_dict()
        if best_match is not None:
            row["vehicle_id"] = best_match["vehicle_id"]
            row["vehicle_lat"] = best_match["latitude"]
            row["vehicle_lon"] = best_match["longitude"]
            row["vehicle_delay_s"] = best_match["delay_seconds"]
            row["current_stop"] = best_match.get("current_stop")
            row["next_stop"] = best_match.get("next_stop")
            if enrich_stops:
                row["current_stop_name"] = best_match.get("current_stop_name")
                row["next_stop_name"] = best_match.get("next_stop_name")
        else:
            for col, default in vehicle_cols.items():
                row[col] = default

        matched_rows.append(row)

    return pd.DataFrame(matched_rows).reset_index(drop=True)


def get_direct_journeys(
    origin: str,
    destination: str,
    n: int = 5,
    dt: datetime | None = None,
) -> pd.DataFrame:
    """Return the next *n* direct bus/rail journeys between two stops.

    Uses the CIF timetable data (Metro/Glider and Ulsterbus/GoldLine) to find
    services that call at both stops in order, without requiring a change.
    No network calls are made beyond resolving stop names; all routing is done
    from the locally cached timetable.

    The workflow is:
    1. Resolve both stop names to NaPTAN ATCOCodes via the CIF stop lookup.
    2. Find all trips in the timetable that call at the origin before the
       destination (``find_direct_trips``).
    3. Filter to trips whose scheduled origin departure is at or after *dt*,
       sorted by departure time.
    4. Return the first *n* matching trips.

    Args:
        origin: Origin stop name (resolved via :func:`~.stops.find_stop`).
        destination: Destination stop name.
        n: Maximum number of journeys to return (default 5).
        dt: Reference datetime (default: now, local Europe/London time).

    Returns:
        DataFrame with columns:
        ``origin``, ``destination``, ``service``,
        ``scheduled_departure`` (HHMM str), ``scheduled_arrival`` (HHMM str),
        ``days``, ``direction``.

    Raises:
        TranslinkDataNotFoundError: If either stop cannot be resolved, or if
            no direct service runs between them at all.
    """
    from .stops import get_stop_lookup
    from .timetable import find_direct_trips

    if dt is None:
        dt = datetime.now(tz=UTC)

    # Resolve stop names → ATCOCodes via the CIF stop lookup (fuzzy name match)
    lookup = get_stop_lookup()
    name_lower = {v.get("name", "").lower(): k for k, v in lookup.items()}

    def _resolve_atco(query: str) -> tuple[str, str]:
        """Return (atco, canonical_name) for the best name match."""
        ql = query.lower()
        if ql in name_lower:
            atco = name_lower[ql]
            return atco, lookup[atco].get("name", query)
        # Partial match: first stop whose name contains the query
        for name, atco in name_lower.items():
            if ql in name:
                return atco, lookup[atco].get("name", query)
        raise TranslinkDataNotFoundError(f"No stop found in timetable matching '{query}'")

    origin_atco, origin_name = _resolve_atco(origin)
    dest_atco, dest_name = _resolve_atco(destination)

    direct = find_direct_trips(origin_atco, dest_atco)
    if not direct:
        raise TranslinkDataNotFoundError(f"No direct service found between '{origin_name}' and '{dest_name}'")

    # Filter to departures at or after the reference time (HHMM comparison)
    from zoneinfo import ZoneInfo

    tz_london = ZoneInfo("Europe/London")
    ref_local = dt.astimezone(tz_london) if dt.tzinfo else dt.replace(tzinfo=UTC).astimezone(tz_london)
    ref_hhmm = ref_local.strftime("%H%M")
    # days string is MTWTFSS (index 0=Mon … 6=Sun); weekday() returns 0=Mon … 6=Sun
    weekday_idx = ref_local.weekday()

    upcoming = [
        (trip, orig_ts, dest_ts)
        for trip, orig_ts, dest_ts in direct
        if len(trip.days) > weekday_idx and trip.days[weekday_idx] == "1" and orig_ts.depart >= ref_hhmm
    ]

    # If nothing upcoming today, fall back to all trips running today (from start of day)
    if not upcoming:
        upcoming = [
            (trip, orig_ts, dest_ts)
            for trip, orig_ts, dest_ts in direct
            if len(trip.days) > weekday_idx and trip.days[weekday_idx] == "1"
        ]

    rows = []
    for trip, orig_ts, dest_ts in upcoming[:n]:
        rows.append(
            {
                "origin": origin_name,
                "destination": dest_name,
                "service": f"{trip.operator} {trip.line}",
                "scheduled_departure": orig_ts.depart,
                "scheduled_arrival": dest_ts.arrive,
                "days": trip.days,
                "direction": trip.direction,
            }
        )

    return pd.DataFrame(rows).reset_index(drop=True)


def _extract_line(service_name: str) -> str:
    """Extract the line identifier from a service name.

    Strips a leading mode prefix ('Bus ', 'Glider ') and uppercases the
    remainder.  Rail and other service types are returned as-is (title-cased).

    Examples:
        'Bus 11e'                     → '11E'
        'Glider G1'                   → 'G1'
        'Rail Larne Line'             → 'Rail Larne Line'
        'Rail Derry/Londonderry Line' → 'Rail Derry/Londonderry Line'
    """
    for prefix in ("Bus ", "Glider "):
        if service_name.startswith(prefix):
            return service_name[len(prefix) :].upper()
    return service_name
