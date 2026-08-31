"""Integrity tests for the First Time Entrant Statistics module.

Tests use real data downloaded from justice-ni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures and cached for
the duration of the test session. Parsing and validation edge cases are
covered by network-free unit tests.
"""

import math

import pandas as pd
import pytest

from bolster.data_sources.justice import first_time_entrants as fte
from bolster.data_sources.justice.first_time_entrants import (
    FirstTimeEntrantsNotFoundError,
    FirstTimeEntrantsValidationError,
)

EXPECTED_BREAKDOWNS = {"age_band", "gender", "offence", "disposal", "summary"}


class TestPublicationDiscovery:
    """Discovery of annual editions from the DoJ series index page."""

    @pytest.fixture(scope="class")
    def publications(self):
        return fte.list_publications()

    def test_publications_found(self, publications):
        assert len(publications) >= 10

    def test_year_labels_well_formed(self, publications):
        assert all(len(p["year"]) == 7 and p["year"][4] == "-" for p in publications)

    def test_years_plausible(self, publications):
        assert all(2005 <= int(p["year"][:4]) <= 2100 for p in publications)

    def test_sorted_newest_first(self, publications):
        years = [p["year"] for p in publications]
        assert years == sorted(years, reverse=True)

    def test_urls_unique(self, publications):
        urls = [p["url"] for p in publications]
        assert len(urls) == len(set(urls))

    def test_latest_matches_first(self, publications):
        assert fte.find_latest_publication() == publications[0]

    def test_latest_is_recent(self, publications):
        """The most recent edition should be no more than ~2 years stale."""
        assert int(publications[0]["year"][:4]) >= 2023


class TestDataFileResolution:
    """Resolving a publication page down to its spreadsheet."""

    @pytest.fixture(scope="class")
    def data_url(self):
        return fte.find_data_file(fte.find_latest_publication()["url"])

    def test_is_spreadsheet(self, data_url):
        assert data_url.lower().endswith((".ods", ".xlsx"))

    def test_ods_preferred(self, data_url):
        """Editions publish both formats; the accessible ODS is canonical."""
        assert data_url.lower().endswith(".ods")

    def test_unknown_publication_raises(self):
        with pytest.raises(FirstTimeEntrantsNotFoundError):
            fte.find_data_file("https://www.justice-ni.gov.uk/publications/not-a-real-publication")


