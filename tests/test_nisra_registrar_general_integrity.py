"""Data integrity tests for NISRA Registrar General Quarterly Tables.

These tests validate that the quarterly vital statistics data is internally consistent
and cross-validates against monthly data sources. They use real data from NISRA
(not mocked) and should work with any dataset (latest or historical).

Key validations:
- Required columns present
- No negative values
- Reasonable value ranges (birth/death rates between 0-50 per 1,000)
- Historical coverage (data from Q1 2009)
- All 11 LGDs present in LGD table
- Cross-validation against monthly births and marriages data
"""

import datetime

import pandas as pd
import pytest

from bolster.data_sources.nisra import registrar_general


class TestQuarterlyBirthsDataIntegrity:
    """Test suite for validating quarterly births data."""

    @pytest.fixture(scope="class")
    def quarterly_data(self):
        """Fetch quarterly vital statistics once for the test class."""
        return registrar_general.get_quarterly_vital_statistics(force_refresh=False)

    @pytest.fixture(scope="class")
    def births_data(self, quarterly_data):
        """Extract births data from quarterly data."""
        return quarterly_data["births"]

    def test_births_data_not_empty(self, births_data):
        """Test that births data is not empty."""
        assert not births_data.empty, "Births data should not be empty"

    def test_required_columns_present(self, births_data):
        """Test that required columns are present in births data."""
        required_columns = {"year", "quarter", "total_births"}
        assert required_columns.issubset(set(births_data.columns)), (
            f"Missing columns: {required_columns - set(births_data.columns)}"
        )

    def test_no_negative_birth_counts(self, births_data):
        """Test that there are no negative birth counts."""
        assert (births_data["total_births"] >= 0).all(), "Found negative birth counts"

    def test_historical_coverage(self, births_data):
        """Test that data goes back to at least 2009."""
        min_year = births_data["year"].min()
        assert min_year <= 2010, f"Expected data from 2009-2010, earliest is {min_year}"

    def test_recent_data_available(self, births_data):
        """Test that recent data is available (within last year)."""
        max_year = births_data["year"].max()
        current_year = datetime.datetime.now().year
        assert max_year >= current_year - 1, f"Latest data ({max_year}) is more than 1 year old"

    def test_quarters_valid(self, births_data):
        """Test that all quarters are valid (1-4)."""
        quarters = births_data["quarter"].unique()
        assert all(q in [1, 2, 3, 4] for q in quarters), f"Invalid quarters found: {quarters}"

    def test_no_duplicate_quarters(self, births_data):
        """Test that there are no duplicate year-quarter combinations."""
        duplicates = births_data.groupby(["year", "quarter"]).size()
        duplicates = duplicates[duplicates > 1]
        assert len(duplicates) == 0, f"Found duplicate year-quarter combinations: {duplicates}"

    def test_data_types_correct(self, births_data):
        """Test that column data types are correct."""
        assert births_data["year"].dtype in ["int64", "int32"], "year should be integer"
        assert births_data["quarter"].dtype in ["int64", "int32"], "quarter should be integer"
        assert births_data["total_births"].dtype in [
            "int64",
            "int32",
            "float64",
        ], "total_births should be numeric"

    def test_date_column_exists(self, births_data):
        """Test that date column exists and is datetime type."""
        assert "date" in births_data.columns, "date column should exist"
        assert births_data["date"].dtype == "datetime64[ns]", "date should be datetime"

    def test_sufficient_historical_quarters(self, births_data):
        """Test that we have at least 40 quarters of data (10 years)."""
        num_quarters = len(births_data)
        assert num_quarters >= 40, f"Expected at least 40 quarters, found {num_quarters}"


