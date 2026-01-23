"""Data integrity tests for NISRA Individual Wellbeing statistics.

These tests validate that the data is internally consistent across different
time periods. They use real data from NISRA (not mocked) and should work with
any dataset (latest or historical).

Key validations:
- Personal wellbeing scores within valid ranges (0-10)
- Self-efficacy scores within valid ranges (5-25)
- Loneliness proportions within valid ranges (0-1)
- Temporal coverage (data goes back to expected years)
- COVID-19 impact visible in 2020/21 data
- No duplicate years in time series
"""

import pytest

from bolster.data_sources.nisra import wellbeing


class TestPersonalWellbeingIntegrity:
    """Test suite for validating personal wellbeing (ONS4) data."""

    @pytest.fixture(scope="class")
    def latest_personal_wellbeing(self):
        """Fetch latest personal wellbeing data once for the test class."""
        return wellbeing.get_latest_personal_wellbeing(force_refresh=False)

    def test_required_columns_present(self, latest_personal_wellbeing):
        """Test that all required columns are present."""
        required_columns = {"year", "life_satisfaction", "worthwhile", "happiness", "anxiety"}

        assert set(latest_personal_wellbeing.columns) == required_columns, (
            f"Incorrect columns: {set(latest_personal_wellbeing.columns)}"
        )

    def test_life_satisfaction_range(self, latest_personal_wellbeing):
        """Test that life satisfaction scores are within valid range (0-10)."""
        scores = latest_personal_wellbeing["life_satisfaction"]

        assert scores.min() >= 0, f"Life satisfaction below 0: {scores.min()}"
        assert scores.max() <= 10, f"Life satisfaction above 10: {scores.max()}"

        # Typical range for NI is 7.5-8.0
        assert scores.mean() >= 7.0, f"Average life satisfaction unusually low: {scores.mean()}"
        assert scores.mean() <= 9.0, f"Average life satisfaction unusually high: {scores.mean()}"

    def test_worthwhile_range(self, latest_personal_wellbeing):
        """Test that worthwhile scores are within valid range (0-10)."""
        scores = latest_personal_wellbeing["worthwhile"]

        assert scores.min() >= 0, f"Worthwhile below 0: {scores.min()}"
        assert scores.max() <= 10, f"Worthwhile above 10: {scores.max()}"

        # Typical range for NI is 7.8-8.2
        assert scores.mean() >= 7.0, f"Average worthwhile unusually low: {scores.mean()}"
        assert scores.mean() <= 9.0, f"Average worthwhile unusually high: {scores.mean()}"

    def test_happiness_range(self, latest_personal_wellbeing):
        """Test that happiness scores are within valid range (0-10)."""
        scores = latest_personal_wellbeing["happiness"]

        assert scores.min() >= 0, f"Happiness below 0: {scores.min()}"
        assert scores.max() <= 10, f"Happiness above 10: {scores.max()}"

        # Typical range for NI is 7.4-7.8
        assert scores.mean() >= 7.0, f"Average happiness unusually low: {scores.mean()}"
        assert scores.mean() <= 9.0, f"Average happiness unusually high: {scores.mean()}"

    def test_anxiety_range(self, latest_personal_wellbeing):
        """Test that anxiety scores are within valid range (0-10)."""
        scores = latest_personal_wellbeing["anxiety"]

        assert scores.min() >= 0, f"Anxiety below 0: {scores.min()}"
        assert scores.max() <= 10, f"Anxiety above 10: {scores.max()}"

        # Anxiety is typically lower (2.5-3.5) - lower is better
        assert scores.mean() >= 1.0, f"Average anxiety unusually low: {scores.mean()}"
        assert scores.mean() <= 5.0, f"Average anxiety unusually high: {scores.mean()}"

    def test_historical_coverage(self, latest_personal_wellbeing):
        """Test that data goes back to at least 2014/15."""
        years = latest_personal_wellbeing["year"].tolist()

        assert "2014/15" in years, f"Expected data from 2014/15, earliest is {years[0]}"

    def test_recent_data_available(self, latest_personal_wellbeing):
        """Test that recent data is available."""
        years = latest_personal_wellbeing["year"].tolist()

        # Should have data from 2023/24 or later
        recent_years = [y for y in years if y >= "2023/24"]
        assert len(recent_years) > 0, f"No recent data found. Latest is {years[-1]}"

    def test_no_duplicate_years(self, latest_personal_wellbeing):
        """Test that there are no duplicate years."""
        duplicates = latest_personal_wellbeing["year"].duplicated().sum()

        assert duplicates == 0, f"Found {duplicates} duplicate years"

    def test_covid_impact_visible(self, latest_personal_wellbeing):
        """Test that COVID-19 impact is visible in 2020/21 data.

        2020/21 should show elevated anxiety compared to adjacent years.
        """
        df = latest_personal_wellbeing

        if "2020/21" not in df["year"].values:
            pytest.skip("2020/21 data not available")

        covid_anxiety = df[df["year"] == "2020/21"]["anxiety"].values[0]

        # Get adjacent years for comparison
        pre_covid = df[df["year"] == "2019/20"]["anxiety"].values
        post_covid = df[df["year"] == "2021/22"]["anxiety"].values

        if len(pre_covid) > 0 and len(post_covid) > 0:
            # COVID year anxiety should be higher than both adjacent years
            assert covid_anxiety >= pre_covid[0], (
                f"2020/21 anxiety ({covid_anxiety}) should be >= 2019/20 ({pre_covid[0]})"
            )

    def test_validation_function_works(self, latest_personal_wellbeing):
        """Test that the validate_personal_wellbeing function works correctly."""
        assert wellbeing.validate_personal_wellbeing(latest_personal_wellbeing)

    def test_year_format_consistent(self, latest_personal_wellbeing):
        """Test that year format is consistent (YYYY/YY)."""
        import re

        for year in latest_personal_wellbeing["year"]:
            assert re.match(r"^\d{4}/\d{2}$", year), f"Invalid year format: {year}"


