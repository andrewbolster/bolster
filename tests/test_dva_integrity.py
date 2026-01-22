"""Data integrity tests for DVA (Driver & Vehicle Agency) statistics module.

These tests validate the structure and consistency of DVA test statistics data.
They use real data from the DVA monthly publications to ensure parsing is correct.
"""

from datetime import datetime

import pytest

from bolster.data_sources import dva


@pytest.fixture(scope="module")
def vehicle_tests_data():
    """Fetch vehicle tests data once for all tests."""
    return dva.get_latest_vehicle_tests(force_refresh=False)


@pytest.fixture(scope="module")
def driver_tests_data():
    """Fetch driver tests data once for all tests."""
    return dva.get_latest_driver_tests(force_refresh=False)


@pytest.fixture(scope="module")
def theory_tests_data():
    """Fetch theory tests data once for all tests."""
    return dva.get_latest_theory_tests(force_refresh=False)


class TestVehicleTestsIntegrity:
    """Test suite for validating vehicle test data structure and quality."""

    @pytest.mark.network
    def test_vehicle_tests_not_empty(self, vehicle_tests_data):
        """Verify that vehicle tests data is not empty."""
        assert len(vehicle_tests_data) > 0, "Vehicle tests data should not be empty"

    @pytest.mark.network
    def test_vehicle_tests_has_required_columns(self, vehicle_tests_data):
        """Verify that all required columns are present."""
        required_cols = ["date", "year", "month", "tests_conducted"]
        for col in required_cols:
            assert col in vehicle_tests_data.columns, f"Missing required column: {col}"

    @pytest.mark.network
    def test_vehicle_tests_positive_values(self, vehicle_tests_data):
        """Verify that test counts are positive."""
        assert (vehicle_tests_data["tests_conducted"] > 0).all(), "All test counts should be positive"

    @pytest.mark.network
    def test_vehicle_tests_reasonable_range(self, vehicle_tests_data):
        """Verify that test counts are within reasonable range."""
        # Vehicle tests typically range from 40,000 to 100,000 per month
        # Note: COVID lockdown (April-June 2020) caused extremely low values
        # Exclude 2020 from minimum check
        non_covid = vehicle_tests_data[vehicle_tests_data["year"] != 2020]
        assert non_covid["tests_conducted"].min() > 10000, "Minimum tests too low (excluding COVID period)"
        assert vehicle_tests_data["tests_conducted"].max() < 200000, "Maximum tests too high"

    @pytest.mark.network
    def test_vehicle_tests_chronological_order(self, vehicle_tests_data):
        """Verify that data is in chronological order."""
        dates = vehicle_tests_data["date"].tolist()
        assert dates == sorted(dates), "Data should be in chronological order"

    @pytest.mark.network
    def test_vehicle_tests_year_range(self, vehicle_tests_data):
        """Verify that data covers expected year range (2014-present)."""
        assert vehicle_tests_data["year"].min() == 2014, "Data should start from 2014"
        assert vehicle_tests_data["year"].max() >= datetime.now().year - 1, "Data should be recent"


class TestDriverTestsIntegrity:
    """Test suite for validating driver test data structure and quality."""

    @pytest.mark.network
    def test_driver_tests_not_empty(self, driver_tests_data):
        """Verify that driver tests data is not empty."""
        assert len(driver_tests_data) > 0, "Driver tests data should not be empty"

    @pytest.mark.network
    def test_driver_tests_has_required_columns(self, driver_tests_data):
        """Verify that all required columns are present."""
        required_cols = ["date", "year", "month", "tests_conducted"]
        for col in required_cols:
            assert col in driver_tests_data.columns, f"Missing required column: {col}"

    @pytest.mark.network
    def test_driver_tests_positive_values(self, driver_tests_data):
        """Verify that test counts are positive."""
        assert (driver_tests_data["tests_conducted"] > 0).all(), "All test counts should be positive"

    @pytest.mark.network
    def test_driver_tests_reasonable_range(self, driver_tests_data):
        """Verify that test counts are within reasonable range."""
        # Driver tests typically range from 2,000 to 7,000 per month
        # Note: COVID lockdowns (2020-2021) caused extremely low values
        non_covid = driver_tests_data[~driver_tests_data["year"].isin([2020, 2021])]
        assert non_covid["tests_conducted"].min() > 500, "Minimum tests too low (excluding COVID period)"
        assert driver_tests_data["tests_conducted"].max() < 20000, "Maximum tests too high"


