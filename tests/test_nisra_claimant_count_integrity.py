"""NISRA Claimant Count data integrity tests.

These tests validate the real NISRA claimant count data against expected
schemas, value ranges, and historical coverage. Network calls are made in
``scope="class"`` fixtures so data is downloaded once per test class.

The ``TestValidation`` class contains pure unit tests for the validation
function that do not require network access.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import claimant_count


class TestHeadlineIntegrity:
    """Integration tests for the Headline breakdown (NI total by sex)."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return claimant_count.get_latest_claimant_count("headline")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"date", "adjusted", "sex", "claimants_000s", "claimant_rate"}
        assert required.issubset(set(latest_data.columns)), (
            f"Missing columns: {required - set(latest_data.columns)}"
        )

    def test_nonempty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0, "Headline DataFrame is empty"

    def test_sex_values(self, latest_data: pd.DataFrame) -> None:
        expected_sexes = {"men", "women", "all_people"}
        actual = set(latest_data["sex"].unique())
        assert expected_sexes == actual, f"Unexpected sex values: {actual}"

    def test_adjusted_values(self, latest_data: pd.DataFrame) -> None:
        expected = {"seasonally_adjusted", "non_seasonally_adjusted"}
        actual = set(latest_data["adjusted"].unique())
        assert expected == actual, f"Unexpected adjusted values: {actual}"

    def test_claimant_count_positive(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["claimants_000s"] > 0).all(), (
            "All claimant counts should be positive"
        )

    def test_claimant_rate_in_range(self, latest_data: pd.DataFrame) -> None:
        rates = latest_data["claimant_rate"].dropna()
        assert (rates >= 0).all() and (rates <= 100).all(), (
            f"Rates out of [0, 100]: min={rates.min()}, max={rates.max()}"
        )

    def test_historical_coverage_pre_2020(self, latest_data: pd.DataFrame) -> None:
        """Time series should extend back to at least April 1997."""
        min_date = latest_data["date"].min()
        assert min_date.year < 2020, (
            f"Expected data before 2020, earliest date is {min_date}"
        )

    def test_historical_coverage_pre_2000(self, latest_data: pd.DataFrame) -> None:
        """Full series starts at April 1997."""
        min_date = latest_data["date"].min()
        assert min_date.year <= 1997, (
            f"Expected data from 1997, earliest date is {min_date}"
        )

    def test_seasonally_adjusted_present(self, latest_data: pd.DataFrame) -> None:
        sa = latest_data[latest_data["adjusted"] == "seasonally_adjusted"]
        assert len(sa) > 0, "No seasonally-adjusted rows found"

    def test_non_seasonally_adjusted_present(self, latest_data: pd.DataFrame) -> None:
        non_sa = latest_data[latest_data["adjusted"] == "non_seasonally_adjusted"]
        assert len(non_sa) > 0, "No non-seasonally-adjusted rows found"

    def test_date_is_datetime(self, latest_data: pd.DataFrame) -> None:
        assert pd.api.types.is_datetime64_any_dtype(latest_data["date"]), (
            "date column should be datetime type"
        )

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert claimant_count.validate_claimant_count(latest_data, "headline") is True

    def test_recent_data_present(self, latest_data: pd.DataFrame) -> None:
        """There should be data within the last 3 months."""
        max_date = latest_data["date"].max()
        now = pd.Timestamp.now().normalize()
        days_old = (now - max_date).days
        assert days_old < 100, f"Most recent data is {days_old} days old: {max_date}"


