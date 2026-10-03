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
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from bolster.utils.fuzzy import fuzzy_match
from bolster.utils.web import session

from ._base import (
    TRANSLINK_BASE_URL,
    TranslinkDataNotFoundError,
    TranslinkValidationError,
    net_ticks_to_timestamp,
)
from .stops import find_stop, get_stop_dataframe, resolve_stop_name
from .timetable import find_trip_for_vehicle

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

        # The API treats DepartureOrArrivalDate as an inclusive lower bound, so
        # advance one second past the last departure in this batch -- otherwise
        # the next page starts by re-fetching this one as its first row, under
        # a freshly-minted unique_id.
        last_dt = batch["actual_departure"].max()
        if last_dt <= current_dt:
            break
        current_dt = last_dt.to_pydatetime() + timedelta(seconds=1)

    if not all_deps:
        return _parse_departures([])

    combined = pd.concat(all_deps, ignore_index=True)
    # Not unique_id: the API mints a fresh one per request, so it can't dedupe a
    # real departure that appears on two pages.
    combined = combined.drop_duplicates(["service", "destination", "planned_departure"])
    combined = combined.sort_values("actual_departure").reset_index(drop=True)
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


def _resolve_target_atcos(stop_display_name: str) -> list[str]:
    """Best-effort, high-confidence crosswalk from a journey-planner display name.

    Resolves to NaPTAN ATCOCode(s) in the local CIF stop table. Translink's live
    display names and NaPTAN's canonical names can diverge (e.g. "Shankill,
    Cambria Street" vs. NaPTAN's "Cambrai Street"), so the "Locality, " prefix
    (everything before the first comma) is stripped before fuzzy-matching just
    the bare street name against the CIF table.

    This is identity resolution for a correctness check (see
    :func:`get_departures_with_vehicles`), not a search suggestion, so it fails
    closed: returns an empty list rather than a low-confidence guess whenever
    nothing clears a high cutoff.

    Ties at the top score are all accepted, not just the first — several
    legitimately related names can tie for a short query (e.g. ``"Agnes
    Street"`` ties both itself and ``"Crumlin Road (Agnes Street)"``), and both
    are worth including rather than picking one arbitrarily.

    Args:
        stop_display_name: Display name as returned by the journey-planner API,
                            e.g. ``"Shankill, Cambria Street"``.

    Returns:
        Every ATCOCode in the local CIF stop table whose name ties for the top
        fuzzy-match score, when that score clears a high cutoff (0.8). Empty list
        if nothing scores that high.
    """
    bare_name = stop_display_name.split(",", 1)[-1].strip() if "," in stop_display_name else stop_display_name

    df = get_stop_dataframe()
    matches = fuzzy_match(bare_name, df["name"].unique().tolist(), n=len(df), cutoff=0.8)
    if not matches:
        return []

    top_score = matches[0][1]
    top_names = [name for name, score in matches if score >= top_score - 1e-9]
    return df.index[df["name"].isin(top_names)].tolist()


_INBOUND_KEYWORDS = {"belfast", "castlecourt", "royal avenue", "city centre", "great victoria"}


def _infer_direction(text: str) -> str:
    """Infer inbound/outbound from a departure's destination or a VMI vehicle's direction text."""
    return "inbound" if any(kw in text.lower() for kw in _INBOUND_KEYWORDS) else "outbound"


def _hhmm_to_timestamp(hhmm: str, ref: "pd.Timestamp") -> "pd.Timestamp | None":
    """Convert an HHMM Europe/London local time to a UTC Timestamp on ref's date.

    CIF (and VMI journey_id) HHMM values are genuine Europe/London local civil
    time, DST included — not a nominal/UTC-direct value.

    Args:
        hhmm: Four-digit local time, e.g. ``"0904"``.
        ref: Any UTC timestamp on the intended calendar date.

    Returns:
        A UTC Timestamp, or ``None`` if ``hhmm`` isn't parseable.
    """
    try:
        h, m = int(hhmm[:2]), int(hhmm[2:])
        ref_local = ref.tz_convert("Europe/London")
        local_dt = ref_local.normalize() + pd.Timedelta(hours=h, minutes=m)
        return local_dt.tz_localize(None).tz_localize("Europe/London").tz_convert("UTC")
    except (ValueError, IndexError, Exception):
        return None


