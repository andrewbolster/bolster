"""Integrity tests for NISRA Annual Survey of Hours and Earnings (ASHE) Module.

These tests validate real data quality, structure, and consistency for the
ASHE earnings statistics module.

Test coverage includes:
- Data structure and types
- Data completeness and ranges
- Timeseries continuity
- Earnings value relationships
- Growth rate calculations
- Helper function behavior
- Geographic data validation
- Sector data validation
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import ashe


class TestASHETimeseriesIntegrity:
    """Integrity tests for ASHE timeseries data."""

    @pytest.fixture(scope="class")
    def latest_weekly(self):
        """Fixture to load latest weekly earnings data once for all tests."""
        return ashe.get_latest_ashe_timeseries(metric="weekly", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_hourly(self):
        """Fixture to load latest hourly earnings data once for all tests."""
        return ashe.get_latest_ashe_timeseries(metric="hourly", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_annual(self):
        """Fixture to load latest annual earnings data once for all tests."""
        return ashe.get_latest_ashe_timeseries(metric="annual", force_refresh=False)

    def test_weekly_data_structure(self, latest_weekly):
        """Test that weekly earnings data has correct structure."""
        assert isinstance(latest_weekly, pd.DataFrame)
        assert len(latest_weekly) > 0

        # Check required columns
        required_cols = ["year", "work_pattern", "median_weekly_earnings"]
        assert all(col in latest_weekly.columns for col in required_cols)

    def test_weekly_data_types(self, latest_weekly):
        """Test that weekly earnings columns have correct data types."""
        assert pd.api.types.is_integer_dtype(latest_weekly["year"])
        assert latest_weekly["work_pattern"].dtype == "object"
        assert pd.api.types.is_float_dtype(latest_weekly["median_weekly_earnings"])

    def test_work_pattern_values(self, latest_weekly):
        """Test that work pattern values are valid."""
        valid_patterns = {"Full-time", "Part-time", "All"}
        assert set(latest_weekly["work_pattern"].unique()) == valid_patterns

    def test_year_range(self, latest_weekly):
        """Test that year range is reasonable (1997-present)."""
        assert latest_weekly["year"].min() == 1997
        assert latest_weekly["year"].max() >= 2025

    def test_weekly_earnings_positive(self, latest_weekly):
        """Test that earnings values are positive."""
        assert (latest_weekly["median_weekly_earnings"] > 0).all()

    def test_no_missing_values(self, latest_weekly):
        """Test that there are no missing values in key columns."""
        assert not latest_weekly["year"].isna().any()
        assert not latest_weekly["work_pattern"].isna().any()
        assert not latest_weekly["median_weekly_earnings"].isna().any()

    def test_chronological_order(self, latest_weekly):
        """Test that data includes all years in sequence."""
        all_pattern = latest_weekly[latest_weekly["work_pattern"] == "All"]
        years = sorted(all_pattern["year"].unique())
        # Check for consecutive years
        for i in range(len(years) - 1):
            assert years[i + 1] == years[i] + 1

    def test_three_records_per_year(self, latest_weekly):
        """Test that each year has exactly 3 records (Full-time, Part-time, All)."""
        records_per_year = latest_weekly.groupby("year").size()
        assert (records_per_year == 3).all()

    def test_hourly_data_structure(self, latest_hourly):
        """Test that hourly earnings data has correct structure."""
        assert isinstance(latest_hourly, pd.DataFrame)
        required_cols = ["year", "work_pattern", "median_hourly_earnings"]
        assert all(col in latest_hourly.columns for col in required_cols)

    def test_annual_data_structure(self, latest_annual):
        """Test that annual earnings data has correct structure."""
        assert isinstance(latest_annual, pd.DataFrame)
        required_cols = ["year", "work_pattern", "median_annual_earnings"]
        assert all(col in latest_annual.columns for col in required_cols)

    def test_annual_data_starts_1999(self, latest_annual):
        """Test that annual earnings data starts from 1999."""
        assert latest_annual["year"].min() == 1999


class TestASHEGeographyIntegrity:
    """Integrity tests for ASHE geographic data."""

    @pytest.fixture(scope="class")
    def latest_workplace(self):
        """Fixture for workplace-based geographic earnings."""
        return ashe.get_latest_ashe_geography(basis="workplace", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_residence(self):
        """Fixture for residence-based geographic earnings."""
        return ashe.get_latest_ashe_geography(basis="residence", force_refresh=False)

    def test_workplace_data_structure(self, latest_workplace):
        """Test that workplace geography data has correct structure."""
        assert isinstance(latest_workplace, pd.DataFrame)
        required_cols = ["year", "lgd", "basis", "median_weekly_earnings"]
        assert all(col in latest_workplace.columns for col in required_cols)

    def test_workplace_has_11_lgds(self, latest_workplace):
        """Test that data includes all 11 LGDs."""
        assert len(latest_workplace) == 11

    def test_lgd_names_valid(self, latest_workplace):
        """Test that LGD names are valid."""
        expected_lgds = {
            "Antrim and Newtownabbey",
            "Ards and North Down",
            "Armagh City, Banbridge and Craigavon",
            "Belfast",
            "Causeway Coast and Glens",
            "Derry City and Strabane",
            "Fermanagh and Omagh",
            "Lisburn and Castlereagh",
            "Mid and East Antrim",
            "Mid Ulster",
            "Newry, Mourne and Down",
        }
        assert set(latest_workplace["lgd"].unique()) == expected_lgds

    def test_basis_value(self, latest_workplace):
        """Test that basis column has correct value."""
        assert (latest_workplace["basis"] == "workplace").all()

    def test_residence_data_structure(self, latest_residence):
        """Test that residence geography data has correct structure."""
        assert isinstance(latest_residence, pd.DataFrame)
        assert len(latest_residence) == 11

    def test_residence_basis_value(self, latest_residence):
        """Test that residence data has correct basis."""
        assert (latest_residence["basis"] == "residence").all()


class TestASHESectorIntegrity:
    """Integrity tests for ASHE sector data."""

    @pytest.fixture(scope="class")
    def latest_sector(self):
        """Fixture for sector earnings data."""
        return ashe.get_latest_ashe_sector(force_refresh=False)

    def test_sector_data_structure(self, latest_sector):
        """Test that sector data has correct structure."""
        assert isinstance(latest_sector, pd.DataFrame)
        required_cols = ["year", "location", "sector", "median_weekly_earnings"]
        assert all(col in latest_sector.columns for col in required_cols)

    def test_sector_data_starts_2005(self, latest_sector):
        """Test that sector data starts from 2005."""
        assert latest_sector["year"].min() == 2005

    def test_sector_values_valid(self, latest_sector):
        """Test that sector values are valid."""
        valid_sectors = {"Public", "Private"}
        assert set(latest_sector["sector"].unique()) == valid_sectors

    def test_location_values_valid(self, latest_sector):
        """Test that location values are valid."""
        valid_locations = {"Northern Ireland", "United Kingdom"}
        assert set(latest_sector["location"].unique()) == valid_locations

    def test_four_records_per_year(self, latest_sector):
        """Test that each year has 4 records (NI Public/Private, UK Public/Private)."""
        records_per_year = latest_sector.groupby("year").size()
        assert (records_per_year == 4).all()

    def test_sector_has_both_locations(self, latest_sector):
        """Test that sector data has entries for both NI and UK."""
        latest_year = latest_sector["year"].max()
        year_data = latest_sector[latest_sector["year"] == latest_year]
        assert len(year_data[year_data["location"] == "Northern Ireland"]) == 2
        assert len(year_data[year_data["location"] == "United Kingdom"]) == 2


class TestHelperFunctionsIntegrity:
    """Integrity tests for helper functions."""

    @pytest.fixture(scope="class")
    def latest_weekly(self):
        """Fixture for weekly earnings data."""
        return ashe.get_latest_ashe_timeseries(metric="weekly", force_refresh=False)

    def test_get_earnings_by_year(self, latest_weekly):
        """Test filtering by year."""
        df_2025 = ashe.get_earnings_by_year(latest_weekly, 2025)

        assert len(df_2025) == 3  # Should have 3 work patterns
        assert (df_2025["year"] == 2025).all()

    def test_calculate_growth_rates(self, latest_weekly):
        """Test growth rate calculation."""
        df_growth = ashe.calculate_growth_rates(latest_weekly)

        # Should have growth rate column
        assert "earnings_yoy_growth" in df_growth.columns

        # First record for each work pattern should have NaN (no prior year)
        for pattern in ["Full-time", "Part-time", "All"]:
            first_record = df_growth[df_growth["work_pattern"] == pattern].iloc[0]
            assert pd.isna(first_record["earnings_yoy_growth"])

        # Later records should have values
        all_pattern = df_growth[df_growth["work_pattern"] == "All"]
        assert not all_pattern["earnings_yoy_growth"].iloc[1:].isna().all()

    def test_growth_rates_multiple_patterns(self, latest_weekly):
        """Test that growth rates are calculated separately for each work pattern."""
        df_growth = ashe.calculate_growth_rates(latest_weekly)

        # Each work pattern should have its own growth trajectory
        for pattern in ["Full-time", "Part-time", "All"]:
            pattern_data = df_growth[df_growth["work_pattern"] == pattern]
            growth_values = pattern_data["earnings_yoy_growth"].dropna()
            # Should have variation in growth rates
            assert growth_values.std() > 0.5


class TestASHEDataQuality:
    """Test data quality checks."""

    @pytest.fixture(scope="class")
    def latest_weekly(self):
        """Fixture for weekly earnings data."""
        return ashe.get_latest_ashe_timeseries(metric="weekly", force_refresh=False)

    def test_recent_data_available(self, latest_weekly):
        """Test that most recent year is recent."""
        latest_year = latest_weekly["year"].max()
        assert latest_year >= 2025
