"""Integrity tests for the Youth Justice Agency workload statistics module.

Tests use real data downloaded from justice-ni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures. Parsing, discovery
and validation edge cases are covered by network-free unit tests that build a
small ODS workbook in the same layout as the real one.
"""

import math

import pandas as pd
import pytest
from bs4 import BeautifulSoup
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P

from bolster.data_sources.justice import yja_workload as yja
from bolster.data_sources.justice.yja_workload import (
    YouthJusticeDataError,
    YouthJusticeDataNotFoundError,
    YouthJusticeValidationError,
)

# Tables whose back-series runs the full length of the bulletin (2008/09 onward)
FULL_HISTORY_TABLES = [5, 6, 7, 8, 9, 10, 11, 12, *range(14, 33), 35, 36]


class TestPublicationDiscovery:
    """Discovery of the bulletin and its workbook from DoJ pages."""

    @pytest.fixture(scope="class")
    def publications(self):
        return yja.list_publications()

    def test_publication_found(self, publications):
        assert not publications.empty

    def test_required_columns(self, publications):
        assert set(publications.columns) == {"year_start", "financial_year", "url"}

    def test_latest_is_recent(self, publications):
        """The series is annual, so the newest bulletin should be current."""
        assert publications.year_start.max() >= 2025

    def test_urls_absolute(self, publications):
        assert publications.url.str.startswith("https://www.justice-ni.gov.uk/publications/").all()

    def test_find_publication_defaults_to_latest(self, publications):
        assert yja.find_publication()["year_start"] == publications.year_start.max()

    def test_workbook_url_is_ods(self, publications):
        assert yja.get_data_file_url(publications.url.iloc[0]).lower().endswith(".ods")

    def test_earlier_publication_resolves_to_its_own_workbook(self):
        publication = yja.find_publication(2024)
        assert publication["financial_year"] == "2024/25"
        assert yja.get_data_file_url(str(publication["url"])).lower().endswith(".ods")

    def test_unpublished_year_raises(self):
        with pytest.raises(YouthJusticeDataNotFoundError):
            yja.get_data_file_url(str(yja.find_publication(1990)["url"]))