def _verified_passing_time(
    vehicle_line: str,
    vehicle_journey_id: str,
    vehicle_current_stop: Any,
    vehicle_next_stop: Any,
    target_atcos: list[str],
    ref_dt: "pd.Timestamp",
    vehicle_delay_seconds: Any = None,
) -> "tuple[pd.Timestamp, pd.Timestamp, str | None] | None":
    """CIF-scheduled/predicted passing time (and a destination hint) for a verified vehicle.

    None if the vehicle's trip can't be verified (via the CIF timetable) as calling
    at any of ``target_atcos``, or as not yet having passed it.

    Returns the unadjusted CIF-scheduled passing time, that same time adjusted by
    the vehicle's own live ``delay_seconds`` (when available), and the verified
    trip's own terminus stop name as a destination hint (``None`` if that stop
    isn't in the local CIF lookup) — always together, from the one verified
    trip, so a caller never pairs one of these with an unrelated schedule/
    prediction/destination sourced elsewhere.

    The destination hint is a CIF stop name (e.g. "Donegall Place"), not the
    journey-planner's own "Belfast, Donegall Place" style text, and for a
    circular route the trip's technical terminus isn't necessarily a meaningful
    "where's this bus going" answer — a best-effort fallback for a vehicle with
    no matching departure row to borrow display text from (see
    :func:`get_departures_with_vehicles`), not a guaranteed-accurate one.

    The predicted value (CIF-scheduled + VMI's live delay) is preferred over the
    journey-planner's own ``actual_departure``/``delay_minutes``, which doesn't
    reliably reflect delay for a significantly late bus.

    Args:
        vehicle_line: VMI vehicle's line, e.g. ``"11E"``.
        vehicle_journey_id: VMI vehicle's journey_id (HHMM origin departure).
        vehicle_current_stop: VMI vehicle's ``current_stop`` ATCOCode (may be NaN).
        vehicle_next_stop: VMI vehicle's ``next_stop`` ATCOCode (may be NaN).
        target_atcos: Candidate ATCOCode(s) for the stop being checked against —
                      see :func:`_resolve_target_atcos`. Empty means "can't verify".
        ref_dt: Reference timestamp (e.g. the departure's own time) for picking the
                correct calendar date/day-of-week.
        vehicle_delay_seconds: VMI's own ``delay_seconds`` for this vehicle
                               (negative = early). Missing/NA is treated as no
                               adjustment (VMI's ``realtime_available=False`` case).

    Returns:
        ``(cif_scheduled, predicted, destination_hint)``; the first two UTC, the
        third a stop name or ``None``. Or ``None`` if unverified.
    """
    if not target_atcos:
        return None
    trips = find_trip_for_vehicle(vehicle_line, vehicle_journey_id, ref_dt=ref_dt.to_pydatetime())
    for trip in trips:
        stop_seqs = {ts.atco: ts.seq for ts in trip.stops}
        target_atco = next((a for a in target_atcos if a in stop_seqs), None)
        if target_atco is None:
            continue  # this trip variant doesn't actually call at the target stop
        vehicle_atco = vehicle_current_stop if pd.notna(vehicle_current_stop) else vehicle_next_stop
        vehicle_seq = stop_seqs.get(vehicle_atco)
        if vehicle_seq is None or vehicle_seq > stop_seqs[target_atco]:
            continue  # vehicle has already passed this stop, or position unknown
        target_ts = next(ts for ts in trip.stops if ts.atco == target_atco)
        hhmm = target_ts.depart or target_ts.arrive
        if not hhmm:
            continue
        scheduled = _hhmm_to_timestamp(hhmm, ref_dt)
        if scheduled is None:
            continue
        delay = vehicle_delay_seconds if pd.notna(vehicle_delay_seconds) else 0
        destination_hint = resolve_stop_name(trip.stops[-1].atco, fallback=False)
        return scheduled, scheduled + pd.Timedelta(seconds=float(delay)), destination_hint
    return None


def _greedy_assign_vehicles(pairs: list[tuple[int, int, "pd.Timedelta"]]) -> dict[int, int]:
    """Assign departures to vehicles, closest-match first, each used at most once.

    A single vehicle must never be reported as the live match for two different
    departures just because its passing time happened to be close to both.

    Args:
        pairs: ``(departure_index, vehicle_index, time_delta)`` triples for every
               candidate pairing within the acceptance window.

    Returns:
        ``{departure_index: vehicle_index}`` for each departure that got a match.
    """
    dep_to_vehicle: dict[int, int] = {}
    assigned_deps: set[int] = set()
    assigned_vehicles: set[int] = set()
    for dep_idx, v_idx, _ in sorted(pairs, key=lambda p: p[2]):
        if dep_idx in assigned_deps or v_idx in assigned_vehicles:
            continue
        dep_to_vehicle[dep_idx] = v_idx
        assigned_deps.add(dep_idx)
        assigned_vehicles.add(v_idx)
    return dep_to_vehicle


