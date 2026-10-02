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

## Persistence approach (implemented)

Built in #1918 as a one-shot snapshot-and-append primitive, not an internal poll loop:
bolster "isn't a service yet", so the responsibility for calling it repeatedly belongs
to whatever's doing the scheduling — a cron entry, a systemd timer, or a person running
`bolster translink poll --watch` in a terminal — not to the library itself.

```
bolster.data_sources.translink.lateness.poll_once():
    GET /velocmap/vmi/VMI (via get_live_vehicles())
    append one snapshot to a generic sqlite store (bolster.utils.snapshots)
```

`bolster translink poll --watch --interval 66` wraps this in a simple loop at the CLI
layer only (graceful Ctrl-C, prints a running total) — a convenience for interactive
use and for quickly accumulating enough data to exercise `bolster translink lateness`
against, not a production scheduler. Unattended collection is a cron/systemd-timer
calling the non-`--watch` form every ~66s.

Volume observed in testing (unfiltered — all operators, not just Metro): **360 rows per
snapshot**, well above the original ~185-vehicle Metro-only estimate below, which undercounted
by excluding Ulsterbus and Glider. At 360 rows/snapshot and a 66s cadence that's
~5,200 rows/hour, ~125,000 rows/day — still trivial for sqlite.

Stored under `~/.cache/bolster/snapshots/translink_vmi.db` (generic per-name sqlite
stores, reusable by any future polling need — not translink-specific).

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

## Implementation

```python
from bolster.data_sources.translink import lateness

lateness.poll_once()  # one GET, appends one snapshot, returns rows written
lateness.poll_once(db_path=custom_path)  # non-default store location

df = lateness.read_snapshots()  # everything polled so far
lateness.lateness_by_line(df)  # per-line delay distribution
lateness.lateness_by_stop(df, enrich_stops=True)
lateness.lateness_by_journey(df)  # best-effort — see journey_id caveat below
```

CLI:

```
bolster translink poll [--operator MET] [--enrich-stops] [--db-path PATH] [--watch] [--interval 66]
bolster translink lateness [--group-by line|stop|journey] [--line X] [--since DATE] [--min-samples N]
```

Not done (explicitly deferred, see the issue): exposing this as a `data_sources`
`get_*` accessor / README coverage table entry — that needs real accumulated data to
validate the shape against first; the #1919 FastAPI/webapp integration; any actual
scheduler setup (deployment, not library code).

## Related

- #1918 — this feature
- #1919 — FastAPI/webapp integration (expects #1918's one-shot primitive to be
  scheduled externally — *"that needs a persistent process, see #1918"*)
- PR #1917 — initial `translink` module (departures, vehicles, stops)
- `src/bolster/data_sources/translink/vehicles.py` — `get_live_vehicles()`
- `src/bolster/data_sources/translink/stops.py` — `get_stop_lookup()` for ATCOCode resolution
- `src/bolster/utils/snapshots.py` — the generic snapshot-to-sqlite utility