class TestFullDatasetIntegrity:
    """Integrity tests across every table in the latest edition."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return fte.get_latest_data()

    def test_required_columns(self, latest_data):
        expected = {"table", "breakdown", "category", "year", "measure", "value"}
        assert expected.issubset(set(latest_data.columns))

    def test_not_empty(self, latest_data):
        assert len(latest_data) > 500

    def test_all_breakdowns_present(self, latest_data):
        assert set(latest_data["breakdown"]) == EXPECTED_BREAKDOWNS

    def test_every_breakdown_has_data(self, latest_data):
        counts = latest_data.groupby("breakdown")["value"].count()
        assert (counts > 5).all()

    def test_keys_unique(self, latest_data):
        """Table, category, year and measure must identify a single value."""
        key = ["table", "category", "year", "measure"]
        assert not latest_data.duplicated(key).any()

    def test_table_ids_well_formed(self, latest_data):
        assert latest_data["table"].str.fullmatch(r"\d+[a-z]?").all()

    def test_expected_table_count(self, latest_data):
        """Recent editions carry 18 tables: 1a-1d, 2a-2d, 3a-3e, 4a-4d and 5."""
        assert len(set(latest_data["table"])) == 18

    def test_year_labels_well_formed(self, latest_data):
        assert latest_data["year"].str.fullmatch(r"\d{4}-\d{2}").all()

    def test_recent_coverage(self, latest_data):
        assert latest_data["year"].max() >= "2024-25"

    def test_measures_are_known(self, latest_data):
        known = {
            "first_count",
            "first_pct",
            "first_convictions_count",
            "first_convictions_pct",
            "first_diversions_count",
            "first_diversions_pct",
            "total_count",
        }
        assert set(latest_data["measure"]).issubset(known)

    def test_counts_are_whole_numbers(self, latest_data):
        counts = latest_data[latest_data["measure"].str.endswith("_count")]["value"].dropna()
        assert (counts % 1 == 0).all()

    def test_values_non_negative(self, latest_data):
        assert (latest_data["value"].dropna() >= 0).all()

    def test_percentages_in_range(self, latest_data):
        pcts = latest_data[latest_data["measure"].str.endswith("_pct")]["value"].dropna()
        assert pcts.between(0, 100).all()

    def test_values_mostly_populated(self, latest_data):
        """Suppression markers exist but should be a small minority."""
        assert latest_data["value"].isna().mean() < 0.1

    def test_category_always_present(self, latest_data):
        assert latest_data["category"].notna().all()

    def test_no_note_refs_leak_into_categories(self, latest_data):
        assert not latest_data["category"].str.contains("note", case=False).any()

    def test_no_table_titles_leak_into_categories(self, latest_data):
        assert not latest_data["category"].str.contains(r"^Table \d", regex=True).any()

    def test_validate_passes(self, latest_data):
        assert fte.validate_data(latest_data) is True


class TestHeadlineFigures:
    """Anchor figures cross-checked against the published 2024-25 tables."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return fte.get_latest_data()

    @staticmethod
    def _value(df, table, category, measure, year="2024-25"):
        match = df[
            (df["table"] == table) & (df["category"] == category) & (df["year"] == year) & (df["measure"] == measure)
        ]
        assert len(match) == 1, f"expected one row for {table}/{category}/{year}/{measure}"
        return match["value"].iloc[0]

    def test_total_first_offences(self, latest_data):
        assert self._value(latest_data, "1a", "Total", "first_count") == 7409

    def test_total_all_offences(self, latest_data):
        assert self._value(latest_data, "1a", "Total", "total_count") == 28188

    def test_total_percentage(self, latest_data):
        assert self._value(latest_data, "1a", "Total", "first_pct") == pytest.approx(26.3, abs=0.05)

    def test_prior_year_comparison_column(self, latest_data):
        """Every table leads with the prior year, which must not collide."""
        assert self._value(latest_data, "1a", "Total", "first_pct", "2023-24") == pytest.approx(26.5, abs=0.05)

    def test_youngest_age_band(self, latest_data):
        assert self._value(latest_data, "1a", "10 to 17", "first_count") == 599

    def test_alias_repaired_age_band(self, latest_data):
        """The published label for this band is typo'd as '40 t0 49'."""
        assert self._value(latest_data, "1a", "40 to 49", "first_count") == 1167

    def test_male_first_offences(self, latest_data):
        assert self._value(latest_data, "2a", "Male", "first_count") == 5141

    def test_female_percentage(self, latest_data):
        assert self._value(latest_data, "2a", "Female", "first_pct") == pytest.approx(36.8, abs=0.05)

    def test_motoring_offences(self, latest_data):
        assert self._value(latest_data, "3a", "Motoring", "first_count") == 4464

    def test_imprisonment_disposals(self, latest_data):
        assert self._value(latest_data, "4a", "Imprisonment", "first_count") == 202

    def test_monetary_penalty_percentage(self, latest_data):
        assert self._value(latest_data, "4a", "Monetary Penalty", "first_pct") == pytest.approx(34.0, abs=0.05)

    def test_caution_diversions(self, latest_data):
        assert self._value(latest_data, "4d", "Caution", "first_count") == 1277


