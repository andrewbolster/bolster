"""Data Integrity Tests for NISRA Labour Market Statistics.

These tests validate the internal consistency and quality of Labour Force Survey data
from NISRA (Northern Ireland Statistics and Research Agency).

Test Philosophy:
    - Uses REAL data from NISRA, not mocked data
    - Validates relationships (Male + Female = All Persons) not specific values
    - Works with any dataset (latest or historical) - future-proof
    - Tests catch data parsing errors, format changes, and source data issues

Test Coverage:
    - Mathematical consistency (totals match across dimensions)
    - Data completeness (all expected categories present)
    - Data quality (no negatives, reasonable ranges, no duplicates)
    - Temporal consistency (chronological order, no gaps)
    - Cross-validation (multiple tables consistent with each other)

Running Tests:
    ```bash
    # Run all labour market integrity tests
    uv run pytest tests/test_nisra_labour_market_integrity.py -v

    # Run specific test class
    uv run pytest tests/test_nisra_labour_market_integrity.py::TestEmploymentDataIntegrity -v

    # Run with coverage
    uv run pytest tests/test_nisra_labour_market_integrity.py --cov=src/bolster/data_sources/nisra
    ```

Author: Claude Code
Date: 2025-12-21
"""

import pytest

from bolster.data_sources.nisra import labour_market


class TestEmploymentDataIntegrity:
    """Test suite for employment by age and sex data (Table 2.15).

    Validates the latest quarterly employment data for internal consistency.
    """

    @pytest.fixture(scope="class")
    def latest_employment(self):
        """Fetch latest employment data once for the test class.

        Uses real NISRA data with caching (no mocking).
        """
        return labour_market.get_latest_employment(force_refresh=False)

    def test_employment_data_exists(self, latest_employment):
        """Test that employment data is returned and non-empty.

        Ensures the data source is accessible and returns meaningful data.
        """
        assert latest_employment is not None
        assert len(latest_employment) > 0, "Employment data should not be empty"

    def test_expected_employment_columns(self, latest_employment):
        """Test that employment data has all expected columns.

        Validates the schema/structure of the returned DataFrame.
        """
        expected_columns = ["quarter_period", "age_group", "sex", "percentage", "number"]
        actual_columns = latest_employment.columns.tolist()

        assert set(expected_columns).issubset(set(actual_columns)), (
            f"Missing expected columns. Expected: {expected_columns}, Got: {actual_columns}"
        )

    def test_expected_sex_categories(self, latest_employment):
        """Test that all expected sex categories are present.

        Employment data should include: Male, Female, All Persons
        """
        expected_sexes = {"Male", "Female", "All Persons"}
        actual_sexes = set(latest_employment["sex"].unique())

        assert expected_sexes.issubset(actual_sexes), (
            f"Missing expected sex categories. Expected: {expected_sexes}, Got: {actual_sexes}"
        )

    def test_age_groups_present(self, latest_employment):
        """Test that multiple age groups are present.

        Should have at least 10 distinct age groups plus "All ages" total.
        """
        age_groups = latest_employment["age_group"].unique()

        assert len(age_groups) >= 10, f"Expected at least 10 age groups, found {len(age_groups)}: {age_groups}"

        # Should include "All ages" total
        assert "All ages" in age_groups, "Should include 'All ages' total"

    def test_no_negative_percentages(self, latest_employment):
        """Test that there are no negative percentage values.

        Percentages should be between 0 and 100.
        """
        percentages = latest_employment["percentage"].dropna()

        negative_pct = percentages[percentages < 0]
        assert len(negative_pct) == 0, f"Found {len(negative_pct)} negative percentages"

        # Percentages should be less than 100
        too_high = percentages[percentages > 100]
        assert len(too_high) == 0, f"Found {len(too_high)} percentages > 100%"

    def test_percentages_sum_to_100(self, latest_employment):
        """Test that age group percentages sum to approximately 100% for each sex.

        The percentage distribution across age groups should sum to 100% (within rounding).
        """
        # Filter out "All ages" total
        age_breakdown = latest_employment[latest_employment["age_group"] != "All ages"].copy()

        # Group by sex and sum percentages
        for sex in ["Male", "Female", "All Persons"]:
            sex_data = age_breakdown[age_breakdown["sex"] == sex]
            total_pct = sex_data["percentage"].sum()

            # Allow for rounding errors (±1%)
            assert 99 <= total_pct <= 101, f"{sex}: Age group percentages sum to {total_pct:.1f}%, expected ~100%"

    def test_male_plus_female_equals_total(self, latest_employment):
        """Test that Male + Female employment equals All Persons total.

        This is a critical consistency check - the sum of male and female
        should match the All Persons total.
        """
        # Get "All ages" totals for each sex
        all_ages = latest_employment[latest_employment["age_group"] == "All ages"].copy()

        male_total = all_ages[all_ages["sex"] == "Male"]["number"].values
        female_total = all_ages[all_ages["sex"] == "Female"]["number"].values
        all_persons_total = all_ages[all_ages["sex"] == "All Persons"]["number"].values

        if len(male_total) > 0 and len(female_total) > 0 and len(all_persons_total) > 0:
            male = male_total[0]
            female = female_total[0]
            total = all_persons_total[0]

            # Sum should match total (within rounding - data is in thousands)
            calculated_total = male + female

            assert abs(calculated_total - total) <= 1000, (
                f"Male ({male:,}) + Female ({female:,}) = {calculated_total:,}, "
                f"but All Persons total is {total:,}. Difference: {abs(calculated_total - total):,}"
            )

    def test_no_duplicate_age_sex_combinations(self, latest_employment):
        """Test that there are no duplicate age group + sex combinations.

        Each combination of age_group and sex should appear only once.
        """
        # Filter out rows where both percentage and number are NaN
        # (these might be valid empty rows)
        non_empty = latest_employment.dropna(subset=["percentage", "number"], how="all")

        duplicates = non_empty.duplicated(subset=["age_group", "sex"], keep=False)

        if duplicates.any():
            dup_records = non_empty[duplicates][["age_group", "sex", "percentage", "number"]]
            assert False, f"Found {duplicates.sum()} duplicate age/sex combinations:\n{dup_records}"


