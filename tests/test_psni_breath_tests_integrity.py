"""Integrity tests for the PSNI Preliminary Breath Tests module.

Tests use real data downloaded from PSNI and cached via the normal
CachedDownloader mechanism. No mocks — all tests hit the real source (or
the local cache on subsequent runs).
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.psni import breath_tests as bt
from bolster.data_sources.psni._base import PSNIDataNotFoundError, PSNIValidationError


@pytest.mark.network
class TestDiscovery:
    """Live workbook discovery."""

    def test_workbook_url_found(self):
        url = bt.find_latest_workbook_url()
        assert url.lower().endswith(".xlsx")

    def test_workbook_url_is_psni_domain(self):
        url = bt.find_latest_workbook_url()
        assert "psni.police.uk" in url


@pytest.mark.network
class TestAnnualTotals:
    """Annual totals and positive/failed-to-provide rate."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return bt.get_annual_totals()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == [
            "year",
            "total_tests",
            "positive_or_failed_to_provide",
            "pct_positive_or_failed_to_provide",
        ]

    def test_starts_at_2010(self, df: pd.DataFrame):
        assert df["year"].min() == 2010

    def test_years_contiguous(self, df: pd.DataFrame):
        years = sorted(df["year"].unique())
        assert years == list(range(years[0], years[-1] + 1))

    def test_counts_positive(self, df: pd.DataFrame):
        assert (df["total_tests"] > 0).all()

    def test_percentage_in_range(self, df: pd.DataFrame):
        assert df["pct_positive_or_failed_to_provide"].between(0, 100).all()

    def test_positive_rate_consistent_with_counts(self, df: pd.DataFrame):
        implied = df["positive_or_failed_to_provide"] / df["total_tests"] * 100
        assert implied.values == pytest.approx(df["pct_positive_or_failed_to_provide"].values, abs=0.05)

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert bt.validate_data(df) is True


@pytest.mark.network
class TestAnnualByResult:
    """Annual breakdown by test result."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return bt.get_annual_by_result()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["year", "zero", "pass", "warning", "fail", "failed_to_provide", "total"]

    def test_components_sum_to_total(self, df: pd.DataFrame):
        components = df[["zero", "pass", "warning", "fail", "failed_to_provide"]].sum(axis=1)
        assert components.values == pytest.approx(df["total"].values)

    def test_totals_match_annual_totals(self, df: pd.DataFrame):
        totals = bt.get_annual_totals().set_index("year")["total_tests"]
        by_result = df.set_index("year")["total"]
        assert by_result.equals(totals.loc[by_result.index])

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert bt.validate_data(df) is True


@pytest.mark.network
class TestAnnualByReason:
    """Annual breakdown by reason for test."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return bt.get_annual_by_reason()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == [
            "year",
            "moving_traffic_offence",
            "road_traffic_collision",
            "suspicion_of_alcohol",
            "other",
            "total",
        ]

    def test_components_sum_to_total(self, df: pd.DataFrame):
        components = df[["moving_traffic_offence", "road_traffic_collision", "suspicion_of_alcohol", "other"]].sum(
            axis=1
        )
        assert components.values == pytest.approx(df["total"].values)

    def test_totals_match_annual_totals(self, df: pd.DataFrame):
        totals = bt.get_annual_totals().set_index("year")["total_tests"]
        by_reason = df.set_index("year")["total"]
        assert by_reason.equals(totals.loc[by_reason.index])

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert bt.validate_data(df) is True


@pytest.mark.network
class TestByMonth:
    """Current-year breakdown by month."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return bt.get_by_month()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == [
            "year",
            "month",
            "total_tests",
            "positive_or_failed_to_provide",
            "pct_positive_or_failed_to_provide",
        ]

    def test_twelve_months(self, df: pd.DataFrame):
        assert len(df) == 12

    def test_no_total_row(self, df: pd.DataFrame):
        assert "Total" not in set(df["month"])

    def test_single_year(self, df: pd.DataFrame):
        assert df["year"].nunique() == 1

    def test_sums_to_annual_total(self, df: pd.DataFrame):
        year = int(df["year"].iloc[0])
        annual = bt.get_annual_totals().set_index("year").loc[year, "total_tests"]
        assert df["total_tests"].sum() == annual

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert bt.validate_data(df) is True


@pytest.mark.network
class TestByDayOfWeek:
    """Current-year breakdown by day of week."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return bt.get_by_day_of_week()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == [
            "year",
            "day_of_week",
            "total_tests",
            "positive_or_failed_to_provide",
            "pct_positive_or_failed_to_provide",
        ]

    def test_seven_days(self, df: pd.DataFrame):
        assert len(df) == 7

    def test_no_total_row(self, df: pd.DataFrame):
        assert "Total" not in set(df["day_of_week"])

    def test_all_weekdays_present(self, df: pd.DataFrame):
        expected = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
        assert set(df["day_of_week"]) == expected

    def test_sums_to_annual_total(self, df: pd.DataFrame):
        year = int(df["year"].iloc[0])
        annual = bt.get_annual_totals().set_index("year").loc[year, "total_tests"]
        assert df["total_tests"].sum() == annual

    def test_weekend_days_have_higher_volume(self, df: pd.DataFrame):
        # More enforcement activity (and more drink-driving suspicion) at
        # weekends than on a typical weekday.
        indexed = df.set_index("day_of_week")["total_tests"]
        weekday_avg = indexed[["Monday", "Tuesday", "Wednesday", "Thursday"]].mean()
        assert indexed["Saturday"] > weekday_avg
        assert indexed["Sunday"] > weekday_avg

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert bt.validate_data(df) is True


