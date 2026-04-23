"""Data integrity tests for NISRA official migration statistics.

Tests use real NISRA data downloaded once per test class (scope="class" fixture).
No mocks - validates actual published data quality.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import migration
from bolster.data_sources.nisra._base import NISRAValidationError


class TestDataIntegrity:
    """Integration tests using real official NISRA migration data.

    Downloads data once and reuses across all tests in this class.
    """

    @pytest.fixture(scope="class")
    def official_data(self):
        """Download real official migration data once for all tests."""
        return migration.get_official_migration()

    def test_required_columns(self, official_data):
        """Verify all required columns are present."""
        required_columns = ["year", "net_migration", "date"]
        for col in required_columns:
            assert col in official_data.columns, f"Missing required column: {col}"

    def test_value_ranges(self, official_data):
        """Verify net_migration values are reasonable."""
        # Net migration can be positive or negative, but must be reasonable
        # (not more than total NI population ~1.9M)
        assert (official_data["net_migration"].abs() < 1_900_000).all(), "Net migration values unreasonably large"

    def test_historical_coverage(self, official_data):
        """Verify data spans multiple years (at least 10 years)."""
        years = official_data["year"].unique()
        assert len(years) >= 10, f"Expected at least 10 years of data, got {len(years)}"

        # Verify years are continuous (no big gaps)
        years_sorted = sorted(years)
        for i in range(len(years_sorted) - 1):
            gap = years_sorted[i + 1] - years_sorted[i]
            assert gap <= 2, f"Gap of {gap} years between {years_sorted[i]} and {years_sorted[i + 1]}"


class TestCrossValidation:
    """Integration tests for cross-validation between official and derived migration.

    Requires both official and derived data — downloads once per class.
    """

    @pytest.fixture(scope="class")
    def comparison(self):
        """Download both datasets and compare."""
        official = migration.get_official_migration()
        derived = migration.get_latest_migration()
        return migration.compare_official_vs_derived(official, derived)

    def test_comparison_required_columns(self, comparison):
        """Verify comparison DataFrame has required columns."""
        required = [
            "year",
            "official_net_migration",
            "derived_net_migration",
            "absolute_difference",
            "percent_difference",
            "exceeds_threshold",
        ]
        for col in required:
            assert col in comparison.columns, f"Missing column: {col}"

    def test_overlapping_years_exist(self, comparison):
        """Verify there is at least some overlap between datasets."""
        assert len(comparison) >= 1, "Expected at least one overlapping year"

    def test_difference_calculation(self, comparison):
        """Verify absolute_difference = |derived - official| for all rows."""
        expected = (comparison["derived_net_migration"] - comparison["official_net_migration"]).abs()
        assert (comparison["absolute_difference"] == expected).all()

    def test_threshold_flag(self, comparison):
        """Verify exceeds_threshold is consistent with absolute_difference."""
        threshold = 1000
        expected_flags = comparison["absolute_difference"] > threshold
        assert (comparison["exceeds_threshold"] == expected_flags).all()


class TestCrossValidationUnit:
    """Unit tests for compare_official_vs_derived edge cases (no network)."""

    def _make_df(self, years, values, col="net_migration"):
        return pd.DataFrame({"year": years, col: values, "date": pd.Timestamp("2020-06-30")})

    def test_no_overlapping_years_returns_empty(self):
        """Non-overlapping year ranges should return empty DataFrame."""
        official = self._make_df([2010, 2011], [1000, 2000])
        derived = pd.DataFrame({
            "year": [2020, 2021],
            "net_migration": [500, 600],
            "population_start": [0, 0], "population_end": [0, 0],
            "births": [0, 0], "deaths": [0, 0],
            "natural_change": [0, 0], "population_change": [0, 0],
            "migration_rate": [0.0, 0.0],
        })
        result = migration.compare_official_vs_derived(official, derived)
        assert result.empty

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        official = pd.DataFrame({
            "year": [2010, 2011],
            "net_migration": [1000, 2000],
            "date": pd.Timestamp("2020-06-30"),
        })
        derived = pd.DataFrame({
            "year": [2010, 2011],
            "net_migration": [1200, 2100],  # diffs: 200, 100
            "population_start": [0, 0], "population_end": [0, 0],
            "births": [0, 0], "deaths": [0, 0],
            "natural_change": [0, 0], "population_change": [0, 0],
            "migration_rate": [0.0, 0.0],
        })
        result = migration.compare_official_vs_derived(official, derived, threshold=150)
        # diff of 200 exceeds 150; diff of 100 does not
        assert result.loc[result["year"] == 2010, "exceeds_threshold"].values[0]
        assert not result.loc[result["year"] == 2011, "exceeds_threshold"].values[0]


class TestValidation:
    """Unit tests for validation edge cases.

    These don't need network calls - test validation logic directly.
    """

    def test_validate_empty_dataframe(self):
        """Validation should fail on empty DataFrame."""
        empty_df = pd.DataFrame()
        with pytest.raises(NISRAValidationError, match="DataFrame is empty"):
            migration.validate_official_migration(empty_df)

    def test_validate_missing_columns(self):
        """Validation should fail if required columns missing."""
        incomplete_df = pd.DataFrame({"year": [2020]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            migration.validate_official_migration(incomplete_df)

    def test_validate_unreasonable_values(self):
        """Validation should fail if values are unreasonably large."""
        invalid_df = pd.DataFrame(
            {
                "year": [2020],
                "net_migration": [2_000_000],  # Larger than NI population
                "date": [pd.Timestamp("2020-06-30")],
            }
        )
        with pytest.raises(NISRAValidationError, match="unreasonably large"):
            migration.validate_official_migration(invalid_df)
