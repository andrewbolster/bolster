"""Translink timetable — trip stop sequences from ATCO-CIF archives.

Parses the QD/QS/QO/QI/QT records from the Metro/Glider and Ulsterbus/GoldLine
CIF zips to build a queryable trip database: for any stop you can find all
services that call there, and for any pair of stops you can find direct services
that serve both in order.

Record formats parsed:
- QD  Journey header: operator, line number, description
- QS  Journey schedule: departure time, date range, days of week, direction
- QO7 Origin timing point: first stop ATCO, departure time
- QI7 Intermediate timing point: stop ATCO, arrival, departure times
- QT7 Terminus timing point: last stop ATCO, arrival time

ATCO code mapping: trip records store 11-digit codes (e.g. ``00000009264``)
while QL/QB stop records use 12-digit codes starting with ``7``
(e.g. ``700000009264``).  The relation is ``stop_atco = '7' + trip_atco[0:11]``.

Example:
    >>> trips = get_trip_index()
    >>> trips["700000001661"]  # stops serving Victoria Square
    [TripStop(...), ...]
"""

import io
import logging
import zipfile
from dataclasses import dataclass, field
from typing import Any

from ._base import (
    OPENDATANI_METRO_GLIDER_URL,
    OPENDATANI_ULSTERBUS_URL,
    download_file,
)

logger = logging.getLogger(__name__)


@dataclass
class TripStop:
    """A single stop within a trip's stop sequence."""

    atco: str
    arrive: str  # HHMM string, empty for origin
    depart: str  # HHMM string, empty for terminus
    seq: int  # 0-based position in trip


@dataclass
class Trip:
    """A single scheduled trip (one journey on one day pattern)."""

    operator: str
    line: str
    description: str
    depart_hhmm: str  # Origin departure time HHMM
    date_from: str  # YYYYMMDD
    date_to: str  # YYYYMMDD
    days: str  # 7-char string '1111100' = Mon-Sat
    direction: str  # 'O' outbound / 'I' inbound
    stops: list[TripStop] = field(default_factory=list)


# In-process cache: stop_atco → list[Trip] where that stop appears
_TRIP_INDEX: dict[str, list[tuple[Trip, TripStop]]] | None = None


def _parse_time_at(s: str, pos: int) -> tuple[str, int]:
    """Read one variable-width CIF time value starting at *pos*.

    Translink CIF stores times as HHMM (4 digits) for times >= 10:00 and as
    HMM (3 digits, no leading zero) for times < 10:00.  The activity
    character immediately follows with no separator.

    Disambiguates by trying 4 digits first; if the 4-digit value exceeds 2359
    (an impossible time), falls back to 3 digits.

    Args:
        s:   The full CIF record string.
        pos: Start position of the time field within *s*.

    Returns:
        ``(hhmm_str, new_pos)`` where *hhmm_str* is a zero-padded 4-char
        string (e.g. ``'0519'``) and *new_pos* is the position immediately
        after the time field.  Returns ``('', pos)`` if no digits found.
    """
    chunk4 = s[pos : pos + 4]
    digits4 = "".join(c for c in chunk4 if c.isdigit())
    if len(digits4) == 4:
        val = int(digits4)
        # Accept hours 0-28 to handle CIF next-day notation (e.g. 2601 = 02:01 next day)
        if val % 100 < 60 and val // 100 <= 28:
            return digits4, pos + 4
    chunk3 = s[pos : pos + 3]
    digits3 = "".join(c for c in chunk3 if c.isdigit())
    if digits3:
        return digits3.zfill(4), pos + 3
    return "", pos


def _trip_atco_to_stop_atco(trip_atco: str) -> str:
    """Map an 11-digit CIF trip ATCO code to a 12-digit NaPTAN ATCOCode.

    Trip records (QO/QI/QT) store 11-digit codes (e.g. ``00000009264``).
    Stop records (QL/QB) use 12-digit codes starting with ``7``
    (e.g. ``700000009264``).
    """
    return "7" + trip_atco


def _parse_cif_trips(zip_bytes: bytes) -> list[Trip]:
    """Extract all trips from an ATCO-CIF zip archive.

    Args:
        zip_bytes: Raw bytes of the zip file.

    Returns:
        List of :class:`Trip` objects, each with a populated ``stops`` list.
    """
    trips: list[Trip] = []
    current_trip: Trip | None = None

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for fname in zf.namelist():
            if not fname.lower().endswith(".cif"):
                continue
            content = zf.read(fname).decode("utf-8", errors="replace")
            for raw_line in content.splitlines():
                rt = raw_line[:3]

                if rt == "QDN":
                    # Journey header: QDN<op:4><line:var space-padded><direction:1><desc>
                    # Line is the first whitespace-delimited token after the 4-char op field.
                    operator = raw_line[3:7].strip()
                    after_op = raw_line[7:]
                    tokens = after_op.split()
                    line = tokens[0] if tokens else ""
                    description = raw_line[14:].strip() if len(raw_line) > 14 else ""
                    current_trip = Trip(
                        operator=operator,
                        line=line,
                        description=description,
                        depart_hhmm="",
                        date_from="",
                        date_to="",
                        days="",
                        direction="",
                    )
                    trips.append(current_trip)

                elif rt == "QSN" and current_trip is not None:
                    # Schedule: QSN<op:4><depart:4><??:2><date_from:8><date_to:8><days:7><school:1><bank:1><line:6>...<direction:1>
                    current_trip.depart_hhmm, _ = _parse_time_at(raw_line, 7)
                    current_trip.date_from = raw_line[13:21].strip()
                    current_trip.date_to = raw_line[21:29].strip()
                    current_trip.days = raw_line[29:36]
                    current_trip.direction = raw_line[-1] if raw_line else ""

                elif rt == "QO7" and current_trip is not None:
                    # QO7<trip_atco:11><depart:var>...  times start at [14]
                    stop_atco = _trip_atco_to_stop_atco(raw_line[3:14])
                    depart, _ = _parse_time_at(raw_line, 14)
                    current_trip.stops.append(TripStop(atco=stop_atco, arrive="", depart=depart, seq=0))

                elif rt == "QI7" and current_trip is not None:
                    # QI7<trip_atco:11><arrive:var><depart:var>...  times start at [14]
                    stop_atco = _trip_atco_to_stop_atco(raw_line[3:14])
                    arrive, pos = _parse_time_at(raw_line, 14)
                    depart, _ = _parse_time_at(raw_line, pos)
                    seq = len(current_trip.stops)
                    current_trip.stops.append(TripStop(atco=stop_atco, arrive=arrive, depart=depart, seq=seq))

                elif rt == "QT7" and current_trip is not None:
                    # QT7<trip_atco:11><arrive:var>...  times start at [14]
                    stop_atco = _trip_atco_to_stop_atco(raw_line[3:14])
                    arrive, _ = _parse_time_at(raw_line, 14)
                    seq = len(current_trip.stops)
                    current_trip.stops.append(TripStop(atco=stop_atco, arrive=arrive, depart="", seq=seq))

    return [t for t in trips if t.stops]


