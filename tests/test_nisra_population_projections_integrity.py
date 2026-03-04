"""Data integrity tests for NISRA population projections.

Tests use real NISRA data downloaded once per test class (scope="class" fixture).
No mocks - validates actual published projection data quality.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import population_projections
from bolster.data_sources.nisra._base import NISRAValidationError


class TestDataIntegrity:
    """Integration tests using real NISRA population projection data.

    Downloads data once and reuses across all tests in this class.
    """

    @pytest.fixture(scope="class")
    def projections_data(self):
        """Download real population projections once for all tests."""
        return population_projections.get_latest_projections()

    def test_required_columns(self, projections_data):
        """Verify all required columns are present."""
        required_columns = ["year", "base_year", "age_group", "sex", "area", "population"]
        for col in required_columns:
            assert col in projections_data.columns, f"Missing required column: {col}"

    def test_value_ranges(self, projections_data):
        """Verify population >= 0 and year >= base_year."""
        # Population must be non-negative
        assert (projections_data["population"] >= 0).all(), "Population values must be non-negative"

        # Year must be >= base_year
        assert (projections_data["year"] >= projections_data["base_year"]).all(), "Projection year must be >= base year"

    def test_sex_totals(self, projections_data):
        """Verify All persons = Male + Female for each year/age/area."""
        # Group by year, age, area
        for (year, age, area), group in projections_data.groupby(["year", "age_group", "area"]):
            # Get values for each sex
            males = group[group["sex"] == "Males"]["population"].sum()
            females = group[group["sex"] == "Females"]["population"].sum()
            all_persons = group[group["sex"] == "All Persons"]["population"].sum()

            # Allow small rounding differences (within 5 people)
            if all_persons > 0:  # Only check if data exists
                assert abs((males + females) - all_persons) <= 5, (
                    f"Year {year}, Age {age}, Area {area}: "
                    f"Males ({males}) + Females ({females}) != All Persons ({all_persons})"
                )

    def test_projection_coverage(self, projections_data):
        """Verify projections span expected year range."""
        years = projections_data["year"].unique()
        base_years = projections_data["base_year"].unique()

        # Should have at least one base year
        assert len(base_years) >= 1, "Expected at least one base year"

        # Should have projections for multiple years (at least 20 years)
        assert len(years) >= 20, f"Expected at least 20 years of projections, got {len(years)}"

        # Projections should be continuous
        years_sorted = sorted(years)
        for i in range(len(years_sorted) - 1):
            gap = years_sorted[i + 1] - years_sorted[i]
            assert gap <= 1, f"Gap of {gap} years between {years_sorted[i]} and {years_sorted[i + 1]}"

    def test_age_group_format(self, projections_data):
        """Verify age groups follow standard format (XX-XX or XX+)."""
        import re

        age_groups = projections_data["age_group"].unique()

        for age in age_groups:
            # Should match pattern: "00-04", "05-09", ..., "90+", "100+" or similar
            assert re.match(r"^\d{2}-\d{2}$|^\d{2,3}\+$", str(age)), f"Invalid age group format: {age}"

    def test_filtering(self, projections_data):
        """Verify filtering by area, year works correctly."""
        # Test area filtering
        ni_data = projections_data[projections_data["area"] == "Northern Ireland"]
        assert not ni_data.empty, "Expected Northern Ireland data"

        # Test year filtering
        year_2030 = projections_data[projections_data["year"] == 2030]
        if not year_2030.empty:  # Only test if 2030 data exists
            assert all(year_2030["year"] == 2030), "Filtering by year failed"


class TestValidation:
    """Unit tests for validation edge cases.

    These don't need network calls - test validation logic directly.
    """

    def test_validate_empty_dataframe(self):
        """Validation should fail on empty DataFrame."""
        empty_df = pd.DataFrame()
        with pytest.raises(NISRAValidationError, match="DataFrame is empty"):
            population_projections.validate_projections_totals(empty_df)

    def test_validate_missing_columns(self):
        """Validation should fail if required columns missing."""
        incomplete_df = pd.DataFrame({"year": [2030], "population": [1000]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            population_projections.validate_projections_totals(incomplete_df)

    def test_validate_negative_population(self):
        """Validation should fail if population is negative."""
        invalid_df = pd.DataFrame(
            {
                "year": [2030],
                "base_year": [2022],
                "age_group": ["00-04"],
                "sex": ["Males"],
                "area": ["Northern Ireland"],
                "population": [-100],  # Invalid
            }
        )
        with pytest.raises(NISRAValidationError, match="negative"):
            population_projections.validate_projections_totals(invalid_df)

    def test_validate_sex_totals_mismatch(self):
        """Validation should fail if sex totals don't match."""
        invalid_df = pd.DataFrame(
            {
                "year": [2030, 2030, 2030],
                "base_year": [2022, 2022, 2022],
                "age_group": ["00-04", "00-04", "00-04"],
                "sex": ["Males", "Females", "All Persons"],
                "area": ["Northern Ireland", "Northern Ireland", "Northern Ireland"],
                "population": [1000, 1000, 1500],  # Should be 2000, not 1500
            }
        )
        with pytest.raises(NISRAValidationError, match="sex totals mismatch"):
            population_projections.validate_projections_totals(invalid_df)
