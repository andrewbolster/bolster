"""Data integrity tests for NISRA deaths statistics.

These tests validate that the data is internally consistent across different
dimensions and breakdowns. They use real data from NISRA (not mocked) and
should work with any dataset (latest or historical).

Key validations:
- Total deaths should equal sum of male + female deaths
- Total deaths should equal sum of all geographies
- Total deaths should equal sum of all places of death
- Age breakdowns should sum to totals
- Cross-dimension consistency for the same weeks
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import deaths


class TestDeathsDataIntegrity:
    """Test suite for validating internal consistency of deaths data."""

    @pytest.fixture(scope="class")
    def latest_all_dimensions(self):
        """Fetch latest data with all dimensions once for the test class."""
        return deaths.get_latest_deaths(dimension="all", force_refresh=False)

    @pytest.fixture(scope="class")
    def latest_totals(self):
        """Fetch latest totals dimension."""
        return deaths.get_latest_deaths(dimension="totals", force_refresh=False)

    def test_demographics_sum_to_total(self, latest_all_dimensions):
        """Test that male + female deaths equal total deaths for each week."""
        demographics = latest_all_dimensions["demographics"]

        # Get weeks that have data
        weeks = demographics["week_ending"].unique()

        for week in weeks:
            week_data = demographics[demographics["week_ending"] == week]

            # Filter for 'All' ages to avoid double counting across age groups
            all_ages = week_data[week_data["age_range"] == "All"]

            # Get totals
            total_deaths = all_ages[all_ages["sex"].str.contains("Total", na=False, case=False)]["deaths"].sum()

            # Get male deaths (excluding Female from the match)
            male_deaths = all_ages[
                all_ages["sex"].str.contains("Male", na=False, case=False)
                & ~all_ages["sex"].str.contains("Female", na=False, case=False)
            ]["deaths"].sum()

            # Get female deaths
            female_deaths = all_ages[all_ages["sex"].str.contains("Female", na=False, case=False)]["deaths"].sum()

            # Validate: total should equal male + female
            assert total_deaths > 0, f"Week {week}: Total deaths is zero or missing"
            assert male_deaths > 0, f"Week {week}: Male deaths is zero or missing"
            assert female_deaths > 0, f"Week {week}: Female deaths is zero or missing"

            assert total_deaths == male_deaths + female_deaths, (
                f"Week {week}: Total deaths ({total_deaths}) != "
                f"Male ({male_deaths}) + Female ({female_deaths}) = {male_deaths + female_deaths}"
            )

    def test_geography_sum_to_total(self, latest_all_dimensions, latest_totals):
        """Test that sum of all LGD deaths equals total deaths for each week."""
        geography = latest_all_dimensions["geography"]
        totals = latest_totals

        # Group geography by week and sum
        geo_weekly_totals = geography.groupby("week_ending")["deaths"].sum()

        # Compare with totals dimension
        for week_ending in geo_weekly_totals.index:
            geo_total = geo_weekly_totals[week_ending]

            # Get corresponding total from totals dimension
            totals_match = totals[totals["week_ending"] == week_ending]

            if not totals_match.empty:
                observed_total = totals_match["observed_deaths"].iloc[0]

                assert geo_total == observed_total, (
                    f"Week {week_ending.date()}: Geography sum ({geo_total}) != Observed total ({observed_total})"
                )

    def test_place_sum_to_total(self, latest_all_dimensions, latest_totals):
        """Test that sum of all places of death equals total deaths for each week."""
        place = latest_all_dimensions["place"]
        totals = latest_totals

        # Group place by week and sum
        place_weekly_totals = place.groupby("week_ending")["deaths"].sum()

        # Compare with totals dimension
        for week_ending in place_weekly_totals.index:
            place_total = place_weekly_totals[week_ending]

            # Get corresponding total from totals dimension
            totals_match = totals[totals["week_ending"] == week_ending]

            if not totals_match.empty:
                observed_total = totals_match["observed_deaths"].iloc[0]

                assert place_total == observed_total, (
                    f"Week {week_ending.date()}: Place sum ({place_total}) != Observed total ({observed_total})"
                )

    def test_demographics_age_breakdowns_sum_to_total(self, latest_all_dimensions):
        """Test that sum of all age ranges equals total for each sex category."""
        demographics = latest_all_dimensions["demographics"]

        # Get unique weeks
        weeks = demographics["week_ending"].unique()

        for week in weeks:
            week_data = demographics[demographics["week_ending"] == week]

            # For each sex category, check age breakdowns
            sex_categories = week_data["sex"].unique()

            for sex in sex_categories:
                sex_data = week_data[week_data["sex"] == sex]

                # Get 'All' ages total
                all_ages = sex_data[sex_data["age_range"] == "All"]["deaths"].sum()

                # Get sum of specific age ranges (exclude 'All')
                age_ranges_sum = sex_data[sex_data["age_range"] != "All"]["deaths"].sum()

                # They should match
                if all_ages > 0:  # Only check if we have data
                    assert all_ages == age_ranges_sum, (
                        f"Week {week.date()}, Sex {sex}: "
                        f"All ages total ({all_ages}) != "
                        f"Sum of age ranges ({age_ranges_sum})"
                    )

    def test_no_negative_deaths(self, latest_all_dimensions, latest_totals):
        """Test that there are no negative death counts in any dimension."""
        # Check totals
        assert (latest_totals["observed_deaths"] >= 0).all(), "Found negative deaths in totals"

        # Check demographics
        assert (latest_all_dimensions["demographics"]["deaths"] >= 0).all(), "Found negative deaths in demographics"

        # Check geography
        assert (latest_all_dimensions["geography"]["deaths"] >= 0).all(), "Found negative deaths in geography"

        # Check place
        assert (latest_all_dimensions["place"]["deaths"] >= 0).all(), "Found negative deaths in place"

    def test_reasonable_weekly_death_counts(self, latest_totals):
        """Test that weekly death counts are within reasonable bounds for NI.

        Northern Ireland has a population of ~1.9 million. Based on crude death rate
        of ~9 per 1,000, we'd expect roughly 330 deaths per week on average.
        This test checks deaths are within plausible bounds (100-800 per week).
        """
        min_expected = 100  # Well below normal minimum
        max_expected = 800  # Well above typical maximum (even during COVID peaks)

        too_low = latest_totals[latest_totals["observed_deaths"] < min_expected]
        too_high = latest_totals[latest_totals["observed_deaths"] > max_expected]

        assert len(too_low) == 0, (
            f"Found {len(too_low)} weeks with unreasonably low deaths (<{min_expected}): "
            f"{too_low[['week_ending', 'observed_deaths']].to_dict('records')}"
        )

        assert len(too_high) == 0, (
            f"Found {len(too_high)} weeks with unreasonably high deaths (>{max_expected}): "
            f"{too_high[['week_ending', 'observed_deaths']].to_dict('records')}"
        )

    def test_covid_deaths_not_exceed_total(self, latest_totals):
        """Test that COVID deaths don't exceed total deaths in any week."""
        # COVID deaths should always be <= total deaths
        invalid = latest_totals[latest_totals["covid_deaths"] > latest_totals["observed_deaths"]]

        assert len(invalid) == 0, (
            f"Found {len(invalid)} weeks where COVID deaths exceed total deaths: "
            f"{invalid[['week_ending', 'covid_deaths', 'observed_deaths']].to_dict('records')}"
        )

    def test_flu_pneumonia_deaths_not_exceed_total(self, latest_totals):
        """Test that flu/pneumonia deaths don't exceed total deaths in any week."""
        invalid = latest_totals[latest_totals["flu_pneumonia_deaths"] > latest_totals["observed_deaths"]]

        assert len(invalid) == 0, (
            f"Found {len(invalid)} weeks where flu/pneumonia deaths exceed total deaths: "
            f"{invalid[['week_ending', 'flu_pneumonia_deaths', 'observed_deaths']].to_dict('records')}"
        )

    def test_weeks_are_chronological(self, latest_totals):
        """Test that weeks are in chronological order."""
        # Check that week_ending dates are sorted
        sorted_dates = latest_totals["week_ending"].is_monotonic_increasing

        assert sorted_dates, "Week ending dates are not in chronological order"

    def test_no_duplicate_weeks(self, latest_all_dimensions):
        """Test that there are no duplicate weeks in any dimension."""
        # Check totals
        demographics = latest_all_dimensions["demographics"]
        geography = latest_all_dimensions["geography"]
        place = latest_all_dimensions["place"]

        # For demographics, check unique combinations of week + sex + age
        demo_duplicates = demographics.duplicated(subset=["week_ending", "sex", "age_range"])
        assert not demo_duplicates.any(), f"Found {demo_duplicates.sum()} duplicate records in demographics"

        # For geography, check unique combinations of week + lgd
        geo_duplicates = geography.duplicated(subset=["week_ending", "lgd"])
        assert not geo_duplicates.any(), f"Found {geo_duplicates.sum()} duplicate records in geography"

        # For place, check unique combinations of week + place
        place_duplicates = place.duplicated(subset=["week_ending", "place_of_death"])
        assert not place_duplicates.any(), f"Found {place_duplicates.sum()} duplicate records in place"

    def test_all_lgds_present_each_week(self, latest_all_dimensions):
        """Test that all 11 NI Local Government Districts are present for each week."""
        geography = latest_all_dimensions["geography"]

        expected_lgd_count = 11  # Northern Ireland has 11 LGDs
        weeks = geography["week_ending"].unique()

        for week in weeks:
            week_lgds = geography[geography["week_ending"] == week]["lgd"].nunique()

            assert week_lgds == expected_lgd_count, (
                f"Week {week.date()}: Expected {expected_lgd_count} LGDs, found {week_lgds}"
            )

    def test_cross_dimension_totals_match(self, latest_all_dimensions, latest_totals):
        """Test that demographics total deaths match the totals dimension.

        This validates that the different tables (demographics and totals) are
        consistent for the same weeks.
        """
        demographics = latest_all_dimensions["demographics"]

        # Get total deaths from demographics (Total sex, All ages)
        demo_totals = demographics[
            (demographics["sex"].str.contains("Total", na=False, case=False)) & (demographics["age_range"] == "All")
        ].copy()

        # Merge with totals dimension
        merged = demo_totals.merge(latest_totals[["week_ending", "observed_deaths"]], on="week_ending", how="inner")

        # Compare
        for _, row in merged.iterrows():
            demo_total = row["deaths"]
            obs_total = row["observed_deaths"]

            assert demo_total == obs_total, (
                f"Week {row['week_ending'].date()}: Demographics total ({demo_total}) != Totals dimension ({obs_total})"
            )

    def test_expected_sex_categories(self, latest_all_dimensions):
        """Test that expected sex categories are present."""
        demographics = latest_all_dimensions["demographics"]

        sex_categories = demographics["sex"].unique()

        # Should have Total, Male, and Female (exact names may vary)
        has_total = any("total" in str(s).lower() for s in sex_categories)
        has_male = any("male" in str(s).lower() and "female" not in str(s).lower() for s in sex_categories)
        has_female = any("female" in str(s).lower() for s in sex_categories)

        assert has_total, f"Missing 'Total' sex category. Found: {sex_categories}"
        assert has_male, f"Missing 'Male' sex category. Found: {sex_categories}"
        assert has_female, f"Missing 'Female' sex category. Found: {sex_categories}"

    def test_expected_age_ranges(self, latest_all_dimensions):
        """Test that expected age ranges are present."""
        demographics = latest_all_dimensions["demographics"]

        age_ranges = demographics["age_range"].unique()

        # Should have 'All' plus specific age bands
        assert "All" in age_ranges, f"Missing 'All' age range. Found: {age_ranges}"

        # Should have at least 5 specific age ranges (excluding 'All')
        specific_ranges = [a for a in age_ranges if a != "All"]
        assert len(specific_ranges) >= 5, (
            f"Expected at least 5 specific age ranges, found {len(specific_ranges)}: {specific_ranges}"
        )

    def test_expected_place_categories(self, latest_all_dimensions):
        """Test that expected place of death categories are present."""
        place = latest_all_dimensions["place"]

        places = place["place_of_death"].unique()

        # Key places we expect (case-insensitive, partial match)
        expected_keywords = ["hospital", "home", "hospice"]

        for keyword in expected_keywords:
            found = any(keyword in str(p).lower() for p in places)
            assert found, f"Missing expected place containing '{keyword}'. Found: {places}"


