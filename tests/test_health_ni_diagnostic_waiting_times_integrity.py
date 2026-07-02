"""Data integrity tests for NISRA diagnostic waiting times statistics.

Tests use real data fetched from the NISRA PxStat API (no mocks).
Fixtures are scoped to the class to avoid redundant network calls.

Key validations:
- Required columns present
- Performance rates between 0 and 1
- All 5 HSC Trusts present
- Historical coverage back to at least 2010
- No negative values
- Validation function edge cases (no network required)
"""

import datetime

import pandas as pd
import pytest

from bolster.data_sources.health_ni import diagnostic_waiting_times as dwt


class TestDiagnosticWaitingTimesIntegrity:
    """Test suite for diagnostic waiting times by HSC Trust."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        """Fetch latest diagnostic waiting times data once for the test class."""
        return dwt.get_latest_diagnostic_waiting_times(force_refresh=False)

    def test_required_columns_present(self, latest_data):
        """Test that all required columns are present."""
        required = {
            "date", "quarter", "year", "trust", "category",
            "total_waiting", "within_9_weeks", "over_9_weeks",
            "over_26_weeks", "performance_rate",
        }
        assert required.issubset(set(latest_data.columns))

    def test_all_five_trusts_present(self, latest_data):
        """Test that all 5 HSC Trusts are present in the data."""
        expected = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}
        actual = set(latest_data["trust"].unique())
        assert expected == actual, f"Missing trusts: {expected - actual}"

    def test_performance_rate_between_0_and_1(self, latest_data):
        """Test that performance rates are between 0 and 1."""
        valid_rates = latest_data["performance_rate"].replace(
            [float("inf"), float("-inf")], float("nan")
        ).dropna()
        assert (valid_rates >= 0).all(), "Performance rates contain values < 0"
        assert (valid_rates <= 1).all(), "Performance rates contain values > 1"

    def test_no_negative_values(self, latest_data):
        """Test that patient counts are not negative."""
        for col in ("total_waiting", "within_9_weeks", "over_9_weeks", "over_26_weeks"):
            col_data = latest_data[col].dropna()
            assert (col_data >= 0).all(), f"Negative values in column '{col}'"

    def test_historical_coverage_back_to_2010(self, latest_data):
        """Test that data goes back to at least 2010."""
        min_year = latest_data["year"].min()
        assert min_year <= 2010, f"Expected data from 2010 or earlier, earliest is {min_year}"

    def test_recent_data_available(self, latest_data):
        """Test that recent data is available (within last 3 years)."""
        max_year = latest_data["year"].max()
        current_year = datetime.datetime.now().year
        assert max_year >= current_year - 3, f"Latest data ({max_year}) is more than 3 years old"

    def test_data_is_quarterly(self, latest_data):
        """Test that data is recorded quarterly (quarter column non-null)."""
        assert latest_data["quarter"].notna().all()
        # Verify quarter format matches expected pattern e.g. '2010/11Q1'
        sample = latest_data["quarter"].iloc[0]
        assert "Q" in str(sample), f"Unexpected quarter format: {sample!r}"

    def test_date_year_consistency(self, latest_data):
        """Test that date and year columns are consistent."""
        date_years = latest_data["date"].dt.year
        assert (date_years == latest_data["year"]).all(), "date and year columns are inconsistent"

    def test_no_duplicate_trust_quarter_rows(self, latest_data):
        """Test no duplicate trust/quarter combinations."""
        dupes = latest_data.groupby(["quarter", "trust"]).size()
        dupes = dupes[dupes > 1]
        assert len(dupes) == 0, f"Duplicate trust/quarter rows found: {dupes}"

    def test_validate_function_passes(self, latest_data):
        """Test that the validate function passes on real data."""
        assert dwt.validate_diagnostic_waiting_times(latest_data) is True


class TestTrustFilter:
    """Test trust and year filtering."""

    @pytest.fixture(scope="class")
    def belfast_data(self):
        """Fetch Belfast Trust data."""
        return dwt.get_latest_diagnostic_waiting_times(trust="Belfast")

    def test_trust_filter_returns_only_belfast(self, belfast_data):
        """Test that trust filter returns only the requested trust."""
        assert set(belfast_data["trust"].unique()) == {"Belfast"}

    def test_year_filter(self):
        """Test that year filter returns only the requested year."""
        df = dwt.get_latest_diagnostic_waiting_times(year=2019)
        assert (df["year"] == 2019).all()
        assert len(df) > 0

    def test_trust_and_year_filter(self):
        """Test combined trust + year filter."""
        df = dwt.get_latest_diagnostic_waiting_times(trust="Western", year=2020)
        assert (df["trust"] == "Western").all()
        assert (df["year"] == 2020).all()


class TestParseQuarter:
    """Unit tests for the quarter parsing helper — no network calls."""

    def test_q4_maps_to_march_next_year(self):
        """Q4 of financial year 2007/08 ends in March 2008."""
        ts = dwt._parse_tlist_quarter("2007/08Q4")
        assert ts == pd.Timestamp("2008-03-01")

    def test_q1_maps_to_june_start_year(self):
        """Q1 of financial year 2023/24 ends in June 2023."""
        ts = dwt._parse_tlist_quarter("2023/24Q1")
        assert ts == pd.Timestamp("2023-06-01")

    def test_q2_maps_to_september(self):
        ts = dwt._parse_tlist_quarter("2023/24Q2")
        assert ts == pd.Timestamp("2023-09-01")

    def test_q3_maps_to_december(self):
        ts = dwt._parse_tlist_quarter("2023/24Q3")
        assert ts == pd.Timestamp("2023-12-01")

    def test_all_quarters_return_timestamp(self):
        for q in ("2020/21Q1", "2020/21Q2", "2020/21Q3", "2020/21Q4"):
            result = dwt._parse_tlist_quarter(q)
            assert isinstance(result, pd.Timestamp)


class TestValidateFunction:
    """Unit tests for the validate function — no network calls needed."""

    def _make_valid_df(self) -> pd.DataFrame:
        """Build a minimal valid DataFrame for testing."""
        rows = []
        for trust in ("Belfast", "Northern", "South Eastern", "Southern", "Western"):
            for i in range(2):
                rows.append({
                    "date": pd.Timestamp("2023-06-01"),
                    "quarter": "2022/23Q1",
                    "year": 2023,
                    "trust": trust,
                    "category": "All categories of test",
                    "total_waiting": 1000.0,
                    "within_9_weeks": 700.0,
                    "over_9_weeks": 300.0,
                    "over_26_weeks": 50.0,
                    "performance_rate": 0.70,
                })
        return pd.DataFrame(rows)

    def test_validate_valid_dataframe(self):
        """Test that a well-formed DataFrame passes validation."""
        df = self._make_valid_df()
        assert dwt.validate_diagnostic_waiting_times(df) is True

    def test_validate_empty_dataframe(self):
        """Test that an empty DataFrame raises ValueError."""
        df = pd.DataFrame(columns=[
            "date", "quarter", "year", "trust", "category",
            "total_waiting", "within_9_weeks", "over_9_weeks",
            "over_26_weeks", "performance_rate",
        ])
        with pytest.raises(ValueError, match="empty"):
            dwt.validate_diagnostic_waiting_times(df)

    def test_validate_too_few_records(self):
        """Test that fewer than 5 records raises ValueError."""
        df = self._make_valid_df().head(3)
        with pytest.raises(ValueError, match="too few records"):
            dwt.validate_diagnostic_waiting_times(df)

    def test_validate_missing_columns(self):
        """Test that missing required columns raises ValueError."""
        df = self._make_valid_df().drop(columns=["total_waiting"])
        with pytest.raises(ValueError, match="Missing required columns"):
            dwt.validate_diagnostic_waiting_times(df)

    def test_validate_negative_values(self):
        """Test that negative patient counts raise ValueError."""
        df = self._make_valid_df()
        df.loc[0, "total_waiting"] = -1.0
        with pytest.raises(ValueError, match="Negative values"):
            dwt.validate_diagnostic_waiting_times(df)

    def test_validate_performance_rate_out_of_range(self):
        """Test that performance rates outside [0, 1] raise ValueError."""
        df = self._make_valid_df()
        df.loc[0, "performance_rate"] = 1.5
        with pytest.raises(ValueError, match="performance_rate outside"):
            dwt.validate_diagnostic_waiting_times(df)

    def test_validate_nan_values_excluded(self):
        """Test that NaN values in numeric columns are tolerated (excluded from checks)."""
        df = self._make_valid_df()
        df.loc[0, "total_waiting"] = float("nan")
        df.loc[0, "performance_rate"] = float("nan")
        # Should not raise — NaNs are dropped before validation
        assert dwt.validate_diagnostic_waiting_times(df) is True
