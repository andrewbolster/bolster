# Translink Network Lateness Tracking

Design notes from initial exploration of the Translink VMI feed (2026-06-25),
following the build of the `translink` data source module (PR #1917).

## Key finding: one call covers the whole network

The VMI feed (`vpos.translinkniplanner.co.uk/velocmap/vmi/VMI`) returns a snapshot
of **every active vehicle on the entire Translink network** in a single unauthenticated
GET request. There is no need to poll per-stop or per-line.

A snapshot taken during evening peak (c. 18:20 BST) showed:

- **185 Metro vehicles** active simultaneously
- **70+ distinct lines** represented
- **~85% of vehicles** have a non-null `delay_seconds` value (`realtime_available=True`)
- Delay range observed: **-449s (7.5 min early) to +1178s (nearly 20 min late)**
- The `delay_seconds` field is computed server-side by Vix Technology — negative = early

Sample lateness snapshot (Metro, evening peak):

| Line | Vehicles | Mean delay (s) | Median delay (s) |
|------|----------|----------------|------------------|
| 11G  | 1        | +1178          | —                |
| 2C   | 4        | +299           | +240             |
| 11E  | 4        | +7             | 0                |
| 10K  | 2        | -9             | -9               |
| 3A   | 2        | -22            | -22              |

## Proposed persistence approach

```
Every 66 seconds (VMI refresh interval):
    GET /velocmap/vmi/VMI
    append rows to store:
        timestamp, vehicle_id, line, direction, journey_id,
        delay_seconds, current_stop, next_stop, latitude, longitude
```

Volume estimate (Metro only, ~185 vehicles):

- ~185 rows per snapshot
- ~2,700 rows/hour
- ~65,000 rows/day
- ~24M rows/year

Parquet partitioned by `date` would be trivially small (\<500 MB/year uncompressed).
SQLite is simpler for a single-machine poller.

## What you could answer with this data

- **Per-line lateness distributions**: median/p95 delay by line, time-of-day, day-of-week
- **Per-stop lateness**: join `current_stop` (NaPTAN ATCOCode) to the stop lookup table
- **Journey reliability**: track individual `journey_id` runs across their full route
- **Early departures**: `delay_seconds < -60` — buses leaving stops ahead of schedule
- **Bunching detection**: two vehicles on same line/direction within small time window
- **Seasonal/event effects**: bank holidays, school terms, major events in Belfast

## Constraints and gaps

- `delay_seconds` is null for ~15% of vehicles (`realtime_available=False`) — these
  runs cannot be tracked for lateness, only presence
- `delay_seconds` is relative to the scheduled time at the **current position**, not
  at any specific stop — it will drift as the bus moves
- VMI `journey_id` is an HHMM string (local time, origin departure), not a globally
  unique trip ID — collisions possible on routes with >1 departure per minute
- The VMI feed has no historical API; data only exists while you're polling
- `current_stop` / `next_stop` are NaPTAN ATCOCodes — joinable to the CIF stop lookup
  via `get_stop_lookup()`, but ~15% of VMI ATCOCodes are not in the current CIF zips
  (newer stops); these fall back to the live `locationApi/find` endpoint

## Implementation sketch

```python
import time
import sqlite3
from datetime import datetime, timezone
from bolster.data_sources.translink.vehicles import get_live_vehicles


def poll_loop(db_path="translink_lateness.db", operator="MET"):
    con = sqlite3.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            polled_at TEXT,
            vehicle_id TEXT,
            line TEXT,
            direction TEXT,
            journey_id TEXT,
            delay_seconds INTEGER,
            current_stop TEXT,
            next_stop TEXT,
            latitude REAL,
            longitude REAL
        )
    """)
    while True:
        polled_at = datetime.now(timezone.utc).isoformat()
        df = get_live_vehicles(operator=operator)
        df["polled_at"] = polled_at
        df[
            [
                "polled_at",
                "vehicle_id",
                "line",
                "direction",
                "journey_id",
                "delay_seconds",
                "current_stop",
                "next_stop",
                "latitude",
                "longitude",
            ]
        ].to_sql("snapshots", con, if_exists="append", index=False)
        con.commit()
        time.sleep(66)
```

A CLI command `bolster translink poll` wrapping this would be a natural extension
of the existing `translink` group in `cli.py`.

## Related

- PR #1917 — initial `translink` module (departures, vehicles, stops)
- `src/bolster/data_sources/translink/vehicles.py` — `get_live_vehicles()`
- `src/bolster/data_sources/translink/stops.py` — `get_stop_lookup()` for ATCOCode resolution