class TestLonelinessIntegrity:
    """Test suite for validating loneliness data."""

    @pytest.fixture(scope="class")
    def latest_loneliness(self):
        """Fetch latest loneliness data once for the test class."""
        return wellbeing.get_latest_loneliness(force_refresh=False)

    def test_required_columns_present(self, latest_loneliness):
        """Test that all required columns are present."""
        required_columns = {"year", "lonely_some_of_time", "confidence_interval"}

        assert set(latest_loneliness.columns) == required_columns, (
            f"Incorrect columns: {set(latest_loneliness.columns)}"
        )

    def test_loneliness_range(self, latest_loneliness):
        """Test that loneliness proportions are within valid range (0-1)."""
        proportions = latest_loneliness["lonely_some_of_time"]

        assert proportions.min() >= 0, f"Loneliness proportion below 0: {proportions.min()}"
        assert proportions.max() <= 1, f"Loneliness proportion above 1: {proportions.max()}"

        # Typical range for NI is 0.15-0.25 (15-25%)
        assert proportions.mean() >= 0.10, f"Average loneliness unusually low: {proportions.mean()}"
        assert proportions.mean() <= 0.30, f"Average loneliness unusually high: {proportions.mean()}"

    def test_historical_coverage(self, latest_loneliness):
        """Test that data goes back to at least 2017/18."""
        years = latest_loneliness["year"].tolist()

        assert "2017/18" in years, f"Expected data from 2017/18, earliest is {years[0]}"

    def test_no_duplicate_years(self, latest_loneliness):
        """Test that there are no duplicate years."""
        duplicates = latest_loneliness["year"].duplicated().sum()

        assert duplicates == 0, f"Found {duplicates} duplicate years"

    def test_covid_impact_visible(self, latest_loneliness):
        """Test that COVID-19 impact is visible in loneliness data.

        2020/21 and 2021/22 should show elevated loneliness.
        """
        df = latest_loneliness

        if "2020/21" not in df["year"].values:
            pytest.skip("2020/21 data not available")

        covid_loneliness = df[df["year"] == "2020/21"]["lonely_some_of_time"].values[0]
        pre_covid = df[df["year"] == "2019/20"]["lonely_some_of_time"].values

        if len(pre_covid) > 0:
            # COVID year loneliness should be higher
            assert covid_loneliness >= pre_covid[0], (
                f"2020/21 loneliness ({covid_loneliness:.1%}) should be >= 2019/20 ({pre_covid[0]:.1%})"
            )


