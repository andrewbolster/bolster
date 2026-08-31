"""Integrity tests for the DfI YPBAS travel to/from school module.

Tests use real data downloaded from infrastructure-ni.gov.uk (no mocks).
Network calls are made once per class via ``scope="class"`` fixtures and
cached for the duration of the test session. Validation and classification
edge cases are covered by network-free unit tests.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from bolster.data_sources.dfi import school_travel
from bolster.data_sources.dfi.school_travel import SchoolTravelValidationError


class TestDetailDataIntegrity:
    """Integrity tests for the per-question detail tables."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return school_travel.get_latest_data()

    def test_required_columns(self, latest_data):
        expected = {
            "survey_year",
            "worksheet",
            "question",
            "category",
            "breakdown_type",
            "breakdown",
            "value_pct",
            "lower_ci",
            "upper_ci",
            "suppressed",
            "total_respondents",
        }
        assert expected.issubset(set(latest_data.columns))

    def test_not_empty(self, latest_data):
        assert len(latest_data) > 400

    def test_survey_year_is_recent(self, latest_data):
        assert latest_data["survey_year"].max() >= 2025

    def test_breakdown_types(self, latest_data):
        assert set(latest_data["breakdown_type"]) == {"all", "sex", "year_group"}

    def test_breakdowns_cover_sex_and_year_groups(self, latest_data):
        breakdowns = set(latest_data["breakdown"])
        assert {"All respondents", "Male", "Female"}.issubset(breakdowns)
        assert {f"Year {n}" for n in range(8, 13)}.issubset(breakdowns)

    def test_percentages_in_range(self, latest_data):
        values = latest_data["value_pct"].dropna()
        assert (values >= 0).all()
        assert (values <= 100).all()

    def test_confidence_bounds_bracket_estimate(self, latest_data):
        rows = latest_data.dropna(subset=["value_pct", "lower_ci", "upper_ci"])
        assert (rows["lower_ci"] <= rows["value_pct"]).all()
        assert (rows["value_pct"] <= rows["upper_ci"]).all()

    def test_suppressed_rows_carry_no_value(self, latest_data):
        suppressed = latest_data[latest_data["suppressed"]]
        assert not suppressed.empty
        assert suppressed["value_pct"].isna().all()

    def test_total_respondents_populated(self, latest_data):
        assert latest_data["total_respondents"].notna().all()
        assert (latest_data["total_respondents"] > 0).all()

    def test_year_group_totals_sum_to_all_respondents(self, latest_data):
        """The five year-group bases should sum to the all-respondents base."""
        with_year_groups = latest_data[latest_data["breakdown_type"] == "year_group"]
        checked = 0
        for _, sheet in latest_data.groupby("worksheet"):
            if not set(sheet["worksheet"]) & set(with_year_groups["worksheet"]):
                continue
            bases = sheet.groupby("breakdown")["total_respondents"].first()
            year_total = sum(bases[f"Year {n}"] for n in range(8, 13))
            assert year_total == bases["All respondents"]
            checked += 1
        assert checked >= 5

    def test_multiple_questions_parsed(self, latest_data):
        assert latest_data["question"].nunique() >= 10

    def test_validate_passes(self, latest_data):
        assert school_travel.validate_data(latest_data) is True


class TestTrendDataIntegrity:
    """Integrity tests for the multi-year trend tables."""

    @pytest.fixture(scope="class")
    def trend_data(self):
        return school_travel.get_trend_data()

    def test_required_columns(self, trend_data):
        expected = {"survey_year", "table", "question", "category", "value_pct", "total_respondents"}
        assert expected.issubset(set(trend_data.columns))

    def test_not_empty(self, trend_data):
        assert len(trend_data) > 100

    def test_survey_years(self, trend_data):
        years = sorted(trend_data["survey_year"].unique().tolist())
        assert years == [2016, 2019, 2022, 2025]

    def test_percentages_in_range(self, trend_data):
        assert (trend_data["value_pct"] >= 0).all()
        assert (trend_data["value_pct"] <= 100).all()

    def test_total_respondents_populated(self, trend_data):
        assert trend_data["total_respondents"].notna().all()

    def test_base_rows_excluded_from_categories(self, trend_data):
        categories = trend_data["category"].str.lower()
        assert not categories.str.startswith("total respondent").any()

    def test_questions_carry_no_percent_marker(self, trend_data):
        assert not trend_data["question"].str.contains("%").any()

    def test_car_travel_present_across_all_years(self, trend_data):
        car = trend_data[trend_data["category"].str.contains("Car", case=False, na=False)]
        assert set(car["survey_year"]) == {2016, 2019, 2022, 2025}