def _build_trip_index(force_refresh: bool = False) -> dict[str, list[tuple[Trip, TripStop]]]:
    """Build an inverted index: stop_atco → [(Trip, TripStop), ...].

    Downloads both CIF zips, parses all trips, then inverts into a lookup
    keyed by ATCOCode so callers can find all services at a given stop.

    Args:
        force_refresh: Re-download and reparse even if cached.

    Returns:
        Dict mapping each ATCOCode to a list of (Trip, TripStop) tuples
        for every trip that calls at that stop.
    """
    all_trips: list[Trip] = []
    for label, url in [
        ("Metro/Glider", OPENDATANI_METRO_GLIDER_URL),
        ("Ulsterbus/GoldLine", OPENDATANI_ULSTERBUS_URL),
    ]:
        logger.info("Parsing timetable trips from %s", label)
        path = download_file(url, cache_ttl_hours=168, force_refresh=force_refresh)
        trips = _parse_cif_trips(path.read_bytes())
        logger.info("%s: parsed %d trips", label, len(trips))
        all_trips.extend(trips)

    index: dict[str, list[tuple[Trip, TripStop]]] = {}
    for trip in all_trips:
        for ts in trip.stops:
            index.setdefault(ts.atco, []).append((trip, ts))

    logger.info(
        "Trip index built: %d stops, %d total trip-stop entries", len(index), sum(len(v) for v in index.values())
    )
    return index


def get_trip_index(force_refresh: bool = False) -> dict[str, list[tuple[Any, Any]]]:
    """Return the stop → [(Trip, TripStop)] inverted index.

    Built on first call and cached in-process for the lifetime of the
    Python process.  The underlying CIF zips are cached on disk for one week.

    Args:
        force_refresh: Re-download CIF zips and rebuild the index.

    Returns:
        Dict mapping ATCOCode → list of ``(Trip, TripStop)`` tuples for
        every scheduled trip that calls at that stop.
    """
    global _TRIP_INDEX
    if _TRIP_INDEX is None or force_refresh:
        _TRIP_INDEX = _build_trip_index(force_refresh=force_refresh)
    return _TRIP_INDEX


def find_services_at_stop(stop_atco: str, force_refresh: bool = False) -> list[Trip]:
    """Return all scheduled trips that call at *stop_atco*.

    Args:
        stop_atco: 12-digit NaPTAN ATCOCode (e.g. ``"700000001661"``).
        force_refresh: Rebuild the trip index from source.

    Returns:
        Deduplicated list of :class:`Trip` objects, ordered by origin
        departure time.
    """
    index = get_trip_index(force_refresh=force_refresh)
    entries = index.get(stop_atco, [])
    seen: set[int] = set()
    trips: list[Trip] = []
    for trip, _ in entries:
        if id(trip) not in seen:
            seen.add(id(trip))
            trips.append(trip)
    return sorted(trips, key=lambda t: t.depart_hhmm)


def find_direct_trips(
    origin_atco: str,
    dest_atco: str,
    force_refresh: bool = False,
) -> list[tuple[Trip, TripStop, TripStop]]:
    """Return all direct trips that serve *origin_atco* then *dest_atco*.

    A trip is considered direct if both stops appear in its stop sequence
    and the origin stop appears *before* the destination stop.

    Args:
        origin_atco: 12-digit NaPTAN ATCOCode of the origin stop.
        dest_atco: 12-digit NaPTAN ATCOCode of the destination stop.
        force_refresh: Rebuild the trip index from source.

    Returns:
        List of ``(Trip, origin_TripStop, dest_TripStop)`` tuples, ordered
        by the trip's origin departure time.  Empty list if no direct service
        runs between the two stops.
    """
    index = get_trip_index(force_refresh=force_refresh)

    origin_trips = {id(trip): (trip, ts) for trip, ts in index.get(origin_atco, [])}
    dest_trips = {id(trip): (trip, ts) for trip, ts in index.get(dest_atco, [])}

    common_ids = set(origin_trips) & set(dest_trips)
    results: list[tuple[Trip, TripStop, TripStop]] = []
    for trip_id in common_ids:
        trip, orig_ts = origin_trips[trip_id]
        _, dest_ts = dest_trips[trip_id]
        if orig_ts.seq < dest_ts.seq:
            results.append((trip, orig_ts, dest_ts))

    return sorted(results, key=lambda x: x[1].depart or x[0].depart_hhmm)
