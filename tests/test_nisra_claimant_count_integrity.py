"""NISRA Claimant Count data integrity tests.

These tests validate the real NISRA claimant count data fetched from the
PxStat API against expected schemas, value ranges, and historical coverage.
Network calls are made in ``scope="class"`` fixtures so data is fetched once
per test class.

The ``TestValidation`` class contains pure unit tests for the validation
function that do not require network access.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import claimant_count


class TestLGDIntegrity:
    """Integration tests for the Local Government District breakdown."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return claimant_count.get_latest_claimant_count("lgd")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {
            "date",
            "geography_code",
            "geography",
            "claimants_total",
            "claimant_rate_total_pct",
        }
        assert required.issubset(set(latest_data.columns)), (
            f"Missing columns: {required - set(latest_data.columns)}"
        )

    def test_nonempty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0, "LGD DataFrame is empty"

    def test_date_is_datetime(self, latest_data: pd.DataFrame) -> None:
        assert pd.api.types.is_datetime64_any_dtype(latest_data["date"]), (
            "date column should be datetime type"
        )

    def test_eleven_districts_in_latest_month(self, latest_data: pd.DataFrame) -> None:
        """There are 11 NI Local Government Districts plus a NI total row."""
        latest_month = latest_data["date"].max()
        month_df = latest_data[latest_data["date"] == latest_month]
        districts = month_df[month_df["geography"] != "Northern Ireland"]
        assert len(districts) == 11, (
            f"Expected 11 districts, got {len(districts)}: {list(districts['geography'])}"
        )

    def test_ni_total_present(self, latest_data: pd.DataFrame) -> None:
        assert "Northern Ireland" in latest_data["geography"].values

    def test_claimant_totals_positive(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["claimants_total"] > 0).all(), (
            "All total claimant counts should be positive"
        )

    def test_rates_in_valid_range(self, latest_data: pd.DataFrame) -> None:
        rates = latest_data["claimant_rate_total_pct"].dropna()
        assert (rates >= 0).all() and (rates <= 100).all(), (
            f"Rates out of range: min={rates.min()}, max={rates.max()}"
        )

    def test_historical_coverage_from_2005(self, latest_data: pd.DataFrame) -> None:
        """PxStat data starts from January 2005."""
        min_date = latest_data["date"].min()
        assert min_date.year <= 2005, (
            f"Expected data from 2005, earliest is {min_date}"
        )

    def test_recent_data_present(self, latest_data: pd.DataFrame) -> None:
        """There should be data within the last 100 days."""
        max_date = latest_data["date"].max()
        now = pd.Timestamp.now().normalize()
        days_old = (now - max_date).days
        assert days_old < 100, f"Most recent data is {days_old} days old: {max_date}"

    def test_belfast_highest_claimants_recent(self, latest_data: pd.DataFrame) -> None:
        """Belfast typically has the highest claimant count among districts."""
        latest_month = latest_data["date"].max()
        month_df = latest_data[latest_data["date"] == latest_month]
        districts = month_df[month_df["geography"] != "Northern Ireland"]
        max_row = districts.loc[districts["claimants_total"].idxmax()]
        assert max_row["geography"] == "Belfast", (
            f"Expected Belfast to have most claimants, got {max_row['geography']}"
        )

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert claimant_count.validate_claimant_count(latest_data, "lgd") is True


class TestAAIntegrity:
    """Integration tests for the Assembly Area breakdown."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return claimant_count.get_latest_claimant_count("aa")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"date", "geography_code", "geography", "claimants_total", "claimant_rate_total_pct"}
        assert required.issubset(set(latest_data.columns)), (
            f"Missing columns: {required - set(latest_data.columns)}"
        )

    def test_nonempty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0, "AA DataFrame is empty"

    def test_eighteen_assembly_areas_in_latest_month(self, latest_data: pd.DataFrame) -> None:
        latest_month = latest_data["date"].max()
        month_df = latest_data[latest_data["date"] == latest_month]
        areas = month_df[month_df["geography"] != "Northern Ireland"]
        assert len(areas) == 18, (
            f"Expected 18 Assembly Areas, got {len(areas)}: {list(areas['geography'])}"
        )

    def test_rates_in_valid_range(self, latest_data: pd.DataFrame) -> None:
        rates = latest_data["claimant_rate_total_pct"].dropna()
        assert (rates >= 0).all() and (rates <= 100).all()

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert claimant_count.validate_claimant_count(latest_data, "aa") is True


class TestValidation:
    """Unit tests for validate_claimant_count — no network calls."""

    def test_validate_empty_dataframe(self) -> None:
        assert claimant_count.validate_claimant_count(pd.DataFrame(), "lgd") is False

    def test_validate_missing_columns_lgd(self) -> None:
        df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "geography": ["Belfast"]})
        assert claimant_count.validate_claimant_count(df, "lgd") is False

    def test_validate_missing_columns_aa(self) -> None:
        df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")]})
        assert claimant_count.validate_claimant_count(df, "aa") is False

    def test_validate_negative_claimants_lgd(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "geography_code": ["N09000003"],
                "geography": ["Belfast"],
                "claimants_total": [-100.0],
                "claimant_rate_total_pct": [3.5],
            }
        )
        assert claimant_count.validate_claimant_count(df, "lgd") is False

    def test_validate_rate_out_of_range_lgd(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "geography_code": ["N09000003"],
                "geography": ["Belfast"],
                "claimants_total": [9000.0],
                "claimant_rate_total_pct": [200.0],
            }
        )
        assert claimant_count.validate_claimant_count(df, "lgd") is False

    def test_validate_valid_lgd(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "geography_code": ["N09000003"],
                "geography": ["Belfast"],
                "claimants_total": [9000.0],
                "claimant_rate_total_pct": [5.2],
            }
        )
        assert claimant_count.validate_claimant_count(df, "lgd") is True

    def test_validate_negative_claimants_soa(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "soa_code": ["95AA01S1"],
                "claimants": [-5.0],
            }
        )
        assert claimant_count.validate_claimant_count(df, "soa") is False

    def test_validate_valid_soa(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "soa_code": ["95AA01S1"],
                "claimants": [10.0],
            }
        )
        assert claimant_count.validate_claimant_count(df, "soa") is True

    def test_validate_unknown_breakdown(self) -> None:
        df = pd.DataFrame({"foo": [1]})
        assert claimant_count.validate_claimant_count(df, "unknown") is False

    def test_validate_empty_aa(self) -> None:
        assert claimant_count.validate_claimant_count(pd.DataFrame(), "aa") is False

    def test_validate_empty_soa(self) -> None:
        assert claimant_count.validate_claimant_count(pd.DataFrame(), "soa") is False

    def test_validate_none_dataframe(self) -> None:
        assert claimant_count.validate_claimant_count(None, "lgd") is False

    def test_breakdown_raises_on_invalid(self) -> None:
        with pytest.raises(ValueError, match="breakdown must be one of"):
            claimant_count.get_latest_claimant_count("headline")