class TestPublicationDiscovery:
    """Tests for locating the latest publication."""

    def test_list_publications_returns_dated_entries(self):
        publications = school_travel.list_publications()
        assert publications
        assert all(isinstance(p["survey_year"], int) for p in publications)
        assert all(p["page_url"].startswith("https://") for p in publications)

    def test_publications_sorted_newest_first(self):
        years = [p["survey_year"] for p in school_travel.list_publications()]
        assert years == sorted(years, reverse=True)

    def test_latest_url_is_a_workbook(self):
        url, year = school_travel.get_latest_publication_url()
        assert url.lower().endswith((".xlsx", ".xls"))
        assert year >= 2025


class TestListQuestions:
    """Tests for the question listing helper."""

    def test_questions_parsed(self):
        assert len(school_travel.list_questions()) >= 10


class TestClassifyBreakdown:
    """Unit tests for breakdown classification - no network."""

    @pytest.mark.parametrize(
        ("group", "expected"),
        [
            ("All respondents", "all"),
            ("all", "all"),
            ("Male", "sex"),
            ("Female", "sex"),
            ("female", "sex"),
            ("Year 8", "year_group"),
            ("Year 12", "year_group"),
            ("Belfast", "other"),
            ("", "other"),
        ],
    )
    def test_classification(self, group, expected):
        assert school_travel.classify_breakdown(group) == expected


class TestCleanQuestion:
    """Unit tests for question-label tidying - no network."""

    def test_strips_percent_marker(self):
        assert school_travel._clean_question("How do you travel? (%)") == "How do you travel?"

    def test_strips_percent_marker_with_footnote(self):
        assert school_travel._clean_question("How do you travel? (%)*") == "How do you travel?"

    def test_collapses_whitespace(self):
        assert school_travel._clean_question("How  do you   travel?") == "How do you travel?"

    def test_leaves_plain_text_untouched(self):
        assert school_travel._clean_question("How do you travel?") == "How do you travel?"


class TestParsePercentage:
    """Unit tests for the percentage cell parser - no network."""

    def test_numeric_value(self):
        assert school_travel._parse_percentage(42.5) == (42.5, False)

    def test_numeric_string(self):
        assert school_travel._parse_percentage(" 12.3 ") == (12.3, False)

    def test_suppression_marker(self):
        assert school_travel._parse_percentage("*") == (None, True)

    def test_blank_cell(self):
        assert school_travel._parse_percentage(None) == (None, False)

    def test_unparseable_text(self):
        assert school_travel._parse_percentage("n/a") == (None, False)


class TestWorksheetParsingEdgeCases:
    """Unit tests for the worksheet parsers using synthetic sheets - no network."""

    def test_header_row_absent(self):
        sheet = pd.DataFrame([["Worksheet 1: Anything"], ["Car"]])
        assert school_travel._find_ci_header_row(sheet) is None

    def test_question_absent(self):
        sheet = pd.DataFrame([["Something else"], ["Car"]])
        assert school_travel._extract_question(sheet) == ""

    def test_question_without_colon(self):
        sheet = pd.DataFrame([["Worksheet 1 how do you travel"]])
        assert school_travel._extract_question(sheet) == "Worksheet 1 how do you travel"

    def test_total_respondents_row_absent(self):
        sheet = pd.DataFrame([["Car", 50.0]])
        assert school_travel._extract_total_respondents(sheet, ["All respondents"]) == {}

    def test_total_respondents_skips_unparseable(self):
        sheet = pd.DataFrame([["Total Respondents", "n/a", "1200"]])
        counts = school_travel._extract_total_respondents(sheet, ["Male", "Female"])
        assert counts == {"Female": 1200}

    def test_worksheet_without_ci_table_yields_empty_frame(self):
        sheet = pd.DataFrame([["Worksheet 1: Q"], ["Car", 50.0]])
        assert school_travel._parse_worksheet(sheet, "1").empty