class TestConvictionsAndDiversionsSplit:
    """Table 3e splits each measure into convictions and diversions."""

    @pytest.fixture(scope="class")
    def table_3e(self):
        df = fte.get_latest_data()
        return df[df["table"] == "3e"]

    def test_both_measure_families_present(self, table_3e):
        measures = set(table_3e["measure"])
        assert {"first_convictions_count", "first_diversions_count"}.issubset(measures)

    def test_convictions_count(self, table_3e):
        row = table_3e[
            (table_3e["category"] == "Total")
            & (table_3e["year"] == "2024-25")
            & (table_3e["measure"] == "first_convictions_count")
        ]
        assert row["value"].iloc[0] == 5667

    def test_diversions_count(self, table_3e):
        row = table_3e[
            (table_3e["category"] == "Total")
            & (table_3e["year"] == "2024-25")
            & (table_3e["measure"] == "first_diversions_count")
        ]
        assert row["value"].iloc[0] == 1742

    def test_split_sums_to_headline_total(self, table_3e):
        """Convictions plus diversions should equal the Table 1a headline."""
        total = table_3e[(table_3e["category"] == "Total") & (table_3e["year"] == "2024-25")]
        convictions = total[total["measure"] == "first_convictions_count"]["value"].iloc[0]
        diversions = total[total["measure"] == "first_diversions_count"]["value"].iloc[0]
        assert convictions + diversions == 7409

    def test_suppressed_offence_yields_nan(self, table_3e):
        """Robbery counts are suppressed but its total is published."""
        robbery = table_3e[(table_3e["category"] == "Robbery") & (table_3e["year"] == "2024-25")]
        counts = robbery[robbery["measure"] == "first_convictions_count"]["value"]
        assert counts.isna().all()


class TestBreakdownAccessors:
    """The per-breakdown convenience wrappers."""

    def test_list_breakdowns(self):
        assert set(fte.list_breakdowns()) == EXPECTED_BREAKDOWNS

    def test_by_age(self):
        assert set(fte.get_by_age()["breakdown"]) == {"age_band"}

    def test_by_gender(self):
        df = fte.get_by_gender()
        assert set(df["breakdown"]) == {"gender"}
        assert {"Male", "Female"}.issubset(set(df["category"]))

    def test_by_offence(self):
        assert set(fte.get_by_offence()["breakdown"]) == {"offence"}

    def test_by_disposal(self):
        assert set(fte.get_by_disposal()["breakdown"]) == {"disposal"}

    def test_index_reset(self):
        assert fte.get_by_age().index[0] == 0

    def test_unknown_breakdown_raises(self):
        with pytest.raises(FirstTimeEntrantsNotFoundError, match="Unknown breakdown"):
            fte.get_latest_data("ethnicity")


class TestHeadlineSeries:
    """Table 5 carries the long-run headline percentage series."""

    @pytest.fixture(scope="class")
    def series(self):
        return fte.get_headline_series()

    def test_not_empty(self, series):
        assert len(series) >= 10

    def test_single_measure(self, series):
        assert set(series["measure"]) == {"first_pct"}

    def test_years_unique(self, series):
        assert not series["year"].duplicated().any()

    def test_years_contiguous(self, series):
        starts = sorted(int(y[:4]) for y in series["year"])
        assert starts == list(range(starts[0], starts[-1] + 1))

    def test_percentages_plausible(self, series):
        """The headline rate has sat in the mid-20s to low-30s for a decade."""
        assert series["value"].between(15, 40).all()

    def test_latest_matches_table_1a(self, series):
        latest = series.sort_values("year")["value"].iloc[-1]
        assert latest == pytest.approx(26.3, abs=0.05)