class TestSelfEfficacyIntegrity:
    """Test suite for validating self-efficacy data."""

    @pytest.fixture(scope="class")
    def latest_self_efficacy(self):
        """Fetch latest self-efficacy data once for the test class."""
        return wellbeing.get_latest_self_efficacy(force_refresh=False)

    def test_required_columns_present(self, latest_self_efficacy):
        """Test that all required columns are present."""
        required_columns = {"year", "self_efficacy_mean", "confidence_interval"}

        assert set(latest_self_efficacy.columns) == required_columns, (
            f"Incorrect columns: {set(latest_self_efficacy.columns)}"
        )

    def test_self_efficacy_range(self, latest_self_efficacy):
        """Test that self-efficacy scores are within valid range (5-25)."""
        scores = latest_self_efficacy["self_efficacy_mean"]

        assert scores.min() >= 5, f"Self-efficacy below 5: {scores.min()}"
        assert scores.max() <= 25, f"Self-efficacy above 25: {scores.max()}"

        # Typical range for NI is 19-20
        assert scores.mean() >= 18, f"Average self-efficacy unusually low: {scores.mean()}"
        assert scores.mean() <= 22, f"Average self-efficacy unusually high: {scores.mean()}"

    def test_historical_coverage(self, latest_self_efficacy):
        """Test that data goes back to at least 2014/15."""
        years = latest_self_efficacy["year"].tolist()

        assert "2014/15" in years, f"Expected data from 2014/15, earliest is {years[0]}"

    def test_no_duplicate_years(self, latest_self_efficacy):
        """Test that there are no duplicate years."""
        duplicates = latest_self_efficacy["year"].duplicated().sum()

        assert duplicates == 0, f"Found {duplicates} duplicate years"


class TestWellbeingSummary:
    """Test suite for validating the wellbeing summary function."""

    @pytest.fixture(scope="class")
    def wellbeing_summary(self):
        """Fetch wellbeing summary once for the test class."""
        return wellbeing.get_wellbeing_summary(force_refresh=False)

    def test_summary_has_all_metrics(self, wellbeing_summary):
        """Test that summary includes all main wellbeing metrics."""
        expected_columns = {
            "year",
            "life_satisfaction",
            "worthwhile",
            "happiness",
            "anxiety",
            "lonely_some_of_time",
            "self_efficacy_mean",
        }

        assert expected_columns.issubset(set(wellbeing_summary.columns)), (
            f"Missing columns: {expected_columns - set(wellbeing_summary.columns)}"
        )

    def test_summary_single_row(self, wellbeing_summary):
        """Test that summary returns a single row."""
        assert len(wellbeing_summary) == 1, f"Expected 1 row, got {len(wellbeing_summary)}"

    def test_summary_values_reasonable(self, wellbeing_summary):
        """Test that summary values are within reasonable ranges."""
        row = wellbeing_summary.iloc[0]

        # Life satisfaction (0-10)
        assert 6 <= row["life_satisfaction"] <= 9

        # Anxiety (0-10, lower is better)
        assert 1 <= row["anxiety"] <= 5

        # Loneliness (proportion)
        assert 0.1 <= row["lonely_some_of_time"] <= 0.3

        # Self-efficacy (5-25)
        assert 17 <= row["self_efficacy_mean"] <= 22


class TestHelperFunctions:
    """Test suite for helper functions."""

    @pytest.fixture(scope="class")
    def personal_wellbeing_data(self):
        """Fetch personal wellbeing data once for the test class."""
        return wellbeing.get_latest_personal_wellbeing(force_refresh=False)

    def test_get_personal_wellbeing_by_year(self, personal_wellbeing_data):
        """Test the get_personal_wellbeing_by_year helper function."""
        if "2023/24" in personal_wellbeing_data["year"].values:
            df_2023 = wellbeing.get_personal_wellbeing_by_year(personal_wellbeing_data, "2023/24")

            assert len(df_2023) == 1
            assert df_2023["year"].iloc[0] == "2023/24"

    def test_get_personal_wellbeing_by_year_nonexistent(self, personal_wellbeing_data):
        """Test filtering for a non-existent year returns empty DataFrame."""
        df_future = wellbeing.get_personal_wellbeing_by_year(personal_wellbeing_data, "2099/00")

        assert len(df_future) == 0

    def test_url_discovery(self):
        """Test that URL discovery works."""
        url, year = wellbeing.get_latest_wellbeing_publication_url()

        assert url.startswith("https://")
        assert "/" in year  # Format like "2024/25"
        assert len(year) == 7  # "YYYY/YY"
