"""Integrity tests for NISRA Economic Indicators Module.

These tests validate real data quality, structure, and consistency for the
Index of Services (IOS) and Index of Production (IOP) modules.

Test coverage includes:
- Data structure and types
- Data completeness and ranges
- Time series continuity
- Growth rate calculations
- Helper function behavior
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import economic_indicators


class TestIndexOfServicesIntegrity:
    """Integrity tests for Index of Services (IOS) data."""

    @pytest.fixture(scope="class")
    def latest_ios(self):
        """Fixture to load latest IOS data once for all tests."""
        return economic_indicators.get_latest_index_of_services(force_refresh=False)

    def test_data_structure(self, latest_ios):
        """Test that IOS data has correct structure."""
        assert isinstance(latest_ios, pd.DataFrame)
        assert len(latest_ios) > 0

        # Check required columns
        required_cols = ["date", "quarter", "year", "ni_index", "uk_index"]
        assert all(col in latest_ios.columns for col in required_cols)

    def test_data_types(self, latest_ios):
        """Test that IOS columns have correct data types."""
        assert pd.api.types.is_datetime64_any_dtype(latest_ios["date"])
        assert latest_ios["quarter"].dtype == "object"
        assert pd.api.types.is_integer_dtype(latest_ios["year"])
        assert pd.api.types.is_float_dtype(latest_ios["ni_index"])
        assert pd.api.types.is_float_dtype(latest_ios["uk_index"])

    def test_quarter_values(self, latest_ios):
        """Test that quarter values are valid."""
        valid_quarters = {"Q1", "Q2", "Q3", "Q4"}
        assert set(latest_ios["quarter"].unique()).issubset(valid_quarters)

    def test_year_range(self, latest_ios):
        """Test that year range is reasonable (2005-present)."""
        assert latest_ios["year"].min() >= 2005
        assert latest_ios["year"].max() <= 2026

    def test_index_values_positive(self, latest_ios):
        """Test that index values are positive."""
        assert (latest_ios["ni_index"] > 0).all()
        assert (latest_ios["uk_index"] > 0).all()

    def test_no_missing_values(self, latest_ios):
        """Test that there are no missing values in key columns."""
        assert not latest_ios["date"].isna().any()
        assert not latest_ios["quarter"].isna().any()
        assert not latest_ios["year"].isna().any()
        assert not latest_ios["ni_index"].isna().any()
        assert not latest_ios["uk_index"].isna().any()

    def test_chronological_order(self, latest_ios):
        """Test that data is in chronological order."""
        assert latest_ios["date"].is_monotonic_increasing

    def test_quarterly_continuity(self, latest_ios):
        """Test that quarters are continuous (no gaps)."""
        # Group by year and check all years have 4 quarters
        for year in latest_ios["year"].unique():
            year_data = latest_ios[latest_ios["year"] == year]
            # Most years should have 4 quarters, except possibly the latest year
            if year < latest_ios["year"].max():
                assert len(year_data) == 4

    def test_date_quarter_consistency(self, latest_ios):
        """Test that date and quarter columns are consistent."""
        for _, row in latest_ios.iterrows():
            quarter_num = int(row["quarter"][1])
            expected_month = (quarter_num - 1) * 3 + 1
            assert row["date"].month == expected_month
            assert row["date"].year == row["year"]
            assert row["date"].day == 1

    def test_coverage_includes_recent_data(self, latest_ios):
        """Test that data includes recent quarters (2024-2025)."""
        assert latest_ios["year"].max() >= 2024


class TestIndexOfProductionIntegrity:
    """Integrity tests for Index of Production (IOP) data."""

    @pytest.fixture(scope="class")
    def latest_iop(self):
        """Fixture to load latest IOP data once for all tests."""
        return economic_indicators.get_latest_index_of_production(force_refresh=False)

    def test_data_structure(self, latest_iop):
        """Test that IOP data has correct structure."""
        assert isinstance(latest_iop, pd.DataFrame)
        assert len(latest_iop) > 0

        # Check required columns
        required_cols = ["date", "quarter", "year", "ni_index", "uk_index"]
        assert all(col in latest_iop.columns for col in required_cols)

    def test_data_types(self, latest_iop):
        """Test that IOP columns have correct data types."""
        assert pd.api.types.is_datetime64_any_dtype(latest_iop["date"])
        assert latest_iop["quarter"].dtype == "object"
        assert pd.api.types.is_integer_dtype(latest_iop["year"])
        assert pd.api.types.is_float_dtype(latest_iop["ni_index"])
        assert pd.api.types.is_float_dtype(latest_iop["uk_index"])

    def test_quarter_values(self, latest_iop):
        """Test that quarter values are valid."""
        valid_quarters = {"Q1", "Q2", "Q3", "Q4"}
        assert set(latest_iop["quarter"].unique()).issubset(valid_quarters)

    def test_year_range(self, latest_iop):
        """Test that year range matches IOS (2005-present)."""
        assert latest_iop["year"].min() >= 2005
        assert latest_iop["year"].max() <= 2026

    def test_index_values_positive(self, latest_iop):
        """Test that index values are positive."""
        assert (latest_iop["ni_index"] > 0).all()
        assert (latest_iop["uk_index"] > 0).all()

    def test_no_missing_values(self, latest_iop):
        """Test that there are no missing values in key columns."""
        assert not latest_iop["date"].isna().any()
        assert not latest_iop["quarter"].isna().any()
        assert not latest_iop["year"].isna().any()
        assert not latest_iop["ni_index"].isna().any()
        assert not latest_iop["uk_index"].isna().any()

    def test_chronological_order(self, latest_iop):
        """Test that data is in chronological order."""
        assert latest_iop["date"].is_monotonic_increasing

    def test_quarterly_continuity(self, latest_iop):
        """Test that quarters are continuous."""
        for year in latest_iop["year"].unique():
            year_data = latest_iop[latest_iop["year"] == year]
            if year < latest_iop["year"].max():
                assert len(year_data) == 4

    def test_date_quarter_consistency(self, latest_iop):
        """Test that date and quarter columns are consistent."""
        for _, row in latest_iop.iterrows():
            quarter_num = int(row["quarter"][1])
            expected_month = (quarter_num - 1) * 3 + 1
            assert row["date"].month == expected_month
            assert row["date"].year == row["year"]
            assert row["date"].day == 1

    def test_coverage_matches_ios(self, latest_iop):
        """Test that IOP coverage period matches IOS."""
        ios = economic_indicators.get_latest_index_of_services(force_refresh=False)

        # Should have same time coverage
        assert latest_iop["year"].min() == ios["year"].min()
        assert latest_iop["year"].max() == ios["year"].max()


class TestHelperFunctionsIntegrity:
    """Integrity tests for helper functions."""

    @pytest.fixture(scope="class")
    def latest_ios(self):
        """Fixture for IOS data."""
        return economic_indicators.get_latest_index_of_services(force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_iop(self):
        """Fixture for IOP data."""
        return economic_indicators.get_latest_index_of_production(force_refresh=False)

    def test_get_ios_by_year(self, latest_ios):
        """Test filtering IOS by year."""
        df_2024 = economic_indicators.get_ios_by_year(latest_ios, 2024)

        assert len(df_2024) == 4  # Should have 4 quarters
        assert (df_2024["year"] == 2024).all()

    def test_get_iop_by_year(self, latest_iop):
        """Test filtering IOP by year."""
        df_2024 = economic_indicators.get_iop_by_year(latest_iop, 2024)

        assert len(df_2024) == 4
        assert (df_2024["year"] == 2024).all()

    def test_get_ios_by_quarter(self, latest_ios):
        """Test getting specific quarter from IOS."""
        q1_2024 = economic_indicators.get_ios_by_quarter(latest_ios, "Q1", 2024)

        assert len(q1_2024) == 1
        assert q1_2024["quarter"].values[0] == "Q1"
        assert q1_2024["year"].values[0] == 2024

    def test_get_iop_by_quarter(self, latest_iop):
        """Test getting specific quarter from IOP."""
        q1_2024 = economic_indicators.get_iop_by_quarter(latest_iop, "Q1", 2024)

        assert len(q1_2024) == 1
        assert q1_2024["quarter"].values[0] == "Q1"
        assert q1_2024["year"].values[0] == 2024

    def test_calculate_ios_growth_rate(self, latest_ios):
        """Test IOS growth rate calculation."""
        ios_growth = economic_indicators.calculate_ios_growth_rate(latest_ios)

        # Should have growth rate columns
        assert "ni_growth_rate" in ios_growth.columns
        assert "uk_growth_rate" in ios_growth.columns

        # First 4 quarters should have NaN (no prior year comparison)
        assert ios_growth["ni_growth_rate"].iloc[:4].isna().all()

        # Later quarters should have values
        assert not ios_growth["ni_growth_rate"].iloc[4:].isna().all()

        # Growth rates should be reasonable (typically -20% to +20%)
        valid_growth = ios_growth["ni_growth_rate"].dropna()
        assert (valid_growth > -50).all()  # No more than 50% decline
        assert (valid_growth < 50).all()  # No more than 50% growth

    def test_calculate_iop_growth_rate(self, latest_iop):
        """Test IOP growth rate calculation."""
        iop_growth = economic_indicators.calculate_iop_growth_rate(latest_iop)

        assert "ni_growth_rate" in iop_growth.columns
        assert "uk_growth_rate" in iop_growth.columns

        # First 4 quarters should have NaN
        assert iop_growth["ni_growth_rate"].iloc[:4].isna().all()

        # Growth rates should be reasonable
        valid_growth = iop_growth["ni_growth_rate"].dropna()
        assert (valid_growth > -50).all()
        assert (valid_growth < 50).all()

    def test_get_ios_summary_statistics(self, latest_ios):
        """Test IOS summary statistics calculation."""
        stats = economic_indicators.get_ios_summary_statistics(latest_ios, start_year=2020)

        # Check required keys
        required_keys = ["period", "ni_mean", "ni_min", "ni_max", "uk_mean", "uk_min", "uk_max", "quarters_count"]
        assert all(key in stats for key in required_keys)

        # Check values are reasonable
        assert stats["ni_mean"] > 0
        assert stats["ni_min"] < stats["ni_mean"] < stats["ni_max"]
        assert stats["uk_min"] < stats["uk_mean"] < stats["uk_max"]
        assert stats["quarters_count"] > 0
        assert "2020" in stats["period"]

    def test_get_iop_summary_statistics(self, latest_iop):
        """Test IOP summary statistics calculation."""
        stats = economic_indicators.get_iop_summary_statistics(latest_iop, start_year=2020)

        required_keys = ["period", "ni_mean", "ni_min", "ni_max", "uk_mean", "uk_min", "uk_max", "quarters_count"]
        assert all(key in stats for key in required_keys)

        assert stats["ni_mean"] > 0
        assert stats["ni_min"] < stats["ni_mean"] < stats["ni_max"]
        assert stats["quarters_count"] > 0

    def test_summary_statistics_date_filtering(self, latest_ios):
        """Test that summary statistics correctly filter by date range."""
        stats_2020_2024 = economic_indicators.get_ios_summary_statistics(latest_ios, start_year=2020, end_year=2024)
        stats_all = economic_indicators.get_ios_summary_statistics(latest_ios)

        # Filtered stats should have fewer quarters
        assert stats_2020_2024["quarters_count"] < stats_all["quarters_count"]

        # Period should reflect the filtering
        assert "2020" in stats_2020_2024["period"]
        assert "2024" in stats_2020_2024["period"]


class TestDataConsistency:
    """Test consistency between IOS and IOP data sources."""

    @pytest.fixture(scope="class")
    def latest_ios(self):
        """Fixture for IOS data."""
        return economic_indicators.get_latest_index_of_services(force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_iop(self):
        """Fixture for IOP data."""
        return economic_indicators.get_latest_index_of_production(force_refresh=False)

    def test_same_time_coverage(self, latest_ios, latest_iop):
        """Test that IOS and IOP have the same time period coverage."""
        assert latest_ios["year"].min() == latest_iop["year"].min()
        assert latest_ios["year"].max() == latest_iop["year"].max()

    def test_same_number_of_quarters(self, latest_ios, latest_iop):
        """Test that IOS and IOP have the same number of data points."""
        assert len(latest_ios) == len(latest_iop)

    def test_matching_dates(self, latest_ios, latest_iop):
        """Test that IOS and IOP have matching quarter dates."""
        assert latest_ios["date"].tolist() == latest_iop["date"].tolist()

    def test_recent_quarter_alignment(self, latest_ios, latest_iop):
        """Test that the most recent quarter is the same for both indices."""
        latest_ios_q = f"{latest_ios.iloc[-1]['quarter']} {latest_ios.iloc[-1]['year']}"
        latest_iop_q = f"{latest_iop.iloc[-1]['quarter']} {latest_iop.iloc[-1]['year']}"

        assert latest_ios_q == latest_iop_q
