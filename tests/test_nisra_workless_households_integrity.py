"""Data integrity tests for NISRA/ONS working and workless household statistics.

These tests validate the data returned by the workless_households module
against real published data (no mocks). They cover both sources the module
draws on: the ONS Table C regional series and NISRA's quarterly LFS
Households workbook.

Key validations:
- ONS regional series has all three statuses and every UK region
- Northern Ireland series spans 1996 to the present
- The three status rates sum to 100 for every period
- Published rates equal households / total households * 100
- NISRA workbook tables have expected shapes and percentage ranges
- Period label parsing handles ONS footnote markers
- validate_data rejects empty, malformed and out-of-range DataFrames
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import workless_households as wh
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError

UK_REGIONS = {
    "North East",
    "North West",
    "Yorkshire and The Humber",
    "East Midlands",
    "West Midlands",
    "East of England",
    "London",
    "South East",
    "South West",
    "Wales",
    "Scotland",
    "Northern Ireland",
}


@pytest.mark.network
class TestRegionalSeriesIntegrity:
    """Validate the ONS Table C regional series."""

    @pytest.fixture(scope="class")
    def regional(self) -> pd.DataFrame:
        return wh.get_regional_series()

    def test_required_columns_present(self, regional: pd.DataFrame) -> None:
        required = {
            "period",
            "year",
            "quarter",
            "region",
            "geography_code",
            "status",
            "households",
            "rate",
        }
        assert required.issubset(set(regional.columns)), f"Missing: {required - set(regional.columns)}"

    def test_not_empty(self, regional: pd.DataFrame) -> None:
        assert len(regional) > 0

    def test_three_statuses(self, regional: pd.DataFrame) -> None:
        assert sorted(regional["status"].unique()) == ["mixed", "working", "workless"]

    def test_all_uk_regions_present(self, regional: pd.DataFrame) -> None:
        present = set(regional["region"])
        assert UK_REGIONS.issubset(present), f"Missing regions: {UK_REGIONS - present}"

    def test_northern_ireland_geography_code(self, regional: pd.DataFrame) -> None:
        ni_codes = set(regional.loc[regional["region"] == "Northern Ireland", "geography_code"])
        assert ni_codes == {"N92000002"}

    def test_rates_within_range(self, regional: pd.DataFrame) -> None:
        rates = regional["rate"].dropna()
        assert rates.between(0, 100).all(), "Rates outside 0-100"

    def test_households_non_negative(self, regional: pd.DataFrame) -> None:
        households = regional["households"].dropna()
        assert (households >= 0).all()

    def test_quarters_valid(self, regional: pd.DataFrame) -> None:
        assert set(regional["quarter"].unique()).issubset({1, 2, 3, 4})

    def test_historical_coverage(self, regional: pd.DataFrame) -> None:
        assert regional["year"].min() <= 1996, "Series should reach back to 1996"

    def test_recent_data_available(self, regional: pd.DataFrame) -> None:
        assert regional["year"].max() >= 2025, "Series looks stale"


@pytest.mark.network
class TestNorthernIrelandSeriesIntegrity:
    """Validate the pivoted Northern Ireland convenience series."""

    @pytest.fixture(scope="class")
    def ni(self) -> pd.DataFrame:
        return wh.get_northern_ireland_series()

    def test_required_columns_present(self, ni: pd.DataFrame) -> None:
        required = {
            "period",
            "year",
            "quarter",
            "working_households",
            "working_rate",
            "mixed_households",
            "mixed_rate",
            "workless_households",
            "workless_rate",
        }
        assert required.issubset(set(ni.columns)), f"Missing: {required - set(ni.columns)}"

    def test_one_row_per_period(self, ni: pd.DataFrame) -> None:
        assert not ni["period"].duplicated().any()

    def test_chronologically_sorted(self, ni: pd.DataFrame) -> None:
        keys = list(zip(ni["year"], ni["quarter"], strict=True))
        assert keys == sorted(keys)

    def test_rates_sum_to_100(self, ni: pd.DataFrame) -> None:
        rates = ni[["working_rate", "mixed_rate", "workless_rate"]].dropna()
        total = rates.sum(axis=1)
        assert (total.sub(100).abs() < 0.01).all(), "Status rates do not sum to 100"

    def test_rates_match_household_shares(self, ni: pd.DataFrame) -> None:
        """Published rates should equal each status share of all households."""
        observed = ni.dropna()
        total = observed["working_households"] + observed["mixed_households"] + observed["workless_households"]
        for status in ("working", "mixed", "workless"):
            derived = observed[f"{status}_households"] / total * 100
            diff = (derived - observed[f"{status}_rate"]).abs().max()
            assert diff < 0.05, f"{status} rate diverges from household share by {diff}"

    def test_household_totals_plausible(self, ni: pd.DataFrame) -> None:
        """NI has roughly 0.5-0.6m households across the series."""
        observed = ni.dropna()
        total = observed["working_households"] + observed["mixed_households"] + observed["workless_households"]
        assert total.between(400_000, 900_000).all(), f"Implausible totals: {total.min()}-{total.max()}"

    def test_suppressed_quarter_preserved_as_null(self, ni: pd.DataFrame) -> None:
        """ONS suppressed Jul-Sep 2023 entirely; markers become nulls, not zeros."""
        row = ni[ni["period"] == "July to September 2023"]
        assert len(row) == 1
        assert row[["working_rate", "mixed_rate", "workless_rate"]].isna().all(axis=None)

    def test_workless_rate_declined_since_1996(self, ni: pd.DataFrame) -> None:
        observed = ni.dropna()
        first = observed.iloc[0]["workless_rate"]
        last = observed.iloc[-1]["workless_rate"]
        assert last < first, f"Expected long-run decline, got {first} -> {last}"

    def test_quarterly_in_recent_years(self, ni: pd.DataFrame) -> None:
        """Coverage became fully quarterly after the annual-only early years."""
        recent = ni[ni["year"] == ni["year"].max() - 1]
        assert len(recent) == 4, f"Expected 4 quarters, got {len(recent)}"


@pytest.mark.network
class TestNISRAWorkbookTables:
    """Validate the NI-only tables from the NISRA LFS Households workbook."""

    def test_publication_url_discoverable(self) -> None:
        url = wh.get_latest_publication_url()
        assert url.startswith("https://www.nisra.gov.uk/")
        assert url.endswith(".xlsx")
        assert "LFS-Households-Quarterly" in url

    def test_household_types(self) -> None:
        df = wh.get_household_types()
        assert list(df.columns) == ["household_type", "percentage"]
        assert len(df) == 5
        assert abs(df["percentage"].sum() - 100) < 1.0

    def test_economic_status_summary(self) -> None:
        df = wh.get_economic_status_summary()
        assert df["status"].tolist() == ["work_rich", "mixed", "workless"]
        assert abs(df["percentage"].sum() - 100) < 1.0
        assert "[note" not in " ".join(df["label"]), "Footnote markers not stripped"

    def test_female_activity_by_children(self) -> None:
        df = wh.get_female_activity_by_children()
        assert list(df.columns) == ["dependent_children", "activity_rate"]
        assert df["activity_rate"].between(0, 100).all()

    def test_female_activity_by_age(self) -> None:
        df = wh.get_female_activity_by_age()
        assert list(df.columns) == ["age_group", "with_dependent_children", "without_dependent_children"]
        assert df["with_dependent_children"].between(0, 100).all()
        assert df["without_dependent_children"].between(0, 100).all()

    def test_female_activity_by_youngest_child(self) -> None:
        df = wh.get_female_activity_by_youngest_child()
        assert list(df.columns) == ["youngest_child_age", "activity_rate"]
        assert df["activity_rate"].between(0, 100).all()


@pytest.mark.network
class TestDispatcher:
    """Validate the table dispatcher used by the CLI."""

    def test_list_tables(self) -> None:
        assert "northern-ireland" in wh.list_tables()

    def test_default_table(self) -> None:
        df = wh.get_latest_data()
        assert "workless_rate" in df.columns

    def test_every_table_returns_data(self) -> None:
        for table in wh.list_tables():
            df = wh.get_latest_data(table)
            assert len(df) > 0, f"{table} returned no rows"

    def test_unknown_table_raises(self) -> None:
        with pytest.raises(NISRADataNotFoundError, match="Unknown table"):
            wh.get_latest_data("not-a-table")


@pytest.mark.network
class TestCrossValidation:
    """Cross-validate the two independent sources against each other."""

    @pytest.fixture(scope="class")
    def ni(self) -> pd.DataFrame:
        return wh.get_northern_ireland_series()

    @pytest.fixture(scope="class")
    def status(self) -> pd.DataFrame:
        return wh.get_economic_status_summary()

    def test_status_split_matches_ons_latest(self, ni: pd.DataFrame, status: pd.DataFrame) -> None:
        """NISRA's headline split should match the latest ONS NI quarter."""
        latest = ni.dropna().iloc[-1]
        published = dict(zip(status["status"], status["percentage"], strict=True))
        pairs = (
            ("work_rich", latest["working_rate"]),
            ("mixed", latest["mixed_rate"]),
            ("workless", latest["workless_rate"]),
        )
        for key, ons_rate in pairs:
            assert abs(published[key] - ons_rate) < 0.5, (
                f"{key}: NISRA {published[key]} vs ONS {ons_rate:.2f} for {latest['period']}"
            )

    def test_ni_is_subset_of_uk_totals(self) -> None:
        """NI household counts must be smaller than the UK aggregate."""
        regional = wh.get_regional_series().dropna(subset=["households"])
        latest_year = regional["year"].max()
        recent = regional[regional["year"] == latest_year]
        ni = recent[recent["region"] == "Northern Ireland"]["households"].sum()
        uk = recent[recent["region"] == "United Kingdom"]["households"].sum()
        assert 0 < ni < uk, f"NI {ni} not a plausible share of UK {uk}"

    def test_female_activity_headline_consistent(self) -> None:
        """The 'all females' row should reconcile across the two age tables."""
        by_age = wh.get_female_activity_by_age()
        by_children = wh.get_female_activity_by_children()
        headline = by_age[by_age["age_group"].str.startswith("All females")].iloc[0]
        with_children = by_children[by_children["dependent_children"] == "1 or more"].iloc[0]
        assert abs(headline["with_dependent_children"] - with_children["activity_rate"]) < 0.5

    def test_household_types_sum_matches_status_sum(self) -> None:
        """Both NISRA breakdowns should partition the same household universe."""
        types_total = wh.get_household_types()["percentage"].sum()
        status_total = wh.get_economic_status_summary()["percentage"].sum()
        assert abs(types_total - status_total) < 1.0


