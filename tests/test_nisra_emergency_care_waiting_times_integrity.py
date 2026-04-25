"""Data integrity tests for NISRA emergency care waiting times statistics.

Tests validate that the data is internally consistent, covers the expected
time range, and that the pct_within_4hrs column is always in [0, 1].

All tests use real data fetched once per class (no mocks).
"""

import datetime

import pandas as pd
import pytest

from bolster.data_sources.nisra import emergency_care_waiting_times as ecwt


class TestEmergencyCareIntegrity:
    """Test suite for emergency care waiting times data."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        """Fetch latest emergency care waiting times data once for the test class."""
        return ecwt.get_latest_data()

    def test_required_columns_present(self, latest_data):
        """All required columns must be present."""
        required = {
            "date",
            "year",
            "month",
            "trust",
            "dept",
            "attendance_type",
            "under_4hrs",
            "btw_4_12hrs",
            "over_12hrs",
            "total",
            "pct_within_4hrs",
        }
        assert required.issubset(set(latest_data.columns)), (
            f"Missing columns: {required - set(latest_data.columns)}"
        )

    def test_all_five_trusts_present(self, latest_data):
        """All 5 HSC Trusts must appear in the data."""
        actual = set(latest_data["trust"].unique())
        assert ecwt.EXPECTED_TRUSTS == actual, (
            f"Expected trusts {ecwt.EXPECTED_TRUSTS}, got {actual}"
        )

    def test_pct_within_4hrs_range(self, latest_data):
        """pct_within_4hrs must always be in [0.0, 1.0] (proportion, not percentage)."""
        pct = latest_data["pct_within_4hrs"].dropna()
        assert (pct >= 0.0).all(), "pct_within_4hrs has values below 0"
        assert (pct <= 1.0).all(), f"pct_within_4hrs has values above 1.0: {pct[pct > 1.0].tolist()}"

    def test_total_attendance_non_negative(self, latest_data):
        """Total attendances must not be negative."""
        valid = latest_data["total"].dropna()
        assert (valid >= 0).all(), "total has negative values"

    def test_historical_coverage_from_2008(self, latest_data):
        """Data must cover back to at least April 2008."""
        min_year = int(latest_data["year"].min())
        assert min_year <= 2008, f"Expected data from 2008, earliest year is {min_year}"

    def test_recent_data_available(self, latest_data):
        """Data must include records from within the last 12 months."""
        max_date = latest_data["date"].max()
        cutoff = pd.Timestamp(datetime.datetime.now()) - pd.DateOffset(months=12)
        assert max_date >= cutoff, (
            f"Latest data ({max_date.date()}) is more than 12 months old"
        )

    def test_attendance_types_present(self, latest_data):
        """All three standard attendance types must be present."""
        types = set(latest_data["attendance_type"].unique())
        assert {"Type 1", "Type 2", "Type 3"}.issubset(types), (
            f"Not all attendance types present; found {types}"
        )

    def test_date_column_is_datetime(self, latest_data):
        """date column must be datetime dtype."""
        assert pd.api.types.is_datetime64_any_dtype(latest_data["date"]), (
            f"date column has dtype {latest_data['date'].dtype}"
        )

    def test_validate_data_passes(self, latest_data):
        """validate_data() must return True for real data."""
        assert ecwt.validate_data(latest_data) is True

    def test_minimum_row_count(self, latest_data):
        """Must have a substantial number of rows (>1000)."""
        assert len(latest_data) > 1000, f"Only {len(latest_data)} rows found"


class TestValidation:
    """Unit tests for validate_data() edge cases — no network calls."""

    def test_validate_empty_dataframe(self):
        """validate_data raises NISRAValidationError on empty DataFrame."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        empty = pd.DataFrame(
            columns=["date", "year", "month", "trust", "attendance_type", "total", "pct_within_4hrs"]
        )
        with pytest.raises(NISRAValidationError, match="empty"):
            ecwt.validate_data(empty)

    def test_validate_missing_columns(self):
        """validate_data raises NISRAValidationError when required columns are missing."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "year": [2024]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            ecwt.validate_data(df)

    def test_validate_pct_out_of_range(self):
        """validate_data raises NISRAValidationError when pct_within_4hrs > 1."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "year": [2024],
                "month": ["January"],
                "trust": ["Belfast"],
                "attendance_type": ["Type 1"],
                "total": [100],
                "pct_within_4hrs": [1.5],
            }
        )
        with pytest.raises(NISRAValidationError, match="pct_within_4hrs"):
            ecwt.validate_data(df)

    def test_validate_negative_pct(self):
        """validate_data raises NISRAValidationError when pct_within_4hrs < 0."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "year": [2024],
                "month": ["January"],
                "trust": ["Belfast"],
                "attendance_type": ["Type 1"],
                "total": [100],
                "pct_within_4hrs": [-0.1],
            }
        )
        with pytest.raises(NISRAValidationError, match="pct_within_4hrs"):
            ecwt.validate_data(df)

    def test_validate_valid_dataframe_passes(self):
        """validate_data returns True for a well-formed DataFrame."""
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01")],
                "year": [2024, 2024],
                "month": ["January", "February"],
                "trust": ["Belfast", "Northern"],
                "attendance_type": ["Type 1", "Type 1"],
                "total": [100, 200],
                "pct_within_4hrs": [0.75, 0.85],
            }
        )
        assert ecwt.validate_data(df) is True
