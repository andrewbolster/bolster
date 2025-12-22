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

    def test_weekly_earnings_reasonable(self, latest_weekly):
        """Test that weekly earnings values are in reasonable range."""
        # Weekly earnings should be roughly £50-£1500
        assert latest_weekly["median_weekly_earnings"].min() > 50
        assert latest_weekly["median_weekly_earnings"].max() < 1500

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

    def test_fulltime_higher_than_parttime(self, latest_weekly):
        """Test that full-time earnings are generally higher than part-time."""
        for year in latest_weekly["year"].unique():
            year_data = latest_weekly[latest_weekly["year"] == year]
            ft_earnings = year_data[year_data["work_pattern"] == "Full-time"]["median_weekly_earnings"].values[0]
            pt_earnings = year_data[year_data["work_pattern"] == "Part-time"]["median_weekly_earnings"].values[0]
            assert ft_earnings > pt_earnings

    def test_all_between_fulltime_parttime(self, latest_weekly):
        """Test that 'All' earnings are between full-time and part-time."""
        for year in latest_weekly["year"].unique():
            year_data = latest_weekly[latest_weekly["year"] == year]
            ft_earnings = year_data[year_data["work_pattern"] == "Full-time"]["median_weekly_earnings"].values[0]
            pt_earnings = year_data[year_data["work_pattern"] == "Part-time"]["median_weekly_earnings"].values[0]
            all_earnings = year_data[year_data["work_pattern"] == "All"]["median_weekly_earnings"].values[0]
            # 'All' should be between part-time and full-time
            assert pt_earnings < all_earnings < ft_earnings

    def test_earnings_growth_over_time(self, latest_weekly):
        """Test that earnings generally increase over time."""
        all_pattern = latest_weekly[latest_weekly["work_pattern"] == "All"].sort_values("year")
        # Latest year earnings should be significantly higher than 1997
        first_year = all_pattern.iloc[0]["median_weekly_earnings"]
        latest_year = all_pattern.iloc[-1]["median_weekly_earnings"]
        assert latest_year > first_year * 2  # At least doubled over the period

    def test_latest_year_earnings(self, latest_weekly):
        """Test that latest year has reasonable earnings values."""
        latest_year = latest_weekly["year"].max()
        latest_data = latest_weekly[latest_weekly["year"] == latest_year]

        # Full-time should be roughly £600-£800 as of 2025
        ft_earnings = latest_data[latest_data["work_pattern"] == "Full-time"]["median_weekly_earnings"].values[0]
        assert 600 < ft_earnings < 900

        # Part-time should be roughly £200-£350 as of 2025
        pt_earnings = latest_data[latest_data["work_pattern"] == "Part-time"]["median_weekly_earnings"].values[0]
        assert 200 < pt_earnings < 400

    def test_hourly_data_structure(self, latest_hourly):
        """Test that hourly earnings data has correct structure."""
        assert isinstance(latest_hourly, pd.DataFrame)
        required_cols = ["year", "work_pattern", "median_hourly_earnings"]
        assert all(col in latest_hourly.columns for col in required_cols)

    def test_hourly_earnings_reasonable(self, latest_hourly):
        """Test that hourly earnings values are in reasonable range."""
        # Hourly earnings should be roughly £4-£30 (lower bound accounts for 1997 data)
        assert latest_hourly["median_hourly_earnings"].min() > 4
        assert latest_hourly["median_hourly_earnings"].max() < 35

    def test_annual_data_structure(self, latest_annual):
        """Test that annual earnings data has correct structure."""
        assert isinstance(latest_annual, pd.DataFrame)
        required_cols = ["year", "work_pattern", "median_annual_earnings"]
        assert all(col in latest_annual.columns for col in required_cols)

    def test_annual_data_starts_1999(self, latest_annual):
        """Test that annual earnings data starts from 1999."""
        assert latest_annual["year"].min() == 1999

    def test_annual_earnings_reasonable(self, latest_annual):
        """Test that annual earnings values are in reasonable range."""
        # Annual earnings should be roughly £5k-£60k
        assert latest_annual["median_annual_earnings"].min() > 5000
        assert latest_annual["median_annual_earnings"].max() < 65000

    def test_annual_weekly_consistency(self, latest_weekly, latest_annual):
        """Test consistency between weekly and annual earnings."""
        # For recent years, annual should be roughly weekly * 52
        recent_year = 2025
        weekly_all = latest_weekly[(latest_weekly["year"] == recent_year) & (latest_weekly["work_pattern"] == "All")][
            "median_weekly_earnings"
        ].values[0]
        annual_all = latest_annual[(latest_annual["year"] == recent_year) & (latest_annual["work_pattern"] == "All")][
            "median_annual_earnings"
        ].values[0]

        # Annual should be roughly weekly * 52 (allowing for some variation)
        expected_annual = weekly_all * 52
        assert 0.9 * expected_annual < annual_all < 1.1 * expected_annual


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

    def test_earnings_variation_by_lgd(self, latest_workplace):
        """Test that earnings vary across LGDs."""
        earnings = latest_workplace["median_weekly_earnings"]
        # Should have variation across LGDs
        assert earnings.std() > 20  # At least £20 standard deviation

    def test_belfast_typically_highest(self, latest_workplace):
        """Test that Belfast typically has among the highest earnings (workplace)."""
        belfast = latest_workplace[latest_workplace["lgd"] == "Belfast"]["median_weekly_earnings"].values[0]
        median_earnings = latest_workplace["median_weekly_earnings"].median()
        # Belfast should be above median
        assert belfast > median_earnings

    def test_residence_data_structure(self, latest_residence):
        """Test that residence geography data has correct structure."""
        assert isinstance(latest_residence, pd.DataFrame)
        assert len(latest_residence) == 11

    def test_residence_basis_value(self, latest_residence):
        """Test that residence data has correct basis."""
        assert (latest_residence["basis"] == "residence").all()

    def test_workplace_residence_differences(self, latest_workplace, latest_residence):
        """Test that workplace and residence earnings differ (commuting effect)."""
        # Merge on LGD
        merged = latest_workplace.merge(latest_residence, on="lgd", suffixes=("_work", "_res"), how="inner")

        # Some LGDs should have different work vs residence earnings
        differences = (merged["median_weekly_earnings_work"] - merged["median_weekly_earnings_res"]).abs()
        # At least some LGDs should have differences > £10
        assert (differences > 10).sum() > 0


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

    def test_public_vs_private_gap(self, latest_sector):
        """Test that public and private sector earnings differ."""
        latest_year = latest_sector["year"].max()
        ni_latest = latest_sector[
            (latest_sector["year"] == latest_year) & (latest_sector["location"] == "Northern Ireland")
        ]

        public = ni_latest[ni_latest["sector"] == "Public"]["median_weekly_earnings"].values[0]
        private = ni_latest[ni_latest["sector"] == "Private"]["median_weekly_earnings"].values[0]

        # Public sector typically pays more in NI
        assert public > private

    def test_uk_ni_comparison(self, latest_sector):
        """Test that UK and NI earnings can be compared."""
        latest_year = latest_sector["year"].max()
        year_data = latest_sector[latest_sector["year"] == latest_year]

        # Should have data for both locations
        assert len(year_data[year_data["location"] == "Northern Ireland"]) == 2
        assert len(year_data[year_data["location"] == "United Kingdom"]) == 2

        # UK private sector typically higher than NI private sector
        uk_private = year_data[(year_data["location"] == "United Kingdom") & (year_data["sector"] == "Private")][
            "median_weekly_earnings"
        ].values[0]
        ni_private = year_data[(year_data["location"] == "Northern Ireland") & (year_data["sector"] == "Private")][
            "median_weekly_earnings"
        ].values[0]

        assert uk_private > ni_private


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

        # Growth rates should be reasonable (typically -10% to +15%)
        valid_growth = df_growth["earnings_yoy_growth"].dropna()
        assert (valid_growth > -20).all()
        assert (valid_growth < 25).all()

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
    """Test data quality and expected trends."""

    @pytest.fixture(scope="class")
    def latest_weekly(self):
        """Fixture for weekly earnings data."""
        return ashe.get_latest_ashe_timeseries(metric="weekly", force_refresh=False)

    def test_earnings_volatility(self, latest_weekly):
        """Test that earnings show expected volatility over time."""
        df_growth = ashe.calculate_growth_rates(latest_weekly)
        all_pattern = df_growth[df_growth["work_pattern"] == "All"]

        # Growth rates should show some variation
        std_growth = all_pattern["earnings_yoy_growth"].dropna().std()
        assert std_growth > 1  # At least 1% standard deviation

    def test_recent_data_available(self, latest_weekly):
        """Test that most recent year is recent."""
        latest_year = latest_weekly["year"].max()

        # Should have data from 2025 or later
        assert latest_year >= 2025

    def test_pre_financial_crisis_growth(self, latest_weekly):
        """Test that earnings grew pre-2008 financial crisis."""
        all_pattern = latest_weekly[latest_weekly["work_pattern"] == "All"]
        pre_crisis = all_pattern[all_pattern["year"] <= 2007].sort_values("year")

        # Earnings should have grown from 1997 to 2007
        earnings_1997 = pre_crisis.iloc[0]["median_weekly_earnings"]
        earnings_2007 = pre_crisis[pre_crisis["year"] == 2007]["median_weekly_earnings"].values[0]
        assert earnings_2007 > earnings_1997

    def test_post_pandemic_recovery(self, latest_weekly):
        """Test that earnings show post-pandemic recovery."""
        all_pattern = latest_weekly[latest_weekly["work_pattern"] == "All"]

        # 2020 (pandemic start) vs 2025 (recovery)
        if 2020 in all_pattern["year"].values and 2025 in all_pattern["year"].values:
            earnings_2020 = all_pattern[all_pattern["year"] == 2020]["median_weekly_earnings"].values[0]
            earnings_2025 = all_pattern[all_pattern["year"] == 2025]["median_weekly_earnings"].values[0]
            assert earnings_2025 > earnings_2020