class TestAgeIntegrity:
    """Integration tests for the Age breakdown."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return claimant_count.get_latest_claimant_count("age")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"date", "age_group", "claimants"}
        assert required.issubset(set(latest_data.columns)), (
            f"Missing columns: {required - set(latest_data.columns)}"
        )

    def test_nonempty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0, "Age DataFrame is empty"

    def test_three_age_groups_present(self, latest_data: pd.DataFrame) -> None:
        expected = {"16-24", "25-49", "50+"}
        actual = set(latest_data["age_group"].unique())
        assert expected == actual, f"Unexpected age groups: {actual}"

    def test_claimants_positive(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["claimants"] > 0).all(), (
            "All claimant counts should be positive"
        )

    def test_data_from_2013(self, latest_data: pd.DataFrame) -> None:
        """Age data starts from January 2013."""
        min_date = latest_data["date"].min()
        assert min_date.year <= 2013, (
            f"Expected data from 2013, earliest is {min_date}"
        )

    def test_date_is_datetime(self, latest_data: pd.DataFrame) -> None:
        assert pd.api.types.is_datetime64_any_dtype(latest_data["date"]), (
            "date column should be datetime type"
        )

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert claimant_count.validate_claimant_count(latest_data, "age") is True


class TestLGDIntegrity:
    """Integration tests for the Local Government District breakdown."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return claimant_count.get_latest_claimant_count("lgd")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {
            "date",
            "geography",
            "geography_type",
            "claimants_male",
            "claimants_female",
            "claimants_total",
            "claimant_rate_total_pct",
            "change_over_month_number",
            "change_over_year_number",
        }
        assert required.issubset(set(latest_data.columns)), (
            f"Missing columns: {required - set(latest_data.columns)}"
        )

    def test_nonempty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0, "LGD DataFrame is empty"

    def test_eleven_districts_present(self, latest_data: pd.DataFrame) -> None:
        """There are 11 NI Local Government Districts, plus a NI total row."""
        # Filter out the NI total row
        districts = latest_data[latest_data["geography"] != "Northern Ireland"]
        assert len(districts) == 11, (
            f"Expected 11 districts, got {len(districts)}: {list(districts['geography'])}"
        )

    def test_geography_type(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["geography_type"] == "LGD_11").all(), (
            "geography_type should be 'LGD_11'"
        )

    def test_claimant_totals_positive(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["claimants_total"] > 0).all(), (
            "All total claimant counts should be positive"
        )

    def test_rates_in_valid_range(self, latest_data: pd.DataFrame) -> None:
        rates = latest_data["claimant_rate_total_pct"].dropna()
        assert (rates >= 0).all() and (rates <= 100).all(), (
            f"Rates out of range: min={rates.min()}, max={rates.max()}"
        )

    def test_male_female_sum_approx_total(self, latest_data: pd.DataFrame) -> None:
        """Male + female claimants should approximately equal total."""
        districts = latest_data[latest_data["geography"] != "Northern Ireland"]
        diff = (districts["claimants_male"] + districts["claimants_female"] - districts["claimants_total"]).abs()
        # Allow small rounding differences (data is rounded to nearest 5)
        assert (diff <= 10).all(), f"Male+Female sum deviates from total by more than 10: {diff.max()}"

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert claimant_count.validate_claimant_count(latest_data, "lgd") is True

    def test_belfast_highest_claimants(self, latest_data: pd.DataFrame) -> None:
        """Belfast typically has the highest claimant count."""
        districts = latest_data[latest_data["geography"] != "Northern Ireland"]
        max_row = districts.loc[districts["claimants_total"].idxmax()]
        assert max_row["geography"] == "Belfast", (
            f"Expected Belfast to have most claimants, got {max_row['geography']}"
        )