class TestPeriodParsing:
    """Unit tests for period label parsing - no network calls needed."""

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("January to March 2026", (2026, 1)),
            ("April to June 1996", (1996, 2)),
            ("July to September 2023", (2023, 3)),
            ("October to December 2019", (2019, 4)),
        ],
    )
    def test_valid_periods(self, label: str, expected: tuple[int, int]) -> None:
        assert wh.parse_period(label) == expected

    def test_footnote_marker_tolerated(self) -> None:
        """ONS appends footnote digits directly to the year in some sheets."""
        assert wh.parse_period("July to September 20232") == (2023, 3)

    def test_extra_whitespace_tolerated(self) -> None:
        assert wh.parse_period("  April  to  June  2010 ") == (2010, 2)

    def test_unrecognised_label_raises(self) -> None:
        with pytest.raises(NISRAValidationError, match="Unrecognised LFS period label"):
            wh.parse_period("Change on year")

    def test_unrecognised_span_raises(self) -> None:
        with pytest.raises(NISRAValidationError, match="Unrecognised LFS period span"):
            wh.parse_period("February to April 2020")


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def test_validate_accepts_valid_frame(self) -> None:
        df = pd.DataFrame({"status": ["workless"], "percentage": [15.6]})
        assert wh.validate_data(df) is True

    def test_validate_empty_dataframe(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            wh.validate_data(pd.DataFrame())

    def test_validate_missing_columns(self) -> None:
        df = pd.DataFrame({"status": ["workless"]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            wh.validate_data(df, required_columns=["status", "percentage"])

    def test_validate_rate_above_100(self) -> None:
        df = pd.DataFrame({"rate": [101.0]})
        with pytest.raises(NISRAValidationError, match="outside 0-100"):
            wh.validate_data(df)

    def test_validate_negative_percentage(self) -> None:
        df = pd.DataFrame({"percentage": [-1.0]})
        with pytest.raises(NISRAValidationError, match="outside 0-100"):
            wh.validate_data(df)

    def test_validate_ignores_nulls(self) -> None:
        df = pd.DataFrame({"rate": [15.6, None]})
        assert wh.validate_data(df) is True
