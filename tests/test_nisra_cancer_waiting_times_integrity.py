"""Data integrity tests for NISRA cancer waiting times statistics.

These tests validate that the data is internally consistent across different
time periods and dimensions. They use real data from the Department of Health
(not mocked) and should work with any dataset (latest or historical).

Key validations:
- Performance rates between 0 and 1
- Within target + over target = total patients
- All trusts and tumour sites present
- Temporal continuity (no unexpected gaps)
- COVID-19 impact visible in 2020-2021
- Historical patterns (31-day better than 62-day)
"""

import datetime

import pytest

from bolster.data_sources.nisra import cancer_waiting_times as cwt


class Test31DayByTrustIntegrity:
    """Test suite for 31-day waiting times by HSC Trust."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        """Fetch latest 31-day by Trust data once for the test class."""
        return cwt.get_latest_31_day_by_trust(force_refresh=False)

    def test_required_columns_present(self, latest_data):
        """Test that all required columns are present."""
        required = {"date", "year", "month", "trust", "within_target", "over_target", "total", "performance_rate"}
        assert set(latest_data.columns) == required

    def test_all_trusts_present(self, latest_data):
        """Test that all 5 HSC Trusts are present."""
        expected_trusts = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}
        actual_trusts = set(latest_data["trust"].unique())
        assert expected_trusts == actual_trusts

    def test_performance_rate_range(self, latest_data):
        """Test that performance rates are between 0 and 1."""
        valid_rates = latest_data["performance_rate"].dropna()
        assert (valid_rates >= 0).all(), "Performance rates contain values < 0"
        assert (valid_rates <= 1).all(), "Performance rates contain values > 1"

    def test_within_plus_over_equals_total(self, latest_data):
        """Test mathematical consistency: within + over = total."""
        valid_data = latest_data.dropna(subset=["within_target", "over_target", "total"])
        diff = abs(valid_data["within_target"] + valid_data["over_target"] - valid_data["total"])
        assert (diff < 1.0).all(), "within_target + over_target != total for some rows"

    def test_no_negative_values(self, latest_data):
        """Test that patient counts are not negative."""
        valid_data = latest_data.dropna(subset=["within_target", "over_target", "total"])
        assert (valid_data["within_target"] >= 0).all()
        assert (valid_data["over_target"] >= 0).all()
        assert (valid_data["total"] >= 0).all()

    def test_historical_coverage(self, latest_data):
        """Test that data goes back to at least 2008."""
        min_year = latest_data["year"].min()
        assert min_year <= 2008, f"Expected data from 2008, earliest is {min_year}"

    def test_recent_data_available(self, latest_data):
        """Test that recent data is available (within last year)."""
        max_year = latest_data["year"].max()
        current_year = datetime.datetime.now().year
        assert max_year >= current_year - 1, f"Latest data ({max_year}) is more than 1 year old"

    def test_validation_function(self, latest_data):
        """Test that the validation function passes."""
        assert cwt.validate_performance_data(latest_data) is True


class Test62DayByTumourIntegrity:
    """Test suite for 62-day waiting times by Tumour Site."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        """Fetch latest 62-day by Tumour data once for the test class."""
        return cwt.get_latest_62_day_by_tumour(force_refresh=False)

    def test_required_columns_present(self, latest_data):
        """Test that all required columns are present."""
        required = {"date", "year", "month", "tumour_site", "within_target", "over_target", "total", "performance_rate"}
        assert set(latest_data.columns) == required

    def test_major_tumour_sites_present(self, latest_data):
        """Test that major tumour sites are present."""
        expected = {"Breast Cancer", "Lung Cancer", "Skin Cancers", "Urological Cancer"}
        actual = set(latest_data["tumour_site"].unique())
        assert expected.issubset(actual), f"Missing tumour sites: {expected - actual}"

    def test_performance_rate_range(self, latest_data):
        """Test that performance rates are between 0 and 1."""
        valid_rates = latest_data["performance_rate"].dropna()
        valid_rates = valid_rates[valid_rates != float("inf")]
        assert (valid_rates >= 0).all(), "Performance rates contain values < 0"
        assert (valid_rates <= 1).all(), "Performance rates contain values > 1"

    def test_62_day_worse_than_31_day(self, latest_data):
        """Test that 62-day performance is typically worse than 31-day.

        This is expected because the 62-day pathway includes diagnosis time.
        """
        df_31 = cwt.get_latest_31_day_by_tumour()

        # Compare recent year averages
        recent_year = max(latest_data["year"].max(), df_31["year"].max()) - 1

        avg_62 = latest_data[latest_data["year"] == recent_year]["performance_rate"].mean()
        avg_31 = df_31[df_31["year"] == recent_year]["performance_rate"].mean()

        assert avg_62 < avg_31, (
            f"62-day ({avg_62:.1%}) should be worse than 31-day ({avg_31:.1%})"
        )

    def test_validation_function(self, latest_data):
        """Test that the validation function passes."""
        assert cwt.validate_performance_data(latest_data) is True


class Test14DayBreastIntegrity:
    """Test suite for 14-day breast cancer waiting times."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        """Fetch latest 14-day breast data once for the test class."""
        return cwt.get_latest_14_day_breast(force_refresh=False)

    def test_required_columns_present(self, latest_data):
        """Test that all required columns are present."""
        required = {"date", "year", "month", "trust", "within_target", "over_target", "total", "performance_rate"}
        assert set(latest_data.columns) == required

    def test_regional_service_transition(self, latest_data):
        """Test that data shows transition to regional service in 2025."""
        # From May 2025, data should include "Northern Ireland" regional entries
        df_2025 = latest_data[latest_data["year"] == 2025]
        trusts_2025 = df_2025["trust"].unique()

        # Check for regional entries (contain "Northern Ireland")
        has_regional = any("Northern Ireland" in str(t) for t in trusts_2025)
        assert has_regional, "Expected regional breast service data from May 2025"

    def test_breast_cancer_crisis_visible(self, latest_data):
        """Test that 14-day breast cancer performance decline is visible.

        Performance has declined dramatically from 2020 to 2025.
        """
        # Group by year and calculate average performance
        yearly = latest_data.groupby("year").agg(
            total=("total", "sum"),
            within=("within_target", "sum")
        ).reset_index()
        yearly["rate"] = yearly["within"] / yearly["total"]

        # Check 2020 vs 2024/2025 decline
        if 2020 in yearly["year"].values and 2024 in yearly["year"].values:
            rate_2020 = yearly[yearly["year"] == 2020]["rate"].values[0]
            rate_2024 = yearly[yearly["year"] == 2024]["rate"].values[0]

            # Performance should have dropped significantly
            decline = (rate_2020 - rate_2024) / rate_2020 * 100
            assert decline > 30, (
                f"Expected >30% decline from 2020 ({rate_2020:.1%}) to 2024 ({rate_2024:.1%}), "
                f"got {decline:.1f}%"
            )


class TestBreastReferralsIntegrity:
    """Test suite for breast cancer referrals data."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        """Fetch latest breast referrals data once for the test class."""
        return cwt.get_latest_breast_referrals(force_refresh=False)

    def test_required_columns_present(self, latest_data):
        """Test that all required columns are present."""
        required = {"date", "year", "month", "trust", "total_referrals", "urgent_referrals", "urgent_rate"}
        assert set(latest_data.columns) == required

    def test_urgent_less_than_total(self, latest_data):
        """Test that urgent referrals <= total referrals."""
        valid_data = latest_data.dropna(subset=["urgent_referrals", "total_referrals"])
        assert (valid_data["urgent_referrals"] <= valid_data["total_referrals"]).all()

    def test_urgent_rate_range(self, latest_data):
        """Test that urgent rate is between 0 and 1."""
        valid_rates = latest_data["urgent_rate"].dropna()
        assert (valid_rates >= 0).all()
        assert (valid_rates <= 1).all()


class TestHelperFunctions:
    """Test suite for helper and analysis functions."""

    @pytest.fixture(scope="class")
    def data_31_trust(self):
        """Fetch 31-day trust data."""
        return cwt.get_latest_31_day_by_trust()

    @pytest.fixture(scope="class")
    def data_62_tumour(self):
        """Fetch 62-day tumour data."""
        return cwt.get_latest_62_day_by_tumour()

    def test_get_data_by_year(self, data_31_trust):
        """Test filtering by year."""
        if 2024 in data_31_trust["year"].values:
            df_2024 = cwt.get_data_by_year(data_31_trust, 2024)
            assert (df_2024["year"] == 2024).all()
            assert len(df_2024) > 0

    def test_get_ni_wide_performance(self, data_31_trust):
        """Test NI-wide aggregation."""
        ni_wide = cwt.get_ni_wide_performance(data_31_trust)

        # Should have fewer rows than original (aggregated across trusts)
        assert len(ni_wide) < len(data_31_trust)

        # Should have required columns
        required = {"date", "year", "month", "within_target", "over_target", "total", "performance_rate"}
        assert required.issubset(set(ni_wide.columns))

    def test_get_performance_summary_by_year(self, data_31_trust):
        """Test annual summary calculation."""
        summary = cwt.get_performance_summary_by_year(data_31_trust, "trust")

        assert "year" in summary.columns
        assert "trust" in summary.columns
        assert "total_patients" in summary.columns
        assert "performance_rate" in summary.columns

    def test_get_tumour_site_ranking(self, data_62_tumour):
        """Test tumour site ranking."""
        ranking = cwt.get_tumour_site_ranking(data_62_tumour, year=2024)

        assert "rank" in ranking.columns
        assert "tumour_site" in ranking.columns
        assert "performance_rate" in ranking.columns

        # Ranks should be sequential
        ranks = ranking["rank"].tolist()
        assert ranks == list(range(1, len(ranks) + 1))

    def test_get_performance_trend(self, data_31_trust):
        """Test rolling trend calculation."""
        ni_wide = cwt.get_ni_wide_performance(data_31_trust)
        trend = cwt.get_performance_trend(ni_wide, window=12)

        assert "rolling_performance" in trend.columns
        # Rolling should smooth out values
        assert trend["rolling_performance"].std() < trend["performance_rate"].std()


class TestCOVIDImpact:
    """Test suite for COVID-19 impact visibility."""

    @pytest.fixture(scope="class")
    def data_31_trust(self):
        """Fetch 31-day trust data."""
        return cwt.get_latest_31_day_by_trust()

    @pytest.fixture(scope="class")
    def data_62_trust(self):
        """Fetch 62-day trust data."""
        return cwt.get_latest_62_day_by_trust()

    def test_covid_visible_in_patient_volumes(self, data_31_trust):
        """Test that COVID-19 impact is visible in 2020 patient volumes.

        Expect reduced patient volumes in 2020 due to delayed presentations.
        """
        yearly_totals = data_31_trust.groupby("year")["total"].sum()

        if 2019 in yearly_totals.index and 2020 in yearly_totals.index:
            vol_2019 = yearly_totals[2019]
            vol_2020 = yearly_totals[2020]

            # 2020 should show reduced volumes (more than 5% drop)
            reduction = (vol_2019 - vol_2020) / vol_2019 * 100
            assert reduction > 5, (
                f"Expected COVID-19 volume reduction, but 2020 ({vol_2020:,.0f}) "
                f"vs 2019 ({vol_2019:,.0f}) shows only {reduction:.1f}% change"
            )

    def test_post_covid_recovery_visible(self, data_62_trust):
        """Test that post-COVID performance decline is visible.

        62-day performance worsened significantly after COVID due to backlogs.
        """
        ni_wide = cwt.get_ni_wide_performance(data_62_trust)
        yearly = ni_wide.groupby("year")["performance_rate"].mean()

        if 2019 in yearly.index and 2023 in yearly.index:
            rate_2019 = yearly[2019]
            rate_2023 = yearly[2023]

            # Post-COVID performance should be worse
            assert rate_2023 < rate_2019, (
                f"Expected post-COVID decline, but 2023 ({rate_2023:.1%}) "
                f"is better than 2019 ({rate_2019:.1%})"
            )


class TestDataQuality:
    """Test suite for overall data quality checks."""

    def test_no_duplicate_rows_31_trust(self):
        """Test no duplicate date-trust combinations in 31-day data."""
        df = cwt.get_latest_31_day_by_trust()
        duplicates = df.groupby(["date", "trust"]).size()
        duplicates = duplicates[duplicates > 1]
        assert len(duplicates) == 0, f"Found duplicates: {duplicates}"

    def test_no_duplicate_rows_62_tumour(self):
        """Test no duplicate date-tumour combinations in 62-day data."""
        df = cwt.get_latest_62_day_by_tumour()
        duplicates = df.groupby(["date", "tumour_site"]).size()
        duplicates = duplicates[duplicates > 1]
        assert len(duplicates) == 0, f"Found duplicates: {duplicates}"

    def test_date_year_consistency(self):
        """Test that date and year columns are consistent."""
        df = cwt.get_latest_31_day_by_trust()
        date_years = df["date"].dt.year
        assert (date_years == df["year"]).all(), "date and year columns are inconsistent"

    def test_month_names_valid(self):
        """Test that all month names are valid."""
        df = cwt.get_latest_31_day_by_trust()
        expected_months = {
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        }
        actual_months = set(df["month"].unique())
        assert actual_months.issubset(expected_months), f"Invalid month names: {actual_months - expected_months}"