class TestHistoricalEditions:
    """Older editions use a different layout and must still parse."""

    @pytest.fixture(scope="class")
    def editions(self):
        """Parse one modern and one pre-2017 edition for comparison."""
        pubs = {p["year"]: p for p in fte.list_publications()}
        parsed = {}
        for year in ("2020-21", "2015-16"):
            path = fte.download_file(fte.find_data_file(pubs[year]["url"]))
            parsed[year] = fte.parse_data(path)
        return parsed

    def test_both_parse(self, editions):
        assert all(len(df) > 300 for df in editions.values())

    def test_schema_matches_across_layouts(self, editions):
        frames = list(editions.values())
        assert list(frames[0].columns) == list(frames[1].columns)

    def test_banded_year_layout_has_no_duplicate_keys(self, editions):
        """Pre-2017 editions put years in a merged band above the header."""
        old = editions["2015-16"]
        assert not old.duplicated(["table", "category", "year", "measure"]).any()

    def test_banded_layout_resolves_two_years(self, editions):
        """The band row must yield both the prior and reporting year."""
        assert len(set(editions["2015-16"]["year"])) >= 2

    def test_historical_breakdowns_recognised(self, editions):
        assert {"age_band", "gender"}.issubset(set(editions["2015-16"]["breakdown"]))

    def test_editions_concatenate(self, editions):
        combined = pd.concat(editions.values(), ignore_index=True)
        assert len(combined) == sum(len(df) for df in editions.values())


class TestValueParsing:
    """Unit tests for the cell value parser - no network calls needed."""

    def test_plain_integer(self):
        assert fte._parse_value("42") == 42.0

    def test_thousands_separator(self):
        assert fte._parse_value("1,277") == 1277.0

    def test_decimal(self):
        assert fte._parse_value("26.3") == 26.3

    def test_percent_sign_stripped(self):
        assert fte._parse_value("26.3%") == 26.3

    def test_zero(self):
        assert fte._parse_value("0") == 0.0

    @pytest.mark.parametrize("marker", ["[z]", "[c]", "[x]", "[low]", "-", "", "  ", ":", "N/A", "n/a", "*"])
    def test_suppression_markers(self, marker):
        assert math.isnan(fte._parse_value(marker))

    def test_brace_typo_marker(self):
        """One published table writes '[d}' rather than '[d]'."""
        assert math.isnan(fte._parse_value("[d}"))

    def test_unparseable_returns_nan(self):
        assert math.isnan(fte._parse_value("not a number"))

    def test_whitespace_stripped(self):
        assert fte._parse_value("  1,234  ") == 1234.0


class TestYearNormalisation:
    """Unit tests for financial year parsing - no network calls needed."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2024/25", "2024-25"),
            ("2024-25", "2024-25"),
            ("2024 - 2025", "2024-25"),
            ("First offences 2024/25", "2024-25"),
            ("2024/2025 All convictions", "2024-25"),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert fte._normalise_year(raw) == expected

    @pytest.mark.parametrize("raw", ["Age band", "", "Total", "Gender"])
    def test_non_years_return_none(self, raw):
        assert fte._normalise_year(raw) is None

    def test_previous_year(self):
        assert fte._previous_year("2021-22") == "2020-21"

    def test_previous_year_across_century(self):
        assert fte._previous_year("2000-01") == "1999-00"


class TestMeasureDerivation:
    """Unit tests for header-to-measure mapping - no network calls needed."""

    @pytest.mark.parametrize(
        "header,expected",
        [
            ("2024-25 First offences", "first_count"),
            ("2024-25 All convictions and diversions", "total_count"),
            ("2024-25 First offences as % of all convictions", "first_pct"),
            ("2024-25 First convictions", "first_count"),
            ("First offences: convictions", "first_convictions_count"),
            ("First offences: diversions", "first_diversions_count"),
            ("First offences: convictions as a percentage", "first_convictions_pct"),
            ("First offences: diversions as a percentage", "first_diversions_pct"),
        ],
    )
    def test_derivation(self, header, expected):
        assert fte._measure_from_header(header) == expected

    def test_note_refs_ignored(self):
        assert fte._measure_from_header("2024-25 First offences [note 2]") == "first_count"

    def test_percentage_word_detected(self):
        assert fte._measure_from_header("First offences as a percentage").endswith("_pct")

    def test_convictions_split_is_table_3e_only(self):
        """Only Table 3e mixes both in one table, so only it needs the split."""
        assert fte._measure_from_header("2024-25 First convictions") == "first_count"
        assert fte._measure_from_header("First offences: convictions") == "first_convictions_count"


class TestCategoryNormalisation:
    """Unit tests for row label canonicalisation - no network calls needed."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("40 t0 49", "40 to 49"),
            ("10 - 17", "10 to 17"),
            ("Total  [note 3]", "Total"),
            ("  Male  ", "Male"),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert fte._normalise_category(raw) == expected

    def test_unknown_label_passes_through(self):
        assert fte._normalise_category("Motoring") == "Motoring"


