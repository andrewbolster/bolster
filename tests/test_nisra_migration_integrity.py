"""Data integrity tests for NISRA migration statistics (derived).

These tests validate that the migration estimates derived from demographic
components (population, births, deaths) are internally consistent.

They use real data from NISRA (not mocked) and validate:
- Demographic accounting equation: ΔPop = (Births - Deaths) + Net Migration
- Data consistency across births, deaths, and population sources
- Reasonable migration estimates
- Temporal continuity
"""

import pytest

from bolster.data_sources.nisra import migration


class TestMigrationDataIntegrity:
    """Test suite for validating internal consistency of derived migration data."""

    @pytest.fixture(scope="class")
    def latest_migration(self):
        """Fetch latest migration data once for the test class."""
        return migration.get_latest_migration(force_refresh=False)

    def test_required_columns_present(self, latest_migration):
        """Test that all required columns are present."""
        required_columns = {
            "year",
            "population_start",
            "population_end",
            "births",
            "deaths",
            "natural_change",
            "population_change",
            "net_migration",
            "migration_rate",
        }

        assert set(latest_migration.columns) == required_columns, f"Incorrect columns: {set(latest_migration.columns)}"

    def test_data_types_correct(self, latest_migration):
        """Test that column data types are correct."""
        assert latest_migration["year"].dtype in ["int64", "int32"], "year should be integer"
        assert latest_migration["population_start"].dtype in ["int64", "int32"], "population_start should be integer"
        assert latest_migration["population_end"].dtype in ["int64", "int32"], "population_end should be integer"
        assert latest_migration["births"].dtype in ["int64", "int32"], "births should be integer"
        assert latest_migration["deaths"].dtype in ["int64", "int32"], "deaths should be integer"
        assert latest_migration["natural_change"].dtype in ["int64", "int32"], "natural_change should be integer"
        assert latest_migration["population_change"].dtype in ["int64", "int32"], "population_change should be integer"
        assert latest_migration["net_migration"].dtype in ["int64", "int32"], "net_migration should be integer"
        assert latest_migration["migration_rate"].dtype in ["float64"], "migration_rate should be float"

    def test_demographic_equation_holds(self, latest_migration):
        """Test that the demographic accounting equation holds for all years.

        Population Change = Natural Change + Net Migration
        """
        # This is the core validation - already done by the module's validation function
        assert migration.validate_demographic_equation(latest_migration)

    def test_natural_change_calculation(self, latest_migration):
        """Test that natural change equals births minus deaths."""
        for _, row in latest_migration.iterrows():
            year = row["year"]
            births = row["births"]
            deaths = row["deaths"]
            natural_change = row["natural_change"]

            assert natural_change == births - deaths, (
                f"Year {year}: Natural change ({natural_change:,}) != Births ({births:,}) - Deaths ({deaths:,})"
            )

    def test_population_change_calculation(self, latest_migration):
        """Test that population change is correctly calculated."""
        for _, row in latest_migration.iterrows():
            year = row["year"]
            pop_start = row["population_start"]
            pop_end = row["population_end"]
            pop_change = row["population_change"]

            assert pop_change == pop_end - pop_start, (
                f"Year {year}: Population change ({pop_change:,}) != End ({pop_end:,}) - Start ({pop_start:,})"
            )

    def test_migration_rate_calculation(self, latest_migration):
        """Test that migration rate is correctly calculated per 1,000 population."""
        for _, row in latest_migration.iterrows():
            year = row["year"]
            net_migration = row["net_migration"]
            pop_start = row["population_start"]
            pop_end = row["population_end"]
            migration_rate = row["migration_rate"]

            # Calculate expected rate
            avg_population = (pop_start + pop_end) / 2
            expected_rate = round((net_migration / avg_population) * 1000, 2)

            assert abs(migration_rate - expected_rate) < 0.01, (
                f"Year {year}: Migration rate ({migration_rate}) != Expected ({expected_rate})"
            )

    def test_temporal_continuity(self, latest_migration):
        """Test that there are no missing years in the time series."""
        years = sorted(latest_migration["year"].unique())

        min_year = min(years)
        max_year = max(years)

        expected_years = set(range(min_year, max_year + 1))
        actual_years = set(years)

        missing_years = expected_years - actual_years

        assert len(missing_years) == 0, f"Missing years in time series: {sorted(missing_years)}"

    def test_reasonable_migration_ranges(self, latest_migration):
        """Test that migration values are within reasonable ranges.

        NI population is ~1.9M, so annual net migration should typically be
        less than ±50,000 (roughly ±2.5% of population).
        """
        for _, row in latest_migration.iterrows():
            year = row["year"]
            net_migration = row["net_migration"]

            # Allow wider range to accommodate unusual events (e.g., post-COVID surge)
            assert -50000 <= net_migration <= 50000, (
                f"Year {year}: Net migration ({net_migration:,}) outside reasonable range (-50k to +50k)"
            )

    def test_population_values_positive(self, latest_migration):
        """Test that all population values are positive."""
        assert (latest_migration["population_start"] > 0).all(), "Population start has non-positive values"
        assert (latest_migration["population_end"] > 0).all(), "Population end has non-positive values"

    def test_births_deaths_positive(self, latest_migration):
        """Test that births and deaths are positive."""
        assert (latest_migration["births"] > 0).all(), "Births has non-positive values"
        assert (latest_migration["deaths"] > 0).all(), "Deaths has non-positive values"

    def test_helper_function_get_migration_by_year(self, latest_migration):
        """Test the get_migration_by_year helper function."""
        # Get data for a specific year
        latest_year = latest_migration["year"].max()
        year_data = migration.get_migration_by_year(latest_migration, latest_year)

        # Should only have data for that year
        assert year_data["year"].nunique() == 1
        assert year_data["year"].iloc[0] == latest_year

        # Should have all required columns
        assert len(year_data) == 1

    def test_helper_function_get_migration_summary_statistics(self, latest_migration):
        """Test the get_migration_summary_statistics helper function."""
        stats = migration.get_migration_summary_statistics(latest_migration)

        # Should have required keys
        required_keys = {
            "total_years",
            "avg_net_migration",
            "avg_migration_rate",
            "positive_years",
            "negative_years",
            "max_immigration_year",
            "max_immigration",
            "max_emigration_year",
            "max_emigration",
        }

        assert set(stats.keys()) == required_keys

        # Total years should match data
        assert stats["total_years"] == len(latest_migration)

        # Positive + negative years should equal total years
        assert stats["positive_years"] + stats["negative_years"] == stats["total_years"]

        # Max immigration should be positive, max emigration should be negative
        assert stats["max_immigration"] > 0
        assert stats["max_emigration"] < 0

    def test_validation_function_works(self, latest_migration):
        """Test that the validate_demographic_equation function works correctly."""
        # Should pass with valid data
        assert migration.validate_demographic_equation(latest_migration)

        # Create invalid data
        invalid_data = latest_migration.copy()
        invalid_data.loc[0, "net_migration"] = 999999  # Impossibly high migration

        # Should fail
        with pytest.raises(migration.NISRAValidationError):
            migration.validate_demographic_equation(invalid_data)

    def test_historical_coverage(self, latest_migration):
        """Test that data goes back to at least 2011."""
        min_year = latest_migration["year"].min()

        assert min_year <= 2011, f"Expected data from 2011, earliest is {min_year}"

    def test_recent_data_available(self, latest_migration):
        """Test that recent data is available (within last year)."""
        import datetime

        max_year = latest_migration["year"].max()
        current_year = datetime.datetime.now().year

        # Should have data up to current year or previous year
        assert max_year >= current_year - 1, f"Latest data ({max_year}) is more than 1 year old"

    def test_post_covid_migration_surge(self, latest_migration):
        """Test that post-COVID migration surge is visible in data.

        2022-2024 should show increased net immigration after COVID-19 restrictions lifted.
        """
        # Get 2020 (COVID year)
        df_2020 = latest_migration[latest_migration["year"] == 2020]

        # Get post-COVID years (2022-2024)
        post_covid = latest_migration[latest_migration["year"].isin([2022, 2023, 2024])]

        if not df_2020.empty and not post_covid.empty:
            migration_2020 = df_2020["net_migration"].values[0]
            avg_post_covid = post_covid["net_migration"].mean()

            # Post-COVID migration should be significantly higher than 2020
            assert avg_post_covid > migration_2020, (
                f"Post-COVID migration ({avg_post_covid:,.0f}) should exceed 2020 migration ({migration_2020:,.0f})"
            )

    def test_no_duplicate_years(self, latest_migration):
        """Test that there are no duplicate years."""
        duplicates = latest_migration.groupby("year").size()
        duplicates = duplicates[duplicates > 1]

        assert len(duplicates) == 0, f"Found duplicate years: {duplicates.index.tolist()}"

    def test_migration_rate_sign_consistency(self, latest_migration):
        """Test that migration rate has the same sign as net migration."""
        for _, row in latest_migration.iterrows():
            year = row["year"]
            net_migration = row["net_migration"]
            migration_rate = row["migration_rate"]

            # Both should have the same sign (or both be zero)
            if net_migration > 0:
                assert migration_rate > 0, f"Year {year}: Positive migration but negative rate"
            elif net_migration < 0:
                assert migration_rate < 0, f"Year {year}: Negative migration but positive rate"
            else:
                assert migration_rate == 0, f"Year {year}: Zero migration but non-zero rate"

    def test_population_growth_explained(self, latest_migration):
        """Test that population growth is fully explained by natural change + migration.

        This is the same as the demographic equation test but verifies it explicitly.
        """
        for _, row in latest_migration.iterrows():
            year = row["year"]
            pop_change = row["population_change"]
            natural_change = row["natural_change"]
            net_migration = row["net_migration"]

            explained_change = natural_change + net_migration

            # Should be exactly equal (no residual)
            assert pop_change == explained_change, (
                f"Year {year}: Population change ({pop_change:,}) != "
                f"Natural change ({natural_change:,}) + Migration ({net_migration:,})"
            )

    def test_births_exceed_deaths_most_years(self, latest_migration):
        """Test that births exceed deaths in most years (positive natural change).

        NI typically has positive natural increase.
        """
        positive_natural_change = (latest_migration["natural_change"] > 0).sum()
        total_years = len(latest_migration)

        # At least 50% of years should have positive natural change
        assert positive_natural_change >= total_years * 0.5, (
            f"Only {positive_natural_change}/{total_years} years have positive natural change"
        )
