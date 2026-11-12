"""Integrity tests for DfC young people's culture, arts, heritage and sport (YPBAS).

Tests use real data from the Department for Communities publications (no mocks).
Network calls are made once per class via ``scope="class"`` fixtures. Parsing and
validation edge cases are covered by network-free unit tests that build the raw
sheets of each table layout by hand.
"""

import logging

import pandas as pd
import pytest

from bolster.data_sources.dfc import young_people_culture_sport as yp

_KEY = ["breakdown", "group"]
_CULTURE_WORKBOOKS_2025 = {
    "experience-of-culture-arts-heritage",
    "experience-of-culture-arts",
    "experience-of-arts",
    "experience-of-museums-science-centres",
    "experience-of-public-library-service",
    "experience-of-heritage",
    "knowledge-of-irish",
    "knowledge-of-ulsterscots",
    "knowledge-of-sign-language",
    "engagement-of-culture-arts-heritage-sport",
}


def _raw(rows: list[list]) -> pd.DataFrame:
    """A sheet read with ``header=None``: rows padded with empty cells to one width."""
    width = max(len(row) for row in rows)
    return pd.DataFrame([list(row) + [None] * (width - len(row)) for row in rows])


_CONTEXT = {"survey_year": 2025, "release_year": 2025, "topic": "sport", "workbook": "w"}


@pytest.fixture(scope="session")
def sport_waves():
    """Wave list for the whole session, doubling as a reachability probe.

    Skips the live tests if the DfC site is unavailable, so a bad day costs one call, not many.
    """
    try:
        return yp.list_waves("sport")
    except yp.YoungPeopleDataNotFoundError as e:
        pytest.skip(f"communities-ni.gov.uk unavailable: {e}")


@pytest.fixture(autouse=True)
def _require_dfc_site(request):
    if request.node.get_closest_marker("integration"):
        request.getfixturevalue("sport_waves")


# ---------------------------------------------------------------------------
# Live data
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDiscovery:
    """Waves and workbooks are discovered from the hub and publication pages."""

    @pytest.fixture(scope="class")
    def culture_waves(self, sport_waves):
        return yp.list_waves("culture")

    def test_every_wave_is_listed_newest_first(self, sport_waves, culture_waves):
        for waves in (sport_waves, culture_waves):
            years = [w["year"] for w in waves]
            assert years == sorted(years, reverse=True)
            assert {2016, 2019, 2022, 2025} <= set(years)

    def test_urls_are_publication_pages(self, sport_waves, culture_waves):
        for wave in sport_waves + culture_waves:
            assert wave["url"].startswith("https://www.communities-ni.gov.uk/publications/experience-")
            assert str(wave["year"]) in wave["url"]

    def test_sport_has_one_workbook(self, sport_waves):
        books = yp.list_workbooks("sport")
        assert [b["key"] for b in books] == ["experience-of-sport"]
        assert books[0]["url"].endswith(".ods")

    def test_culture_2025_has_the_ten_workbooks(self, culture_waves):
        books = yp.list_workbooks("culture", 2025)
        assert {b["key"] for b in books} == _CULTURE_WORKBOOKS_2025
        assert all(b["year"] == 2025 for b in books)

    def test_file_urls_are_discovered_not_built_from_the_year(self, culture_waves):
        books = yp.list_workbooks("culture", 2025)
        assert all(b["url"].startswith("https://www.communities-ni.gov.uk/") for b in books)

    def test_unknown_year_lists_the_available_waves(self, sport_waves):
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="2025"):
            yp.list_workbooks("sport", 2021)

    def test_ambiguous_workbook_is_refused(self, culture_waves):
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="several"):
            yp.get_survey_tables("culture", workbook="heritage")


@pytest.mark.integration
class TestSport2025:
    """The latest sport wave: every estimate, and the comparison with 2022."""

    @pytest.fixture(scope="class")
    def estimates(self, sport_waves):
        return yp.get_survey_tables("sport")

    @pytest.fixture(scope="class")
    def comparisons(self, sport_waves):
        return yp.get_wave_comparisons("sport")

    def test_latest_wave_is_2025(self, estimates):
        assert set(estimates["survey_year"]) == {2025}
        assert set(estimates["release_year"]) == {2025}

    def test_every_table_is_read(self, estimates, comparisons):
        """The workbook has 21 tables: 19 of estimates and 2 (tables 2 and 4) that compare with 2022."""
        assert estimates["table_id"].nunique() == 19
        assert set(comparisons["table_id"]) == {"2", "4"}
        assert estimates.attrs["skipped_tables"] == []

    def test_validates(self, estimates, comparisons):
        assert yp.validate_survey_tables(estimates) is True
        assert yp.validate_wave_comparisons(comparisons) is True
        assert yp.validate_data(estimates) is True

    def test_participation_in_the_last_year(self, estimates):
        row = estimates[(estimates["table_id"] == "1") & (estimates["breakdown"] == "All")].iloc[0]
        assert row["percent"] == 98
        assert row["base"] == 2997
        assert row["ci_lower"] <= row["percent"] <= row["ci_upper"]

    def test_breakdowns_are_the_five_profile_dimensions(self, estimates):
        assert set(estimates["breakdown"]) == {
            "All",
            "Sex",
            "Year Group",
            "Religious background",
            "Disability",
            "Entitlement to free school meals",
        }

    def test_group_bases_of_a_breakdown_sum_to_the_whole(self, estimates):
        table = estimates[estimates["table_id"] == "1"].set_index(_KEY)["base"]
        total = table[("All", "All")]
        assert table.loc["Sex"].sum() == pytest.approx(total, abs=10)
        assert table.loc["Year Group"].sum() == pytest.approx(total, abs=10)

    def test_comparison_tables_are_participation_last_year_and_last_week(self, comparisons):
        assert set(comparisons["table_id"]) == {"2", "4"}
        assert (comparisons.groupby("table_id").size() == 15).all()
        assert set(comparisons["comparison_year"]) == {2022}

    def test_last_week_participation_fell_significantly(self, comparisons):
        row = comparisons[(comparisons["table_id"] == "4") & (comparisons["breakdown"] == "All")].iloc[0]
        assert (row["percent"], row["percent_comparison"]) == (92, 94)
        assert row["significance"] == "lower"
        assert row["marker"] == "È"
        assert bool(row["marker_consistent"])

    def test_all_markers_in_2025_agree_with_the_figures(self, comparisons):
        assert comparisons["marker_consistent"].all()
        assert set(comparisons["marker"].dropna()) <= {"¬", "È", "Ç"}

    @pytest.mark.parametrize(("single", "comparison"), [("1", "2"), ("3", "4")])
    def test_comparison_tables_repeat_the_single_wave_estimates(self, estimates, comparisons, single, comparison):
        """Within one release, a table's 2025 figures appear identically in its comparison table."""
        a = estimates[estimates["table_id"] == single].set_index(_KEY)[["percent", "base"]]
        b = comparisons[comparisons["table_id"] == comparison].set_index(_KEY)[["percent", "base"]]
        assert len(a) == len(b) == 15
        pd.testing.assert_frame_equal(a.sort_index(), b.sort_index())

    def test_item_table_totals_equal_the_profile_bases(self, estimates):
        """Table 5 (sports) has a 'Total' row of respondents per group; it matches table 1's bases."""
        t5 = estimates[estimates["table_id"] == "5"]
        bases5 = t5[t5["group"] != "All"].groupby(_KEY)["base"].first()
        bases1 = estimates[estimates["table_id"] == "1"].set_index(_KEY)["base"]
        assert len(bases5) == 14
        assert (bases5 == bases1.loc[bases5.index]).all()

    def test_football_is_a_boys_sport(self, estimates):
        t5 = estimates[
            (estimates["table_id"] == "5") & (estimates["item"] == "Football") & (estimates["breakdown"] == "Sex")
        ]
        by_group = t5.set_index("group")["percent"]
        assert by_group["Boys"] > by_group["Girls"]

    def test_distribution_table_rows_sum_to_about_100(self, estimates):
        """Enjoyment of sport (table 7) is a single-answer question: its three answers sum to 100 within rounding."""
        t7 = estimates[estimates["table_id"] == "7"]
        assert set(t7["item"]) == {"A lot", "A little", "Not at all"}
        sums = t7.groupby(_KEY)["percent"].sum()
        assert sums.between(98.5, 101.5).all()


