"""Unit tests for bolster.data_sources.translink.lateness — no network calls.

Covers the snapshot store wiring (poll_once/read_snapshots against a real tmp_path
sqlite file, no mocks) and the aggregation math (lateness_by_line/_by_stop/_by_journey
against small synthetic DataFrames with known values).
"""

import pandas as pd
import pytest

from bolster.data_sources.translink import lateness
from bolster.utils.snapshots import append_snapshot


def _row(**overrides):
    base = {
        "polled_at": "2026-06-01T17:30:00+00:00",
        "vehicle_id": "TM-1234",
        "operator": "MET",
        "line": "11E",
        "direction": "Royal Avenue",
        "journey_id": "1730",
        "delay_seconds": 30,
        "current_stop": "700000014482",
        "next_stop": "700000014483",
        "is_at_stop": False,
        "realtime_available": True,
        "latitude": 54.62,
        "longitude": -5.99,
    }
    base.update(overrides)
    return base


def _snapshots_df(*rows):
    return pd.DataFrame([_row(**r) for r in rows])


class TestDefaultDbPath:
    def test_lives_under_snapshots_dir(self, tmp_path, monkeypatch):
        import bolster.utils.snapshots as snapshots_module

        monkeypatch.setattr(snapshots_module, "_SNAPSHOT_DIR", tmp_path)
        assert lateness.default_db_path() == tmp_path / "translink_vmi.db"


class TestPollOnceAndReadSnapshots:
    def test_writes_and_reads_back(self, tmp_path, monkeypatch):
        vehicles = pd.DataFrame(
            [
                {
                    "vehicle_id": "TM-1",
                    "operator": "MET",
                    "line": "11E",
                    "direction": "Royal Avenue",
                    "journey_id": "1730",
                    "delay_seconds": 30,
                    "current_stop": "700000014482",
                    "next_stop": "700000014483",
                    "is_at_stop": False,
                    "realtime_available": True,
                    "latitude": 54.62,
                    "longitude": -5.99,
                    # extra columns get_live_vehicles also returns, should be dropped
                    "day_of_operation": "Monday",
                    "operator_raw": "TM",
                }
            ]
        )
        monkeypatch.setattr(lateness, "get_live_vehicles", lambda operator=None, enrich_stops=False: vehicles)
        db = tmp_path / "store.db"

        written = lateness.poll_once(db_path=db)

        assert written == 1
        df = lateness.read_snapshots(db_path=db)
        assert len(df) == 1
        assert set(lateness._SNAPSHOT_COLUMNS).issubset(df.columns)
        assert "day_of_operation" not in df.columns

    def test_restores_bool_columns_after_sqlite_roundtrip(self, tmp_path):
        db = tmp_path / "store.db"
        append_snapshot(db, lateness._TABLE, _snapshots_df({"is_at_stop": True, "realtime_available": False}))

        df = lateness.read_snapshots(db_path=db)

        assert df["is_at_stop"].dtype == bool
        assert df["realtime_available"].dtype == bool
        assert df["is_at_stop"].iloc[0] is True or df["is_at_stop"].iloc[0] == True  # noqa: E712
        assert df["realtime_available"].iloc[0] == False  # noqa: E712

    def test_empty_feed_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lateness, "get_live_vehicles", lambda operator=None, enrich_stops=False: pd.DataFrame())
        db = tmp_path / "store.db"

        assert lateness.poll_once(db_path=db) == 0
        assert lateness.read_snapshots(db_path=db).empty