class TestLatestDataIntegrity:
    """Integrity tests for the parsed long frame."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return yja.get_latest_data()

    def test_required_columns(self, latest_data):
        assert set(latest_data.columns) == {
            "table_id",
            "table_title",
            "block",
            "row_label",
            "row_group",
            "column",
            "value",
        }

    def test_validates(self, latest_data):
        assert yja.validate_data(latest_data)

    def test_all_36_tables_present(self, latest_data):
        assert sorted(latest_data.table_id.unique()) == list(range(1, 37))

    def test_no_note_markers_left_in_labels(self, latest_data):
        for column in ("table_title", "block", "row_label", "column"):
            assert not latest_data[column].str.contains(r"\[Note", case=False, na=False).any(), column

    def test_no_dangling_commas_in_headers(self, latest_data):
        assert not latest_data["column"].str.endswith(",").any()

    @pytest.mark.parametrize("table_id", FULL_HISTORY_TABLES)
    def test_full_history_tables_span_2008_to_latest(self, latest_data, table_id):
        table = latest_data[latest_data.table_id == table_id]
        years = set(table.row_label.map(yja._year_start).dropna()) | set(table.column.map(yja._year_start).dropna())
        assert min(years) == 2008
        assert max(years) >= 2025
        assert len(years) == max(years) - 2008 + 1, f"table {table_id} has a gap in its financial years"

    def test_short_series_start_where_published(self, latest_data):
        def years(table_id):
            table = latest_data[latest_data.table_id == table_id]
            return set(table.row_label.map(yja._year_start).dropna()) | set(table.column.map(yja._year_start).dropna())

        assert min(years(1)) == 2023
        assert min(years(13)) == 2019
        assert min(years(33)) == 2009

    def test_suppression_is_rare(self, latest_data):
        assert latest_data.value.isna().mean() < 0.05

    def test_list_tables(self):
        tables = yja.list_tables()
        assert list(tables.columns) == ["table_id", "table_title", "records"]
        assert len(tables) == 36


class TestReferralsIntegrity:
    """Integrity tests for the referral accessors."""

    @pytest.fixture(scope="class")
    def summary(self):
        return yja.get_referrals_summary()

    @pytest.fixture(scope="class")
    def by_type(self):
        return yja.get_referrals_by_type()

    @pytest.fixture(scope="class")
    def by_area(self):
        return yja.get_referrals_by_area()

    def test_summary_columns(self, summary):
        assert list(summary.columns) == [
            "financial_year",
            "year_start",
            "referrals",
            "children",
            "population_10_17",
            "rate_per_1000",
        ]

    def test_summary_covers_18_years(self, summary):
        assert summary.year_start.min() == 2008
        assert summary.year_start.max() >= 2025
        assert len(summary) == summary.year_start.max() - 2008 + 1

    def test_summary_ascending_and_unique(self, summary):
        assert summary.year_start.is_monotonic_increasing
        assert summary.year_start.is_unique

    def test_summary_value_ranges(self, summary):
        assert summary.referrals.between(500, 4000).all()
        assert summary.children.between(300, 2500).all()
        assert summary.population_10_17.between(150_000, 250_000).all()
        assert summary.rate_per_1000.between(1, 12).all()

    def test_children_never_exceed_referrals(self, summary):
        assert (summary.children <= summary.referrals).all()

    def test_rate_matches_children_over_population(self, summary):
        """The published rate is children per 1,000 of the 10-17 population, rounded to 1dp."""
        derived = summary.children / summary.population_10_17 * 1000
        assert (derived - summary.rate_per_1000).abs().max() < 0.06

    def test_referral_types_sum_to_total(self, summary, by_type):
        """Types suppressed in early years are NaN, but the rest must still add up exactly."""
        summed = by_type.groupby("year_start").referrals.sum()
        totals = summary.set_index("year_start").referrals
        assert (summed == totals.loc[summed.index]).all()

    def test_referral_types_include_diversionary_and_court_ordered(self, by_type):
        assert {"Diversionary", "Court Ordered"}.issubset(set(by_type.referral_type))

    def test_total_excluded_from_types(self, by_type):
        assert not by_type.referral_type.str.startswith("Total").any()

    def test_areas_sum_to_total(self, summary, by_area):
        """DoJ's own 2024/25 area rows sum to 1,400 against a published total of 1,402, so allow a few."""
        summed = by_area.groupby("year_start").referrals.sum()
        totals = summary.set_index("year_start").referrals
        assert (summed - totals.loc[summed.index]).abs().max() <= 5

    def test_area_names_are_ni_districts(self, by_area):
        assert {"Belfast", "Mid Ulster", "Causeway Coast and Glens"}.issubset(set(by_area.area))
        assert "Total" not in set(by_area.area)

    def test_belfast_is_largest_district_most_years(self, by_area):
        busiest = by_area[~by_area.area.isin(["Resident outside NI", "Unassigned"])]
        top = busiest.loc[busiest.groupby("year_start").referrals.idxmax()]
        assert (top.area == "Belfast").mean() > 0.6


class TestCustodyIntegrity:
    """Integrity tests for the custody accessors."""

    @pytest.fixture(scope="class")
    def by_age(self):
        return yja.get_children_in_custody_by_age()

    @pytest.fixture(scope="class")
    def population(self):
        return yja.get_custody_population()

    @pytest.fixture(scope="class")
    def pace(self):
        return yja.get_pace_conversion()

    def test_age_bands(self, by_age):
        assert set(by_age.age_band) == {"10 to 13", "14", "15", "16", "17"}

    def test_age_counts_non_negative(self, by_age):
        assert (by_age.children >= 0).all()

    def test_children_in_custody_fell_over_time(self, by_age):
        yearly = by_age.groupby("year_start").children.sum()
        assert yearly.loc[2008] > yearly.loc[yearly.index.max()]

    def test_population_statuses(self, population):
        assert set(population.status) == {"PACE", "Remand", "Sentence"}

    def test_population_value_range(self, population):
        assert population.average_population.between(0, 40).all()

    def test_remand_exceeds_sentence_in_latest_year(self, population):
        latest = population[population.year_start == population.year_start.max()].set_index("status")
        assert latest.loc["Remand", "average_population"] > latest.loc["Sentence", "average_population"]

    def test_pace_columns(self, pace):
        assert list(pace.columns) == [
            "financial_year",
            "year_start",
            "pace_admissions",
            "pace_to_remand_sentence",
            "conversion_rate",
        ]

    def test_conversion_rate_is_a_proportion(self, pace):
        assert pace.conversion_rate.between(0, 1).all()

    def test_conversion_rate_matches_counts(self, pace):
        derived = pace.pace_to_remand_sentence / pace.pace_admissions
        assert (derived - pace.conversion_rate).abs().max() < 0.006

    def test_conversions_never_exceed_admissions(self, pace):
        assert (pace.pace_to_remand_sentence <= pace.pace_admissions).all()


