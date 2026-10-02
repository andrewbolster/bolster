"""Network-wide lateness tracking from repeated Translink VMI snapshots.

The VMI feed (:func:`bolster.data_sources.translink.vehicles.get_live_vehicles`) has no
historical API: it only ever shows the current instant. The only way to build a lateness
time series is to call it repeatedly and keep what comes back. :func:`poll_once` does
exactly one such call-and-store; something else — a cron entry, a systemd timer, a
person running ``bolster translink poll --watch`` in a terminal — is responsible for
calling it repeatedly roughly every 66 seconds (the feed's own refresh cadence). This
module does not loop or sleep itself.

``delay_seconds`` (from the feed) is relative to the scheduled time at the vehicle's
*current* position, not at any particular stop, so it drifts as a vehicle moves along
its route; a single snapshot is a point sample, not a journey summary. The aggregation
functions here (:func:`lateness_by_line`, :func:`lateness_by_stop`,
:func:`lateness_by_journey`) treat every stored row as one such point sample and
summarise across however many samples have accumulated.

``journey_id`` (from the feed) is usually an HHMM string — the origin departure time,
local time — not a globally unique trip identifier; a minority of vehicles carry a
non-HHMM value instead (observed in testing, e.g. ``"AWS_ME..."``-style ids on some
services), which :func:`~.vehicles._parse_journey_time` passes through unchanged. Two
distinct real journeys on the same line that happen to depart at the same minute on
different days, or two different lines that both depart at that minute, are not
distinguishable by ``journey_id`` alone.
:func:`lateness_by_journey` groups by ``(line, direction, journey_id, date)`` to reduce
same-day collisions, but a high-frequency route with more than one departure in the same
clock minute will still collide; treat its output as an approximation, not ground truth.

See Also:
    ``docs/development/translink-lateness-tracking.md`` for the full design notes this
    module implements.
"""

import os
from pathlib import Path

import pandas as pd

from bolster.utils import snapshots as _snapshots

from .stops import resolve_stop_name
from .vehicles import get_live_vehicles

_DB_NAME = "translink_vmi"
_TABLE = "vmi_snapshots"

_SNAPSHOT_COLUMNS = [
    "vehicle_id",
    "operator",
    "line",
    "direction",
    "journey_id",
    "delay_seconds",
    "current_stop",
    "next_stop",
    "is_at_stop",
    "realtime_available",
    "latitude",
    "longitude",
]


def default_db_path() -> Path:
    """Path to the local lateness snapshot store (see :func:`~bolster.utils.snapshots.snapshot_db_path`)."""
    return _snapshots.snapshot_db_path(_DB_NAME)


def poll_once(
    operator: str | None = None, enrich_stops: bool = False, db_path: str | os.PathLike[str] | None = None
) -> int:
    """Fetch one live VMI snapshot and append it to the local lateness store.

    Args:
        operator: Optional operator filter passed through to :func:`get_live_vehicles`.
        enrich_stops: If True, also resolve and store ``current_stop_name``/
            ``next_stop_name``. Slower (builds the stop lookup on first call).
        db_path: Store location; defaults to :func:`default_db_path`.

    Returns:
        Number of vehicle rows written (``0`` if the feed currently has no active
        vehicles — not an error, just outside service hours).

    Raises:
        TranslinkDataNotFoundError: If the VMI feed cannot be reached.
        TranslinkValidationError: If the feed response is malformed.
    """
    df = get_live_vehicles(operator=operator, enrich_stops=enrich_stops)
    if df.empty:
        return 0

    columns = [*_SNAPSHOT_COLUMNS, "current_stop_name", "next_stop_name"] if enrich_stops else _SNAPSHOT_COLUMNS
    return _snapshots.append_snapshot(db_path or default_db_path(), _TABLE, df[columns])


def read_snapshots(
    db_path: str | os.PathLike[str] | None = None, since: str | pd.Timestamp | None = None
) -> pd.DataFrame:
    """Read previously polled snapshots from the local lateness store.

    Args:
        db_path: Store location; defaults to :func:`default_db_path`.
        since: If given, only snapshots polled at or after this time.

    Returns:
        All matching snapshot rows, oldest first. Empty if nothing has been polled yet.
        ``is_at_stop``/``realtime_available`` are restored to bool (sqlite round-trips
        them as 0/1 integers).
    """
    df = _snapshots.read_snapshots(db_path or default_db_path(), _TABLE, since=since)
    for col in ("is_at_stop", "realtime_available"):
        if col in df.columns:
            df[col] = df[col].astype(bool)
    return df


