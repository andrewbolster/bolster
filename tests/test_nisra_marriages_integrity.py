"""Data integrity tests for NISRA marriage statistics.

These tests validate that the data is internally consistent across different
time periods. They use real data from NISRA (not mocked) and should work with
any dataset (latest or historical).

Key validations:
- No negative values
- Realistic marriage counts
- Temporal continuity (no missing months in time series)
- Year-over-year changes within reasonable bounds
- Seasonal patterns (summer months typically have more marriages)
- COVID-19 impact visible in 2020
"""

import pytest

from bolster.data_sources.nisra import marriages


class TestMarriagesDataIntegrity:
    """Test suite for validating internal consistency of marriage data."""

    @pytest.fixture(scope="class")
    def latest_marriages(self):
        """Fetch latest marriage data once for the test class."""
        return marriages.get_latest_marriages(force_refresh=False)

    def test_required_columns_present(self, latest_marriages):
        """Test that all required columns are present."""
        required_columns = {"date", "year", "month", "marriages"}

        assert set(latest_marriages.columns) == required_columns, f"Incorrect columns: {set(latest_marriages.columns)}"

    def test_no_negative_values(self, latest_marriages):
        """Test that there are no negative marriage counts."""
        # Filter out NaN values first
        non_null_data = latest_marriages[latest_marriages["marriages"].notna()]

        assert (non_null_data["marriages"] >= 0).all(), "Data contains negative marriage counts"

    def test_realistic_marriage_ranges(self, latest_marriages):
        """Test that marriage counts are within realistic ranges.

        Monthly marriages in NI typically range from 0-2000.
        """
        # Filter out NaN values
        non_null_data = latest_marriages[latest_marriages["marriages"].notna()]

        # Check upper bound (no month should have more than 2000 marriages)
        max_marriages = non_null_data["marriages"].max()
        assert max_marriages < 2000, f"Maximum marriages ({max_marriages}) seems unrealistically high"

        # Check that most months have at least some marriages
        # (COVID-19 months are exception)
        min_marriages = non_null_data["marriages"].min()
        assert min_marriages >= 0, f"Minimum marriages ({min_marriages}) is negative"

    def test_temporal_continuity(self, latest_marriages):
        """Test that there are no unexpected gaps in the time series.

        Each year should have consecutive months.
        """
        # Group by year and check month continuity
        for year in latest_marriages["year"].unique():
            year_data = latest_marriages[latest_marriages["year"] == year].copy()
            year_data = year_data.sort_values("date")

            # Check that months are consecutive (or there's a data gap at the end for current year)
            months = year_data["date"].dt.month.tolist()

            # Allow incomplete years (current year may not have all 12 months)
            if len(months) < 12:
                # Check that months are consecutive from January
                expected_months = list(range(1, len(months) + 1))
                assert months == expected_months or months == list(range(months[0], months[0] + len(months))), (
                    f"Year {year}: Months are not consecutive: {months}"
                )

    def test_validation_function_works(self, latest_marriages):
        """Test that the validate_marriages_temporal_continuity function works correctly."""
        # Should pass with valid data
        assert marriages.validate_marriages_temporal_continuity(latest_marriages)

    def test_annual_totals_reasonable(self, latest_marriages):
        """Test that annual marriage totals are within expected ranges.

        NI typically has 7,000-9,000 marriages per year (except COVID-19 years).
        """
        summary = marriages.get_marriages_summary_by_year(latest_marriages)

        # Check non-COVID years (before 2020 and after 2021)
        normal_years = summary[(summary["year"] < 2020) | (summary["year"] > 2021)]

        for _, row in normal_years.iterrows():
            if row["months_reported"] == 12:  # Only check complete years
                total = row["total_marriages"]
                assert 6000 <= total <= 10000, (
                    f"Year {row['year']}: Total marriages ({total:,.0f}) outside expected range"
                )

    def test_covid_impact_visible(self, latest_marriages):
        """Test that COVID-19 impact is visible in 2020 data.

        2020 should show significantly reduced marriages due to lockdowns.
        """
        df_2020 = marriages.get_marriages_by_year(latest_marriages, 2020)

        # 2020 total should be significantly lower than typical years
        total_2020 = df_2020["marriages"].sum()

        # Compare with 2019
        if 2019 in latest_marriages["year"].values:
            df_2019 = marriages.get_marriages_by_year(latest_marriages, 2019)
            total_2019 = df_2019["marriages"].sum()

            # 2020 should be significantly less than 2019 (more than 30% reduction)
            reduction = ((total_2019 - total_2020) / total_2019) * 100

            assert reduction > 30, (
                f"2020 marriages ({total_2020:,.0f}) should show COVID-19 impact "
                f"(>30% reduction from 2019: {total_2019:,.0f})"
            )

        # Check specific months (April/May 2020 lockdown)
        april_2020 = df_2020[df_2020["month"] == "April"]["marriages"].values[0]
        may_2020 = df_2020[df_2020["month"] == "May"]["marriages"].values[0]

        # These should be very low (less than 20 marriages/month during strict lockdown)
        assert april_2020 < 50, f"April 2020 marriages ({april_2020}) should reflect lockdown impact"
        assert may_2020 < 50, f"May 2020 marriages ({may_2020}) should reflect lockdown impact"

    def test_seasonal_patterns(self, latest_marriages):
        """Test that summer months typically have more marriages.

        Peak wedding season is typically June-September.
        """
        # Calculate average marriages by month across all years
        monthly_avg = latest_marriages.groupby("month")["marriages"].mean()

        # Define peak months
        peak_months = ["June", "July", "August", "September"]
        off_peak_months = ["January", "February", "November", "December"]

        peak_avg = monthly_avg[monthly_avg.index.isin(peak_months)].mean()
        off_peak_avg = monthly_avg[monthly_avg.index.isin(off_peak_months)].mean()

        # Peak months should have significantly more marriages than off-peak
        assert peak_avg > off_peak_avg * 1.5, (
            f"Peak months ({peak_avg:.0f}) should have significantly more marriages "
            f"than off-peak months ({off_peak_avg:.0f})"
        )

    def test_year_over_year_changes_reasonable(self, latest_marriages):
        """Test that year-over-year marriage changes are within reasonable bounds.

        Excluding COVID-19 years, marriages typically don't change by more than 20% year-to-year.
        """
        summary = marriages.get_marriages_summary_by_year(latest_marriages)

        # Filter to complete years only
        complete_years = summary[summary["months_reported"] == 12].copy()
        complete_years = complete_years.sort_values("year")

        for i in range(1, len(complete_years)):
            prev_year = complete_years.iloc[i - 1]["year"]
            curr_year = complete_years.iloc[i]["year"]

            prev_total = complete_years.iloc[i - 1]["total_marriages"]
            curr_total = complete_years.iloc[i]["total_marriages"]

            pct_change = abs(((curr_total - prev_total) / prev_total) * 100)

            # Skip COVID-19 transition years (2019-2020, 2020-2021)
            if prev_year in [2019, 2020] or curr_year in [2020, 2021]:
                continue

            # Normal years shouldn't change by more than 25%
            assert pct_change <= 25, (
                f"Year {prev_year} to {curr_year}: Marriage change {pct_change:.1f}% exceeds reasonable bounds "
                f"({prev_total:,.0f} -> {curr_total:,.0f})"
            )

    def test_data_types_correct(self, latest_marriages):
        """Test that column data types are correct."""
        assert latest_marriages["date"].dtype == "datetime64[ns]", "date column should be datetime"
        assert latest_marriages["year"].dtype in ["int64", "int32"], "year column should be integer"
        assert latest_marriages["month"].dtype == "object", "month column should be string"
        assert latest_marriages["marriages"].dtype in ["float64", "int64"], "marriages column should be numeric"

    def test_month_names_valid(self, latest_marriages):
        """Test that all month names are valid."""
        expected_months = {
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        }

        actual_months = set(latest_marriages["month"].unique())
        assert actual_months == expected_months, f"Unexpected month names: {actual_months - expected_months}"

    def test_date_year_consistency(self, latest_marriages):
        """Test that date and year columns are consistent."""
        # Extract year from date and compare with year column
        date_years = latest_marriages["date"].dt.year
        assert (date_years == latest_marriages["year"]).all(), "date and year columns are inconsistent"

    def test_helper_function_get_marriages_by_year(self, latest_marriages):
        """Test the get_marriages_by_year helper function."""
        # Get data for 2024
        if 2024 in latest_marriages["year"].values:
            df_2024 = marriages.get_marriages_by_year(latest_marriages, 2024)

            # Should only have 2024 data
            assert df_2024["year"].nunique() == 1
            assert df_2024["year"].iloc[0] == 2024

            # Should have 12 or fewer months
            assert len(df_2024) <= 12

    def test_helper_function_get_marriages_summary_by_year(self, latest_marriages):
        """Test the get_marriages_summary_by_year helper function."""
        summary = marriages.get_marriages_summary_by_year(latest_marriages)

        # Should have required columns
        required_cols = {"year", "total_marriages", "months_reported", "avg_per_month"}
        assert set(summary.columns) == required_cols

        # All years should have at least 1 month of data
        assert (summary["months_reported"] >= 1).all()
        assert (summary["months_reported"] <= 12).all()

        # Average should match total / months for complete years
        complete_years = summary[summary["months_reported"] == 12]
        for _, row in complete_years.iterrows():
            expected_avg = row["total_marriages"] / 12
            assert abs(row["avg_per_month"] - expected_avg) < 1, (
                f"Year {row['year']}: Average {row['avg_per_month']} doesn't match calculated {expected_avg:.1f}"
            )

    def test_historical_coverage(self, latest_marriages):
        """Test that data goes back to at least 2006."""
        min_year = latest_marriages["year"].min()

        assert min_year <= 2006, f"Expected data from 2006, earliest is {min_year}"

    def test_recent_data_available(self, latest_marriages):
        """Test that recent data is available (within last year)."""
        import datetime

        max_year = latest_marriages["year"].max()
        current_year = datetime.datetime.now().year

        assert max_year >= current_year - 1, f"Latest data ({max_year}) is more than 1 year old"

    def test_no_duplicate_months(self, latest_marriages):
        """Test that there are no duplicate year-month combinations."""
        duplicates = latest_marriages.groupby(["year", "month"]).size()
        duplicates = duplicates[duplicates > 1]

        assert len(duplicates) == 0, f"Found duplicate year-month combinations: {duplicates}"

    def test_august_typically_highest(self, latest_marriages):
        """Test that August is typically the highest month for marriages.

        August is traditionally peak wedding season in Northern Ireland.
        """
        # Calculate average by month across all years
        monthly_avg = latest_marriages.groupby("month")["marriages"].mean().sort_values(ascending=False)

        # August should be in top 3 months
        top_3_months = monthly_avg.head(3).index.tolist()

        assert "August" in top_3_months, f"August should be in top 3 months, but top 3 are: {top_3_months}"