def _make_ods(path, sheets: dict[str, list[list[str]]]) -> None:
    """Write a workbook whose cells are plain strings, as in the DoJ layout."""
    doc = OpenDocumentSpreadsheet()
    for name, rows in sheets.items():
        table = Table(name=name)
        for cells in rows:
            row = TableRow()
            for text in cells:
                cell = TableCell(valuetype="string")
                cell.addElement(P(text=text))
                row.addElement(cell)
            table.addElement(row)
        doc.spreadsheet.addElement(table)
    doc.save(str(path))


PREAMBLE = ["This worksheet contains one table."], ["Return to table of contents"]

FIXTURE_SHEETS = {
    "Cover_sheet": [["Youth Justice Agency Annual Workload Statistics"]],
    "5": [
        ["Table 5: Referrals to YJS, Number of Children Involved and Population Comparison, 2008/09 to 2010/11"],
        *PREAMBLE,
        [
            "Financial Year",
            "Total referrals to the YJS",
            "Individual children involved",
            "NI population aged 10 to 17 [Note 4 and 5],",
            "Rate per 1,000 [Note 5]",
        ],
        ["2008/09 [Note 6]", "1,636", "1,143", "199,352", "5.7"],
        ["2009/10", "1,927", "1,229", "197,816", "6.2"],
        ["2010/11", "2,111", "1,332", "195,689", "6.8"],
    ],
    "6": [
        ["Table 6: Referrals by Type, 2008/09 to 2010/11"],
        *PREAMBLE,
        ["Count of Referrals"],
        ["Financial Year", "Diversionary", "Court Ordered", "Community Orders [Note 6], [Note 7]", "Total Referrals"],
        ["2008/09 [Note 6]", "844", "792", "[x]", "1,636"],
        ["2009/10", "949", "892", "86", "1,927"],
        ["2010/11", "1,051", "960", "100", "2,111"],
        ["Percentage of Referrals"],
        ["Financial Year", "% Diversionary", "% Court Ordered", "% Community Orders", "% Total Referrals"],
        ["2008/09", "51.6", "48.4", "[x]", "100.0"],
        ["2009/10", "49.2", "46.3", "4.5", "100.0"],
        ["2010/11", "49.8", "45.5", "4.7", "100.0"],
    ],
    "12": [
        ["Table 12: Referrals To YJS By Area Of Residence [Note 11], 2008/09 to 2009/10"],
        *PREAMBLE,
        ["Area", "2008/09", "2009/10"],
        ["Belfast", "433", "568"],
        ["Mid Ulster", "91", "100"],
        ["Unassigned [Note 12]", "3", "9"],
        ["Total", "527", "677"],
    ],
    "20": [
        ["Table 20: Children In Custody By Age, 2008/09 to 2009/10"],
        *PREAMBLE,
        ["Count of Children in Custody"],
        ["Financial Year", "10 to 13", "14", "Total Children"],
        ["2008/09", "7", "13", "20"],
        ["2009/10", "8", "27", "35"],
        ["Percentage of Children in Custody"],
        ["Financial Year", "% 10 to 13", "% 14", "% Total Children"],
        ["2008/09", "35.0", "65.0", "100.0"],
        ["2009/10", "22.9", "77.1", "100.0"],
    ],
    "32": [
        ["Table 32: Average Population By Status, 2008/09 to 2009/10"],
        *PREAMBLE,
        ["Financial Year", "PACE", "Remand", "Sentence", "Total"],
        ["2008/09", "0.4", "16.9", "9.5", "26.8"],
        ["2009/10", "0.6", "15.4", "10.1", "26.2"],
    ],
    "33": [
        ["Table 33: Maximum And Minimum Monthly Population, 2009/10 to 2009/10"],
        *PREAMBLE,
        ["Financial Year", "Month", "Max Population", "Min Population"],
        ["2009/10", "April", "30", "22"],
        ["2009/10", "May", "31", "20"],
    ],
    "36": [
        ["Table 36: PACE To Remand/Sentence Conversion Estimate, 2008/09 to 2009/10"],
        *PREAMBLE,
        ["Financial year", "PACE admissions", "PACE to remand/sentence", "Conversion rate (%)"],
        ["2008/09", "118", "63", "53.4"],
        ["2009/10", "200", "101", "50.5"],
    ],
}