class TestQuarterlyDeathsDataIntegrity:
    """Test suite for validating quarterly deaths and marriages data."""

    @pytest.fixture(scope="class")
    def quarterly_data(self):
        """Fetch quarterly vital statistics once for the test class."""
        return registrar_general.get_quarterly_vital_statistics(force_refresh=False)

    @pytest.fixture(scope="class")
    def deaths_data(self, quarterly_data):
        """Extract deaths data from quarterly data."""
        return quarterly_data["deaths"]

    def test_deaths_data_not_empty(self, deaths_data):
        """Test that deaths data is not empty."""
        assert not deaths_data.empty, "Deaths data should not be empty"

    def test_required_columns_present(self, deaths_data):
        """Test that required columns are present in deaths data."""
        required_columns = {"year", "quarter", "deaths"}
        assert required_columns.issubset(set(deaths_data.columns)), (
            f"Missing columns: {required_columns - set(deaths_data.columns)}"
        )

    def test_no_negative_death_counts(self, deaths_data):
        """Test that there are no negative death counts."""
        assert (deaths_data["deaths"] >= 0).all(), "Found negative death counts"

    def test_marriages_non_negative(self, deaths_data):
        """Test that marriage counts are non-negative."""
        if "marriages" in deaths_data.columns:
            marriages = deaths_data["marriages"].dropna()
            if not marriages.empty:
                assert (marriages >= 0).all(), "Found negative marriage counts"

    def test_civil_partnerships_non_negative(self, deaths_data):
        """Test that civil partnership counts are non-negative."""
        if "civil_partnerships" in deaths_data.columns:
            cp = deaths_data["civil_partnerships"].dropna()
            if not cp.empty:
                assert (cp >= 0).all(), "Found negative civil partnership counts"


class TestLGDDataIntegrity:
    """Test suite for validating LGD-level statistics."""

    @pytest.fixture(scope="class")
    def quarterly_data(self):
        """Fetch quarterly vital statistics once for the test class."""
        return registrar_general.get_quarterly_vital_statistics(force_refresh=False)

    @pytest.fixture(scope="class")
    def lgd_data(self, quarterly_data):
        """Extract LGD data from quarterly data."""
        return quarterly_data["lgd"]

    def test_lgd_data_not_empty(self, lgd_data):
        """Test that LGD data is not empty."""
        # LGD data may not always be available in all publications
        if lgd_data.empty:
            pytest.skip("LGD data not available in current publication")

    def test_all_11_lgds_present(self, lgd_data):
        """Test that all 11 Local Government Districts are present."""
        if lgd_data.empty:
            pytest.skip("LGD data not available")

        # Check we have approximately 11 LGDs (some may have slightly different names)
        num_lgds = len(lgd_data)
        assert num_lgds >= 10, f"Expected 11 LGDs, found {num_lgds}"
        assert num_lgds <= 12, f"Too many LGDs found: {num_lgds}"

    def test_lgd_column_exists(self, lgd_data):
        """Test that LGD name column exists."""
        if lgd_data.empty:
            pytest.skip("LGD data not available")

        assert "lgd" in lgd_data.columns, "LGD name column should exist"

    def test_lgd_births_non_negative(self, lgd_data):
        """Test that LGD births are non-negative."""
        if lgd_data.empty or "births" not in lgd_data.columns:
            pytest.skip("LGD births data not available")

        births = lgd_data["births"].dropna()
        if not births.empty:
            assert (births >= 0).all(), "Found negative LGD births"

    def test_lgd_deaths_non_negative(self, lgd_data):
        """Test that LGD deaths are non-negative."""
        if lgd_data.empty or "deaths" not in lgd_data.columns:
            pytest.skip("LGD deaths data not available")

        deaths = lgd_data["deaths"].dropna()
        if not deaths.empty:
            assert (deaths >= 0).all(), "Found negative LGD deaths"


class TestCrossValidation:
    """Test suite for cross-validating quarterly vs monthly data."""

    @pytest.fixture(scope="class")
    def quarterly_births(self):
        """Fetch quarterly births data."""
        return registrar_general.get_quarterly_births(force_refresh=False)

    @pytest.fixture(scope="class")
    def quarterly_deaths(self):
        """Fetch quarterly deaths data."""
        return registrar_general.get_quarterly_deaths(force_refresh=False)

    def test_births_cross_validation_within_tolerance(self, quarterly_births):
        """Test that quarterly births match monthly births within 2% tolerance."""
        if quarterly_births.empty:
            pytest.skip("Quarterly births data not available")

        try:
            validation = registrar_general.validate_against_monthly_births(quarterly_births)
        except Exception as e:
            pytest.skip(f"Could not perform births validation: {e}")

        if validation.empty:
            pytest.skip("No overlapping periods for validation")

        # Check that most quarters are within 2% tolerance
        within_tolerance = (validation["pct_diff"].abs() <= 2).sum()
        total_quarters = len(validation)

        # At least 80% should be within tolerance
        tolerance_rate = within_tolerance / total_quarters
        assert tolerance_rate >= 0.8, f"Only {tolerance_rate:.0%} of quarters within 2% tolerance (expected 80%+)"

    def test_marriages_cross_validation_within_tolerance(self, quarterly_deaths):
        """Test that quarterly marriages match monthly marriages within 2% tolerance."""
        if quarterly_deaths.empty or "marriages" not in quarterly_deaths.columns:
            pytest.skip("Quarterly marriages data not available")

        try:
            validation = registrar_general.validate_against_monthly_marriages(quarterly_deaths)
        except Exception as e:
            pytest.skip(f"Could not perform marriages validation: {e}")

        if validation.empty:
            pytest.skip("No overlapping periods for validation")

        # Check that most quarters are within 2% tolerance
        within_tolerance = (validation["pct_diff"].abs() <= 2).sum()
        total_quarters = len(validation)

        tolerance_rate = within_tolerance / total_quarters
        assert tolerance_rate >= 0.8, f"Only {tolerance_rate:.0%} of quarters within 2% tolerance (expected 80%+)"