class TestPCAIntegrity:
    """Integration tests for Parliamentary Constituency Area breakdown."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return claimant_count.get_latest_claimant_count("pca")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"date", "geography", "geography_type", "claimants_total", "claimant_rate_total_pct"}
        assert required.issubset(set(latest_data.columns))

    def test_eighteen_constituencies(self, latest_data: pd.DataFrame) -> None:
        # Exclude the NI total row if present
        areas = latest_data[latest_data["geography"] != "Northern Ireland"]
        assert len(areas) == 18, (
            f"Expected 18 PCA rows, got {len(areas)}: {list(areas['geography'])}"
        )

    def test_geography_type(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["geography_type"] == "PCA").all()

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert claimant_count.validate_claimant_count(latest_data, "pca") is True


class TestTTWAIntegrity:
    """Integration tests for Travel-to-Work Area breakdown."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return claimant_count.get_latest_claimant_count("ttwa")

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"date", "geography", "geography_type", "claimants_total", "claimant_rate_total_pct"}
        assert required.issubset(set(latest_data.columns))

    def test_ten_ttwa_areas(self, latest_data: pd.DataFrame) -> None:
        # Exclude the NI total row if present
        areas = latest_data[latest_data["geography"] != "Northern Ireland"]
        assert len(areas) == 10, (
            f"Expected 10 TTWA rows, got {len(areas)}: {list(areas['geography'])}"
        )

    def test_geography_type(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["geography_type"] == "TTWA").all()

    def test_validate_passes(self, latest_data: pd.DataFrame) -> None:
        assert claimant_count.validate_claimant_count(latest_data, "ttwa") is True


class TestValidation:
    """Unit tests for validate_claimant_count — no network calls."""

    def test_validate_empty_dataframe(self) -> None:
        assert claimant_count.validate_claimant_count(pd.DataFrame(), "headline") is False

    def test_validate_missing_columns_headline(self) -> None:
        df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "sex": ["men"]})
        assert claimant_count.validate_claimant_count(df, "headline") is False

    def test_validate_missing_columns_age(self) -> None:
        df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")]})
        assert claimant_count.validate_claimant_count(df, "age") is False

    def test_validate_negative_claimants_headline(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "adjusted": ["seasonally_adjusted"],
                "sex": ["men"],
                "claimants_000s": [-1.0],
                "claimant_rate": [3.0],
            }
        )
        assert claimant_count.validate_claimant_count(df, "headline") is False

    def test_validate_rate_out_of_range(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "adjusted": ["seasonally_adjusted"],
                "sex": ["men"],
                "claimants_000s": [10.0],
                "claimant_rate": [150.0],  # > 100
            }
        )
        assert claimant_count.validate_claimant_count(df, "headline") is False

    def test_validate_valid_headline(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "adjusted": ["seasonally_adjusted"],
                "sex": ["all_people"],
                "claimants_000s": [35.0],
                "claimant_rate": [3.5],
            }
        )
        assert claimant_count.validate_claimant_count(df, "headline") is True

    def test_validate_negative_claimants_age(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "age_group": ["16-24"],
                "claimants": [-5],
            }
        )
        assert claimant_count.validate_claimant_count(df, "age") is False

    def test_validate_valid_age(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "age_group": ["16-24"],
                "claimants": [18000],
            }
        )
        assert claimant_count.validate_claimant_count(df, "age") is True

    def test_validate_negative_total_lgd(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "geography": ["Belfast"],
                "geography_type": ["LGD_11"],
                "claimants_total": [-100],
                "claimant_rate_total_pct": [3.5],
            }
        )
        assert claimant_count.validate_claimant_count(df, "lgd") is False

    def test_validate_rate_out_of_range_lgd(self) -> None:
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "geography": ["Belfast"],
                "geography_type": ["LGD_11"],
                "claimants_total": [9000],
                "claimant_rate_total_pct": [200.0],
            }
        )
        assert claimant_count.validate_claimant_count(df, "lgd") is False

    def test_validate_unknown_breakdown(self) -> None:
        df = pd.DataFrame({"foo": [1]})
        assert claimant_count.validate_claimant_count(df, "unknown") is False

    def test_validate_soa_missing_columns(self) -> None:
        df = pd.DataFrame({"soa_code": ["95AA01S1"]})
        assert claimant_count.validate_claimant_count(df, "soa") is False

    def test_validate_empty_pca(self) -> None:
        assert claimant_count.validate_claimant_count(pd.DataFrame(), "pca") is False

    def test_validate_empty_ttwa(self) -> None:
        assert claimant_count.validate_claimant_count(pd.DataFrame(), "ttwa") is False