class TestCivilPartnershipsDataIntegrity:
    """Test suite for validating internal consistency of civil partnership data."""

    @pytest.fixture(scope="class")
    def latest_civil_partnerships(self):
        """Fetch latest civil partnerships data once for the test class."""
        return marriages.get_latest_civil_partnerships(force_refresh=False)

    def test_required_columns_present(self, latest_civil_partnerships):
        """Test that all required columns are present."""
        required_columns = {"date", "year", "month", "civil_partnerships"}

        assert set(latest_civil_partnerships.columns) == required_columns, (
            f"Incorrect columns: {set(latest_civil_partnerships.columns)}"
        )

    def test_no_negative_values(self, latest_civil_partnerships):
        """Test that there are no negative civil partnership counts."""
        non_null_data = latest_civil_partnerships[latest_civil_partnerships["civil_partnerships"].notna()]

        assert (non_null_data["civil_partnerships"] >= 0).all(), "Data contains negative counts"

    def test_realistic_ranges(self, latest_civil_partnerships):
        """Test that civil partnership counts are within realistic ranges.

        Monthly civil partnerships in NI typically range from 0-30.
        """
        non_null_data = latest_civil_partnerships[latest_civil_partnerships["civil_partnerships"].notna()]

        max_cp = non_null_data["civil_partnerships"].max()
        assert max_cp < 50, f"Maximum civil partnerships ({max_cp}) seems unrealistically high"

    def test_data_types_correct(self, latest_civil_partnerships):
        """Test that column data types are correct."""
        assert latest_civil_partnerships["date"].dtype == "datetime64[ns]", "date should be datetime"
        assert latest_civil_partnerships["year"].dtype in ["int64", "int32"], "year should be integer"
        assert latest_civil_partnerships["month"].dtype == "object", "month should be string"
        assert latest_civil_partnerships["civil_partnerships"].dtype in ["int64", "int32"], (
            "civil_partnerships should be integer"
        )

    def test_month_names_valid(self, latest_civil_partnerships):
        """Test that all month names are valid."""
        expected_months = {
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        }

        actual_months = set(latest_civil_partnerships["month"].unique())
        assert actual_months == expected_months, f"Unexpected month names: {actual_months - expected_months}"

    def test_historical_coverage(self, latest_civil_partnerships):
        """Test that data goes back to at least 2006."""
        min_year = latest_civil_partnerships["year"].min()

        assert min_year <= 2006, f"Expected data from 2006, earliest is {min_year}"

    def test_recent_data_available(self, latest_civil_partnerships):
        """Test that recent data is available (within last year)."""
        import datetime

        max_year = latest_civil_partnerships["year"].max()
        current_year = datetime.datetime.now().year

        assert max_year >= current_year - 1, f"Latest data ({max_year}) is more than 1 year old"

    def test_helper_function_get_civil_partnerships_by_year(self, latest_civil_partnerships):
        """Test the get_civil_partnerships_by_year helper function."""
        if 2024 in latest_civil_partnerships["year"].values:
            df_2024 = marriages.get_civil_partnerships_by_year(latest_civil_partnerships, 2024)

            assert df_2024["year"].nunique() == 1
            assert df_2024["year"].iloc[0] == 2024
            assert len(df_2024) <= 12

    def test_helper_function_get_civil_partnerships_summary_by_year(self, latest_civil_partnerships):
        """Test the get_civil_partnerships_summary_by_year helper function."""
        summary = marriages.get_civil_partnerships_summary_by_year(latest_civil_partnerships)

        required_cols = {"year", "total_civil_partnerships", "months_reported", "avg_per_month"}
        assert set(summary.columns) == required_cols

        assert (summary["months_reported"] >= 1).all()
        assert (summary["months_reported"] <= 12).all()

    def test_covid_impact_visible(self, latest_civil_partnerships):
        """Test that COVID-19 impact is visible in 2020 data."""
        if 2020 not in latest_civil_partnerships["year"].values:
            pytest.skip("2020 data not available")

        df_2020 = marriages.get_civil_partnerships_by_year(latest_civil_partnerships, 2020)
        df_2019 = marriages.get_civil_partnerships_by_year(latest_civil_partnerships, 2019)

        total_2020 = df_2020["civil_partnerships"].sum()
        total_2019 = df_2019["civil_partnerships"].sum()

        # 2020 should be significantly less than 2019
        assert total_2020 < total_2019, (
            f"2020 civil partnerships ({total_2020}) should be less than 2019 ({total_2019})"
        )
