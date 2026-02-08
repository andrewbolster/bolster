"""Data integrity tests for NISRA population statistics.

These tests validate that the data is internally consistent across different
dimensions and time periods. They use real data from NISRA (not mocked) and
should work with any dataset (latest or historical).

Key validations:
- Total population should equal sum of male + female population
- No negative values
- Temporal continuity (no missing years in time series)
- Required columns, age bands, sex categories present
"""

import pytest

from bolster.data_sources.nisra import population


class TestPopulationDataIntegrity:
    """Test suite for validating internal consistency of population data."""

    @pytest.fixture(scope="class")
    def latest_population_ni(self):
        """Fetch latest Northern Ireland population data once for the test class."""
        return population.get_latest_population(area="Northern Ireland", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_population_all(self):
        """Fetch all geographic areas for testing."""
        return population.get_latest_population(area="all", force_refresh=False)

    def test_sex_sum_to_total(self, latest_population_ni):
        """Test that male + female population equals all persons for each year/age group."""
        # Use constitutional validation function instead of manual checks
        assert population.validate_population_totals(latest_population_ni)

    def test_no_negative_values(self, latest_population_all):
        """Test that there are no negative population counts."""
        assert (latest_population_all["population"] >= 0).all(), "Data contains negative population counts"

    def test_temporal_continuity(self, latest_population_ni):
        """Test that there are no missing years in the time series."""
        years = sorted(latest_population_ni["year"].unique())

        # Check for NI overall (should have 1971-present)
        min_year = min(years)
        max_year = max(years)

        expected_years = set(range(min_year, max_year + 1))
        actual_years = set(years)

        missing_years = expected_years - actual_years

        assert len(missing_years) == 0, f"Missing years in time series: {sorted(missing_years)}"

    def test_required_columns_present(self, latest_population_all):
        """Test that all required columns are present."""
        required_columns = {
            "area",
            "area_code",
            "area_name",
            "year",
            "sex",
            "age_5",
            "age_band",
            "age_broad",
            "population",
        }

        assert set(latest_population_all.columns) == required_columns, (
            f"Incorrect columns: {set(latest_population_all.columns)}"
        )

    def test_sex_categories_complete(self, latest_population_all):
        """Test that all expected sex categories are present."""
        expected_sexes = {"All persons", "Males", "Females"}

        actual_sexes = set(latest_population_all["sex"].unique())
        assert actual_sexes == expected_sexes, f"Expected sexes {expected_sexes}, got {actual_sexes}"

    def test_age_bands_complete(self, latest_population_ni):
        """Test that all expected 5-year age bands are present."""
        expected_age_bands = {
            "00-04",
            "05-09",
            "10-14",
            "15-19",
            "20-24",
            "25-29",
            "30-34",
            "35-39",
            "40-44",
            "45-49",
            "50-54",
            "55-59",
            "60-64",
            "65-69",
            "70-74",
            "75-79",
            "80-84",
            "85-89",
            "90+",
        }

        actual_age_bands = set(latest_population_ni["age_5"].unique())
        assert actual_age_bands == expected_age_bands, (
            f"Age bands mismatch. Missing: {expected_age_bands - actual_age_bands}, "
            f"Extra: {actual_age_bands - expected_age_bands}"
        )

    def test_area_filter_works(self, latest_population_all):
        """Test that area filtering returns correct data."""
        areas = latest_population_all["area"].unique()

        # Should have 4 area types
        assert len(areas) == 4, f"Expected 4 area types, got {len(areas)}"

        # Each area should have expected naming pattern
        for area in areas:
            assert area.startswith(("1.", "2.", "3.", "4.")), f"Unexpected area format: {area}"

    def test_get_population_by_year_function(self, latest_population_ni):
        """Test the get_population_by_year helper function."""
        # Get data for a specific year
        latest_year = latest_population_ni["year"].max()
        year_data = population.get_population_by_year(latest_population_ni, latest_year)

        # Should only have data for that year
        assert year_data["year"].nunique() == 1
        assert year_data["year"].iloc[0] == latest_year

        # Should have all sex categories by default
        assert set(year_data["sex"].unique()) == {"All persons"}

        # Test with specific sex
        male_data = population.get_population_by_year(latest_population_ni, latest_year, sex="Males")
        assert male_data["sex"].nunique() == 1
        assert male_data["sex"].iloc[0] == "Males"

    def test_population_pyramid_function(self, latest_population_ni):
        """Test the get_population_pyramid_data helper function."""
        latest_year = latest_population_ni["year"].max()
        pyramid = population.get_population_pyramid_data(latest_population_ni, latest_year)

        # Should have 19 age bands
        assert len(pyramid) == 19

        # Should have males, females, age_5 columns
        assert set(pyramid.columns) == {"age_5", "males", "females"}

        # Males should be positive, females negative (for pyramid plotting)
        assert (pyramid["males"] > 0).all()
        assert (pyramid["females"] < 0).all()

        # Total should match NI population
        total_males = pyramid["males"].sum()
        total_females = abs(pyramid["females"].sum())

        expected_total = latest_population_ni[
            (latest_population_ni["year"] == latest_year) & (latest_population_ni["sex"] == "All persons")
        ]["population"].sum()

        assert total_males + total_females == expected_total

    def test_validate_function_works(self, latest_population_ni):
        """Test that the validate_population_totals function works correctly."""
        # Should pass with valid data
        assert population.validate_population_totals(latest_population_ni)

        # Create invalid data
        invalid_data = latest_population_ni.copy()
        invalid_data.loc[invalid_data["sex"] == "Males", "population"] = 0

        # Should fail
        with pytest.raises(population.NISRAValidationError):
            population.validate_population_totals(invalid_data)

    def test_historical_data_coverage(self, latest_population_ni):
        """Test that Northern Ireland has historical data back to 1971."""
        min_year = latest_population_ni["year"].min()
        max_year = latest_population_ni["year"].max()

        # NI overall should have data from 1971
        assert min_year <= 1971, f"Expected data from 1971, earliest is {min_year}"

        # Should have recent data (within last 2 years)
        import datetime

        current_year = datetime.datetime.now().year
        assert max_year >= current_year - 2, f"Latest data ({max_year}) is more than 2 years old"