@pytest.mark.integration
class TestCulture2025:
    """The latest culture wave, across its ten workbooks."""

    @pytest.fixture(scope="class")
    def estimates(self, sport_waves):
        return yp.get_survey_tables("culture")

    @pytest.fixture(scope="class")
    def comparisons(self, sport_waves):
        return yp.get_wave_comparisons("culture")

    def test_every_workbook_is_read_without_skips(self, estimates):
        assert set(estimates["workbook"]) == _CULTURE_WORKBOOKS_2025
        assert estimates.attrs["skipped_tables"] == []

    def test_validates(self, estimates, comparisons):
        assert yp.validate_survey_tables(estimates) is True
        assert yp.validate_wave_comparisons(comparisons) is True

    def test_markers_are_all_directional_and_consistent(self, comparisons):
        assert set(comparisons["significance"].dropna()) == {"lower", "higher", "no_significant_difference"}
        assert comparisons["marker_consistent"].all()

    def test_overall_engagement(self, estimates):
        row = estimates[
            (estimates["workbook"] == "experience-of-culture-arts-heritage") & (estimates["table_id"] == "2_1")
        ]
        all_row = row[row["breakdown"] == "All"].iloc[0]
        assert (all_row["percent"], all_row["base"]) == (96, 2968)
        by_sex = row[row["breakdown"] == "Sex"].set_index("group")["percent"]
        assert by_sex["Girls"] > by_sex["Boys"]

    def test_heritage_table_ids_keep_their_workbook_prefix(self, estimates):
        heritage = estimates[estimates["workbook"] == "experience-of-heritage"]
        assert {"7_1", "7_3", "7_4"} <= set(heritage["table_id"])

    def test_heritage_comparison_repeats_the_single_wave_estimates(self, estimates, comparisons):
        a = estimates[(estimates["workbook"] == "experience-of-heritage") & (estimates["table_id"] == "7_1")]
        b = comparisons[(comparisons["workbook"] == "experience-of-heritage") & (comparisons["table_id"] == "7_2")]
        assert a.iloc[0]["percent"] == 64
        pd.testing.assert_frame_equal(
            a.set_index(_KEY)[["percent", "base"]].sort_index(), b.set_index(_KEY)[["percent", "base"]].sort_index()
        )

    def test_trend_table_spans_five_waves(self, estimates):
        trend = estimates[estimates["table_id"] == "1_4"]
        assert set(trend["survey_year"]) == {2013, 2016, 2019, 2022, 2025}
        assert set(trend["release_year"]) == {2025}
        series = trend[trend["item"] == "Participated in sport and physical activity in the last 7 days"].set_index(
            "survey_year"
        )
        assert series["percent"].to_dict() == {2013: 96, 2016: 96, 2019: 95, 2022: 94, 2025: 92}

    def test_trend_table_agrees_with_the_sport_release(self, estimates, sport_waves):
        """The culture workbook's 2025 sport figure is the sport release's participation in the last week."""
        trend = estimates[(estimates["table_id"] == "1_4") & (estimates["survey_year"] == 2025)]
        culture_value = trend[trend["item"] == "Participated in sport and physical activity in the last 7 days"].iloc[
            0
        ]["percent"]
        sport = yp.get_survey_tables("sport")
        sport_value = sport[(sport["table_id"] == "3") & (sport["breakdown"] == "All")].iloc[0]["percent"]
        assert culture_value == sport_value == 92