class TestYearBandResolution:
    """Unit tests for the pre-2017 merged year band - no network calls needed."""

    def test_forward_fills_merged_cells(self):
        rows = [["", "2015/16", "2016/17"], ["Age band", "a", "b", "c"]]
        assert fte._year_band(rows, 1) == {1: "2015-16", 2: "2016-17", 3: "2016-17"}

    def test_no_band_row_returns_empty(self):
        rows = [["Table 1a: something"], ["Age band", "2024-25 First offences"]]
        assert fte._year_band(rows, 1) == {}

    def test_header_at_top_returns_empty(self):
        assert fte._year_band([["Age band", "a"]], 0) == {}

    def test_leading_year_corrected_on_collision(self):
        columns = [(1, "2021-22", "first_pct"), (4, "2021-22", "first_pct")]
        assert fte._fix_leading_year(columns) == [(1, "2020-21", "first_pct"), (4, "2021-22", "first_pct")]

    def test_distinct_years_untouched(self):
        columns = [(1, "2020-21", "first_pct"), (4, "2021-22", "first_pct")]
        assert fte._fix_leading_year(columns) == columns

    def test_same_year_different_measure_untouched(self):
        columns = [(1, "2021-22", "first_count"), (4, "2021-22", "first_pct")]
        assert fte._fix_leading_year(columns) == columns

    def test_single_column_untouched(self):
        columns = [(1, "2021-22", "first_pct")]
        assert fte._fix_leading_year(columns) == columns


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    @staticmethod
    def _frame(n=600, **overrides):
        data = {
            "table": ["1a"] * n,
            "breakdown": ["age_band"] * n,
            "category": ["Total"] * n,
            "year": ["2024-25"] * n,
            "measure": ["first_count"] * n,
            "value": [1.0] * n,
        }
        data.update(overrides)
        return pd.DataFrame(data)

    def test_validate_passes(self):
        assert fte.validate_data(self._frame()) is True

    def test_validate_empty_dataframe(self):
        with pytest.raises(FirstTimeEntrantsValidationError, match="empty"):
            fte.validate_data(pd.DataFrame())

    def test_validate_none(self):
        with pytest.raises(FirstTimeEntrantsValidationError, match="empty"):
            fte.validate_data(None)

    def test_validate_missing_columns(self):
        df = self._frame().drop(columns=["value"])
        with pytest.raises(FirstTimeEntrantsValidationError, match="Missing required columns"):
            fte.validate_data(df)

    def test_validate_too_few_records(self):
        with pytest.raises(FirstTimeEntrantsValidationError, match="Too few records"):
            fte.validate_data(self._frame(n=10))

    def test_validate_custom_minimum(self):
        assert fte.validate_data(self._frame(n=10), min_records=5) is True

    def test_validate_negative_values(self):
        df = self._frame()
        df.loc[0, "value"] = -1.0
        with pytest.raises(FirstTimeEntrantsValidationError, match="[Nn]egative"):
            fte.validate_data(df)

    def test_validate_percentage_out_of_range(self):
        df = self._frame(measure=["first_pct"] * 600)
        df.loc[0, "value"] = 150.0
        with pytest.raises(FirstTimeEntrantsValidationError):
            fte.validate_data(df)

    def test_validate_tolerates_suppressed_values(self):
        df = self._frame()
        df.loc[0, "value"] = float("nan")
        assert fte.validate_data(df) is True


class TestCacheManagement:
    """Cache clearing must not break subsequent downloads."""

    def test_clear_returns_count(self):
        assert isinstance(fte.clear_cache(), int)

    def test_download_after_clear(self):
        fte.clear_cache()
        assert fte.get_latest_data() is not None
