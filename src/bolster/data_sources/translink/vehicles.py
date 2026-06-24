"""Translink live vehicle positions from the VMI (Vehicle Monitoring Interface) feed.

The VMI feed at ``vpos.translinkniplanner.co.uk/velocmap/vmi/VMI`` is an
undocumented, unauthenticated JSON endpoint operated by Vix Technology on behalf
of Translink.  It returns a snapshot of all active vehicles across Ulsterbus,
Metro, and Glider services, updated approximately every 66 seconds.

Key notes on the feed:
- ``X`` / ``Y`` are strings (longitude / latitude WGS84), not floats.
- ``JourneyIdentifier`` contains ``#!ADD!#vixvm_new#`` suffixes — strip from ``#``.
- ``IsAtStop`` only appears when ``True`` (sparse field).
- ``Delay`` is in seconds (negative = early).
- Operator code ``TM`` in ``VehicleIdentifier`` denotes Metro buses.
- ``CurrentStop`` / ``NextStop`` are NaPTAN ATCOCodes (``700000xxxxxx``).

Example:
    >>> vdf = get_live_vehicles()
    >>> {"vehicle_id", "line", "latitude", "longitude"}.issubset(vdf.columns)
    True
    >>> len(vdf) > 0
    True
"""

import logging
import re

import pandas as pd

from bolster.utils.web import session

from ._base import OPERATOR_ALIASES, VMI_URL, TranslinkDataNotFoundError, TranslinkValidationError
from .stops import resolve_stop_name

logger = logging.getLogger(__name__)

_JOURNEY_ID_RE = re.compile(r"^(\d{4})(?:#.*)?$")


def _parse_journey_time(journey_id: str) -> str:
    """Strip VMI suffix from JourneyIdentifier and return the bare HHMM code.

    Args:
        journey_id: Raw JourneyIdentifier, e.g. ``"1741#!ADD!#vixvm_new#"``.

    Returns:
        Bare HHMM string e.g. ``"1741"``, or the original if not matched.
    """
    return journey_id.split("#")[0]


def _normalise_operator(raw: str) -> str:
    """Return the canonical operator code, resolving known aliases.

    Args:
        raw: Operator code from ``VehicleIdentifier`` prefix, e.g. ``"TM"``.

    Returns:
        Canonical code, e.g. ``"MET"``.
    """
    return OPERATOR_ALIASES.get(raw, raw)