class TestHistoricalDeathsIntegrity:
    """Test suite for validating historical deaths data integrity."""

    @pytest.fixture(scope="class")
    def historical_data_sample(self):
        """Fetch a sample of historical data (2024 only) for testing."""
        return deaths.get_historical_deaths(years=[2024], force_refresh=False)

    @pytest.fixture(scope="class")
    def historical_with_age(self):
        """Fetch historical data with age breakdowns."""
        return deaths.get_historical_deaths(years=[2024], include_age_breakdowns=True, force_refresh=False)

    def test_historical_age_breakdowns_sum_to_total(self, historical_with_age):
        """Test that age breakdowns sum to total deaths for each week."""
        totals = historical_with_age["totals"]
        age_data = historical_with_age["age_breakdowns"]

        # Sum age breakdowns by week
        age_weekly_sums = age_data.groupby("week_ending")["deaths"].sum()

        for week_ending in age_weekly_sums.index:
            age_sum = age_weekly_sums[week_ending]

            # Get corresponding total
            total_match = totals[totals["week_ending"] == week_ending]

            if not total_match.empty:
                total_deaths = total_match["total_deaths"].iloc[0]

                assert age_sum == total_deaths, (
                    f"Week {week_ending.date()}: Age breakdown sum ({age_sum}) != Total deaths ({total_deaths})"
                )

    def test_historical_covid_and_respiratory_consistency(self, historical_data_sample):
        """Test that COVID deaths are included in respiratory deaths counts.

        COVID-19 is classified as a respiratory disease, so deaths involving COVID
        should generally be <= deaths involving respiratory diseases.
        """
        df = historical_data_sample

        # Filter to weeks where we have both values
        with_both = df[df["covid_deaths_involving"].notna() & df["respiratory_deaths_involving"].notna()]

        # COVID deaths should not exceed respiratory deaths
        # (though they may be equal in weeks with only COVID respiratory deaths)
        invalid = with_both[with_both["covid_deaths_involving"] > with_both["respiratory_deaths_involving"]]

        assert len(invalid) == 0, (
            f"Found {len(invalid)} weeks where COVID deaths exceed respiratory deaths: "
            f"{invalid[['week_ending', 'covid_deaths_involving', 'respiratory_deaths_involving']].to_dict('records')}"
        )

    def test_historical_no_future_dates(self, historical_data_sample):
        """Test that historical data doesn't contain future dates."""
        df = historical_data_sample
        today = pd.Timestamp.now()

        future_dates = df[df["week_ending"] > today]

        assert len(future_dates) == 0, (
            f"Found {len(future_dates)} records with future dates: {future_dates['week_ending'].tolist()}"
        )

    def test_covid_deaths_timeline(self):
        """Test that COVID deaths follow expected timeline.

        COVID-19 emerged in late 2019/early 2020. We should see:
        - Very low COVID deaths before 2020 (some data quality issues in source)
        - Significant COVID deaths from 2020 onwards

        Note: NISRA's historical data has some apparent coding errors with ~39
        "COVID deaths" reported in 2019, which is impossible. This test allows
        for some source data quality issues but validates the overall pattern.
        """
        # Get data for years around pandemic start
        df = deaths.get_historical_deaths(years=[2019, 2020, 2021], force_refresh=False)

        # Check 2019: should have very low COVID deaths
        # (ideally 0, but source data has quality issues)
        covid_2019 = df[df["year"] == 2019]["covid_deaths_involving"].sum()

        assert covid_2019 < 100, (
            f"Found {covid_2019} COVID deaths in 2019. "
            "Expected < 100 (source has some data quality issues, but shouldn't be high)."
        )

        # Check 2020: should have significant COVID deaths
        covid_2020 = df[df["year"] == 2020]["covid_deaths_involving"].sum()

        assert covid_2020 > 1000, (
            f"Found only {covid_2020} COVID deaths in 2020. "
            "Expected significant numbers (>1000) during first pandemic year."
        )

        # COVID in 2020 should be >> COVID in 2019 (orders of magnitude more)
        assert covid_2020 > covid_2019 * 10, (
            f"COVID deaths in 2020 ({covid_2020}) should be much higher than "
            f"2019 ({covid_2019}). Expected at least 10x increase."
        )

    def test_excess_deaths_reasonable_bounds(self, historical_data_sample):
        """Test that excess deaths are within reasonable bounds.

        Excess deaths can be positive or negative, but should not be extreme.
        During COVID peaks, excess deaths reached ~150-200 per week.
        During quiet periods, can be -50 to -100.
        """
        df = historical_data_sample

        # Filter to where excess deaths are available
        with_excess = df[df["excess_deaths"].notna()]

        if len(with_excess) == 0:
            pytest.skip("No excess deaths data available")

        # Check for extreme values
        max_excess = with_excess["excess_deaths"].max()
        min_excess = with_excess["excess_deaths"].min()

        # During COVID peaks, saw ~200 excess deaths/week
        # Allow some headroom but flag if wildly beyond historical max
        assert max_excess < 300, (
            f"Found extreme positive excess deaths: {max_excess}. This exceeds historical COVID peaks (~200)."
        )

        # Negative excess deaths of -150 seen in some periods
        # Flag if much more negative
        assert min_excess > -200, f"Found extreme negative excess deaths: {min_excess}. This is unusually low."

    def test_historical_year_completeness(self):
        """Test that historical years have complete data (52 or 53 weeks).

        Each year should have 52 or 53 weeks depending on how ISO week boundaries fall.
        Incomplete years suggest data issues.
        """
        # Check last 3 complete years (excluding current and previous year due to publication lag)
        from datetime import datetime

        current_year = datetime.now().year
        years_to_check = [current_year - 4, current_year - 3, current_year - 2]

        df = deaths.get_historical_deaths(years=years_to_check, force_refresh=False)

        for year in years_to_check:
            year_data = df[df["year"] == year]
            week_count = len(year_data)

            assert week_count >= 52, (
                f"Year {year} has only {week_count} weeks. Expected 52 or 53 weeks for complete year."
            )

            assert week_count <= 53, f"Year {year} has {week_count} weeks. Expected maximum 53 weeks."