class TestWorkbookErrorPaths:
    """Unit tests for workbook-level failures using a throwaway file."""

    @pytest.fixture(scope="class")
    def empty_workbook(self, tmp_path_factory):
        path = tmp_path_factory.mktemp("ypbas") / "empty.xlsx"
        pd.DataFrame({"a": [1]}).to_excel(path, sheet_name="Not a question", index=False)
        return path

    def test_parse_data_without_question_sheets(self, empty_workbook):
        with pytest.raises(SchoolTravelValidationError, match="No question worksheets"):
            school_travel.parse_data(empty_workbook)

    def test_parse_trend_data_without_trend_sheet(self, empty_workbook):
        with pytest.raises(SchoolTravelValidationError, match="Trend tables"):
            school_travel.parse_trend_data(empty_workbook)


class TestFindPublicationXlsxErrorPaths:
    """Link parsing lives in utils.web; this wrapper only adds YPBAS error translation."""

    PAGE = "https://www.infrastructure-ni.gov.uk/publications/ypbas-2024"

    def test_no_spreadsheet_on_page(self):
        with (
            patch("bolster.data_sources.dfi.school_travel.scrape_file_links", return_value=[]),
            pytest.raises(school_travel.SchoolTravelDataNotFoundError, match="No spreadsheet linked"),
        ):
            school_travel.find_publication_xlsx(self.PAGE)

    def test_fetch_failure_is_translated(self):
        with (
            patch(
                "bolster.data_sources.dfi.school_travel.scrape_file_links",
                side_effect=Exception("Network error"),
            ),
            pytest.raises(school_travel.SchoolTravelDataNotFoundError, match="Failed to fetch publication page"),
        ):
            school_travel.find_publication_xlsx(self.PAGE)


class TestListPublicationsErrorPaths:
    def test_index_fetch_failure_is_translated(self):
        with (
            patch("bolster.data_sources.dfi.school_travel.fetch_soup", side_effect=Exception("Network error")),
            pytest.raises(school_travel.SchoolTravelDataNotFoundError, match="Failed to fetch YPBAS index page"),
        ):
            school_travel.list_publications()


class TestCacheManagement:
    """Tests for the cache helper."""

    def test_clear_cache_returns_count(self):
        assert isinstance(school_travel.clear_cache(), int)


class TestValidation:
    """Unit tests for validation edge cases - no network."""

    def _valid_frame(self, rows: int = 120) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "question": ["How do you travel to school?"] * rows,
                "category": ["Car"] * rows,
                "breakdown": ["All respondents"] * rows,
                "value_pct": [50.0] * rows,
                "lower_ci": [48.0] * rows,
                "upper_ci": [52.0] * rows,
                "suppressed": [False] * rows,
            }
        )

    def test_validate_good_dataframe(self):
        assert school_travel.validate_data(self._valid_frame()) is True

    def test_validate_empty_dataframe(self):
        with pytest.raises(SchoolTravelValidationError, match="empty"):
            school_travel.validate_data(pd.DataFrame())

    def test_validate_none_dataframe(self):
        with pytest.raises(SchoolTravelValidationError, match="empty"):
            school_travel.validate_data(None)

    def test_validate_missing_columns(self):
        df = self._valid_frame().drop(columns=["lower_ci"])
        with pytest.raises(SchoolTravelValidationError, match="Missing required columns"):
            school_travel.validate_data(df)

    def test_validate_too_few_records(self):
        with pytest.raises(SchoolTravelValidationError, match="Too few records"):
            school_travel.validate_data(self._valid_frame(rows=10))

    def test_validate_percentage_out_of_range(self):
        df = self._valid_frame()
        df.loc[0, "value_pct"] = 140.0
        df.loc[0, "upper_ci"] = 150.0
        with pytest.raises(SchoolTravelValidationError, match="0-100"):
            school_travel.validate_data(df)

    def test_validate_bounds_do_not_bracket(self):
        df = self._valid_frame()
        df.loc[0, "lower_ci"] = 60.0
        with pytest.raises(SchoolTravelValidationError, match="bracket"):
            school_travel.validate_data(df)

    def test_validate_suppressed_row_with_value(self):
        df = self._valid_frame()
        df.loc[0, "suppressed"] = True
        with pytest.raises(SchoolTravelValidationError, match="Suppressed"):
            school_travel.validate_data(df)

    def test_validate_suppressed_row_without_value(self):
        df = self._valid_frame()
        df.loc[0, ["value_pct", "lower_ci", "upper_ci"]] = None
        df.loc[0, "suppressed"] = True
        assert school_travel.validate_data(df) is True