@pytest.fixture(scope="module")
def fixture_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("yja") / "excel_tables.ods"
    _make_ods(path, FIXTURE_SHEETS)
    return path


@pytest.fixture
def offline(monkeypatch, fixture_path):
    """Serve the small fixture workbook wherever the module would fetch the real one."""
    monkeypatch.setattr(yja, "get_latest_data", lambda year=None, force_refresh=False: yja.parse_data(fixture_path))


class TestParsing:
    """Network-free tests of the workbook parser against a small fixture."""

    @pytest.fixture(scope="class")
    def parsed(self, fixture_path):
        return yja.parse_data(fixture_path)

    def test_only_numbered_tables_are_parsed(self, parsed):
        assert sorted(parsed.table_id.unique()) == [5, 6, 12, 20, 32, 33, 36]

    def test_title_has_table_prefix_and_notes_removed(self, parsed):
        titles = parsed.set_index("table_id").table_title
        assert titles.loc[12].iloc[0] == "Referrals To YJS By Area Of Residence, 2008/09 to 2009/10"

    def test_single_table_sheet_has_empty_block(self, parsed):
        assert set(parsed[parsed.table_id == 5].block) == {""}

    def test_stacked_blocks_are_labelled(self, parsed):
        assert set(parsed[parsed.table_id == 6].block) == {"Count of Referrals", "Percentage of Referrals"}

    def test_commentary_rows_are_not_data(self, parsed):
        assert not parsed.row_label.str.contains("worksheet|table of contents", case=False).any()

    def test_values_are_numeric_with_thousands_separators(self, parsed):
        row = parsed[
            (parsed.table_id == 5) & (parsed.row_label == "2008/09") & (parsed.column == "Total referrals to the YJS")
        ]
        assert row.value.iloc[0] == 1636

    def test_suppressed_cells_become_nan(self, parsed):
        suppressed = parsed[
            (parsed.table_id == 6) & (parsed.column == "Community Orders") & (parsed.row_label == "2008/09")
        ]
        assert suppressed.value.isna().all()

    def test_multi_note_and_trailing_comma_headers_are_cleaned(self, parsed):
        assert "NI population aged 10 to 17" in set(parsed.column)
        assert "Community Orders" in set(parsed.column)

    def test_second_label_column_goes_into_row_group(self, parsed):
        table = parsed[parsed.table_id == 33]
        assert set(table.row_group) == {"April", "May"}
        assert set(table.row_label) == {"2009/10"}

    def test_unreadable_workbook_raises(self, tmp_path):
        bad = tmp_path / "bad.ods"
        bad.write_text("not an ods file")
        with pytest.raises(YouthJusticeDataError, match="Failed to read workbook"):
            yja.parse_data(bad)

    def test_workbook_without_tables_raises(self, tmp_path):
        path = tmp_path / "empty.ods"
        _make_ods(path, {"Cover_sheet": [["Just a cover"]]})
        with pytest.raises(YouthJusticeDataError, match="No data tables found"):
            yja.parse_data(path)