def get_departures_with_vehicles(
    stop_name: str,
    n: int = 5,
    dt: datetime | None = None,
    enrich_stops: bool = False,
) -> pd.DataFrame:
    """Return next-N departures enriched with live vehicle positions where available.

    Fetches departures and live VMI vehicles in parallel (two API calls), then
    matches them in two stages:

    1. Candidates share line + inferred direction, and the local CIF timetable
       confirms the vehicle's own scheduled trip actually calls at this stop
       *and* its live position (current_stop/next_stop) is at or before that
       stop in the trip's sequence — this rules out a vehicle still elsewhere on
       a branching route (e.g. 11/11A/11B/11C/11E) that hasn't reached this stop
       yet. Candidates are then matched on each side's own *scheduled* time
       (the vehicle's CIF-derived schedule at this stop vs. the departure row's
       ``planned_departure``) within a tight 5-minute window, closest-first,
       each departure and vehicle used at most once — not the delay-adjusted
       side, which could otherwise match a vehicle whose own row has already
       rolled past "now" to a different, unrelated, later departure instead.
    2. A verified vehicle left over from stage 1 (its own row has rolled out of
       the journey-planner's retrievable past) gets a row of its own instead of
       being dropped, since it's typically the single most relevant "next bus"
       on the board: ``service``/``destination`` borrowed from any other
       departure sharing its line+direction, or — if none exists — the verified
       trip's own CIF terminus stop name (a different naming style, and not
       always meaningful for a circular route, but better than leaving
       ``destination`` blank).

    When the stop can't be confidently crosswalked to a CIF ATCOCode (see
    :func:`_resolve_target_atcos`) or its scheduled trip isn't found in the CIF
    data, this fails closed: no vehicle is matched for that departure.

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
        ``current_stop``, ``next_stop``, ``vehicle_scheduled_departure``,
        ``vehicle_predicted_departure``, and (if enrich_stops)
        ``current_stop_name``, ``next_stop_name``.  Vehicle columns are
        ``None`` / ``NaN`` where no match.

        ``vehicle_scheduled_departure``/``vehicle_predicted_departure`` are both
        sourced from the one verified CIF trip — the former unadjusted, the
        latter adjusted by the vehicle's own live delay — and should be
        preferred together over ``planned_departure``/``actual_departure``
        when present, never mixed one-from-each: the journey-planner's own
        ``actual_departure``/``delay_minutes`` doesn't reliably reflect real
        delay for a significantly late bus, and pairing a vehicle-derived value
        with a journey-planner-derived value from a different, unrelated row
        can show a "Predicted" earlier than its own "Scheduled".
    """
    from .vehicles import get_live_vehicles

    if dt is None:
        dt = datetime.now(tz=UTC)
    dt_aware = pd.Timestamp(dt)
    deps = get_departures_by_name(stop_name, n=n + 2, dt=dt)
    if deps.empty:
        return deps

    # Collect lines present in departures to reduce VMI filtering work
    dep_lines = {_extract_line(s) for s in deps["service"].unique()}

    all_vehicles = []
    for line in dep_lines:
        vdf = get_live_vehicles(line=line, enrich_stops=enrich_stops)
        all_vehicles.append(vdf)

    if not all_vehicles or all(v.empty for v in all_vehicles):
        # No live vehicles on any line — return departures as-is with empty vehicle cols.
        # deps was over-fetched (n+2) to absorb a stale boundary row, so restore the
        # "next N" contract here too, not just on the vehicle-matched path below.
        for col in ("vehicle_id", "vehicle_lat", "vehicle_lon", "vehicle_delay_s", "current_stop", "next_stop"):
            deps[col] = None
        deps["vehicle_scheduled_departure"] = pd.NaT
        deps["vehicle_predicted_departure"] = pd.NaT
        return deps.head(n).reset_index(drop=True)

    vehicles = pd.concat([v for v in all_vehicles if not v.empty], ignore_index=True)

    vehicle_cols = {
        "vehicle_id": None,
        "vehicle_lat": None,
        "vehicle_lon": None,
        "vehicle_delay_s": None,
        "current_stop": None,
        "next_stop": None,
        "vehicle_scheduled_departure": pd.NaT,
        "vehicle_predicted_departure": pd.NaT,
    }
    if enrich_stops:
        vehicle_cols["current_stop_name"] = None
        vehicle_cols["next_stop_name"] = None

    target_atcos = _resolve_target_atcos(deps["stop_name"].iloc[0]) if "stop_name" in deps.columns else []

    # Verify every candidate vehicle once, independent of any departure row.
    verified: dict[int, tuple[pd.Timestamp, pd.Timestamp, str | None]] = {}
    for v_idx, v in vehicles.iterrows():
        result_v = _verified_passing_time(
            v["line"],
            v["journey_id"],
            v.get("current_stop"),
            v.get("next_stop"),
            target_atcos,
            dt_aware,
            vehicle_delay_seconds=v.get("delay_seconds"),
        )
        if result_v is not None:
            verified[v_idx] = result_v

    # Match on each side's own scheduled time, within a tight window (see docstring).
    deps_list = list(deps.iterrows())
    pairs: list[tuple[int, int, pd.Timedelta]] = []
    for dep_idx, (_, dep) in enumerate(deps_list):
        line = _extract_line(dep["service"])
        direction = _infer_direction(dep["destination"])

        candidates = vehicles[
            (vehicles["line"].str.upper() == line.upper())
            & (vehicles["direction"].apply(_infer_direction) == direction)
        ]
        for v_idx in candidates.index:
            if v_idx not in verified:
                continue
            scheduled, _, _ = verified[v_idx]
            delta = abs(dep["planned_departure"] - scheduled)
            if delta < pd.Timedelta(minutes=5):
                pairs.append((dep_idx, v_idx, delta))

    dep_to_vehicle = _greedy_assign_vehicles(pairs)

    def _apply_vehicle_cols(row: dict[str, Any], v_idx: int) -> None:
        best_match = vehicles.loc[v_idx]
        scheduled, predicted, _ = verified[v_idx]
        row["vehicle_id"] = best_match["vehicle_id"]
        row["vehicle_lat"] = best_match["latitude"]
        row["vehicle_lon"] = best_match["longitude"]
        row["vehicle_delay_s"] = best_match["delay_seconds"]
        row["current_stop"] = best_match.get("current_stop")
        row["next_stop"] = best_match.get("next_stop")
        row["vehicle_scheduled_departure"] = scheduled
        row["vehicle_predicted_departure"] = predicted
        if enrich_stops:
            row["current_stop_name"] = best_match.get("current_stop_name")
            row["next_stop_name"] = best_match.get("next_stop_name")

    matched_rows = []
    for dep_idx, (_, dep) in enumerate(deps_list):
        row = dep.to_dict()
        v_idx = dep_to_vehicle.get(dep_idx)
        if v_idx is not None:
            _apply_vehicle_cols(row, v_idx)
        else:
            for col, default in vehicle_cols.items():
                row[col] = default
        matched_rows.append(row)

    # A verified vehicle left unmatched above gets a row of its own (see docstring).
    used_vehicles = set(dep_to_vehicle.values())
    for v_idx in verified:
        if v_idx in used_vehicles:
            continue
        v = vehicles.loc[v_idx]
        line = v["line"]
        direction = _infer_direction(v["direction"])
        same_line = deps[
            (deps["service"].apply(_extract_line).str.upper() == line.upper())
            & (deps["destination"].apply(_infer_direction) == direction)
        ]
        scheduled, predicted, destination_hint = verified[v_idx]
        # Prefer a sibling departure's own destination text; fall back to the
        # verified trip's CIF terminus name (see docstring) only when none exists.
        destination = same_line["destination"].iloc[0] if not same_line.empty else (destination_hint or "")
        row = {
            "planned_departure": scheduled,
            "actual_departure": predicted,
            "service": f"Bus {line}",
            "destination": destination,
            "transport_mode": same_line["transport_mode"].iloc[0] if not same_line.empty else "Bus",
            "is_real_time": True,
            "is_cancelled": False,
            "delay_minutes": (predicted - scheduled).total_seconds() / 60,
            "unique_id": f"vehicle-{v['vehicle_id']}-{scheduled.isoformat()}",
        }
        if "stop_name" in deps.columns:
            row["stop_name"] = deps["stop_name"].iloc[0]
        _apply_vehicle_cols(row, v_idx)
        matched_rows.append(row)

    result = pd.DataFrame(matched_rows)
    # When every row is unmatched, these columns are all-NaT with no real
    # Timestamp to infer a tz from, so pandas defaults to naive datetime64
    # instead of tz-aware UTC -- force it explicitly.
    result["vehicle_scheduled_departure"] = pd.to_datetime(result["vehicle_scheduled_departure"], utc=True)
    result["vehicle_predicted_departure"] = pd.to_datetime(result["vehicle_predicted_departure"], utc=True)
    # Prefer the vehicle-derived prediction over the journey-planner's own
    # estimate, then restore the "next N" contract (the +2 over-fetch above
    # can leave extra, now-past or surplus rows).
    effective = result["vehicle_predicted_departure"].where(
        result["vehicle_predicted_departure"].notna(), result["actual_departure"]
    )
    result = result[effective >= dt_aware].copy()
    effective = effective[effective >= dt_aware]
    result = result.loc[effective.sort_values().index].head(n)
    return result.reset_index(drop=True)


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