@pytest.mark.integration
class TestEarlierWaves:
    """Earlier waves use different table layouts; what is supported parses, and the rest says so."""

    @pytest.fixture(scope="class")
    def sport_2022(self, sport_waves):
        return yp.get_survey_tables("sport", year=2022), yp.get_wave_comparisons("sport", year=2022)

    def test_2022_sport_parses_strictly(self, sport_2022):
        estimates, comparisons = sport_2022
        assert set(estimates["survey_year"]) == {2022}
        assert set(comparisons["comparison_year"]) == {2019}
        assert yp.validate_survey_tables(estimates) is True

    def test_breakdown_names_match_the_2025_wave(self, sport_2022, sport_waves):
        latest = yp.get_survey_tables("sport")
        assert set(sport_2022[0]["breakdown"]) == set(latest["breakdown"])

    def test_publisher_marker_error_is_flagged_not_hidden(self, sport_2022):
        """Table 13 (2022) marks the Protestant row, 69% against 65%, as significantly lower."""
        comparisons = sport_2022[1]
        inconsistent = comparisons[~comparisons["marker_consistent"].astype(bool)]
        assert len(inconsistent) == 1
        row = inconsistent.iloc[0]
        assert (row["table_id"], row["group"]) == ("13", "Protestant")
        assert (row["percent"], row["percent_comparison"], row["marker"]) == (69, 65, "È")
        with pytest.raises(yp.YoungPeopleValidationError, match="contradict"):
            yp.validate_wave_comparisons(comparisons)
        assert yp.validate_wave_comparisons(comparisons, allow_inconsistent_markers=True) is True

    def test_2022_wave_reproduces_in_the_2025_comparison_column(self, sport_2022, sport_waves):
        """The 2022 release's own table 1 equals the 2022 column of the 2025 release's table 2, group by group."""
        wave_2022 = sport_2022[0]
        a = wave_2022[wave_2022["table_id"] == "1"].set_index(_KEY)[["percent", "base"]]
        b = yp.get_wave_comparisons("sport")
        b = b[b["table_id"] == "2"].set_index(_KEY)[["percent_comparison", "base_comparison"]]
        b.columns = ["percent", "base"]
        shared = a.index.intersection(b.index)
        assert len(shared) >= 14
        pd.testing.assert_frame_equal(a.loc[shared].sort_index(), b.loc[shared].sort_index())

    def test_2025_comparison_adds_a_religion_group_the_2022_release_never_published(self, sport_2022, sport_waves):
        wave_2022 = sport_2022[0]
        assert "Other/None" not in set(wave_2022[wave_2022["breakdown"] == "Religious background"]["group"])
        comparisons = yp.get_wave_comparisons("sport")
        assert "Other/None" in set(comparisons[comparisons["breakdown"] == "Religious background"]["group"])

    def test_2016_numeric_markers_raise_rather_than_guess(self, sport_waves):
        with pytest.raises(yp.YoungPeopleLayoutError, match="not guessed"):
            yp.get_wave_comparisons("sport", year=2016)

    def test_2016_estimates_read_even_though_its_comparisons_cannot(self, sport_waves):
        """A comparison table the module cannot read does not stop the estimate tables being read."""
        estimates = yp.get_survey_tables("sport", year=2016)
        assert len(estimates) > 500
        assert estimates.attrs["skipped_tables"] == []
        comparisons = yp.get_wave_comparisons("sport", year=2016, strict=False)
        assert comparisons.attrs["skipped_tables"]
        assert all("not guessed" in item["reason"] for item in comparisons.attrs["skipped_tables"])

    def test_unrecognised_layout_raises_not_partial_data(self, sport_waves):
        """A culture count table is not a percentage table: strict mode refuses it, lenient mode lists it."""
        with pytest.raises(yp.YoungPeopleLayoutError, match="museums"):
            yp.get_survey_tables("culture", year=2022, workbook="experience-of-museums-and-science-centres")
        lenient = yp.get_survey_tables(
            "culture", year=2022, workbook="experience-of-museums-and-science-centres", strict=False
        )
        assert [item["sheet"] for item in lenient.attrs["skipped_tables"]] == ["Table_6"]
        assert (lenient["percent"].dropna() <= 100).all()


# ---------------------------------------------------------------------------
# Unit tests: label cleaning and discovery helpers (no network)
# ---------------------------------------------------------------------------


class TestLabels:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Gender", "Sex"),
            ("sex", "Sex"),
            ("Year group", "Year Group"),
            ("Year Group", "Year Group"),
            ("Religion", "Religious background"),
            ("Free school meals entitlement", "Entitlement to free school meals"),
            ("entitled to free to school meals", "Entitlement to free school meals"),
            ("  Language   spoken ", "Language spoken"),
        ],
    )
    def test_clean_breakdown(self, label, expected):
        assert yp.clean_breakdown(label) == expected

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Year 8", "8"),
            ("Year 12", "12"),
            ("8", "8"),
            ("Other/ None", "Other/None"),
            ("Other / None", "Other/None"),
            ("Entitled to free to school meals", "Entitled to free school meals"),
            ("Not entitled to free school meals", "Not entitled to free school meals"),
            ("Boys", "Boys"),
        ],
    )
    def test_clean_group(self, label, expected):
        assert yp.clean_group(label) == expected

    def test_parse_table_title(self):
        assert yp.parse_table_title("Table 7_1: Visited any historic building in the last year 2025") == (
            "7_1",
            "Visited any historic building in the last year 2025",
            "Visited any historic building in the last year",
        )

    def test_parse_table_title_with_letter_suffix_and_wave_range(self):
        table_id, _, indicator = yp.parse_table_title("Table 1b: Participation in arts activities 2019 - 2022")
        assert (table_id, indicator) == ("1b", "Participation in arts activities")

    def test_parse_table_title_rejects_other_text(self):
        with pytest.raises(yp.YoungPeopleLayoutError, match="Unrecognised table title"):
            yp.parse_table_title("Contents")

    @pytest.mark.parametrize(
        ("name", "key"),
        [
            ("experience-of-heritage-by-young-people-in-northern-ireland-2025.ods", "experience-of-heritage"),
            ("experience-sport-by-young-people-northern-ireland-2019.ods", "experience-sport"),
            ("knowledge-of-ulsterscots-by-young-people-in-northern-ireland-2025.ods", "knowledge-of-ulsterscots"),
            (
                "https://example.org/files/experience-of-arts-by-young-people-in-northern-ireland-2022.ods",
                "experience-of-arts",
            ),
        ],
    )
    def test_workbook_key(self, name, key):
        assert yp.workbook_key(name) == key