class TestCombinedDeathsIntegrity:
    """Test suite for combined historical + current data."""

    @pytest.fixture(scope="class")
    def combined_data(self):
        """Fetch combined data (2 complete historical years + current)."""
        from datetime import datetime

        current_year = datetime.now().year
        # Use years with complete data (current-3, current-2) due to publication lag
        return deaths.get_combined_deaths(
            years=[current_year - 3, current_year - 2], include_current_year=True, force_refresh=False
        )

    def test_combined_data_sources_labeled(self, combined_data):
        """Test that all records have a data_source label."""
        assert "data_source" in combined_data.columns, "Missing data_source column"

        # Check all records have a source
        missing_source = combined_data["data_source"].isna().sum()
        assert missing_source == 0, f"Found {missing_source} records without data_source"

        # Check valid sources
        valid_sources = {"historical", "current"}
        invalid = combined_data[~combined_data["data_source"].isin(valid_sources)]

        assert len(invalid) == 0, (
            f"Found {len(invalid)} records with invalid data_source: {invalid['data_source'].unique()}"
        )

    def test_combined_no_duplicate_weeks(self, combined_data):
        """Test that there are no duplicate weeks in combined data."""
        duplicates = combined_data.duplicated(subset=["week_ending"])

        assert not duplicates.any(), f"Found {duplicates.sum()} duplicate weeks in combined data"

    def test_combined_chronological_order(self, combined_data):
        """Test that combined data is in chronological order."""
        is_sorted = combined_data["week_ending"].is_monotonic_increasing

        assert is_sorted, "Combined data is not in chronological order"

    def test_combined_no_gaps_in_weeks(self, combined_data):
        """Test that there are no unexpected gaps in the weekly time series.

        We allow for year boundaries (52/53 week years) but within a year
        there shouldn't be missing weeks.
        """
        df = combined_data.sort_values("week_ending")

        # Calculate week differences
        week_diffs = df["week_ending"].diff().dt.days

        # Most weeks should be ~7 days apart
        # Allow for some variation (5-9 days) due to how week boundaries fall
        unusual_gaps = week_diffs[(week_diffs < 5) | (week_diffs > 9)]

        # Remove the first NaT
        unusual_gaps = unusual_gaps.dropna()

        # We might have one or two unusual gaps at year boundaries, but not many
        assert len(unusual_gaps) < 5, (
            f"Found {len(unusual_gaps)} unusual gaps in the time series: Gaps of {unusual_gaps.tolist()} days"
        )


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
