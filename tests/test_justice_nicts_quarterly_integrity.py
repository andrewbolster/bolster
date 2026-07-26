"""Integrity tests for the NICTS Quarterly Provisional Figures module.

Tests use real data downloaded from justice-ni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures and cached for
the duration of the test session. Parsing and validation edge cases are
covered by network-free unit tests.
"""

import math

import pandas as pd
import pytest

from bolster.data_sources.justice import nicts_quarterly
from bolster.data_sources.justice.nicts_quarterly import (
    NICTSDataNotFoundError,
    NICTSValidationError,
)

EXPECTED_COURTS = {
    "children_order",
    "county_court",
    "court_of_appeal_civil",
    "court_of_appeal_criminal",
    "crown_court",
    "high_court_chancery_division",
    "high_court_family_division",
    "high_court_kings_bench_division",
    "judge_court_sitting_days",
    "magistrates_courts",
}


class TestPublicationDiscovery:
    """Discovery of quarterly bulletins from the DoJ publication page."""

    @pytest.fixture(scope="class")
    def publications(self):
        return nicts_quarterly.list_publications()

    def test_publications_found(self, publications):
        assert len(publications) >= 10

    def test_all_ods_urls(self, publications):
        assert all(p["url"].lower().endswith(".ods") for p in publications)

    def test_quarters_in_range(self, publications):
        assert all(1 <= p["quarter"] <= 4 for p in publications)

    def test_years_plausible(self, publications):
        assert all(2020 <= p["year"] <= 2100 for p in publications)

    def test_sorted_newest_first(self, publications):
        keys = [(p["year"], p["quarter"]) for p in publications]
        assert keys == sorted(keys, reverse=True)

    def test_urls_unique(self, publications):
        urls = [p["url"] for p in publications]
        assert len(urls) == len(set(urls))

    def test_latest_matches_first(self, publications):
        latest = nicts_quarterly.find_latest_publication()
        assert latest == publications[0]

    def test_latest_is_recent(self, publications):
        """The most recent bulletin should be no more than ~2 years stale."""
        assert publications[0]["year"] >= 2025