class TestTheoryTestsIntegrity:
    """Test suite for validating theory test data structure and quality."""

    @pytest.mark.network
    def test_theory_tests_not_empty(self, theory_tests_data):
        """Verify that theory tests data is not empty."""
        assert len(theory_tests_data) > 0, "Theory tests data should not be empty"

    @pytest.mark.network
    def test_theory_tests_has_required_columns(self, theory_tests_data):
        """Verify that all required columns are present."""
        required_cols = ["date", "year", "month", "tests_conducted"]
        for col in required_cols:
            assert col in theory_tests_data.columns, f"Missing required column: {col}"

    @pytest.mark.network
    def test_theory_tests_positive_values(self, theory_tests_data):
        """Verify that test counts are positive."""
        assert (theory_tests_data["tests_conducted"] > 0).all(), "All test counts should be positive"


class TestHelperFunctions:
    """Test suite for helper functions."""

    @pytest.mark.network
    def test_get_tests_by_year(self, vehicle_tests_data):
        """Verify get_tests_by_year returns correct data."""
        df_2024 = dva.get_tests_by_year(vehicle_tests_data, 2024)
        assert len(df_2024) == 12, "Should have 12 months for 2024"
        assert (df_2024["year"] == 2024).all(), "All rows should be from 2024"

    @pytest.mark.network
    def test_get_tests_by_month(self, vehicle_tests_data):
        """Verify get_tests_by_month returns correct data."""
        df_jan_2024 = dva.get_tests_by_month(vehicle_tests_data, "January", 2024)
        assert len(df_jan_2024) == 1, "Should have exactly 1 row"
        assert df_jan_2024.iloc[0]["month"] == "January", "Month should be January"
        assert df_jan_2024.iloc[0]["year"] == 2024, "Year should be 2024"

    @pytest.mark.network
    def test_calculate_growth_rates(self, vehicle_tests_data):
        """Verify growth rate calculation."""
        df_growth = dva.calculate_growth_rates(vehicle_tests_data)
        assert "yoy_growth" in df_growth.columns, "Should have yoy_growth column"
        # First 12 months should have NaN growth (no prior year data)
        assert df_growth["yoy_growth"].iloc[:12].isna().all(), "First year should have NaN growth"

    @pytest.mark.network
    def test_get_summary_statistics(self, vehicle_tests_data):
        """Verify summary statistics calculation."""
        stats = dva.get_summary_statistics(vehicle_tests_data, start_year=2024, end_year=2024)
        assert "total_tests" in stats, "Should have total_tests"
        assert "monthly_mean" in stats, "Should have monthly_mean"
        assert stats["months_count"] == 12, "Should have 12 months for 2024"
        assert stats["total_tests"] > 0, "Total tests should be positive"


class TestGetLatestAllTests:
    """Test suite for get_latest_all_tests function."""

    @pytest.mark.network
    def test_returns_all_test_types(self):
        """Verify that all test types are returned."""
        data = dva.get_latest_all_tests(force_refresh=False)
        assert "vehicle" in data, "Should have vehicle tests"
        assert "driver" in data, "Should have driver tests"
        assert "theory" in data, "Should have theory tests"

    @pytest.mark.network
    def test_all_dataframes_not_empty(self):
        """Verify that all returned DataFrames have data."""
        data = dva.get_latest_all_tests(force_refresh=False)
        for test_type, df in data.items():
            assert len(df) > 0, f"{test_type} tests should not be empty"
