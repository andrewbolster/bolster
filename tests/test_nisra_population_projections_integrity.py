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


class TestLGDProjectionsIntegrity:
    """Integration tests for LGD sub-area population projections (2022-based)."""

    @pytest.fixture(scope="class")
    def lgd_data(self):
        return population_projections.get_lgd_projections()

    def test_required_columns(self, lgd_data):
        required = {"lgd_name", "lgd_code", "year", "base_year", "sex", "age", "age_group", "population"}
        assert required.issubset(set(lgd_data.columns))

    def test_eleven_lgds(self, lgd_data):
        assert lgd_data["lgd_code"].nunique() == 11

    def test_lgd_codes_format(self, lgd_data):
        codes = lgd_data["lgd_code"].unique()
        assert all(c.startswith("N09") for c in codes)

    def test_known_lgds_present(self, lgd_data):
        expected = {
            "Antrim and Newtownabbey", "Ards and North Down", "Armagh City, Banbridge and Craigavon",
            "Belfast", "Causeway Coast and Glens", "Derry City and Strabane", "Fermanagh and Omagh",
            "Lisburn and Castlereagh", "Mid Ulster", "Mid and East Antrim", "Newry, Mourne and Down",
        }
        assert expected == set(lgd_data["lgd_name"].unique())

    def test_year_range(self, lgd_data):
        assert lgd_data["year"].min() == 2022
        assert lgd_data["year"].max() == 2047

    def test_base_year(self, lgd_data):
        assert (lgd_data["base_year"] == 2022).all()

    def test_no_negative_population(self, lgd_data):
        assert (lgd_data["population"] >= 0).all()

    def test_sex_values(self, lgd_data):
        assert set(lgd_data["sex"].unique()) == {"All persons", "Male", "Female"}

    def test_sex_totals_consistent(self, lgd_data):
        # All persons should equal Male + Female for each LGD/year/age group
        for (lgd, year, age), grp in lgd_data.groupby(["lgd_code", "year", "age_group"]):
            all_p = grp[grp["sex"] == "All persons"]["population"].sum()
            male = grp[grp["sex"] == "Male"]["population"].sum()
            female = grp[grp["sex"] == "Female"]["population"].sum()
            if all_p > 0:
                assert abs((male + female) - all_p) <= 5, (
                    f"{lgd} year {year} age {age}: Male+Female={male+female} != All persons={all_p}"
                )

    def test_filter_by_lgd_name(self, lgd_data):
        belfast = population_projections.get_lgd_projections(lgd="Belfast")
        assert (belfast["lgd_name"] == "Belfast").all()
        assert belfast["lgd_code"].iloc[0] == "N09000003"

    def test_filter_by_lgd_code(self, lgd_data):
        df = population_projections.get_lgd_projections(lgd="N09000003")
        assert (df["lgd_code"] == "N09000003").all()

    def test_filter_by_year(self, lgd_data):
        df = population_projections.get_lgd_projections(start_year=2030, end_year=2035)
        assert df["year"].min() >= 2030
        assert df["year"].max() <= 2035

    def test_validate_rejects_empty(self):
        with pytest.raises(NISRAValidationError, match="empty"):
            population_projections.validate_lgd_projections(pd.DataFrame())

    def test_validate_rejects_wrong_lgd_count(self):
        bad = pd.DataFrame({
            "lgd_name": ["Belfast"], "lgd_code": ["N09000003"],
            "year": [2025], "sex": ["Male"], "age_group": ["00-04"], "population": [1000],
        })
        with pytest.raises(NISRAValidationError, match="11 LGDs"):
            population_projections.validate_lgd_projections(bad)

    def test_chronological_years(self, lgd_data):
        years = sorted(lgd_data["year"].unique())
        for i in range(len(years) - 1):
            assert years[i + 1] - years[i] == 1, f"Gap between {years[i]} and {years[i+1]}"