class TestSelectWorkbooks:
    BOOKS = [{"key": "experience-of-arts"}, {"key": "experience-of-heritage"}, {"key": "engagement-of-heritage-sport"}]

    def test_all_when_none(self):
        assert yp.select_workbooks(self.BOOKS, None) == self.BOOKS

    def test_exact_key_wins_over_substring(self):
        assert yp.select_workbooks(self.BOOKS, "experience-of-heritage") == [{"key": "experience-of-heritage"}]

    def test_unique_substring(self):
        assert yp.select_workbooks(self.BOOKS, "arts") == [{"key": "experience-of-arts"}]

    def test_ambiguous_substring_names_the_candidates(self):
        with pytest.raises(
            yp.YoungPeopleDataNotFoundError, match="experience-of-heritage, engagement-of-heritage-sport"
        ):
            yp.select_workbooks(self.BOOKS, "heritage")

    def test_no_match_lists_the_available_keys(self):
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="Available workbooks: experience-of-arts"):
            yp.select_workbooks(self.BOOKS, "library")

    def test_unknown_topic(self):
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="Unknown topic"):
            yp.list_waves("music")


# ---------------------------------------------------------------------------
# Unit tests: table parsing, one layout at a time (no network)
# ---------------------------------------------------------------------------

_SINGLE_2025 = [
    ["Table 1: Participation in sport within the last year 2025"],
    [],
    ["Profile of respondent", "%", "confidence intervals lower limit", "confidence intervals upper limit", "Base"],
    ["All", 98, 97.9, 98.8, 2997],
    ["Sex"],
    ["Boys", 99, 98.1, 99.3, 1313],
    ["Girls", 98, 97.3, 98.6, 1684],
    ["Year Group"],
    ["8", 98, 97.4, 99.4, 609],
    [],
    ["Note - something"],
]