class TestFullDatasetIntegrity:
    """Integrity tests across all ten court worksheets."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return nicts_quarterly.get_latest_data()

    def test_required_columns(self, latest_data):
        expected = {"court", "category", "subcategory", "detail", "period", "year", "quarter", "value"}
        assert expected.issubset(set(latest_data.columns))

    def test_not_empty(self, latest_data):
        assert len(latest_data) > 5000

    def test_all_courts_present(self, latest_data):
        assert set(latest_data["court"]) == EXPECTED_COURTS

    def test_every_court_has_data(self, latest_data):
        counts = latest_data.groupby("court")["value"].count()
        assert (counts > 50).all()

    def test_historical_coverage_from_2017(self, latest_data):
        assert latest_data["year"].min() == 2017

    def test_recent_coverage(self, latest_data):
        assert latest_data["year"].max() >= 2025

    def test_year_dtype_integer(self, latest_data):
        assert pd.api.types.is_integer_dtype(latest_data["year"])

    def test_quarter_nullable_integer(self, latest_data):
        assert isinstance(latest_data["quarter"].dtype, pd.Int64Dtype)

    def test_quarters_in_range(self, latest_data):
        quarters = latest_data["quarter"].dropna()
        assert quarters.between(1, 4).all()

    def test_annual_totals_have_no_quarter(self, latest_data):
        annual = latest_data[latest_data["period"].str.endswith("Total")]
        assert annual["quarter"].isna().all()

    def test_quarterly_periods_have_quarter(self, latest_data):
        quarterly = latest_data[~latest_data["period"].str.endswith("Total")]
        assert quarterly["quarter"].notna().all()

    def test_period_label_matches_year(self, latest_data):
        derived = latest_data["period"].str.slice(0, 4).astype(int)
        assert (derived == latest_data["year"]).all()

    def test_values_non_negative(self, latest_data):
        assert (latest_data["value"].dropna() >= 0).all()

    def test_values_mostly_populated(self, latest_data):
        """Suppression markers exist but should be a small minority."""
        assert latest_data["value"].isna().mean() < 0.05

    def test_category_always_present(self, latest_data):
        assert latest_data["category"].notna().all()

    def test_every_court_shares_period_columns(self, latest_data):
        """All worksheets use the same period header, so all courts align."""
        per_court = latest_data.groupby("court")["period"].apply(lambda s: frozenset(s))
        assert per_court.nunique() == 1

    def test_periods_are_contiguous_years(self, latest_data):
        years = sorted(latest_data["year"].unique())
        assert years == list(range(years[0], years[-1] + 1))

    def test_validate_passes(self, latest_data):
        assert nicts_quarterly.validate_data(latest_data) is True


class TestCourtFiltering:
    """Filtering the combined frame down to a single court."""

    @pytest.fixture(scope="class")
    def crown(self):
        return nicts_quarterly.get_crown_court()

    def test_single_court(self, crown):
        assert set(crown["court"]) == {"crown_court"}

    def test_index_reset(self, crown):
        assert crown.index[0] == 0

    def test_has_receipts_and_disposals(self, crown):
        assert {"Received", "Disposed"}.issubset(set(crown["subcategory"]))

    def test_case_and_defendant_levels(self, crown):
        assert {"Case", "Defendant"}.issubset(set(crown["category"]))

    def test_crown_receipts_plausible(self, crown):
        """Crown Court receives roughly 1,000-2,000 cases annually."""
        totals = crown[
            (crown["category"] == "Case") & (crown["subcategory"] == "Received") & (crown["detail"] == "Total")
        ]
        annual = totals[totals["quarter"].isna()]["value"].dropna()
        assert annual.between(500, 5000).all()

    def test_unknown_court_raises(self):
        with pytest.raises(NICTSDataNotFoundError, match="Unknown court"):
            nicts_quarterly.get_latest_data("supreme_court")

    def test_list_courts(self):
        assert set(nicts_quarterly.list_courts()) == EXPECTED_COURTS


class TestMagistratesCourts:
    """The highest-volume court, useful for catching thousands-separator bugs."""

    @pytest.fixture(scope="class")
    def magistrates(self):
        return nicts_quarterly.get_magistrates_courts()

    def test_single_court(self, magistrates):
        assert set(magistrates["court"]) == {"magistrates_courts"}

    def test_large_values_parsed(self, magistrates):
        """Adult defendant receipts run to tens of thousands per year."""
        assert magistrates["value"].max() > 20000

    def test_adult_defendants_present(self, magistrates):
        assert any("Adult Defendants" in str(c) for c in magistrates["category"].unique())

    def test_three_label_levels(self, magistrates):
        assert magistrates["detail"].notna().any()


class TestCountyCourt:
    """County Court has the largest worksheet."""

    @pytest.fixture(scope="class")
    def county(self):
        return nicts_quarterly.get_county_court()

    def test_single_court(self, county):
        assert set(county["court"]) == {"county_court"}

    def test_appeals_business_area(self, county):
        assert any("Appeals" in str(c) for c in county["category"].unique())

    def test_row_count_substantial(self, county):
        assert len(county) > 1000


class TestSittingDays:
    """Sitting days exercise the HH:MM duration parser."""

    @pytest.fixture(scope="class")
    def sitting(self):
        return nicts_quarterly.get_sitting_days()

    def test_single_court(self, sitting):
        assert set(sitting["court"]) == {"judge_court_sitting_days"}

    def test_both_categories(self, sitting):
        assert {"Total Sitting Days", "Average sitting times"}.issubset(set(sitting["category"]))

    def test_average_times_are_fractional_hours(self, sitting):
        """Averages are HH:MM durations; a typical sitting day is 1-8 hours."""
        avg = sitting[sitting["category"] == "Average sitting times"]["value"].dropna()
        assert not avg.empty
        assert avg.between(0, 24).all()

    def test_average_times_not_all_integers(self, sitting):
        """If HH:MM parsing collapsed to hours only, every value would be whole."""
        avg = sitting[sitting["category"] == "Average sitting times"]["value"].dropna()
        assert (avg % 1 != 0).any()

    def test_sitting_days_are_whole_numbers(self, sitting):
        days = sitting[sitting["category"] == "Total Sitting Days"]["value"].dropna()
        assert (days % 1 == 0).all()

    def test_judge_levels(self, sitting):
        assert any("Judge" in str(s) for s in sitting["subcategory"].unique())


class TestTwoLabelSheets:
    """Court of Appeal sheets have two label columns, not three."""

    @pytest.fixture(scope="class")
    def appeals(self):
        return nicts_quarterly.get_latest_data("court_of_appeal_civil")

    def test_detail_column_empty(self, appeals):
        assert appeals["detail"].isna().all()

    def test_category_and_subcategory_populated(self, appeals):
        assert appeals["category"].notna().all()
        assert appeals["subcategory"].notna().all()

    def test_receipts_and_disposals(self, appeals):
        assert {"Received", "Disposed"}.issubset(set(appeals["subcategory"]))

    def test_concatenates_with_three_label_sheets(self):
        """Two- and three-label sheets must share a schema to concat cleanly."""
        combined = nicts_quarterly.get_latest_data()
        two_label = combined[combined["court"] == "court_of_appeal_civil"]
        three_label = combined[combined["court"] == "crown_court"]
        assert list(two_label.columns) == list(three_label.columns)


class TestValueParsing:
    """Unit tests for the cell value parser - no network calls needed."""

    def test_plain_integer(self):
        assert nicts_quarterly._parse_value("42") == 42.0

    def test_thousands_separator(self):
        assert nicts_quarterly._parse_value("32,339") == 32339.0

    def test_decimal(self):
        assert nicts_quarterly._parse_value("12.5") == 12.5

    def test_duration_under_24h(self):
        assert nicts_quarterly._parse_value("2:44") == pytest.approx(2 + 44 / 60)

    def test_duration_over_24h(self):
        """Cumulative sitting hours exceed 24, which breaks naive time parsing."""
        assert nicts_quarterly._parse_value("6485:30") == 6485.5

    def test_zero(self):
        assert nicts_quarterly._parse_value("0") == 0.0

    @pytest.mark.parametrize("marker", ["[z]", "N/A", "n/a", "-", "", "  ", "[c]", "[x]", ":"])
    def test_suppression_markers(self, marker):
        assert math.isnan(nicts_quarterly._parse_value(marker))

    def test_unparseable_returns_nan(self):
        assert math.isnan(nicts_quarterly._parse_value("not a number"))

    def test_whitespace_stripped(self):
        assert nicts_quarterly._parse_value("  1,234  ") == 1234.0


class TestPeriodParsing:
    """Unit tests for period header parsing - no network calls needed."""

    def test_annual_total(self):
        assert nicts_quarterly._parse_period("2024 Total") == (2024, None)

    @pytest.mark.parametrize("quarter", [1, 2, 3, 4])
    def test_quarters(self, quarter):
        assert nicts_quarterly._parse_period(f"2025 Q{quarter}") == (2025, quarter)

    def test_whitespace_tolerated(self):
        assert nicts_quarterly._parse_period("  2025 Q1  ") == (2025, 1)

    @pytest.mark.parametrize("label", ["Business Area", "Status of case", "", "Q1", "2025", "2025 Q5"])
    def test_non_period_labels(self, label):
        assert nicts_quarterly._parse_period(label) is None


class TestSheetNameNormalisation:
    """Unit tests for worksheet name normalisation - no network calls needed."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Court_of_Appeal__Criminal", "court_of_appeal_criminal"),
            ("Court_of_Appeal_Civil", "court_of_appeal_civil"),
            ("Magistrates'_Courts", "magistrates_courts"),
            ("Judge_Court_Sitting_Days", "judge_court_sitting_days"),
            ("Children_Order", "children_order"),
            ("  Crown Court  ", "crown_court"),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert nicts_quarterly._normalise_sheet_name(raw) == expected

    def test_empty_string(self):
        assert nicts_quarterly._normalise_sheet_name("") == ""


