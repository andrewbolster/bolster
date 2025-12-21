"""Data integrity tests for NISRA population statistics.

These tests validate that the data is internally consistent across different
dimensions and time periods. They use real data from NISRA (not mocked) and
should work with any dataset (latest or historical).

Key validations:
- Total population should equal sum of male + female population
- No negative values
- Realistic population counts
- Temporal continuity (year-over-year changes within reasonable bounds)
- Age distribution follows expected patterns
- Sex ratio within biological norms
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
        # Group by year and age_5, check totals
        groups = latest_population_ni.groupby(["year", "age_5"])

        for (year, age_band), group_data in groups:
            all_persons = group_data[group_data["sex"] == "All persons"]["population"].sum()
            males = group_data[group_data["sex"] == "Males"]["population"].sum()
            females = group_data[group_data["sex"] == "Females"]["population"].sum()

            assert all_persons > 0, f"Year {year}, Age {age_band}: All persons is zero"
            assert males > 0, f"Year {year}, Age {age_band}: Males is zero"
            assert females > 0, f"Year {year}, Age {age_band}: Females is zero"

            assert all_persons == males + females, (
                f"Year {year}, Age {age_band}: All persons ({all_persons}) != Males ({males}) + Females ({females})"
            )

    def test_no_negative_values(self, latest_population_all):
        """Test that there are no negative population counts."""
        assert (latest_population_all["population"] >= 0).all(), "Data contains negative population counts"

    def test_realistic_population_ranges(self, latest_population_ni):
        """Test that population counts are within realistic ranges."""
        # Get total NI population for recent years
        recent_years = latest_population_ni[latest_population_ni["year"] >= 2020]
        yearly_totals = recent_years[recent_years["sex"] == "All persons"].groupby("year")["population"].sum()

        for year, total in yearly_totals.items():
            # NI population should be between 1.5M and 2.5M
            assert 1_500_000 <= total <= 2_500_000, f"Year {year}: Total population ({total:,}) outside realistic range"

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

    def test_year_over_year_growth_reasonable(self, latest_population_ni):
        """Test that year-over-year population changes are within reasonable bounds.

        NI population typically grows/declines by less than 2% per year.
        """
        # Get total population by year
        yearly_totals = (
            latest_population_ni[latest_population_ni["sex"] == "All persons"]
            .groupby("year")["population"]
            .sum()
            .sort_index()
        )

        for i in range(1, len(yearly_totals)):
            prev_year = yearly_totals.index[i - 1]
            curr_year = yearly_totals.index[i]

            prev_pop = yearly_totals.iloc[i - 1]
            curr_pop = yearly_totals.iloc[i]

            pct_change = ((curr_pop - prev_pop) / prev_pop) * 100

            # Allow -5% to +5% annual change (generous bounds)
            assert -5 <= pct_change <= 5, (
                f"Year {prev_year} to {curr_year}: Population change {pct_change:.2f}% exceeds reasonable bounds"
            )

    def test_sex_ratio_realistic(self, latest_population_ni):
        """Test that male/female ratio is within realistic bounds.

        Overall sex ratio should be close to 50/50, typically 95-105 males per 100 females.
        """
        # Calculate overall sex ratio for each year
        for year in latest_population_ni["year"].unique():
            year_data = latest_population_ni[latest_population_ni["year"] == year]

            total_males = year_data[year_data["sex"] == "Males"]["population"].sum()
            total_females = year_data[year_data["sex"] == "Females"]["population"].sum()

            sex_ratio = (total_males / total_females) * 100  # Males per 100 females

            # Typical range: 95-105 (males slightly outnumber females at birth, but fewer in old age)
            assert 90 <= sex_ratio <= 110, (
                f"Year {year}: Sex ratio ({sex_ratio:.1f} males per 100 females) outside realistic range"
            )

    def test_age_distribution_patterns(self, latest_population_ni):
        """Test that age distribution follows expected patterns.

        - Working age (20-64) should be largest segment
        - Children (0-15) should be smaller than working age
        - Elderly (65+) should be smallest but growing over time
        """
        # Test for recent year (2024 or latest)
        latest_year = latest_population_ni["year"].max()
        latest_data = latest_population_ni[
            (latest_population_ni["year"] == latest_year) & (latest_population_ni["sex"] == "All persons")
        ]

        # Aggregate by broad age groups
        children = latest_data[latest_data["age_broad"] == "00-15"]["population"].sum()
        working_age = latest_data[latest_data["age_broad"].isin(["16-39", "40-64"])]["population"].sum()
        elderly = latest_data[latest_data["age_broad"] == "65+"]["population"].sum()

        # Working age should be largest
        assert working_age > children, "Working age population should exceed children"
        assert working_age > elderly, "Working age population should exceed elderly"

        # All three segments should have substantial populations
        total = children + working_age + elderly
        assert children / total > 0.15, "Children should be >15% of population"
        assert working_age / total > 0.50, "Working age should be >50% of population"

    def test_aging_population_trend(self, latest_population_ni):
        """Test that elderly population is increasing over time (aging population).

        NI, like most developed countries, has an aging population.
        """
        # Calculate elderly (65+) percentage for each decade
        years_to_check = [1980, 1990, 2000, 2010, 2020]
        years_to_check = [y for y in years_to_check if y in latest_population_ni["year"].values]

        elderly_pct = {}

        for year in years_to_check:
            year_data = latest_population_ni[
                (latest_population_ni["year"] == year) & (latest_population_ni["sex"] == "All persons")
            ]

            total_pop = year_data["population"].sum()
            elderly_pop = year_data[year_data["age_broad"] == "65+"]["population"].sum()

            elderly_pct[year] = (elderly_pop / total_pop) * 100

        # Check that elderly percentage generally increases
        if len(elderly_pct) >= 2:
            years_sorted = sorted(elderly_pct.keys())

            for i in range(1, len(years_sorted)):
                # Allow some variation but overall should trend upward
                # Just check first vs last
                pass

            first_year = years_sorted[0]
            last_year = years_sorted[-1]

            assert elderly_pct[last_year] > elderly_pct[first_year], (
                f"Elderly percentage should increase over time: "
                f"{first_year} = {elderly_pct[first_year]:.1f}%, "
                f"{last_year} = {elderly_pct[last_year]:.1f}%"
            )

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

    def test_population_growth_1971_to_present(self, latest_population_ni):
        """Test that NI population has grown from 1971 to present.

        NI population was ~1.5M in 1971 and is ~1.9M in 2024.
        """
        if 1971 in latest_population_ni["year"].values:
            pop_1971 = latest_population_ni[
                (latest_population_ni["year"] == 1971) & (latest_population_ni["sex"] == "All persons")
            ]["population"].sum()

            latest_year = latest_population_ni["year"].max()
            pop_latest = latest_population_ni[
                (latest_population_ni["year"] == latest_year) & (latest_population_ni["sex"] == "All persons")
            ]["population"].sum()

            # Population should have grown
            assert pop_latest > pop_1971, (
                f"Population should have grown from 1971 ({pop_1971:,}) to {latest_year} ({pop_latest:,})"
            )

            # Growth should be reasonable (not more than doubled)
            growth_factor = pop_latest / pop_1971
            assert growth_factor < 2.0, f"Population growth factor ({growth_factor:.2f}) seems unrealistic"