class TestParseSingleWaveTable:
    def test_2025_layout(self):
        kind, frame = yp.parse_table(_raw(_SINGLE_2025), "Table_1", _CONTEXT)
        assert kind == "estimates"
        assert frame[["breakdown", "group", "percent", "ci_lower", "ci_upper", "base"]].values.tolist() == [
            ["All", "All", 98, 97.9, 98.8, 2997],
            ["Sex", "Boys", 99, 98.1, 99.3, 1313],
            ["Sex", "Girls", 98, 97.3, 98.6, 1684],
            ["Year Group", "8", 98, 97.4, 99.4, 609],
        ]
        assert set(frame["item"]) == {"Participation in sport within the last year"}
        assert set(frame["table_id"]) == {"1"}

    def test_notes_after_the_data_are_not_rows(self):
        _, frame = yp.parse_table(_raw(_SINGLE_2025), "Table_1", _CONTEXT)
        assert not frame["group"].str.startswith("Note").any()

    def test_2022_layout_with_a_three_row_header_and_gender(self):
        rows = [
            ["Table 1: Participation in sport within the last year"],
            [],
            ["Profile of respondent", 2022],
            [None, "%", "Confidence intervals", None, "Base"],
            [None, None, "lower limit", "upper limit", None],
            ["All", 98, 98, 98.8, 3724],
            ["Gender"],
            ["Boys", 99, 98, 99.4, 1843],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_1", {**_CONTEXT, "survey_year": 2022, "release_year": 2022})
        assert frame[["breakdown", "group", "percent", "ci_lower", "ci_upper", "base"]].values.tolist() == [
            ["All", "All", 98, 98, 98.8, 3724],
            ["Sex", "Boys", 99, 98, 99.4, 1843],
        ]

    def test_2019_layout_with_the_base_in_the_upper_header_row(self):
        rows = [
            ["Table 1: Participation in sport within the last year"],
            [],
            ["Profile of respondent", 2019],
            [None, "%", "Confidence intervals", None, "Base"],
            [None, None, "lower limit", "upper limit", None],
            ["All", 99, 98.4, 99.1, 3891],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_1", _CONTEXT)
        assert frame.iloc[0][["percent", "ci_lower", "ci_upper", "base"]].tolist() == [99, 98.4, 99.1, 3891]

    def test_distribution_table_has_one_row_per_answer_and_no_interval(self):
        rows = [
            ["Table 7: Enjoyment of sport or physical activity"],
            [],
            ["Profile of respondent", "A lot", "A little", "Not at all", "Base"],
            ["All", 80, 18, 2, 3000],
            ["Sex"],
            ["Boys", 85, 13, 2, 1300],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_7", _CONTEXT)
        assert len(frame) == 6
        assert set(frame["item"]) == {"A lot", "A little", "Not at all"}
        assert frame["ci_lower"].isna().all()
        assert (frame["base"] == [3000, 3000, 3000, 1300, 1300, 1300]).all()

    def test_percent_with_unit_in_the_header_is_the_item_name(self):
        rows = [
            ["Table 9: Minutes a day"],
            [],
            ["Profile of respondent", "15 mins  %", "30 mins  %", "Base"],
            ["All", 5, 15, 100],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_9", _CONTEXT)
        assert list(frame["item"]) == ["15 mins", "30 mins"]

    def test_suppressed_cell_is_missing_not_zero(self):
        rows = _SINGLE_2025[:5] + [["Boys", "[c]", None, None, 20]]
        _, frame = yp.parse_table(_raw(rows), "Table_1", _CONTEXT)
        assert frame.iloc[1]["percent"] != frame.iloc[1]["percent"]  # NaN
        assert frame.iloc[1]["base"] == 20

    def test_missing_all_row_is_a_layout_error(self):
        rows = [row for row in _SINGLE_2025 if row[:1] != ["All"]]
        with pytest.raises(yp.YoungPeopleLayoutError, match="No 'All' row"):
            yp.parse_table(_raw(rows), "Table_1", _CONTEXT)

    def test_title_error_names_the_workbook_and_sheet(self):
        rows = [["Contents"]] + _SINGLE_2025[1:]
        with pytest.raises(yp.YoungPeopleLayoutError, match="w 2025 sheet Table_1"):
            yp.parse_table(_raw(rows), "Table_1", _CONTEXT)

    def test_no_percentage_column_is_a_layout_error(self):
        rows = [
            ["Table 3: Odd"],
            [],
            ["Profile of respondent", "confidence intervals lower limit", "Base"],
            ["All", 1, 2],
        ]
        with pytest.raises(yp.YoungPeopleLayoutError, match="No percentage column"):
            yp.parse_table(_raw(rows), "Table_3", _CONTEXT)


_COMPARISON_2025 = [
    ["Table 2: Participation in sport within the last year 2022-2025"],
    [],
    ["Profile of respondent", "2025         %", "2025 Base", "2022         %", "2022 Base", "Significant difference"],
    ["All", 92, 2992, 94, 3720, "È"],
    ["Sex"],
    ["Boys", 94, 1309, 96, 1840, "È"],
    ["Girls", 90, 1683, 90, 1880, "¬"],
    ["Year Group"],
    ["8", 96, 600, 90, 700, "Ç"],
]


class TestParseComparisonTable:
    def test_2025_layout(self):
        kind, frame = yp.parse_table(_raw(_COMPARISON_2025), "Table_2", _CONTEXT)
        assert kind == "comparison"
        assert frame[
            ["group", "percent", "base", "percent_comparison", "base_comparison", "change_points"]
        ].values.tolist() == [
            ["All", 92, 2992, 94, 3720, -2],
            ["Boys", 94, 1309, 96, 1840, -2],
            ["Girls", 90, 1683, 90, 1880, 0],
            ["8", 96, 600, 90, 700, 6],
        ]
        assert list(frame["significance"]) == ["lower", "lower", "no_significant_difference", "higher"]
        assert set(frame["comparison_year"]) == {2022}
        assert frame["marker_consistent"].all()

    def test_2022_layout_with_the_years_in_a_header_row_of_their_own(self):
        rows = [
            ["Table 2: Participation in sport within the previous year"],
            [],
            [
                "Profile of respondent",
                "Sport participation",
                None,
                None,
                None,
                "Significant difference from previous year?",
            ],
            [None, 2022, None, 2019, None, None],
            [None, "%", "Base", "%", "Base", None],
            ["All", 98, 3724, 99, 3891, "È"],
            ["Gender"],
            ["Boys", 99, 1843, 99, 2125, "-"],
        ]
        kind, frame = yp.parse_table(_raw(rows), "Table_2", {**_CONTEXT, "survey_year": 2022})
        assert kind == "comparison"
        assert frame[["breakdown", "group", "comparison_year", "significance"]].values.tolist() == [
            ["All", "All", 2019, "lower"],
            ["Sex", "Boys", 2019, "no_significant_difference"],
        ]

    def test_this_wave_is_the_later_year_whatever_the_column_order(self):
        rows = [
            ["Table 2: Something 2022-2025"],
            [],
            ["Profile of respondent", "2022 %", "2022 Base", "2025 %", "2025 Base", "Significant difference"],
            ["All", 94, 3720, 92, 2992, "È"],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_2", _CONTEXT)
        assert frame.iloc[0][["percent", "percent_comparison", "comparison_year"]].tolist() == [92, 94, 2022]

    def test_group_without_a_marker_has_no_significance(self):
        rows = _COMPARISON_2025[:4] + [["Sex"], ["Boys", 94, 1309, 96, 1840, None]]
        _, frame = yp.parse_table(_raw(rows), "Table_2", _CONTEXT)
        assert pd.isna(frame.iloc[1]["significance"])
        assert frame.iloc[1]["marker_consistent"]

    def test_marker_contradicting_the_figures_is_kept_and_flagged(self, caplog):
        rows = _COMPARISON_2025[:4] + [["Sex"], ["Boys", 96, 1309, 92, 1840, "È"]]
        with caplog.at_level(logging.WARNING):
            _, frame = yp.parse_table(_raw(rows), "Table_2", _CONTEXT)
        row = frame.iloc[1]
        assert (row["marker"], row["significance"], row["change_points"]) == ("È", "lower", 4)
        assert not row["marker_consistent"]
        assert "marker_consistent is False" in caplog.text

    def test_undocumented_marker_is_not_guessed(self):
        rows = _COMPARISON_2025[:4] + [["Sex"], ["Boys", 96, 1309, 92, 1840, "-1"]]
        with pytest.raises(yp.YoungPeopleLayoutError, match="not guessed"):
            yp.parse_table(_raw(rows), "Table_2", _CONTEXT)

    def test_same_year_twice_is_a_layout_error(self):
        rows = [
            ["Table 2: Something"],
            [],
            ["Profile of respondent", "2025 %", "2025 Base", "2025 %", "2025 Base", "Significant difference"],
            ["All", 1, 2, 3, 4, "¬"],
        ]
        with pytest.raises(yp.YoungPeopleLayoutError, match="Cannot tell the two waves"):
            yp.parse_table(_raw(rows), "Table_2", _CONTEXT)

    def test_missing_base_column_is_a_layout_error(self):
        rows = [
            ["Table 2: Something"],
            [],
            ["Profile of respondent", "2025 %", "2022 %", "Significant difference"],
            ["All", 1, 2, "¬"],
        ]
        with pytest.raises(yp.YoungPeopleLayoutError, match="two percentage, two base and one marker"):
            yp.parse_table(_raw(rows), "Table_2", _CONTEXT)


class TestParseItemTables:
    def test_2025_blocks_by_breakdown(self):
        rows = [
            ["Table 5: Sports participation within the last year"],
            [],
            ["a) by sex"],
            ["Sport", "All %", "Boys %", "Girls %"],
            ["Football", 55, 74, 35],
            ["Dancing", 15, 2, 29],
            ["Total", 2997, 1313, 1684],
            [],
            ["b) by year group"],
            ["Sport", "All %", "Year 8 %", "Year 9 %"],
            ["Football", 55, 50, 56],
            ["Total", 2997, 609, 611],
            [],
            ["Percentages may not add to 100% as multiple responses were allowed."],
        ]
        kind, frame = yp.parse_table(_raw(rows), "Table_5", _CONTEXT)
        assert kind == "estimates"
        assert len(frame) == 9
        football = frame[(frame["item"] == "Football") & (frame["breakdown"] == "Year Group")]
        assert football[["group", "percent", "base"]].values.tolist() == [
            ["All", 55, 2997],
            ["8", 50, 609],
            ["9", 56, 611],
        ]
        assert "Total" not in set(frame["item"])
        assert frame["ci_lower"].isna().all()

    def test_old_layout_with_unit_row_base_row_and_an_index_of_blocks(self):
        rows = [
            ["Table 8: Benefits of sport or physical activity"],
            [],
            ["a) by gender"],
            [],
            ["Benefit", "All", "Boys", "Girls"],
            [None, "%", "%", "%"],
            ["Have fun", 80, 80, 80],
            ["Base", 3836, 792, 831],
            [],
            ["Note"],
            ["Percentages may not add to 100% as multiple responses were allowed."],
            [],
            ["Data is available by:"],
            ["a) by gender"],
            ["b) by year group"],
            [],
            ["b) by year group"],
            [],
            ["Benefit", "All", "Year 8", "Year 9"],
            [None, "%", "%", "%"],
            ["Have fun", 80, 81, 79],
            ["Base", 3836, 792, 800],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_8", _CONTEXT)
        assert frame[["breakdown", "group", "percent", "base"]].values.tolist() == [
            ["Sex", "All", 80, 3836],
            ["Sex", "Boys", 80, 792],
            ["Sex", "Girls", 80, 831],
            ["Year Group", "All", 80, 3836],
            ["Year Group", "8", 81, 792],
            ["Year Group", "9", 79, 800],
        ]

    def test_footer_lines_directly_below_the_data_are_not_items(self):
        rows = [
            ["Table 4: Arts"],
            [],
            ["a) by sex"],
            ["Activity", "All %", "Boys %"],
            ["Singing", 40, 30],
            ["Note"],
            ["Data is available by:"],
            ["a) by sex"],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_4", _CONTEXT)
        assert list(frame["item"]) == ["Singing", "Singing"]

    def test_single_block_named_in_the_title(self):
        rows = [
            ["Table 5: Sports participation within the last year by gender"],
            [],
            ["Sport", "All", "Boys", "Girls"],
            [None, "%", "%", "%"],
            ["Football", 58, 78, 37],
        ]
        _, frame = yp.parse_table(_raw(rows), "Table_5", _CONTEXT)
        assert set(frame["breakdown"]) == {"Sex"}
        assert frame[frame["group"] == "Girls"].iloc[0]["percent"] == 37

    def test_table_of_counts_is_not_read_as_percentages(self):
        """A table whose columns are counts with bases, under a title that names no known breakdown, is refused."""
        rows = [
            ["Table 6: Class visited by a museum within the last year"],
            [],
            [None, "All pupils", None, "Visitors", None],
            [None, "%", "Base", "%", "Base"],
            ["All", 5, 3636, 6, 1442],
        ]
        with pytest.raises(yp.YoungPeopleLayoutError, match="Not a table this module recognises"):
            yp.parse_table(_raw(rows), "Table_6", _CONTEXT)

    def test_unknown_breakdown_in_the_title_is_refused(self):
        rows = [
            ["Table 6: Something by country of birth"],
            [],
            ["Item", "All", "UK"],
            ["Football", 5, 6],
        ]
        with pytest.raises(yp.YoungPeopleLayoutError, match="Not a table this module recognises"):
            yp.parse_table(_raw(rows), "Table_6", _CONTEXT)


class TestParseTrendTable:
    ROWS = [
        ["Table 1_4: Engagement in culture, arts, heritage and sport by young people in Northern Ireland 2013 - 2025"],
        [],
        ["Culture, arts, heritage and sport", "2013%", "2016   %", "2019%"],
        ["Participated in sport", 99, 99, 99],
        ["Knowledge of Irish", None, None, 30],
        [],
        ["Note"],
    ]

    def test_each_wave_column_becomes_a_survey_year(self):
        kind, frame = yp.parse_table(_raw(self.ROWS), "Table_1_4", {**_CONTEXT, "workbook": "engagement"})
        assert kind == "estimates"
        assert frame[["survey_year", "item", "percent"]].values.tolist() == [
            [2013, "Participated in sport", 99],
            [2016, "Participated in sport", 99],
            [2019, "Participated in sport", 99],
            [2019, "Knowledge of Irish", 30],
        ]
        assert set(frame["release_year"]) == {2025}
        assert set(frame["group"]) == {"All"}

    def test_trend_table_with_no_values_is_a_layout_error(self):
        rows = self.ROWS[:3] + [["Participated in sport", None, None, None]]
        with pytest.raises(yp.YoungPeopleLayoutError, match="No values found in the trend table"):
            yp.parse_table(_raw(rows), "Table_1_4", _CONTEXT)


# ---------------------------------------------------------------------------
# Unit tests: loading and validation (no network)
# ---------------------------------------------------------------------------


def _write_workbook(path, sheets: dict[str, list[list]]) -> None:
    with pd.ExcelWriter(path, engine="odf") as writer:
        for name, rows in sheets.items():
            _raw(rows).to_excel(writer, sheet_name=name, header=False, index=False)


@pytest.fixture
def offline_workbook(tmp_path, monkeypatch):
    """Point discovery and download at one small ODS file written to disk."""
    path = tmp_path / "experience-of-sport-by-young-people-in-northern-ireland-2025.ods"

    def install(sheets):
        _write_workbook(path, sheets)
        book = {
            "year": 2025,
            "topic": "sport",
            "key": "experience-of-sport",
            "name": path.name,
            "url": "https://x/" + path.name,
        }
        monkeypatch.setattr(yp, "list_workbooks", lambda topic, year, force_refresh: [book])
        monkeypatch.setattr(yp, "download_file", lambda url, force_refresh=False: path)

    return install


class TestLoadOffline:
    def test_reads_the_table_sheets_and_ignores_the_rest(self, offline_workbook):
        offline_workbook(
            {"Contents": [["Contents"]], "Table_1": _SINGLE_2025, "Table_2": _COMPARISON_2025, "Metadata": [["x"]]}
        )
        estimates = yp.get_survey_tables("sport")
        comparisons = yp.get_wave_comparisons("sport")
        assert set(estimates["table_id"]) == {"1"}
        assert set(comparisons["table_id"]) == {"2"}
        assert yp.validate_survey_tables(estimates) is True
        assert yp.validate_wave_comparisons(comparisons) is True
        assert yp.get_latest_data("sport").equals(estimates)

    def test_workbook_with_no_table_sheets_is_a_layout_error(self, offline_workbook):
        offline_workbook({"Contents": [["Contents"]], "Metadata": [["x"]]})
        with pytest.raises(yp.YoungPeopleLayoutError, match="no table sheets"):
            yp.get_survey_tables("sport")

    def test_strict_mode_raises_on_an_unrecognised_sheet(self, offline_workbook):
        offline_workbook({"Table_1": _SINGLE_2025, "Table_9": [["Table 9: Odd"], [], ["Nothing recognisable here"]]})
        with pytest.raises(yp.YoungPeopleLayoutError, match="Table_9"):
            yp.get_survey_tables("sport")

    def test_lenient_mode_lists_what_it_skipped(self, offline_workbook):
        offline_workbook({"Table_1": _SINGLE_2025, "Table_9": [["Table 9: Odd"], [], ["Nothing recognisable here"]]})
        estimates = yp.get_survey_tables("sport", strict=False)
        assert set(estimates["table_id"]) == {"1"}
        skipped = estimates.attrs["skipped_tables"]
        assert [(s["workbook"], s["sheet"]) for s in skipped] == [("experience-of-sport", "Table_9")]
        assert "Table_9" in skipped[0]["reason"]

    def test_empty_result_still_has_the_documented_columns(self, offline_workbook):
        offline_workbook({"Table_2": _COMPARISON_2025})
        estimates = yp.get_survey_tables("sport")
        assert estimates.empty
        assert list(estimates.columns) == [
            "survey_year",
            "release_year",
            "topic",
            "workbook",
            "table_id",
            "table_title",
            "indicator",
            "item",
            "breakdown",
            "group",
            "percent",
            "ci_lower",
            "ci_upper",
            "base",
        ]
        with pytest.raises(yp.YoungPeopleValidationError, match="No survey estimates"):
            yp.validate_survey_tables(estimates)


def _estimates(**changes) -> pd.DataFrame:
    row = {
        "survey_year": 2025,
        "release_year": 2025,
        "topic": "sport",
        "workbook": "w",
        "table_id": "1",
        "table_title": "t",
        "indicator": "i",
        "item": "i",
        "breakdown": "All",
        "group": "All",
        "percent": 98.0,
        "ci_lower": 97.0,
        "ci_upper": 99.0,
        "base": 2997.0,
    }
    return pd.DataFrame([{**row, **changes}])


class TestValidateSurveyTables:
    def test_valid(self):
        assert yp.validate_survey_tables(_estimates()) is True

    def test_missing_columns(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="Missing columns"):
            yp.validate_survey_tables(_estimates().drop(columns=["base"]))

    def test_empty(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="No survey estimates"):
            yp.validate_survey_tables(_estimates().iloc[0:0])

    @pytest.mark.parametrize("percent", [-1.0, 100.5])
    def test_percent_out_of_range(self, percent):
        with pytest.raises(yp.YoungPeopleValidationError, match="outside 0 to 100"):
            yp.validate_survey_tables(_estimates(percent=percent, ci_lower=float("nan"), ci_upper=float("nan")))

    def test_interval_must_bracket_the_estimate(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="do not bracket"):
            yp.validate_survey_tables(_estimates(percent=90.0))

    def test_rounding_of_a_point_is_allowed_in_the_interval(self):
        assert yp.validate_survey_tables(_estimates(percent=100.0, ci_lower=99.6, ci_upper=99.9)) is True

    def test_base_must_be_positive(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="Non-positive base"):
            yp.validate_survey_tables(_estimates(base=0.0))

    def test_duplicate_rows(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="duplicated"):
            yp.validate_survey_tables(pd.concat([_estimates(), _estimates()], ignore_index=True))

    def test_missing_interval_and_base_are_allowed(self):
        assert (
            yp.validate_survey_tables(_estimates(ci_lower=float("nan"), ci_upper=float("nan"), base=float("nan")))
            is True
        )


def _comparison(**changes) -> pd.DataFrame:
    row = {
        "survey_year": 2025,
        "comparison_year": 2022,
        "topic": "sport",
        "workbook": "w",
        "table_id": "2",
        "table_title": "t",
        "indicator": "i",
        "breakdown": "All",
        "group": "All",
        "percent": 92.0,
        "base": 2992.0,
        "percent_comparison": 94.0,
        "base_comparison": 3720.0,
        "change_points": -2.0,
        "significance": "lower",
        "marker": "È",
        "marker_consistent": True,
    }
    return pd.DataFrame([{**row, **changes}])


class TestValidateWaveComparisons:
    def test_valid(self):
        assert yp.validate_wave_comparisons(_comparison()) is True

    def test_missing_columns(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="Missing columns"):
            yp.validate_wave_comparisons(_comparison().drop(columns=["marker"]))

    def test_empty(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="No wave comparisons"):
            yp.validate_wave_comparisons(_comparison().iloc[0:0])

    def test_percent_out_of_range(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="percent_comparison outside"):
            yp.validate_wave_comparisons(_comparison(percent_comparison=120.0, change_points=-28.0))

    def test_change_must_be_the_difference(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="change_points is not"):
            yp.validate_wave_comparisons(_comparison(change_points=-3.0))

    def test_contradicted_marker_fails_unless_allowed(self):
        frame = _comparison(percent=96.0, change_points=2.0, marker_consistent=False)
        with pytest.raises(yp.YoungPeopleValidationError, match="1 significance markers contradict"):
            yp.validate_wave_comparisons(frame)
        assert yp.validate_wave_comparisons(frame, allow_inconsistent_markers=True) is True

    def test_flag_must_match_the_markers(self):
        with pytest.raises(yp.YoungPeopleValidationError, match="marker_consistent does not match"):
            yp.validate_wave_comparisons(_comparison(percent=96.0, change_points=2.0, marker_consistent=True))

    def test_higher_marker_with_a_fall_is_contradicted(self):
        frame = _comparison(significance="higher", marker="Ç", marker_consistent=False)
        with pytest.raises(yp.YoungPeopleValidationError, match="contradict"):
            yp.validate_wave_comparisons(frame)


class TestDiscoveryErrors:
    """Failures of the hub and publication pages are named, not swallowed (no network)."""

    @staticmethod
    def _wave(topic, force_refresh=False):
        return [{"year": 2025, "topic": topic, "url": "https://x/p"}]

    def test_unreachable_hub(self, monkeypatch):
        def fail(url, force_refresh=False):
            raise OSError("connection refused")

        monkeypatch.setattr(yp, "fetch_soup", fail)
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="Could not fetch .*connection refused"):
            yp.list_waves("sport")

    def test_hub_with_no_young_people_publications(self, monkeypatch):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup('<a href="/publications/other">x</a>', "html.parser")
        monkeypatch.setattr(yp, "fetch_soup", lambda url, force_refresh=False: soup)
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="No young people's publications"):
            yp.list_waves("culture")

    def test_hub_links_are_read_newest_first_and_deduplicated(self, monkeypatch):
        from bs4 import BeautifulSoup

        html = (
            '<a href="/publications/experience-sport-young-people-northern-ireland-2019">a</a>'
            '<a href="/publications/experience-sport-young-people-northern-ireland-2025">b</a>'
            '<a href="/publications/experience-sport-young-people-northern-ireland-2025">again</a>'
        )
        soup = BeautifulSoup(html, "html.parser")
        monkeypatch.setattr(yp, "fetch_soup", lambda url, force_refresh=False: soup)
        waves = yp.list_waves("sport")
        assert [w["year"] for w in waves] == [2025, 2019]
        assert waves[0]["url"].endswith("/publications/experience-sport-young-people-northern-ireland-2025")

    def test_unreachable_publication_page(self, monkeypatch):
        def fail(url, file_extension, force_refresh=False):
            raise OSError("timed out")

        monkeypatch.setattr(yp, "list_waves", self._wave)
        monkeypatch.setattr(yp, "scrape_file_links", fail)
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="Could not fetch https://x/p: timed out"):
            yp.list_workbooks("sport")

    def test_publication_page_with_no_workbooks(self, monkeypatch):
        monkeypatch.setattr(yp, "list_waves", self._wave)
        monkeypatch.setattr(yp, "scrape_file_links", lambda url, file_extension, force_refresh=False: [])
        with pytest.raises(yp.YoungPeopleDataNotFoundError, match="No .ods workbooks linked on https://x/p"):
            yp.list_workbooks("sport")

    def test_workbooks_are_keyed_from_their_file_names(self, monkeypatch):
        link = {
            "url": "https://x/files/experience-of-arts-by-young-people-in-northern-ireland-2022.ods",
            "text": "Arts",
        }
        monkeypatch.setattr(
            yp, "list_waves", lambda topic, force_refresh=False: [{"year": 2022, "topic": topic, "url": "https://x/p"}]
        )
        monkeypatch.setattr(yp, "scrape_file_links", lambda url, file_extension, force_refresh=False: [link])
        books = yp.list_workbooks("culture", 2022)
        assert [(b["year"], b["key"], b["name"]) for b in books] == [
            (2022, "experience-of-arts", "experience-of-arts-by-young-people-in-northern-ireland-2022.ods")
        ]


class TestLayoutErrors:
    """Each way a table can fail to be recognised raises a named error (no network)."""

    def test_empty_column_between_value_columns_is_ignored(self):
        rows = [["Table 1: Something"], [], ["Profile of respondent", "%", None, "Base"], ["All", 50, None, 100]]
        _, frame = yp.parse_table(_raw(rows), "Table_1", _CONTEXT)
        assert frame.iloc[0][["percent", "base"]].tolist() == [50, 100]

    def test_values_without_a_row_label(self):
        rows = _SINGLE_2025[:4] + [[None, 5, 1, 2, 3]]
        with pytest.raises(yp.YoungPeopleLayoutError, match="values but no label"):
            yp.parse_table(_raw(rows), "Table_1", _CONTEXT)

    def test_note_directly_below_the_data_ends_the_table(self):
        rows = _SINGLE_2025[:4] + [["Note - something"], ["Boys", 99, 98.1, 99.3, 1313]]
        _, frame = yp.parse_table(_raw(rows), "Table_1", _CONTEXT)
        assert list(frame["group"]) == ["All"]

    def test_all_row_with_no_values_leaves_no_data(self):
        rows = _SINGLE_2025[:3] + [["All"]]
        with pytest.raises(yp.YoungPeopleLayoutError, match="No data rows"):
            yp.parse_table(_raw(rows), "Table_1", _CONTEXT)

    def test_two_base_columns_in_a_single_wave_table(self):
        rows = [["Table 1: Something"], [], ["Profile of respondent", "%", "Base", "Base"], ["All", 50, 100, 100]]
        with pytest.raises(yp.YoungPeopleLayoutError, match="More than one base column"):
            yp.parse_table(_raw(rows), "Table_1", _CONTEXT)

    def test_confidence_limit_beside_several_percentage_columns(self):
        rows = [
            ["Table 1: Something"],
            [],
            ["Profile of respondent", "A %", "B %", "confidence intervals lower limit", "Base"],
            ["All", 50, 50, 40, 100],
        ]
        with pytest.raises(yp.YoungPeopleLayoutError, match="Confidence limits beside several percentage columns"):
            yp.parse_table(_raw(rows), "Table_1", _CONTEXT)

    def test_comparison_base_columns_for_other_years(self):
        rows = [
            ["Table 2: Something"],
            [],
            ["Profile of respondent", "2025 %", "2025 Base", "2022 %", "2019 Base", "Significant difference"],
            ["All", 1, 2, 3, 4, "¬"],
        ]
        with pytest.raises(yp.YoungPeopleLayoutError, match="base columns do not match"):
            yp.parse_table(_raw(rows), "Table_2", _CONTEXT)

    def test_trend_table_ends_at_a_note(self):
        rows = TestParseTrendTable.ROWS[:4] + [["Note - something", 1, 2, 3]]
        _, frame = yp.parse_table(_raw(rows), "Table_1_4", _CONTEXT)
        assert set(frame["item"]) == {"Participated in sport"}

    def test_item_block_with_no_items(self):
        rows = [["Table 5: Sports"], [], ["a) by sex"], ["Sport", "All %", "Boys %"], []]
        with pytest.raises(yp.YoungPeopleLayoutError, match="No values found in the item table"):
            yp.parse_table(_raw(rows), "Table_5", _CONTEXT)

    def test_sheet_with_only_a_title(self):
        with pytest.raises(yp.YoungPeopleLayoutError, match="Not a table this module recognises"):
            yp.parse_table(_raw([["Table 9: Odd"], [], []]), "Table_9", _CONTEXT)