@pytest.mark.network
class TestByTimeOfDay:
    """Current-year breakdown by time of day."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return bt.get_by_time_of_day()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == [
            "year",
            "time_of_day",
            "total_tests",
            "positive_or_failed_to_provide",
            "pct_positive_or_failed_to_provide",
        ]

    def test_eight_bands(self, df: pd.DataFrame):
        assert len(df) == 8

    def test_no_total_row(self, df: pd.DataFrame):
        assert "Total" not in set(df["time_of_day"])

    def test_bands_are_three_hour_ranges(self, df: pd.DataFrame):
        assert all(" - " in band for band in df["time_of_day"])

    def test_sums_to_annual_total(self, df: pd.DataFrame):
        year = int(df["year"].iloc[0])
        annual = bt.get_annual_totals().set_index("year").loc[year, "total_tests"]
        assert df["total_tests"].sum() == annual

    def test_late_night_has_highest_positive_rate(self, df: pd.DataFrame):
        # Drink-driving detection should be most concentrated in the small
        # hours, when suspicion-led (rather than routine) tests dominate.
        indexed = df.set_index("time_of_day")["pct_positive_or_failed_to_provide"]
        assert indexed.idxmax() in {"0000 - 0259", "0300 - 0559"}

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert bt.validate_data(df) is True


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(PSNIValidationError):
            bt.validate_data(pd.DataFrame())

    def test_rejects_missing_column(self):
        with pytest.raises(PSNIValidationError):
            bt.validate_data(pd.DataFrame({"year": [2024]}), value_column="total_tests")

    def test_rejects_all_null_column(self):
        df = pd.DataFrame({"total_tests": [None, None]})
        with pytest.raises(PSNIValidationError):
            bt.validate_data(df)

    def test_rejects_negative_count(self):
        df = pd.DataFrame({"total_tests": [-1]})
        with pytest.raises(PSNIValidationError):
            bt.validate_data(df)

    def test_rejects_implausible_year(self):
        df = pd.DataFrame({"year": [1066], "total_tests": [10]})
        with pytest.raises(PSNIValidationError):
            bt.validate_data(df)

    def test_infers_total_column(self):
        df = pd.DataFrame({"year": [2024], "total": [100]})
        assert bt.validate_data(df) is True


class TestReadTable:
    """Behaviour of the shared table-extraction helper (no network required)."""

    def test_raises_when_no_data_rows(self):
        sheet = pd.DataFrame([["Title"], [None], ["Year"], [None]])
        with pytest.raises(PSNIValidationError):
            bt._read_table(sheet, ["year"])

    def test_stops_at_stop_label(self):
        sheet = pd.DataFrame(
            [
                ["Title"],
                [None],
                ["Month"],
                ["January"],
                ["February"],
                ["Total"],
            ]
        )
        result = bt._read_table(sheet, ["month"], stop_labels={"Total"})
        assert list(result["month"]) == ["January", "February"]


class TestTitleYear:
    """Behaviour of the title-year extraction helper (no network required)."""

    def test_extracts_year_from_title(self):
        sheet = pd.DataFrame([["Number of preliminary breath tests by month of year, 2025"]])
        assert bt._title_year(sheet) == 2025

    def test_raises_when_no_year_in_title(self):
        sheet = pd.DataFrame([["Number of preliminary breath tests by month of year"]])
        with pytest.raises(PSNIValidationError):
            bt._title_year(sheet)


@pytest.mark.network
class TestDataNotFound:
    """Error handling for missing sheets."""

    def test_unknown_sheet_raises(self):
        with pytest.raises(PSNIDataNotFoundError):
            bt._sheet("NoSuchSheet")