class TestEconomicInactivityDataIntegrity:
    """Test suite for economic inactivity data (Table 2.21).

    Validates the historical time series of economic inactivity data.
    """

    @pytest.fixture(scope="class")
    def latest_inactivity(self):
        """Fetch latest economic inactivity data once for the test class.

        Uses real NISRA data with caching (no mocking).
        """
        return labour_market.get_latest_economic_inactivity(force_refresh=False)

    def test_inactivity_data_exists(self, latest_inactivity):
        """Test that economic inactivity data is returned and non-empty."""
        assert latest_inactivity is not None
        assert len(latest_inactivity) > 0, "Economic inactivity data should not be empty"

    def test_expected_inactivity_columns(self, latest_inactivity):
        """Test that economic inactivity data has all expected columns."""
        expected_columns = ["time_period", "sex", "economically_inactive_number", "economic_inactivity_rate"]
        actual_columns = latest_inactivity.columns.tolist()

        assert set(expected_columns).issubset(set(actual_columns)), (
            f"Missing expected columns. Expected: {expected_columns}, Got: {actual_columns}"
        )

    def test_expected_sex_categories_inactivity(self, latest_inactivity):
        """Test that all expected sex categories are present."""
        expected_sexes = {"Male", "Female", "All Persons"}
        actual_sexes = set(latest_inactivity["sex"].unique())

        assert expected_sexes == actual_sexes, (
            f"Sex categories mismatch. Expected: {expected_sexes}, Got: {actual_sexes}"
        )

    def test_male_plus_female_equals_total_inactivity(self, latest_inactivity):
        """Test that Male + Female inactivity equals All Persons total.

        This validates consistency across all time periods in the historical series.
        """
        # Get unique time periods
        time_periods = latest_inactivity["time_period"].unique()

        for period in time_periods:
            period_data = latest_inactivity[latest_inactivity["time_period"] == period]

            male_num = period_data[period_data["sex"] == "Male"]["economically_inactive_number"].values
            female_num = period_data[period_data["sex"] == "Female"]["economically_inactive_number"].values
            all_num = period_data[period_data["sex"] == "All Persons"]["economically_inactive_number"].values

            if len(male_num) > 0 and len(female_num) > 0 and len(all_num) > 0:
                male = male_num[0]
                female = female_num[0]
                total = all_num[0]

                calculated_total = male + female

                # Allow for rounding (data is in thousands)
                assert abs(calculated_total - total) <= 1000, (
                    f"{period}: Male ({male:,}) + Female ({female:,}) = {calculated_total:,}, "
                    f"but All Persons = {total:,}. Difference: {abs(calculated_total - total):,}"
                )

    def test_inactivity_rates_between_0_and_100(self, latest_inactivity):
        """Test that all inactivity rates are between 0% and 100%."""
        rates = latest_inactivity["economic_inactivity_rate"].dropna()

        too_low = rates[rates < 0]
        too_high = rates[rates > 100]

        assert len(too_low) == 0, f"Found {len(too_low)} inactivity rates < 0%"
        assert len(too_high) == 0, f"Found {len(too_high)} inactivity rates > 100%"

    def test_time_series_chronological(self, latest_inactivity):
        """Test that time periods are in chronological order.

        The time series should progress from oldest to newest.
        """

        # Extract years from time periods (e.g., "Jul to Sep 2025" -> 2025)
        def extract_year(period_str):
            import re

            match = re.search(r"\b(\d{4})\b", period_str)
            return int(match.group(1)) if match else 0

        # Get unique time periods (each appears 3 times for Male, Female, All Persons)
        unique_periods = latest_inactivity["time_period"].unique()

        years = [extract_year(period) for period in unique_periods]

        # Should be sorted
        assert years == sorted(years), f"Time periods not in chronological order. Years: {years}"

    def test_no_duplicate_time_period_sex_combinations(self, latest_inactivity):
        """Test that there are no duplicate time period + sex combinations."""
        duplicates = latest_inactivity.duplicated(subset=["time_period", "sex"], keep=False)

        if duplicates.any():
            dup_records = latest_inactivity[duplicates]
            assert False, f"Found {duplicates.sum()} duplicate time_period/sex combinations:\n{dup_records}"

    def test_historical_data_completeness(self, latest_inactivity):
        """Test that historical data includes multiple years.

        Table 2.21 should provide a time series with at least 10 years of data.
        """
        unique_periods = latest_inactivity["time_period"].unique()

        # Each unique period has 3 rows (Male, Female, All Persons)
        num_years = len(unique_periods)

        assert num_years >= 10, f"Expected at least 10 years of historical data, found {num_years} periods"


