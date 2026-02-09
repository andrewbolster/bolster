"""Integrity tests for NISRA Construction Output Module.

These tests validate real data quality, structure, and consistency for the
Construction Output statistics module.

Test coverage includes:
- Data structure and types
- Data completeness and ranges
- Time series continuity
- Index value relationships
- Growth rate calculations
- Helper function behavior
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import construction_output


class TestConstructionOutputIntegrity:
    """Integrity tests for Construction Output data."""

    @pytest.fixture(scope="class")
    def latest_construction(self):
        """Fixture to load latest Construction Output data once for all tests."""
        return construction_output.get_latest_construction_output(force_refresh=False)

    def test_data_structure(self, latest_construction):
        """Test that Construction Output data has correct structure."""
        assert isinstance(latest_construction, pd.DataFrame)
        assert len(latest_construction) > 0

        # Check required columns
        required_cols = ["date", "quarter", "year", "all_work_index", "new_work_index", "repair_maintenance_index"]
        assert all(col in latest_construction.columns for col in required_cols)

    def test_data_types(self, latest_construction):
        """Test that columns have correct data types."""
        assert pd.api.types.is_datetime64_any_dtype(latest_construction["date"])
        assert latest_construction["quarter"].dtype == "object"
        assert pd.api.types.is_integer_dtype(latest_construction["year"])
        assert pd.api.types.is_float_dtype(latest_construction["all_work_index"])
        assert pd.api.types.is_float_dtype(latest_construction["new_work_index"])
        assert pd.api.types.is_float_dtype(latest_construction["repair_maintenance_index"])

    def test_quarter_values(self, latest_construction):
        """Test that quarter values are valid."""
        valid_quarters = {"Q1", "Q2", "Q3", "Q4"}
        assert set(latest_construction["quarter"].unique()).issubset(valid_quarters)

    def test_year_range(self, latest_construction):
        """Test that year range is reasonable (2000-present)."""
        assert latest_construction["year"].min() >= 2000
        assert latest_construction["year"].max() <= 2026

    def test_data_starts_2000(self, latest_construction):
        """Test that data starts from Q2 2000."""
        earliest = latest_construction.iloc[0]
        assert earliest["year"] == 2000
        assert earliest["quarter"] == "Q2"  # Data starts from Q2 2000, not Q1

    def test_index_values_positive(self, latest_construction):
        """Test that index values are positive."""
        assert (latest_construction["all_work_index"] > 0).all()
        assert (latest_construction["new_work_index"] > 0).all()
        assert (latest_construction["repair_maintenance_index"] > 0).all()

    def test_no_missing_values(self, latest_construction):
        """Test that there are no missing values in key columns."""
        assert not latest_construction["date"].isna().any()
        assert not latest_construction["quarter"].isna().any()
        assert not latest_construction["year"].isna().any()
        assert not latest_construction["all_work_index"].isna().any()
        assert not latest_construction["new_work_index"].isna().any()
        assert not latest_construction["repair_maintenance_index"].isna().any()

    def test_chronological_order(self, latest_construction):
        """Test that data is in chronological order."""
        assert latest_construction["date"].is_monotonic_increasing

    def test_quarterly_continuity(self, latest_construction):
        """Test that quarters are continuous (no gaps)."""
        # Group by year and check most years have 4 quarters
        for year in latest_construction["year"].unique():
            year_data = latest_construction[latest_construction["year"] == year]
            # Most years should have 4 quarters, except:
            # - Year 2000 only has Q2-Q4 (3 quarters)
            # - Latest year may be incomplete
            if year < latest_construction["year"].max() and year > 2000:
                assert len(year_data) == 4

    def test_date_quarter_consistency(self, latest_construction):
        """Test that date and quarter columns are consistent."""
        for _, row in latest_construction.iterrows():
            quarter_num = int(row["quarter"][1])
            expected_month = (quarter_num - 1) * 3 + 1
            assert row["date"].month == expected_month
            assert row["date"].year == row["year"]
            assert row["date"].day == 1

    def test_coverage_includes_recent_data(self, latest_construction):
        """Test that data includes recent quarters (2024-2025)."""
        assert latest_construction["year"].max() >= 2024

    def test_2022_base_year(self, latest_construction):
        """Test that 2022 data shows base year values around 100."""
        df_2022 = latest_construction[latest_construction["year"] == 2022]

        # 2022 should have index values close to 100 (base year)
        mean_2022 = df_2022["all_work_index"].mean()
        assert 90 < mean_2022 < 110


class TestHelperFunctionsIntegrity:
    """Integrity tests for helper functions."""

    @pytest.fixture(scope="class")
    def latest_construction(self):
        """Fixture for Construction Output data."""
        return construction_output.get_latest_construction_output(force_refresh=False)

    def test_get_construction_by_year(self, latest_construction):
        """Test filtering by year."""
        df_2024 = construction_output.get_construction_by_year(latest_construction, 2024)

        assert len(df_2024) == 4  # Should have 4 quarters
        assert (df_2024["year"] == 2024).all()

    def test_get_construction_by_quarter(self, latest_construction):
        """Test getting specific quarter."""
        q1_2024 = construction_output.get_construction_by_quarter(latest_construction, "Q1", 2024)

        assert len(q1_2024) == 1
        assert q1_2024["quarter"].values[0] == "Q1"
        assert q1_2024["year"].values[0] == 2024

    def test_calculate_growth_rates(self, latest_construction):
        """Test growth rate calculation."""
        df_growth = construction_output.calculate_growth_rates(latest_construction)

        # Should have growth rate columns
        assert "all_work_yoy_growth" in df_growth.columns
        assert "new_work_yoy_growth" in df_growth.columns
        assert "repair_maintenance_yoy_growth" in df_growth.columns

        # First 4 quarters should have NaN (no prior year comparison)
        assert df_growth["all_work_yoy_growth"].iloc[:4].isna().all()

        # Later quarters should have values
        assert not df_growth["all_work_yoy_growth"].iloc[4:].isna().all()

        # Growth rates should be reasonable (typically -50% to +50%)
        valid_growth = df_growth["all_work_yoy_growth"].dropna()
        assert (valid_growth > -100).all()
        assert (valid_growth < 100).all()

    def test_get_summary_statistics(self, latest_construction):
        """Test summary statistics calculation."""
        stats = construction_output.get_summary_statistics(latest_construction, start_year=2020)

        # Check required keys
        required_keys = [
            "period",
            "all_work_mean",
            "all_work_min",
            "all_work_max",
            "new_work_mean",
            "repair_maintenance_mean",
            "quarters_count",
        ]
        assert all(key in stats for key in required_keys)

        # Check values are reasonable
        assert stats["all_work_mean"] > 0
        assert stats["all_work_min"] < stats["all_work_mean"] < stats["all_work_max"]
        assert stats["quarters_count"] > 0
        assert "2020" in stats["period"]

    def test_summary_statistics_date_filtering(self, latest_construction):
        """Test that summary statistics correctly filter by date range."""
        stats_2020_2024 = construction_output.get_summary_statistics(
            latest_construction, start_year=2020, end_year=2024
        )
        stats_all = construction_output.get_summary_statistics(latest_construction)

        # Filtered stats should have fewer quarters
        assert stats_2020_2024["quarters_count"] < stats_all["quarters_count"]

        # Period should reflect the filtering
        assert "2020" in stats_2020_2024["period"]
        assert "2024" in stats_2020_2024["period"]


class TestConstructionTrends:
    """Test expected trends in construction output data."""

    @pytest.fixture(scope="class")
    def latest_construction(self):
        """Fixture for Construction Output data."""
        return construction_output.get_latest_construction_output(force_refresh=False)

    def test_volatility_visible(self, latest_construction):
        """Test that construction sector shows expected volatility."""
        df_growth = construction_output.calculate_growth_rates(latest_construction)

        # Construction sector is known for volatility
        # Standard deviation of growth rates should be significant
        std_growth = df_growth["all_work_yoy_growth"].dropna().std()
        assert std_growth > 3  # At least 3% standard deviation

    def test_recent_data_available(self, latest_construction):
        """Test that most recent quarter is recent."""
        latest_date = latest_construction["date"].max()
        latest_year = latest_construction["year"].max()

        # Should have data from 2024 or later
        assert latest_year >= 2024

        # Latest quarter should be within last year
        from datetime import datetime

        assert (datetime.now() - latest_date).days < 450

    def test_base_year_transition(self, latest_construction):
        """Test that base year (2022=100) is reflected in data."""
        df_2022 = latest_construction[latest_construction["year"] == 2022]

        # All quarters in 2022 should have values reasonably close to 100
        for _, row in df_2022.iterrows():
            assert 80 < row["all_work_index"] < 120  # Allow some variation around 100