class TestAccessorsOffline:
    """Network-free tests of the typed accessors against the fixture workbook."""

    def test_summary(self, offline):
        df = yja.get_referrals_summary()
        assert list(df.financial_year) == ["2008/09", "2009/10", "2010/11"]
        assert list(df.referrals) == [1636, 1927, 2111]
        assert list(df.children) == [1143, 1229, 1332]
        assert df.rate_per_1000.iloc[0] == 5.7
        assert df.population_10_17.iloc[2] == 195689

    def test_referrals_by_type_uses_count_block_and_drops_total(self, offline):
        df = yja.get_referrals_by_type()
        assert set(df.referral_type) == {"Diversionary", "Court Ordered", "Community Orders"}
        assert df[(df.year_start == 2009) & (df.referral_type == "Diversionary")].referrals.iloc[0] == 949
        assert math.isnan(df[(df.year_start == 2008) & (df.referral_type == "Community Orders")].referrals.iloc[0])

    def test_referrals_by_area_drops_total_and_note_markers(self, offline):
        df = yja.get_referrals_by_area()
        assert set(df.area) == {"Belfast", "Mid Ulster", "Unassigned"}
        assert df[df.year_start == 2008].referrals.sum() == 527
        assert df[df.year_start == 2009].referrals.sum() == 677

    def test_custody_by_age_uses_count_block(self, offline):
        df = yja.get_children_in_custody_by_age()
        assert set(df.age_band) == {"10 to 13", "14"}
        assert df[(df.year_start == 2009) & (df.age_band == "14")].children.iloc[0] == 27

    def test_custody_population_drops_total(self, offline):
        df = yja.get_custody_population()
        assert set(df.status) == {"PACE", "Remand", "Sentence"}
        assert df[(df.year_start == 2008) & (df.status == "Remand")].average_population.iloc[0] == 16.9

    def test_pace_conversion_is_a_proportion(self, offline):
        df = yja.get_pace_conversion()
        assert df.conversion_rate.iloc[0] == pytest.approx(0.534)
        assert list(df.pace_to_remand_sentence) == [63, 101]

    def test_missing_table_raises(self, monkeypatch, fixture_path):
        long_frame = yja.parse_data(fixture_path)
        long_frame = long_frame[long_frame.table_id != 36]
        monkeypatch.setattr(yja, "get_latest_data", lambda year=None, force_refresh=False: long_frame)
        with pytest.raises(YouthJusticeDataNotFoundError, match="No table matching"):
            yja.get_pace_conversion()

    def test_list_tables(self, offline):
        tables = yja.list_tables()
        assert list(tables.table_id) == [5, 6, 12, 20, 32, 33, 36]
        assert tables.records.min() > 0


class TestDiscoveryOffline:
    """Network-free tests of publication and workbook discovery."""

    TOPIC_HTML = """
    <a href="/publications/youth-justice-agency-annual-workload-statistics-2024-25">2024/25</a>
    <a href="/publications/youth-justice-agency-annual-workload-statistics-2025-26/">2025/26</a>
    <a href="/publications/youth-justice-agency-annual-workload-statistics-2025-26">duplicate link</a>
    <a href="/articles/youth-justice-agency-governance">Governance</a>
    """

    def test_list_publications_dedupes_and_sorts(self, monkeypatch):
        monkeypatch.setattr(yja, "fetch_soup", lambda url: BeautifulSoup(self.TOPIC_HTML, "html.parser"))
        df = yja.list_publications()
        assert list(df.year_start) == [2025, 2024]
        assert list(df.financial_year) == ["2025/26", "2024/25"]
        assert df.url.iloc[0] == (
            "https://www.justice-ni.gov.uk/publications/youth-justice-agency-annual-workload-statistics-2025-26/"
        )

    def test_list_publications_without_links_raises(self, monkeypatch):
        monkeypatch.setattr(yja, "fetch_soup", lambda url: BeautifulSoup("<a href='/x'>x</a>", "html.parser"))
        with pytest.raises(YouthJusticeDataNotFoundError, match="No workload statistics publication"):
            yja.list_publications()

    def test_list_publications_fetch_failure_raises(self, monkeypatch):
        def boom(url):
            raise RuntimeError("down")

        monkeypatch.setattr(yja, "fetch_soup", boom)
        with pytest.raises(YouthJusticeDataNotFoundError, match="Failed to fetch topic page"):
            yja.list_publications()

    def test_find_publication_by_year_builds_slug(self):
        publication = yja.find_publication(2023)
        assert publication["financial_year"] == "2023/24"
        assert str(publication["url"]).endswith("youth-justice-agency-annual-workload-statistics-2023-24")

    def test_find_publication_defaults_to_latest(self, monkeypatch):
        monkeypatch.setattr(yja, "fetch_soup", lambda url: BeautifulSoup(self.TOPIC_HTML, "html.parser"))
        assert yja.find_publication()["year_start"] == 2025

    def test_get_data_file_url_returns_first_ods(self, monkeypatch):
        monkeypatch.setattr(
            yja,
            "scrape_file_links",
            lambda url, ext, base_url=None: [{"url": "https://example/a.ods"}, {"url": "https://example/b.ods"}],
        )
        assert yja.get_data_file_url("https://example/page") == "https://example/a.ods"

    def test_get_data_file_url_no_attachment_raises(self, monkeypatch):
        monkeypatch.setattr(yja, "scrape_file_links", lambda url, ext, base_url=None: [])
        with pytest.raises(YouthJusticeDataNotFoundError, match="No ODS workbook"):
            yja.get_data_file_url("https://example/page")

    def test_get_data_file_url_page_failure_raises(self, monkeypatch):
        def boom(url, ext, base_url=None):
            raise RuntimeError("404")

        monkeypatch.setattr(yja, "scrape_file_links", boom)
        with pytest.raises(YouthJusticeDataNotFoundError, match="Failed to fetch publication page"):
            yja.get_data_file_url("https://example/page")

    def test_get_latest_data_wires_discovery_download_and_parse(self, monkeypatch, fixture_path):
        monkeypatch.setattr(yja, "find_publication", lambda year=None: {"financial_year": "2025/26", "url": "page"})
        monkeypatch.setattr(yja, "get_data_file_url", lambda url: "https://example/a.ods")
        monkeypatch.setattr(yja, "download_file", lambda url, force_refresh=False: fixture_path)
        assert sorted(yja.get_latest_data().table_id.unique()) == [5, 6, 12, 20, 32, 33, 36]