class TestLatenessByLine:
    def test_ranks_worst_median_first(self):
        df = _snapshots_df(
            *(
                [{"line": "1A", "delay_seconds": d} for d in (10, 20, 30, -10, 0)]
                + [{"line": "2B", "delay_seconds": d} for d in (100, 90, 80, 70, 60)]
            )
        )
        out = lateness.lateness_by_line(df, min_samples=3)
        assert out["line"].tolist() == ["2B", "1A"]
        assert out.loc[out["line"] == "2B", "median_delay_seconds"].iloc[0] == 80

    def test_drops_lines_below_min_samples(self):
        df = _snapshots_df(*([{"line": "1A", "delay_seconds": 10}] * 5 + [{"line": "RARE", "delay_seconds": 999}] * 2))
        out = lateness.lateness_by_line(df, min_samples=3)
        assert out["line"].tolist() == ["1A"]

    def test_excludes_rows_without_realtime(self):
        df = _snapshots_df(
            *(
                [{"line": "1A", "delay_seconds": 10, "realtime_available": True}] * 3
                + [{"line": "1A", "delay_seconds": 9999, "realtime_available": False}] * 3
            )
        )
        out = lateness.lateness_by_line(df, min_samples=1)
        assert out.loc[0, "samples"] == 3
        assert out.loc[0, "mean_delay_seconds"] == 10

    def test_pct_early_and_pct_late(self):
        df = _snapshots_df(*[{"line": "1A", "delay_seconds": d} for d in (-100, -50, 0, 70, 200)])
        out = lateness.lateness_by_line(df, min_samples=1)
        row = out.iloc[0]
        assert row["pct_early"] == pytest.approx(40.0)
        assert row["pct_late_over_60s"] == pytest.approx(40.0)


class TestLatenessByStop:
    def test_groups_by_current_stop(self):
        df = _snapshots_df(
            *(
                [{"current_stop": "A", "delay_seconds": d} for d in (10, 20, 30)]
                + [{"current_stop": "B", "delay_seconds": d} for d in (100, 110, 120)]
            )
        )
        out = lateness.lateness_by_stop(df, min_samples=3)
        assert set(out["current_stop"]) == {"A", "B"}

    def test_drops_rows_with_no_current_stop(self):
        df = _snapshots_df(
            *([{"current_stop": "A", "delay_seconds": 10}] * 3 + [{"current_stop": None, "delay_seconds": 10}] * 3)
        )
        out = lateness.lateness_by_stop(df, min_samples=1)
        assert out["current_stop"].tolist() == ["A"]

    def test_enrich_stops_resolves_names(self, monkeypatch):
        monkeypatch.setattr(lateness, "resolve_stop_name", lambda code: f"Stop {code}")
        df = _snapshots_df(*[{"current_stop": "A", "delay_seconds": 10}] * 3)
        out = lateness.lateness_by_stop(df, min_samples=1, enrich_stops=True)
        assert out["current_stop_name"].iloc[0] == "Stop A"


class TestLatenessByJourney:
    def test_distinct_lines_sharing_a_journey_id_stay_separate(self):
        df = _snapshots_df(
            *(
                [{"line": "1A", "journey_id": "1730", "delay_seconds": d} for d in (10, 20, 30)]
                + [{"line": "2B", "journey_id": "1730", "delay_seconds": d} for d in (100, 110, 120)]
            )
        )
        out = lateness.lateness_by_journey(df, min_samples=3)
        assert len(out) == 2
        assert set(out["line"]) == {"1A", "2B"}

    def test_tracks_first_last_and_max_delay_in_polled_order(self):
        df = _snapshots_df(
            {"polled_at": "2026-06-01T17:30:00+00:00", "delay_seconds": 10},
            {"polled_at": "2026-06-01T17:31:06+00:00", "delay_seconds": 50},
            {"polled_at": "2026-06-01T17:32:12+00:00", "delay_seconds": 30},
        )
        out = lateness.lateness_by_journey(df, min_samples=3)
        row = out.iloc[0]
        assert row["first_delay_seconds"] == 10
        assert row["last_delay_seconds"] == 30
        assert row["max_delay_seconds"] == 50

    def test_drops_journeys_below_min_samples(self):
        df = _snapshots_df({"delay_seconds": 10}, {"delay_seconds": 20})
        assert lateness.lateness_by_journey(df, min_samples=3).empty