class TestCombinedLabourMarketIntegrity:
    """Test suite for combined labour market data validation.

    Tests that validate consistency across multiple tables (employment + inactivity).
    """

    @pytest.fixture(scope="class")
    def latest_employment(self):
        """Fetch latest employment data."""
        return labour_market.get_latest_employment(force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_inactivity(self):
        """Fetch latest economic inactivity data."""
        return labour_market.get_latest_economic_inactivity(force_refresh=False)

    def test_consistent_quarter_periods(self, latest_employment, latest_inactivity):
        """Test that employment and inactivity data are from the same quarter.

        Both tables should reference the same time period (e.g., "July to September 2025").
        """
        # Get quarter period from employment data
        emp_quarters = latest_employment["quarter_period"].unique()

        # Get latest time period from inactivity data
        inact_periods = latest_inactivity["time_period"].unique()
        latest_inact_period = inact_periods[-1]  # Last period is most recent

        # Employment should have one quarter period
        assert len(emp_quarters) == 1, f"Expected 1 quarter period, found {len(emp_quarters)}"

        emp_quarter = emp_quarters[0]

        # Both should refer to the same time period
        # Note: Format might differ slightly ("July to September" vs "Jul to Sep")
        # Extract year and validate it matches
        import re

        emp_year = re.search(r"\b(\d{4})\b", emp_quarter)
        inact_year = re.search(r"\b(\d{4})\b", latest_inact_period)

        if emp_year and inact_year:
            assert emp_year.group(1) == inact_year.group(1), (
                f"Employment data from {emp_quarter} but inactivity data from {latest_inact_period}"
            )

    def test_employment_plus_unemployment_plus_inactivity_reasonable(self, latest_employment, latest_inactivity):
        """Test that employment + unemployment + inactivity forms a coherent picture.

        The sum of employed, unemployed, and economically inactive should roughly
        equal the working age population.

        Note: We don't have unemployment data in current parser, so this test
        validates that employed + inactive is less than working age population.
        """
        # Get total employment (All Persons, All ages)
        emp_total = latest_employment[
            (latest_employment["age_group"] == "All ages") & (latest_employment["sex"] == "All Persons")
        ]["number"].values

        # Get latest economic inactivity (All Persons)
        latest_period = latest_inactivity["time_period"].unique()[-1]
        inact_total = latest_inactivity[
            (latest_inactivity["time_period"] == latest_period) & (latest_inactivity["sex"] == "All Persons")
        ]["economically_inactive_number"].values

        if len(emp_total) > 0 and len(inact_total) > 0:
            employed = emp_total[0]
            inactive = inact_total[0]

            # Employed + inactive should be less than working age population (~1.2M)
            # (Missing unemployment component, typically ~30-50k)
            total = employed + inactive

            assert total < 1_300_000, (
                f"Employed ({employed:,}) + Inactive ({inactive:,}) = {total:,} "
                "exceeds reasonable working age population (~1.2M)"
            )

            assert total > 1_000_000, (
                f"Employed ({employed:,}) + Inactive ({inactive:,}) = {total:,} "
                "seems too low for working age population (~1.2M)"
            )


class TestLGDEmploymentIntegrity:
    """Test suite for employment by Local Government District data (Table 1.16a).

    Validates annual LGD employment data for internal consistency and quality.
    """

    @pytest.fixture(scope="class")
    def latest_lgd_employment(self):
        """Fetch latest LGD employment data once for the test class."""
        return labour_market.get_latest_employment_by_lgd(force_refresh=False)

    def test_data_structure(self, latest_lgd_employment):
        """Test that LGD employment data has correct structure."""
        assert len(latest_lgd_employment) > 0
        required_cols = [
            "year",
            "lgd",
            "population_16plus",
            "economically_active",
            "in_employment",
            "full_time_employment",
            "part_time_employment",
            "economically_inactive",
            "economic_activity_rate",
            "employment_rate",
        ]
        assert all(col in latest_lgd_employment.columns for col in required_cols)

    def test_eleven_lgds(self, latest_lgd_employment):
        """Test that data includes all 11 Northern Ireland LGDs."""
        assert len(latest_lgd_employment) == 11

    def test_lgd_names_valid(self, latest_lgd_employment):
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
            "Newry Mourne and Down",
        }
        assert set(latest_lgd_employment["lgd"].unique()) == expected_lgds

    def test_no_missing_values(self, latest_lgd_employment):
        """Test that there are no missing values in key columns."""
        numeric_cols = [
            "population_16plus",
            "economically_active",
            "in_employment",
            "full_time_employment",
            "part_time_employment",
            "economically_inactive",
            "economic_activity_rate",
            "employment_rate",
        ]
        for col in numeric_cols:
            assert not latest_lgd_employment[col].isna().any(), f"Column {col} has missing values"

    def test_employment_components_sum(self, latest_lgd_employment):
        """Test that full-time + part-time = total employment for each LGD."""
        for _, row in latest_lgd_employment.iterrows():
            ft = row["full_time_employment"]
            pt = row["part_time_employment"]
            total = row["in_employment"]
            lgd = row["lgd"]

            # Allow for rounding differences
            assert abs((ft + pt) - total) <= 1, (
                f"{lgd}: Full-time ({ft}) + Part-time ({pt}) = {ft + pt} != Total employment ({total})"
            )

    def test_active_inactive_sum(self, latest_lgd_employment):
        """Test that economically active + inactive = population 16+ for each LGD."""
        for _, row in latest_lgd_employment.iterrows():
            active = row["economically_active"]
            inactive = row["economically_inactive"]
            pop = row["population_16plus"]
            lgd = row["lgd"]

            # Allow for rounding differences
            assert abs((active + inactive) - pop) <= 1, (
                f"{lgd}: Active ({active}) + Inactive ({inactive}) = {active + inactive} != Population 16+ ({pop})"
            )

    def test_employment_rate_calculation(self, latest_lgd_employment):
        """Test that employment rate is correctly calculated."""
        for _, row in latest_lgd_employment.iterrows():
            employment = row["in_employment"]
            population = row["population_16plus"]
            rate = row["employment_rate"]
            lgd = row["lgd"]

            expected_rate = (employment / population) * 100

            # Allow for rounding differences (within 1%)
            assert abs(rate - expected_rate) < 1.0, (
                f"{lgd}: Employment rate {rate}% != expected {expected_rate:.1f}% "
                f"(Employment {employment} / Population {population})"
            )

    def test_economic_activity_rate_calculation(self, latest_lgd_employment):
        """Test that economic activity rate is correctly calculated."""
        for _, row in latest_lgd_employment.iterrows():
            active = row["economically_active"]
            population = row["population_16plus"]
            rate = row["economic_activity_rate"]
            lgd = row["lgd"]

            expected_rate = (active / population) * 100

            # Allow for rounding differences (within 1%)
            assert abs(rate - expected_rate) < 1.0, (
                f"{lgd}: Activity rate {rate}% != expected {expected_rate:.1f}% "
                f"(Active {active} / Population {population})"
            )

    def test_year_value(self, latest_lgd_employment):
        """Test that year is reasonable."""
        year = latest_lgd_employment["year"].unique()[0]
        assert 2020 <= year <= 2030

    def test_no_duplicates(self, latest_lgd_employment):
        """Test that there are no duplicate LGD rows."""
        assert not latest_lgd_employment["lgd"].duplicated().any()
