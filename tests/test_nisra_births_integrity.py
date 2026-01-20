"""Data integrity tests for NISRA births statistics.

These tests validate that the data is internally consistent across different
dimensions and time periods. They use real data from NISRA (not mocked) and
should work with any dataset (latest or historical).

Key validations:
- Total births should equal sum of male + female births
- No negative values
- Realistic birth counts (not impossibly high/low)
- Temporal continuity (no missing months in time series)
- Registration vs occurrence consistency
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import births


class TestBirthsDataIntegrity:
    """Test suite for validating internal consistency of births data."""

    @pytest.fixture(scope="class")
    def latest_births_data(self):
        """Fetch latest data with both event types once for the test class."""
        return births.get_latest_births(event_type="both", force_refresh=False)

    @pytest.fixture(scope="class")
    def registration_data(self, latest_births_data):
        """Registration data fixture."""
        return latest_births_data["registration"]

    @pytest.fixture(scope="class")
    def occurrence_data(self, latest_births_data):
        """Occurrence data fixture."""
        return latest_births_data["occurrence"]

    def test_sex_sum_to_total_registration(self, registration_data):
        """Test that male + female births equal persons births for registration data."""
        months = registration_data["month"].unique()

        for month in months:
            month_data = registration_data[registration_data["month"] == month]

            persons = month_data[month_data["sex"] == "Persons"]["births"].sum()
            male = month_data[month_data["sex"] == "Male"]["births"].sum()
            female = month_data[month_data["sex"] == "Female"]["births"].sum()

            assert persons > 0, f"Month {month.date()}: Persons births is zero"
            assert male > 0, f"Month {month.date()}: Male births is zero"
            assert female > 0, f"Month {month.date()}: Female births is zero"

            assert persons == male + female, (
                f"Month {month.date()}: Persons ({persons}) != Male ({male}) + Female ({female})"
            )

    def test_sex_sum_to_total_occurrence(self, occurrence_data):
        """Test that male + female births equal persons births for occurrence data."""
        months = occurrence_data["month"].unique()

        for month in months:
            month_data = occurrence_data[occurrence_data["month"] == month]

            persons = month_data[month_data["sex"] == "Persons"]["births"].sum()
            male = month_data[month_data["sex"] == "Male"]["births"].sum()
            female = month_data[month_data["sex"] == "Female"]["births"].sum()

            assert persons > 0, f"Month {month.date()}: Persons births is zero"
            assert male > 0, f"Month {month.date()}: Male births is zero"
            assert female > 0, f"Month {month.date()}: Female births is zero"

            assert persons == male + female, (
                f"Month {month.date()}: Persons ({persons}) != Male ({male}) + Female ({female})"
            )

    def test_no_negative_values(self, latest_births_data):
        """Test that there are no negative birth counts."""
        for event_type, df in latest_births_data.items():
            assert (df["births"] >= 0).all(), f"{event_type} data contains negative births"

    def test_realistic_monthly_ranges(self, latest_births_data):
        """Test that monthly births are within realistic ranges.

        NI has ~1,200-2,600 births per month historically.
        Anything outside 50-5,000 would be suspicious.

        Note: Registration data has anomalies in April-May 2020 (COVID-19 lockdown,
        registration offices closed) with only 93 and 408 registrations respectively.
        These are real data points reflecting administrative disruption, not birth occurrence.
        Occurrence data remains normal during this period (~1,650-1,750 births).
        """
        for event_type, df in latest_births_data.items():
            persons_data = df[df["sex"] == "Persons"]

            min_births = persons_data["births"].min()
            max_births = persons_data["births"].max()

            # Lower threshold for registration data (COVID-19 disruption in April 2020 = 93 births)
            # Higher threshold for occurrence data (actual births should be 500+)
            min_threshold = 50 if event_type == "registration" else 500

            assert min_births >= min_threshold, f"{event_type}: Suspiciously low births ({min_births})"
            assert max_births <= 5000, f"{event_type}: Suspiciously high births ({max_births})"

    def test_temporal_continuity_registration(self, registration_data):
        """Test that there are no missing months in the time series for registration data."""
        persons_data = registration_data[registration_data["sex"] == "Persons"].copy()
        persons_data = persons_data.sort_values("month")

        # Get min and max dates
        min_date = persons_data["month"].min()
        max_date = persons_data["month"].max()

        # Create expected date range (monthly frequency)
        expected_dates = pd.date_range(start=min_date, end=max_date, freq="MS")  # Month Start

        # Check all expected dates are present
        actual_dates = set(persons_data["month"])
        expected_dates_set = set(expected_dates)

        missing_dates = expected_dates_set - actual_dates

        assert len(missing_dates) == 0, f"Missing months in registration data: {sorted(missing_dates)}"

    def test_temporal_continuity_occurrence(self, occurrence_data):
        """Test that there are no missing months in the time series for occurrence data."""
        persons_data = occurrence_data[occurrence_data["sex"] == "Persons"].copy()
        persons_data = persons_data.sort_values("month")

        # Get min and max dates
        min_date = persons_data["month"].min()
        max_date = persons_data["month"].max()

        # Create expected date range (monthly frequency)
        expected_dates = pd.date_range(start=min_date, end=max_date, freq="MS")

        # Check all expected dates are present
        actual_dates = set(persons_data["month"])
        expected_dates_set = set(expected_dates)

        missing_dates = expected_dates_set - actual_dates

        assert len(missing_dates) == 0, f"Missing months in occurrence data: {sorted(missing_dates)}"

    def test_chronological_ordering(self, latest_births_data):
        """Test that data can be sorted chronologically without issues."""
        for event_type, df in latest_births_data.items():
            sorted_df = df.sort_values(["month", "sex"])

            # Check no NaT (Not a Time) values
            assert not sorted_df["month"].isna().any(), f"{event_type} has NaT values"

            # Check months are valid
            assert (sorted_df["month"].dt.year >= 2000).all(), f"{event_type} has pre-2000 dates"
            assert (sorted_df["month"].dt.year <= 2030).all(), f"{event_type} has future dates beyond 2030"

    def test_sex_ratio_realistic(self, latest_births_data):
        """Test that male/female ratio is within realistic bounds (95-105 males per 100 females)."""
        for event_type, df in latest_births_data.items():
            # Calculate overall sex ratio
            total_male = df[df["sex"] == "Male"]["births"].sum()
            total_female = df[df["sex"] == "Female"]["births"].sum()

            sex_ratio = (total_male / total_female) * 100  # Males per 100 females

            # Biological sex ratio at birth is typically 103-107 males per 100 females
            # Allow wider range (95-110) to account for statistical variation
            assert 95 <= sex_ratio <= 110, (
                f"{event_type}: Sex ratio ({sex_ratio:.1f} males per 100 females) outside realistic range"
            )

    def test_registration_lags_occurrence(self, registration_data, occurrence_data):
        """Test that registration data includes more recent months than occurrence data.

        Registration is ongoing, so latest registration month should be >= latest occurrence month.
        """
        latest_registration = registration_data["month"].max()
        latest_occurrence = occurrence_data["month"].max()

        assert latest_registration >= latest_occurrence, (
            f"Registration data ({latest_registration.date()}) should be at least as recent as "
            f"occurrence data ({latest_occurrence.date()})"
        )

    def test_annual_totals_similar_registration_occurrence(self, registration_data, occurrence_data):
        """Test that annual totals are similar between registration and occurrence.

        Over a full year, total registrations should approximately equal total occurrences
        (within ~5% due to cross-year registration delays).
        """
        # Calculate annual totals for persons
        reg_annual = (
            registration_data[registration_data["sex"] == "Persons"]
            .copy()
            .assign(year=lambda x: x["month"].dt.year)
            .groupby("year")["births"]
            .sum()
        )

        occ_annual = (
            occurrence_data[occurrence_data["sex"] == "Persons"]
            .copy()
            .assign(year=lambda x: x["month"].dt.year)
            .groupby("year")["births"]
            .sum()
        )

        # Compare years that exist in both datasets (excluding recent incomplete years)
        common_years = set(reg_annual.index) & set(occ_annual.index)

        # Exclude current year and previous year as data may be incomplete
        # (NISRA data typically has a publication lag of several months)
        current_year = pd.Timestamp.now().year
        common_years = common_years - {current_year, current_year - 1}

        for year in sorted(common_years):
            reg_total = reg_annual[year]
            occ_total = occ_annual[year]

            # Calculate percentage difference
            pct_diff = abs(reg_total - occ_total) / occ_total * 100

            assert pct_diff < 5, (
                f"Year {year}: Registration ({reg_total}) and occurrence ({occ_total}) "
                f"differ by {pct_diff:.1f}% (expected <5%)"
            )

    def test_required_columns_present(self, latest_births_data):
        """Test that all required columns are present."""
        required_columns = {"month", "sex", "births"}

        for event_type, df in latest_births_data.items():
            assert set(df.columns) == required_columns, f"{event_type} has incorrect columns: {set(df.columns)}"

    def test_sex_categories_complete(self, latest_births_data):
        """Test that all expected sex categories are present."""
        expected_sexes = {"Persons", "Male", "Female"}

        for event_type, df in latest_births_data.items():
            actual_sexes = set(df["sex"].unique())
            assert actual_sexes == expected_sexes, f"{event_type}: Expected sexes {expected_sexes}, got {actual_sexes}"

    def test_monthly_distribution_reasonable(self, latest_births_data):
        """Test that births are reasonably distributed across months.

        No single month should have >20% of annual births (would be ~8.3% if evenly distributed).
        """
        for event_type, df in latest_births_data.items():
            persons_data = df[df["sex"] == "Persons"].copy()

            # Group by year
            persons_data = persons_data.assign(
                year=lambda x: x["month"].dt.year, month_num=lambda x: x["month"].dt.month
            )

            # For each year, check distribution across months
            for year in persons_data["year"].unique():
                year_data = persons_data[persons_data["year"] == year]

                # Skip if incomplete year (< 12 months)
                if len(year_data) < 12:
                    continue

                annual_total = year_data["births"].sum()
                max_month = year_data["births"].max()

                max_pct = (max_month / annual_total) * 100

                assert max_pct < 20, f"{event_type} - Year {year}: Single month has {max_pct:.1f}% of annual births"

    def test_declining_trend_recent_years(self, latest_births_data):
        """Test that recent birth trends align with known demographic patterns.

        NI births have been declining since ~2008 peak. Not a strict test but checks
        that 2024 births < 2015 births (general downward trend).
        """
        for event_type, df in latest_births_data.items():
            persons_data = df[df["sex"] == "Persons"].copy()

            # Get annual totals
            annual = persons_data.assign(year=lambda x: x["month"].dt.year).groupby("year")["births"].sum()

            # Check if we have data for these years
            if 2015 in annual.index and 2024 in annual.index:
                births_2015 = annual[2015]
                births_2024 = annual[2024]

                assert births_2024 < births_2015, (
                    f"{event_type}: Expected declining trend, but 2024 ({births_2024}) >= 2015 ({births_2015})"
                )

    def test_validate_function_works(self, registration_data):
        """Test that the validate_births_totals function works correctly."""
        # Should pass with valid data
        assert births.validate_births_totals(registration_data)

        # Create invalid data
        invalid_data = registration_data.copy()
        invalid_data.loc[invalid_data["sex"] == "Male", "births"] = 0

        # Should fail
        with pytest.raises(births.NISRAValidationError):
            births.validate_births_totals(invalid_data)
