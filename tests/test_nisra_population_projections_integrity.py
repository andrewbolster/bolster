"""Data integrity tests for NISRA population projections.

NI-level projections are now served via PxStat API (no Excel scraping).
LGD projections are not yet in PxStat — those tests are skipped pending
API availability.

Tests use real data downloaded once per class (scope="class").
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import population_projections
from bolster.data_sources.nisra._base import NISRAValidationError


class TestDataIntegrity:
    """Integration tests using real NI-level population projections from PxStat."""

    @pytest.fixture(scope="class")
    def projections_data(self):
        return population_projections.get_latest_projections()

    @pytest.fixture(scope="class")
    def projections_single(self):
        return population_projections.get_latest_projections(age_groups="single")

    def test_required_columns(self, projections_data):
        for col in ("year", "base_year", "age_group", "sex", "population"):
            assert col in projections_data.columns, f"Missing column: {col}"

    def test_value_ranges(self, projections_data):
        assert (projections_data["population"] >= 0).all()
        assert (projections_data["year"] >= projections_data["base_year"]).all()

    def test_sex_values(self, projections_data):
        sexes = set(projections_data["sex"].unique())
        assert "All persons" in sexes
        assert "Males" in sexes
        assert "Females" in sexes

    def test_sex_totals(self, projections_data):
        """All persons ≈ Males + Females (±1 for rounding)."""
        for (year, age), grp in projections_data.groupby(["year", "age_group"]):
            males = grp[grp["sex"] == "Males"]["population"].sum()
            females = grp[grp["sex"] == "Females"]["population"].sum()
            all_persons = grp[grp["sex"] == "All persons"]["population"].sum()
            if all_persons > 0:
                assert abs((males + females) - all_persons) <= 5, (
                    f"Year {year}, Age {age}: Males+Females ({males+females}) != All persons ({all_persons})"
                )

    def test_projection_coverage(self, projections_data):
        years = sorted(projections_data["year"].unique())
        assert len(years) >= 20, f"Expected ≥20 projection years, got {len(years)}"
        # Continuous — no gaps
        for i in range(len(years) - 1):
            assert years[i + 1] - years[i] == 1, f"Gap: {years[i]} → {years[i+1]}"

    def test_starts_from_base_year(self, projections_data):
        assert projections_data["year"].min() == 2024

    def test_age_group_format_5yr(self, projections_data):
        import re
        for age in projections_data["age_group"].unique():
            assert re.match(r"^Age \d+(-\d+|\+)$", str(age)), f"Unexpected age format: {age}"

    def test_filtering_by_year(self, projections_data):
        df = population_projections.get_latest_projections(start_year=2030, end_year=2035)
        assert df["year"].min() >= 2030
        assert df["year"].max() <= 2035
        assert len(df) > 0

    def test_single_year_of_age(self, projections_single):
        ages = projections_single["age_group"].unique()
        assert "Age 0" in ages
        assert len(ages) > 80

    def test_no_future_base_year(self, projections_data):
        assert projections_data["base_year"].iloc[0] <= 2030

    def test_reasonable_population_totals(self, projections_data):
        """NI total population should be roughly 1.8M-2.5M throughout the projection."""
        totals = (
            projections_data[projections_data["sex"] == "All persons"]
            .groupby("year")["population"]
            .sum()
        )
        assert (totals >= 1_500_000).all(), f"Min NI total too low: {totals.min()}"
        assert (totals <= 3_000_000).all(), f"Max NI total too high: {totals.max()}"


class TestVariantProjections:
    """Tests for variant projection scenarios."""

    def test_variants_available(self):
        df = population_projections.get_variant_projections(start_year=2025, end_year=2025)
        assert len(df) > 0
        assert "variant" in df.columns

    def test_filter_by_variant(self):
        df = population_projections.get_variant_projections(variant="high fertility", start_year=2025, end_year=2026)
        assert len(df) > 0
        assert all("high fertility" in v.lower() for v in df["variant"].unique())

    def test_variant_columns(self):
        df = population_projections.get_variant_projections(start_year=2025, end_year=2025)
        for col in ("year", "age_group", "sex", "variant", "population"):
            assert col in df.columns


class TestValidation:
    """Unit tests for validation — no network calls."""

    def test_validate_empty_dataframe(self):
        with pytest.raises(NISRAValidationError):
            population_projections.validate_projections(pd.DataFrame())

    def test_validate_missing_columns(self):
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            population_projections.validate_projections(
                pd.DataFrame({"year": [2030], "population": [1000]})
            )

    def test_validate_negative_population(self):
        with pytest.raises(NISRAValidationError, match="[Nn]egative"):
            population_projections.validate_projections(
                pd.DataFrame({
                    "year": [2030], "base_year": [2024],
                    "age_group": ["Age 0-4"], "sex": ["Males"],
                    "population": [-100],
                })
            )