class TestLabelHelpers:
    """Network-free tests of the small label helpers."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Community Orders [Note 6], [Note 7]", "Community Orders"),
            ("2008/09 [Note 6]", "2008/09"),
            ("NI population aged 10 to 17 [Note 4 and 5],", "NI population aged 10 to 17"),
            ("Rate per 1000 [Note 4 and 5], 2008/09", "Rate per 1000, 2008/09"),
            ("Belfast", "Belfast"),
        ],
    )
    def test_clean_label(self, raw, expected):
        assert yja._clean_label(raw) == expected

    @pytest.mark.parametrize(("label", "expected"), [("2008/09", 2008), ("2025/26 [Note 1]", 2025), ("Total", None)])
    def test_year_start(self, label, expected):
        assert yja._year_start(label) == expected

    @pytest.mark.parametrize(("start", "expected"), [(2008, "2008/09"), (2025, "2025/26"), (1999, "1999/00")])
    def test_financial_year_label(self, start, expected):
        assert yja.financial_year_label(start) == expected


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    @staticmethod
    def _frame(rows: int = 5, **overrides) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "table_id": [1] * rows,
                "table_title": ["t"] * rows,
                "block": [""] * rows,
                "row_label": ["2008/09"] * rows,
                "row_group": [None] * rows,
                "column": ["c"] * rows,
                "value": [1.0] * rows,
            }
        )
        for column, values in overrides.items():
            df[column] = values
        return df

    def test_valid_frame_passes(self):
        assert yja.validate_data(self._frame(), min_records=5)

    def test_empty_frame_raises(self):
        with pytest.raises(YouthJusticeValidationError, match="empty"):
            yja.validate_data(pd.DataFrame())

    def test_none_raises(self):
        with pytest.raises(YouthJusticeValidationError, match="empty"):
            yja.validate_data(None)

    def test_missing_columns_raises(self):
        with pytest.raises(YouthJusticeValidationError, match="Missing required columns"):
            yja.validate_data(self._frame().drop(columns=["block"]), min_records=1)

    def test_too_few_records_raises(self):
        with pytest.raises(YouthJusticeValidationError, match="Too few records"):
            yja.validate_data(self._frame(rows=3), min_records=10)

    def test_negative_values_raise(self):
        with pytest.raises(YouthJusticeValidationError, match="Negative values"):
            yja.validate_data(self._frame(value=[1.0, -1.0, 1.0, 1.0, 1.0]), min_records=1)

    def test_too_many_nans_raise(self):
        with pytest.raises(YouthJusticeValidationError, match="Too many unparsed"):
            yja.validate_data(self._frame(value=[float("nan")] * 4 + [1.0]), min_records=1)

    def test_clear_cache_returns_count(self):
        assert yja.clear_cache() >= 0