class TestNoteStripping:
    """Unit tests for footnote reference removal - no network calls needed."""

    def test_single_note(self):
        assert nicts_quarterly._strip_note_refs("Total [note 3]") == "Total"

    def test_multiple_notes(self):
        assert nicts_quarterly._strip_note_refs("Received [note 1] [note 32]") == "Received"

    def test_brace_typo_variant(self):
        """One published table uses '{note 32]' rather than '[note 32]'."""
        assert nicts_quarterly._strip_note_refs("Disposed {note 32]") == "Disposed"

    def test_no_notes_unchanged(self):
        assert nicts_quarterly._strip_note_refs("Business Area") == "Business Area"

    def test_case_insensitive(self):
        assert nicts_quarterly._strip_note_refs("Total [Note 5]") == "Total"


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    @staticmethod
    def _frame(n=1000, **overrides):
        data = {
            "court": ["crown_court"] * n,
            "category": ["Case"] * n,
            "subcategory": ["Received"] * n,
            "detail": ["Total"] * n,
            "period": ["2024 Total"] * n,
            "year": [2024] * n,
            "quarter": pd.array([None] * n, dtype="Int64"),
            "value": [1.0] * n,
        }
        data.update(overrides)
        return pd.DataFrame(data)

    def test_validate_empty_dataframe(self):
        with pytest.raises(NICTSValidationError, match="empty"):
            nicts_quarterly.validate_data(pd.DataFrame())

    def test_validate_none(self):
        with pytest.raises(NICTSValidationError, match="empty"):
            nicts_quarterly.validate_data(None)

    def test_validate_missing_columns(self):
        df = self._frame().drop(columns=["value"])
        with pytest.raises(NICTSValidationError, match="Missing required columns"):
            nicts_quarterly.validate_data(df)

    def test_validate_too_few_records(self):
        with pytest.raises(NICTSValidationError, match="Too few records"):
            nicts_quarterly.validate_data(self._frame(n=10))

    def test_validate_year_too_early(self):
        with pytest.raises(NICTSValidationError, match="Year range out of bounds"):
            nicts_quarterly.validate_data(self._frame(year=[1999] * 1000))

    def test_validate_year_too_late(self):
        with pytest.raises(NICTSValidationError, match="Year range out of bounds"):
            nicts_quarterly.validate_data(self._frame(year=[2200] * 1000))

    def test_validate_quarter_out_of_bounds(self):
        df = self._frame(quarter=pd.array([7] * 1000, dtype="Int64"))
        with pytest.raises(NICTSValidationError, match="Quarter out of bounds"):
            nicts_quarterly.validate_data(df)

    def test_validate_negative_values(self):
        with pytest.raises(NICTSValidationError, match="Negative values"):
            nicts_quarterly.validate_data(self._frame(value=[-1.0] * 1000))

    def test_validate_custom_min_records(self):
        assert nicts_quarterly.validate_data(self._frame(n=20), min_records=10) is True

    def test_validate_all_nan_values_passes(self):
        """Fully suppressed values are unusual but structurally valid."""
        assert nicts_quarterly.validate_data(self._frame(value=[float("nan")] * 1000)) is True