def _delay_stats(grouped: "pd.core.groupby.generic.DataFrameGroupBy", min_samples: int) -> pd.DataFrame:
    """Shared delay-distribution aggregation for a groupby of rows with a ``delay_seconds`` column."""
    stats = grouped["delay_seconds"].agg(
        samples="count",
        mean_delay_seconds="mean",
        median_delay_seconds="median",
        p95_delay_seconds=lambda s: s.quantile(0.95),
        pct_early=lambda s: 100 * (s < 0).mean(),
        pct_late_over_60s=lambda s: 100 * (s > 60).mean(),
    )
    return stats[stats["samples"] >= min_samples].reset_index()


def lateness_by_line(df: pd.DataFrame, min_samples: int = 5) -> pd.DataFrame:
    """Summarise delay distribution per line, across all polled snapshots.

    Args:
        df: Snapshots as returned by :func:`read_snapshots`.
        min_samples: Lines with fewer than this many realtime-available samples are
            dropped — not enough data to say anything useful about them yet.

    Returns:
        One row per line with ``samples``, ``mean_delay_seconds``,
        ``median_delay_seconds``, ``p95_delay_seconds``, ``pct_early`` (share with
        negative delay) and ``pct_late_over_60s``, sorted by ``median_delay_seconds``
        descending (worst first).

    Example:
        >>> df = pd.DataFrame({
        ...     "line": ["1A"] * 6 + ["2B"] * 6,
        ...     "delay_seconds": [10, 20, 30, -10, 0, 15, 100, 90, 80, 70, 60, 110],
        ... })
        >>> out = lateness_by_line(df, min_samples=3)
        >>> out["line"].tolist()
        ['2B', '1A']
    """
    available = df[df["realtime_available"]] if "realtime_available" in df.columns else df
    out = _delay_stats(available.groupby("line"), min_samples)
    return out.sort_values("median_delay_seconds", ascending=False).reset_index(drop=True)


def lateness_by_stop(df: pd.DataFrame, min_samples: int = 5, enrich_stops: bool = False) -> pd.DataFrame:
    """Summarise delay distribution per current stop, across all polled snapshots.

    A vehicle's ``delay_seconds`` is sampled at whatever point it happened to be when
    polled, not specifically when it was at a stop — this groups by whichever stop
    ``current_stop`` names at that moment, a coarse proxy for "lateness near this stop".

    Args:
        df: Snapshots as returned by :func:`read_snapshots`.
        min_samples: Stops with fewer than this many samples are dropped.
        enrich_stops: If True and the snapshots don't already have a
            ``current_stop_name`` column, resolve one via
            :func:`~bolster.data_sources.translink.stops.resolve_stop_name`
            (one live lookup per distinct unresolved stop, on first use).

    Returns:
        One row per ``current_stop`` (plus ``current_stop_name`` if resolved) with the
        same delay-distribution columns as :func:`lateness_by_line`.
    """
    available = df[df["realtime_available"]] if "realtime_available" in df.columns else df
    available = available.dropna(subset=["current_stop"])
    out = _delay_stats(available.groupby("current_stop"), min_samples)

    if enrich_stops and "current_stop_name" not in out.columns:
        out.insert(1, "current_stop_name", out["current_stop"].apply(resolve_stop_name))

    return out.sort_values("median_delay_seconds", ascending=False).reset_index(drop=True)


def lateness_by_journey(df: pd.DataFrame, min_samples: int = 3) -> pd.DataFrame:
    """Best-effort per-journey delay summary, grouping by ``(line, direction, journey_id, date)``.

    ``journey_id`` is an HHMM string, not a globally unique trip id (see module
    docstring) — this is an approximation of "one run of one journey", not a guarantee.
    Including the polled date in the group key at least separates the same scheduled
    departure on different days; it does not separate two genuinely distinct journeys
    that depart in the same clock minute on the same day.

    Args:
        df: Snapshots as returned by :func:`read_snapshots`.
        min_samples: Journeys with fewer than this many samples are dropped.

    Returns:
        One row per ``(line, direction, journey_id, date)`` with ``samples`` and the
        delay range/trend observed across that journey's polled samples: ``first_delay_seconds``,
        ``last_delay_seconds`` and ``max_delay_seconds`` (ordered by ``polled_at``).
    """
    available = df[df["realtime_available"]] if "realtime_available" in df.columns else df
    available = available.copy()
    available["date"] = pd.to_datetime(available["polled_at"]).dt.date

    ordered = available.sort_values("polled_at")
    grouped = ordered.groupby(["line", "direction", "journey_id", "date"])
    out = grouped["delay_seconds"].agg(
        samples="count",
        first_delay_seconds="first",
        last_delay_seconds="last",
        max_delay_seconds="max",
    )
    out = out[out["samples"] >= min_samples].reset_index()
    return out.sort_values("last_delay_seconds", ascending=False).reset_index(drop=True)