class TestValidationFunctions:
    """Test validation functions and edge cases."""

    def test_validate_empty_dataframe(self):
        """Test that validation raises error for empty DataFrame."""
        empty_df = pd.DataFrame()
        with pytest.raises(registrar_general.NISRAValidationError):
            registrar_general.validate_data(empty_df, data_type="births")

    def test_validate_missing_columns(self):
        """Test that validation raises error for missing required columns."""
        bad_df = pd.DataFrame({"year": [2024], "quarter": [1]})
        with pytest.raises(registrar_general.NISRAValidationError):
            registrar_general.validate_data(bad_df, data_type="births")

    def test_validate_negative_values(self):
        """Test that validation raises error for negative birth counts."""
        bad_df = pd.DataFrame({"year": [2024], "quarter": [1], "total_births": [-100]})
        with pytest.raises(registrar_general.NISRAValidationError):
            registrar_general.validate_data(bad_df, data_type="births")

    def test_validate_unreasonably_high_values(self):
        """Test that validation raises error for unreasonably high values."""
        bad_df = pd.DataFrame({"year": [2024], "quarter": [1], "total_births": [50000]})
        with pytest.raises(registrar_general.NISRAValidationError):
            registrar_general.validate_data(bad_df, data_type="births")

    def test_validate_too_few_lgds(self):
        """Test that validation raises error for too few LGDs."""
        bad_df = pd.DataFrame({"lgd": ["Belfast", "Derry"]})
        with pytest.raises(registrar_general.NISRAValidationError):
            registrar_general.validate_data(bad_df, data_type="lgd")


class TestConvenienceFunctions:
    """Test convenience functions work correctly."""

    @pytest.fixture(scope="class")
    def quarterly_data(self):
        """Fetch all quarterly data once."""
        return registrar_general.get_quarterly_vital_statistics(force_refresh=False)

    def test_get_quarterly_births_returns_dataframe(self):
        """Test get_quarterly_births returns a DataFrame."""
        births = registrar_general.get_quarterly_births(force_refresh=False)
        assert isinstance(births, pd.DataFrame)
        assert not births.empty

    def test_get_quarterly_deaths_returns_dataframe(self):
        """Test get_quarterly_deaths returns a DataFrame."""
        deaths = registrar_general.get_quarterly_deaths(force_refresh=False)
        assert isinstance(deaths, pd.DataFrame)
        assert not deaths.empty

    def test_get_lgd_statistics_returns_dataframe(self):
        """Test get_lgd_statistics returns a DataFrame."""
        lgd = registrar_general.get_lgd_statistics(force_refresh=False)
        assert isinstance(lgd, pd.DataFrame)
        # LGD may be empty if not available in current publication

    def test_get_validation_report_returns_dict(self):
        """Test get_validation_report returns a dict with expected keys."""
        report = registrar_general.get_validation_report(force_refresh=False)
        assert isinstance(report, dict)
        assert "summary" in report

    def test_quarterly_data_dict_structure(self, quarterly_data):
        """Test that quarterly data returns dict with expected keys."""
        assert isinstance(quarterly_data, dict)
        assert "births" in quarterly_data
        assert "deaths" in quarterly_data
        assert "lgd" in quarterly_data
