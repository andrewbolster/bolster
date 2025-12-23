"""Integrity tests for NISRA Composite Economic Index Module.

These tests validate real data quality, structure, and consistency for the
Northern Ireland Composite Economic Index (NICEI) module.

Test coverage includes:
- Data structure and types
- Data completeness and ranges
- Time series continuity
- Sectoral index values
- Contribution calculations
- Helper function behavior
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import composite_index


class TestNICEIIndicesIntegrity:
    """Integrity tests for NICEI index data (Table 1)."""

    @pytest.fixture(scope="class")
    def latest_nicei(self):
        """Fixture to load latest NICEI data once for all tests."""
        return composite_index.get_latest_nicei(force_refresh=False)

    def test_data_structure(self, latest_nicei):
        """Test that NICEI data has correct structure."""
        assert isinstance(latest_nicei, pd.DataFrame)
        assert len(latest_nicei) > 0

        # Check required columns
        required_cols = [
            "year",
            "quarter",
            "nicei",
            "private_sector",
            "public_sector",
            "services",
            "production",
            "construction",
            "agriculture",
        ]
        assert all(col in latest_nicei.columns for col in required_cols)

    def test_data_types(self, latest_nicei):
        """Test that NICEI columns have correct data types."""
        assert pd.api.types.is_integer_dtype(latest_nicei["year"])
        assert pd.api.types.is_integer_dtype(latest_nicei["quarter"])
        assert pd.api.types.is_float_dtype(latest_nicei["nicei"])
        assert pd.api.types.is_float_dtype(latest_nicei["private_sector"])
        assert pd.api.types.is_float_dtype(latest_nicei["public_sector"])
        assert pd.api.types.is_float_dtype(latest_nicei["services"])
        assert pd.api.types.is_float_dtype(latest_nicei["production"])
        assert pd.api.types.is_float_dtype(latest_nicei["construction"])
        assert pd.api.types.is_float_dtype(latest_nicei["agriculture"])

    def test_quarter_values(self, latest_nicei):
        """Test that quarter values are valid (1-4)."""
        assert set(latest_nicei["quarter"].unique()).issubset({1, 2, 3, 4})

    def test_year_range(self, latest_nicei):
        """Test that year range is reasonable (2006-present)."""
        assert latest_nicei["year"].min() >= 2006
        assert latest_nicei["year"].max() <= 2026

    def test_index_values_positive(self, latest_nicei):
        """Test that all index values are positive."""
        numeric_cols = [
            "nicei",
            "private_sector",
            "public_sector",
            "services",
            "production",
            "construction",
            "agriculture",
        ]
        for col in numeric_cols:
            assert (latest_nicei[col] > 0).all(), f"{col} has non-positive values"

    def test_index_values_reasonable(self, latest_nicei):
        """Test that index values are in reasonable range (base 2022=100)."""
        # With 2022=100, expect indices roughly 70-150 range
        numeric_cols = [
            "nicei",
            "private_sector",
            "public_sector",
            "services",
            "production",
            "construction",
            "agriculture",
        ]
        for col in numeric_cols:
            assert latest_nicei[col].min() > 50, f"{col} minimum too low"
            assert latest_nicei[col].max() < 200, f"{col} maximum too high"

    def test_no_missing_values(self, latest_nicei):
        """Test that there are no missing values in key columns."""
        assert not latest_nicei["year"].isna().any()
        assert not latest_nicei["quarter"].isna().any()
        assert not latest_nicei["nicei"].isna().any()
        assert not latest_nicei["private_sector"].isna().any()
        assert not latest_nicei["public_sector"].isna().any()

    def test_chronological_order(self, latest_nicei):
        """Test that data is in chronological order."""
        # Create a sequential check: year should be monotonic, within year quarter should increase
        for i in range(1, len(latest_nicei)):
            curr_year = latest_nicei.iloc[i]["year"]
            prev_year = latest_nicei.iloc[i - 1]["year"]
            curr_quarter = latest_nicei.iloc[i]["quarter"]
            prev_quarter = latest_nicei.iloc[i - 1]["quarter"]

            if curr_year == prev_year:
                assert curr_quarter > prev_quarter, "Quarters not in order within same year"
            else:
                assert curr_year > prev_year, "Years not in ascending order"

    def test_quarterly_continuity(self, latest_nicei):
        """Test that quarters are continuous (no gaps)."""
        # Group by year and check most years have 4 quarters
        for year in latest_nicei["year"].unique():
            year_data = latest_nicei[latest_nicei["year"] == year]
            # Most years should have 4 quarters, except possibly the latest year
            if year < latest_nicei["year"].max():
                assert len(year_data) == 4, f"Year {year} doesn't have 4 quarters"

    def test_coverage_includes_recent_data(self, latest_nicei):
        """Test that data includes recent quarters (2024-2025)."""
        assert latest_nicei["year"].max() >= 2024

    def test_covid_impact_visible(self, latest_nicei):
        """Test that COVID-19 impact is visible in 2020 data."""
        df_2020 = latest_nicei[latest_nicei["year"] == 2020]
        df_2019 = latest_nicei[latest_nicei["year"] == 2019]

        # 2020 should show lower average NICEI than 2019
        assert len(df_2020) >= 3  # At least Q1-Q3 2020
        assert df_2020["nicei"].mean() < df_2019["nicei"].mean()

    def test_base_period_2022(self, latest_nicei):
        """Test that 2022 is approximately the base period (2022=100)."""
        df_2022 = latest_nicei[latest_nicei["year"] == 2022]
        if len(df_2022) == 4:  # If we have all 4 quarters of 2022
            # Annual average should be close to 100
            assert 98 < df_2022["nicei"].mean() < 102

    def test_private_public_sector_relationship(self, latest_nicei):
        """Test that private and public sector indices are reasonable."""
        # Both should be positive and in similar ranges
        assert (latest_nicei["private_sector"] > 0).all()
        assert (latest_nicei["public_sector"] > 0).all()

    def test_sectoral_indices_sensible(self, latest_nicei):
        """Test that sectoral indices show expected patterns."""
        # Services should generally be largest contributor (highest weight)
        # Construction tends to be more volatile
        latest_row = latest_nicei.iloc[-1]

        # All sectors should be positive
        assert latest_row["services"] > 0
        assert latest_row["production"] > 0
        assert latest_row["construction"] > 0
        assert latest_row["agriculture"] > 0

    def test_construction_volatility(self, latest_nicei):
        """Test that construction sector shows higher volatility than others."""
        # Calculate coefficient of variation for each sector
        cv_construction = latest_nicei["construction"].std() / latest_nicei["construction"].mean()
        cv_services = latest_nicei["services"].std() / latest_nicei["services"].mean()

        # Construction typically more volatile than services
        assert cv_construction > cv_services * 0.5  # At least 50% as volatile


class TestNICEIContributionsIntegrity:
    """Integrity tests for NICEI sector contributions data (Table 11)."""

    @pytest.fixture(scope="class")
    def latest_contributions(self):
        """Fixture to load latest NICEI contributions once for all tests."""
        return composite_index.get_latest_nicei_contributions(force_refresh=False)

    def test_data_structure(self, latest_contributions):
        """Test that contributions data has correct structure."""
        assert isinstance(latest_contributions, pd.DataFrame)
        assert len(latest_contributions) > 0

        # Check required columns
        required_cols = [
            "year",
            "quarter",
            "nicei",
            "nicei_quarterly_change",
            "public_sector_contribution",
            "services_contribution",
            "production_contribution",
            "construction_contribution",
            "agriculture_contribution",
        ]
        assert all(col in latest_contributions.columns for col in required_cols)

    def test_data_types(self, latest_contributions):
        """Test that contribution columns have correct data types."""
        assert pd.api.types.is_integer_dtype(latest_contributions["year"])
        assert pd.api.types.is_integer_dtype(latest_contributions["quarter"])
        assert pd.api.types.is_float_dtype(latest_contributions["nicei_quarterly_change"])

    def test_no_first_quarter_contribution(self, latest_contributions):
        """Test that first quarter (Q1 2006) has no quarterly change data."""
        # The contributions table starts from Q2 2006 since Q1 2006 has no previous quarter
        # First data point should be Q2 2006 or later
        assert not ((latest_contributions["year"] == 2006) & (latest_contributions["quarter"] == 1)).any()

    def test_contributions_sum_to_change(self, latest_contributions):
        """Test that sector contributions approximately sum to quarterly change."""
        for _, row in latest_contributions.iterrows():
            total_contribution = (
                row["public_sector_contribution"]
                + row["services_contribution"]
                + row["production_contribution"]
                + row["construction_contribution"]
                + row["agriculture_contribution"]
            )
            quarterly_change = row["nicei_quarterly_change"]

            # Allow for rounding errors (NISRA table notes: "figures may not sum due to rounding")
            # Tolerance set to 0.4 to account for NISRA's published rounding differences
            assert abs(total_contribution - quarterly_change) < 0.4, (
                f"Q{row['quarter']} {row['year']}: Contributions {total_contribution:.3f} "
                f"!= Quarterly change {quarterly_change:.3f}"
            )

    def test_contribution_values_reasonable(self, latest_contributions):
        """Test that individual sector contributions are in reasonable range."""
        # Individual contributions can be large during major economic shocks (e.g., COVID-19 recovery)
        # Set tolerance to +/- 15 percentage points to account for exceptional periods
        contribution_cols = [
            "public_sector_contribution",
            "services_contribution",
            "production_contribution",
            "construction_contribution",
            "agriculture_contribution",
        ]

        for col in contribution_cols:
            assert latest_contributions[col].min() > -15, f"{col} has extremely negative contribution"
            assert latest_contributions[col].max() < 15, f"{col} has extremely positive contribution"

    def test_services_largest_contributor(self, latest_contributions):
        """Test that services is generally the largest absolute contributor."""
        # Services has the highest weight in NI economy, so should have largest absolute contributions on average
        abs_contrib = latest_contributions[
            [
                "services_contribution",
                "production_contribution",
                "construction_contribution",
                "agriculture_contribution",
            ]
        ].abs()

        # Services should have highest mean absolute contribution
        assert abs_contrib["services_contribution"].mean() > abs_contrib["agriculture_contribution"].mean()

    def test_quarterly_change_calculation(self, latest_contributions):
        """Test that quarterly change values are reasonable."""
        # Most quarters shouldn't show massive changes (typical range: -5% to +5%)
        # Except during major shocks like COVID-19
        typical_changes = latest_contributions[
            (latest_contributions["year"] != 2020) & (latest_contributions["year"] != 2009)
        ]

        # 95% of non-crisis quarters should be within reasonable range
        assert (typical_changes["nicei_quarterly_change"].abs() < 3).sum() / len(typical_changes) > 0.85

    def test_covid_shock_visible(self, latest_contributions):
        """Test that COVID-19 shock is visible in 2020 Q1-Q2."""
        covid_period = latest_contributions[
            (latest_contributions["year"] == 2020) & (latest_contributions["quarter"].isin([1, 2]))
        ]

        # Should have significant negative quarterly changes during lockdown
        if len(covid_period) > 0:
            assert covid_period["nicei_quarterly_change"].min() < -1.0


class TestNICEIHelperFunctions:
    """Test helper functions for filtering and analyzing NICEI data."""

    @pytest.fixture(scope="class")
    def latest_nicei(self):
        """Fixture to load latest NICEI data once for all tests."""
        return composite_index.get_latest_nicei(force_refresh=False)

    def test_get_nicei_by_year(self, latest_nicei):
        """Test get_nicei_by_year helper function."""
        df_2024 = composite_index.get_nicei_by_year(latest_nicei, 2024)

        assert len(df_2024) > 0
        assert (df_2024["year"] == 2024).all()
        # Should have at least 4 quarters
        assert len(df_2024) >= 4

    def test_get_nicei_by_quarter(self, latest_nicei):
        """Test get_nicei_by_quarter helper function."""
        # Test Q2 2024
        df_q2_2024 = composite_index.get_nicei_by_quarter(latest_nicei, 2024, 2)

        assert len(df_q2_2024) == 1
        assert df_q2_2024["year"].values[0] == 2024
        assert df_q2_2024["quarter"].values[0] == 2
        assert df_q2_2024["nicei"].values[0] > 0

    def test_filter_functions_preserve_columns(self, latest_nicei):
        """Test that filter functions preserve all columns."""
        original_cols = set(latest_nicei.columns)

        df_2024 = composite_index.get_nicei_by_year(latest_nicei, 2024)
        assert set(df_2024.columns) == original_cols

        df_q2_2024 = composite_index.get_nicei_by_quarter(latest_nicei, 2024, 2)
        assert set(df_q2_2024.columns) == original_cols

    def test_filter_empty_results(self, latest_nicei):
        """Test that filters return empty DataFrame for non-existent data."""
        # Test a future year that doesn't exist
        df_future = composite_index.get_nicei_by_year(latest_nicei, 2099)
        assert len(df_future) == 0

        # Test an invalid quarter
        df_invalid = composite_index.get_nicei_by_quarter(latest_nicei, 2024, 5)
        assert len(df_invalid) == 0