def _fetch_vmi() -> list[dict]:
    """Fetch the raw VMI JSON feed.

    Returns:
        List of vehicle dicts as returned by the feed.

    Raises:
        TranslinkDataNotFoundError: If the feed cannot be reached.
        TranslinkValidationError: If the response is not a JSON list.
    """
    try:
        resp = session.get(VMI_URL, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        raise TranslinkDataNotFoundError(f"VMI feed request failed: {e}") from e

    data = resp.json()
    if not isinstance(data, list):
        raise TranslinkValidationError(f"VMI feed returned unexpected type: {type(data)}")
    return data


def _parse_vmi(raw: list[dict], enrich_stops: bool = False) -> pd.DataFrame:
    """Convert raw VMI feed records to a clean DataFrame.

    Args:
        raw: List of vehicle dicts from the VMI feed.
        enrich_stops: If True, resolve CurrentStop/NextStop ATCOCodes to names
                      via the stop lookup table.  Adds ``current_stop_name`` and
                      ``next_stop_name`` columns.  Slows first call (builds lookup).

    Returns:
        DataFrame with columns:
        ``id``, ``vehicle_id``, ``operator``, ``operator_raw``, ``line``,
        ``direction``, ``journey_id``, ``day_of_operation``, ``longitude``,
        ``latitude``, ``longitude_prev``, ``latitude_prev``,
        ``timestamp``, ``timestamp_prev``, ``delay_seconds``,
        ``current_stop``, ``next_stop``, ``is_at_stop``, ``realtime_available``,
        ``mot_code``.
        Plus ``current_stop_name`` and ``next_stop_name`` if ``enrich_stops=True``.
    """
    rows = []
    for v in raw:
        vid = v.get("VehicleIdentifier", "")
        operator_raw = vid.split("-")[0] if "-" in vid else ""
        operator = _normalise_operator(operator_raw)

        rows.append(
            {
                "id": v.get("ID", ""),
                "vehicle_id": vid,
                "operator": operator,
                "operator_raw": operator_raw,
                "line": v.get("LineText", ""),
                "direction": v.get("DirectionText", ""),
                "journey_id": _parse_journey_time(v.get("JourneyIdentifier", "")),
                "day_of_operation": v.get("DayOfOperation", ""),
                "longitude": float(v["X"]) if v.get("X") else None,
                "latitude": float(v["Y"]) if v.get("Y") else None,
                "longitude_prev": float(v["XPrevious"]) if v.get("XPrevious") else None,
                "latitude_prev": float(v["YPrevious"]) if v.get("YPrevious") else None,
                "timestamp": pd.Timestamp(v["Timestamp"]) if v.get("Timestamp") else pd.NaT,
                "timestamp_prev": pd.Timestamp(v["TimestampPrevious"]) if v.get("TimestampPrevious") else pd.NaT,
                "delay_seconds": v.get("Delay"),
                "current_stop": v.get("CurrentStop"),
                "next_stop": v.get("NextStop"),
                "is_at_stop": bool(v.get("IsAtStop", False)),
                "realtime_available": bool(v.get("RealtimeAvailable", False)),
                "mot_code": v.get("MOTCode"),
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["delay_seconds"] = pd.to_numeric(df["delay_seconds"], errors="coerce").astype("Int64")
    df["mot_code"] = pd.to_numeric(df["mot_code"], errors="coerce").astype("Int64")

    if enrich_stops:
        df["current_stop_name"] = df["current_stop"].apply(
            lambda c: resolve_stop_name(c) if pd.notna(c) and c else None
        )
        df["next_stop_name"] = df["next_stop"].apply(lambda n: resolve_stop_name(n) if pd.notna(n) and n else None)

    return df


def get_live_vehicles(
    line: str | None = None,
    operator: str | None = None,
    enrich_stops: bool = False,
) -> pd.DataFrame:
    """Return a snapshot of live vehicle positions from the Translink VMI feed.

    Args:
        line: Optional line filter, case-insensitive (e.g. ``"11E"`` or ``"G1"``).
        operator: Optional operator filter, case-insensitive.  Accepts canonical
                  codes (``"MET"``) or VMI codes (``"TM"``).  Both map to Metro.
        enrich_stops: If True, resolve ``current_stop`` / ``next_stop`` ATCOCodes
                      to human-readable names.  Requires building the stop lookup
                      table on first call (~1.3 MB download).

    Returns:
        DataFrame with one row per active vehicle.  Columns:
        ``id``, ``vehicle_id``, ``operator``, ``operator_raw``, ``line``,
        ``direction``, ``journey_id``, ``day_of_operation``, ``longitude``,
        ``latitude``, ``longitude_prev``, ``latitude_prev``,
        ``timestamp`` (tz-aware), ``timestamp_prev`` (tz-aware),
        ``delay_seconds`` (Int64, negative = early), ``current_stop``,
        ``next_stop``, ``is_at_stop`` (bool), ``realtime_available`` (bool),
        ``mot_code`` (Int64).

    Raises:
        TranslinkDataNotFoundError: If the VMI feed cannot be reached.
        TranslinkValidationError: If the response is malformed.

    Example:
        >>> vdf = get_live_vehicles(line="11E")
        >>> all(vdf["line"].str.upper() == "11E")
        True
    """
    raw = _fetch_vmi()
    df = _parse_vmi(raw, enrich_stops=enrich_stops)

    if line is not None:
        df = df[df["line"].str.upper() == line.upper()]

    if operator is not None:
        canonical = _normalise_operator(operator.upper())
        df = df[df["operator"] == canonical]

    return df.reset_index(drop=True)


def validate_vehicles(df: pd.DataFrame) -> bool:
    """Validate a live vehicles DataFrame.

    Args:
        df: DataFrame as returned by :func:`get_live_vehicles`.

    Returns:
        True if validation passes.

    Raises:
        TranslinkValidationError: If required columns are missing or coordinates are invalid.
    """
    required = {"vehicle_id", "line", "latitude", "longitude", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        raise TranslinkValidationError(f"Vehicles DataFrame missing columns: {missing}")

    if len(df) == 0:
        return True  # Empty is valid outside service hours

    lats = df["latitude"].dropna()
    lons = df["longitude"].dropna()
    if len(lats) > 0 and not ((lats >= 53.9) & (lats <= 55.4)).all():
        bad = lats[(lats < 53.9) | (lats > 55.4)]
        raise TranslinkValidationError(f"Latitude values outside NI bounds [53.9, 55.4]: {bad.head().tolist()}")
    if len(lons) > 0 and not ((lons >= -8.2) & (lons <= -5.4)).all():
        bad = lons[(lons < -8.2) | (lons > -5.4)]
        raise TranslinkValidationError(f"Longitude values outside NI bounds [-8.2, -5.4]: {bad.head().tolist()}")

    return True
