"""Tests for bolster.utils.snapshots — generic sqlite snapshot persistence.

Real sqlite against tmp_path throughout, no mocks and no network: these are small,
synchronous, local filesystem operations.
"""

import pandas as pd

from bolster.utils.snapshots import append_snapshot, read_snapshots, snapshot_db_path


class TestSnapshotDbPath:
    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        import bolster.utils.snapshots as snapshots_module

        monkeypatch.setattr(snapshots_module, "_SNAPSHOT_DIR", tmp_path / "snapshots")
        path = snapshot_db_path("example")

        assert path == tmp_path / "snapshots" / "example.db"
        assert path.parent.is_dir()

    def test_name_becomes_filename(self, tmp_path, monkeypatch):
        import bolster.utils.snapshots as snapshots_module

        monkeypatch.setattr(snapshots_module, "_SNAPSHOT_DIR", tmp_path)
        assert snapshot_db_path("widgets").name == "widgets.db"


class TestAppendSnapshot:
    def test_creates_db_and_table_on_first_write(self, tmp_path):
        db = tmp_path / "store.db"
        rows = append_snapshot(db, "t", pd.DataFrame({"x": [1, 2, 3]}))

        assert rows == 3
        assert db.exists()

    def test_accepts_plain_string_path(self, tmp_path):
        db = str(tmp_path / "store.db")
        assert append_snapshot(db, "t", pd.DataFrame({"x": [1]})) == 1
        assert read_snapshots(db, "t")["x"].tolist() == [1]

    def test_empty_dataframe_is_a_noop(self, tmp_path):
        db = tmp_path / "store.db"
        rows = append_snapshot(db, "t", pd.DataFrame())

        assert rows == 0
        assert not db.exists()

    def test_second_write_appends_not_replaces(self, tmp_path):
        db = tmp_path / "store.db"
        append_snapshot(db, "t", pd.DataFrame({"x": [1]}))
        append_snapshot(db, "t", pd.DataFrame({"x": [2, 3]}))

        assert len(read_snapshots(db, "t")) == 3

    def test_stamps_polled_at_when_absent(self, tmp_path):
        db = tmp_path / "store.db"
        append_snapshot(db, "t", pd.DataFrame({"x": [1]}))

        df = read_snapshots(db, "t")
        assert "polled_at" in df.columns
        assert df["polled_at"].notna().all()

    def test_does_not_overwrite_existing_polled_at(self, tmp_path):
        db = tmp_path / "store.db"
        append_snapshot(db, "t", pd.DataFrame({"x": [1], "polled_at": ["2020-01-01T00:00:00+00:00"]}))

        df = read_snapshots(db, "t")
        assert df["polled_at"].iloc[0] == "2020-01-01T00:00:00+00:00"

    def test_does_not_mutate_caller_dataframe(self, tmp_path):
        db = tmp_path / "store.db"
        original = pd.DataFrame({"x": [1]})
        append_snapshot(db, "t", original)

        assert "polled_at" not in original.columns


class TestReadSnapshots:
    def test_missing_db_returns_empty_dataframe(self, tmp_path):
        df = read_snapshots(tmp_path / "nonexistent.db", "t")

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_missing_table_returns_empty_dataframe(self, tmp_path):
        db = tmp_path / "store.db"
        append_snapshot(db, "other_table", pd.DataFrame({"x": [1]}))

        assert read_snapshots(db, "t").empty

    def test_since_filters_by_polled_at(self, tmp_path):
        db = tmp_path / "store.db"
        append_snapshot(db, "t", pd.DataFrame({"x": [1], "polled_at": ["2020-01-01T00:00:00+00:00"]}))
        append_snapshot(db, "t", pd.DataFrame({"x": [2], "polled_at": ["2020-06-01T00:00:00+00:00"]}))

        recent = read_snapshots(db, "t", since="2020-03-01")

        assert recent["x"].tolist() == [2]

    def test_rows_ordered_by_polled_at(self, tmp_path):
        db = tmp_path / "store.db"
        append_snapshot(db, "t", pd.DataFrame({"x": [2], "polled_at": ["2020-06-01T00:00:00+00:00"]}))
        append_snapshot(db, "t", pd.DataFrame({"x": [1], "polled_at": ["2020-01-01T00:00:00+00:00"]}))

        assert read_snapshots(db, "t")["x"].tolist() == [1, 2]
