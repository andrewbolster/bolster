"""Data integrity tests for the NISRA Respect Index module.

Live tests read the Executive Office workbook and cross-check it against the PxStat
cubes ``RESPECTNI`` and ``RESPECTEQ``; the parser and validation tests at the end
build small workbooks in a temporary directory and need no network.
"""

import logging

import pandas as pd
import pytest

from bolster.data_sources.nisra import respect_index as ri
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError
from bolster.data_sources.nisra.pxstat import read_dataset
from bolster.utils.web import is_url_host

EXPECTED_GROUPS = {
    "All",
    "Male",
    "Female",
    "18-24 years",
    "25-34 years",
    "35-49 years",
    "50-64 years",
    "65+ years",
    "Catholic",
    "Protestant",
    "Other religion/ None/ Missing",
    "With disability",
    "Without disability",
}

# PxStat labels mapped to the workbook's group labels.
RESPECTNI_GROUPS = {
    "Northern Ireland": "All",
    "Sex - Male": "Male",
    "Sex - Female": "Female",
    "Age 18-24 years": "18-24 years",
    "Age 25-34 years": "25-34 years",
    "Age 35-49 years": "35-49 years",
    "Age 50-64 years": "50-64 years",
    "Age 65+ years": "65+ years",
    "Religion - Catholic": "Catholic",
    "Religion - Protestant": "Protestant",
    "Religion - Other/No religion/Missing": "Other religion/ None/ Missing",
    "Disability - Yes": "With disability",
    "Disability - No": "Without disability",
}
RESPECTEQ_GROUPS = {
    "Northern Ireland": "All",
    "Sex - Male": "Male",
    "Sex - Female": "Female",
    "Age - 18-24": "18-24 years",
    "Age - 25-34": "25-34 years",
    "Age - 35-49": "35-49 years",
    "Age - 50-64": "50-64 years",
    "Age - 65+": "65+ years",
    "Religion - Catholic": "Catholic",
    "Religion - Protestant": "Protestant",
    "Religion - Other/no religion": "Other religion/ None/ Missing",
    "Disability - Disabled": "With disability",
    "Disability - Not Disabled": "Without disability",
}


class TestPublicationDiscovery:
    def test_workbook_url_is_on_the_executive_office_site(self):
        url = ri.get_latest_publication_url()
        assert is_url_host(url, "www.executiveoffice-ni.gov.uk")
        assert url.endswith("data-tables.xlsx")


class TestRespectIndexIntegrity:
    @pytest.fixture(scope="class")
    def latest(self):
        return ri.get_latest_respect_index()

    def test_columns(self, latest):
        assert list(latest.columns) == ri.INDEX_COLUMNS

    def test_validates(self, latest):
        assert ri.validate_data(latest) is True

    def test_series_starts_in_2016_and_is_contiguous(self, latest):
        years = sorted(latest["year"].unique())
        assert years[0] == 2016
        assert years[-1] >= 2025
        assert years == list(range(years[0], years[-1] + 1))

    def test_every_year_has_every_group_once(self, latest):
        for year, rows in latest.groupby("year"):
            assert sorted(rows["group"]) == sorted(EXPECTED_GROUPS), year

    def test_no_unrecognised_group_types(self, latest):
        assert set(latest["group_type"]) == {"all", "sex", "age", "religion", "disability"}

    def test_all_adult_sample_sizes_are_plausible(self, latest):
        sizes = latest.loc[latest["group_type"] == "all", "sample_size"]
        assert sizes.between(800, 2500).all()

    def test_sex_samples_reconcile_to_the_all_adult_sample(self, latest):
        pivot = latest[latest["group_type"].isin(["all", "sex"])].pivot(
            index="year", columns="group", values="sample_size"
        )
        gap = (pivot["All"] - pivot["Male"] - pivot["Female"]).abs() / pivot["All"]
        # A few respondents give neither answer: well under one percent in every year.
        assert (gap < 0.01).all()

    def test_sex_percentages_reconcile_to_the_all_adult_percentage(self, latest):
        sample = latest[latest["group_type"].isin(["all", "sex"])].pivot(
            index="year", columns="group", values="sample_size"
        )
        pct = latest[latest["group_type"].isin(["all", "sex"])].pivot(
            index="year", columns="group", values="pct_respected"
        )
        implied = (pct["Male"] * sample["Male"] + pct["Female"] * sample["Female"]) / (
            sample["Male"] + sample["Female"]
        )
        assert ((pct["All"] - implied).abs() < 0.5).all()


class TestPxStatCrossValidation:
    """The workbook and PxStat publish the same survey results for 2016-2023."""

    @pytest.fixture(scope="class")
    def latest(self):
        return ri.get_latest_respect_index()

    @pytest.fixture(scope="class")
    def respectni(self):
        df = read_dataset("RESPECTNI")
        df["group"] = df["Equality Groups"].map(RESPECTNI_GROUPS)
        return df

    @pytest.fixture(scope="class")
    def respecteq(self):
        df = read_dataset("RESPECTEQ")
        df["group"] = df["Equality group"].map(RESPECTEQ_GROUPS)
        return df

    def test_respectni_groups_are_all_mapped(self, respectni):
        assert respectni["group"].notna().all()

    def test_respectni_matches_the_workbook_to_rounding(self, latest, respectni):
        merged = respectni.merge(latest, left_on=["Year", "group"], right_on=["year", "group"], how="left")
        assert len(merged) == 13 * 8
        assert merged["pct_respected"].notna().all()
        # RESPECTNI is published to whole percentages.
        assert (merged["VALUE"].astype(float) - merged["pct_respected"]).abs().max() <= 0.5

    def test_respecteq_matches_the_workbook_to_one_decimal_place(self, latest, respecteq):
        estimates = respecteq[respecteq["Statistic Label"].str.startswith("Proportion")]
        merged = estimates.merge(latest, left_on=["Year", "group"], right_on=["year", "group"], how="inner")
        assert len(merged) == 13 * 8
        assert (merged["VALUE"].astype(float) - merged["pct_respected"]).abs().max() <= 0.05 + 1e-9

    def test_all_adult_value_lies_inside_the_published_confidence_interval(self, latest, respecteq):
        national = respecteq[respecteq["group"] == "All"]
        lower = national[national["Statistic Label"].str.contains("lower")].set_index("Year")["VALUE"].astype(float)
        upper = national[national["Statistic Label"].str.contains("upper")].set_index("Year")["VALUE"].astype(float)
        workbook = latest[latest["group_type"] == "all"].set_index("year")["pct_respected"]
        for year in lower.index:
            assert lower[year] <= workbook[year] <= upper[year], year


class TestQuestionResponses:
    @pytest.fixture(scope="class")
    def questions(self):
        return ri.get_question_responses()

    @pytest.fixture(scope="class")
    def latest(self):
        return ri.get_latest_respect_index()

    def test_columns(self, questions):
        assert list(questions.columns) == ri.QUESTION_COLUMNS

    def test_validates(self, questions):
        assert ri.validate_question_responses(questions) is True

    def test_two_consecutive_years_of_nine_questions(self, questions):
        years = sorted(questions["year"].unique())
        assert len(years) == 2
        assert years[1] == years[0] + 1
        assert (questions.groupby("year")["question"].nunique() == 9).all()

    def test_question_years_are_survey_years_of_the_index(self, questions, latest):
        assert set(questions["year"]) <= set(latest["year"])

    def test_index_cannot_exceed_the_most_often_never_answered_question(self, questions, latest):
        """Feeling respected means answering Never to all nine, so it is rarer than any one Never."""
        national = latest[latest["group_type"] == "all"].set_index("year")["pct_respected"]
        for year, rows in questions.groupby("year"):
            assert national[year] <= rows["pct_never"].min(), year


class TestTables:
    def test_list_tables(self):
        assert ri.list_tables()["table"].tolist() == ["index", "questions"]

    def test_unknown_table_raises(self):
        with pytest.raises(ValueError, match="Unknown table"):
            ri.get_latest_data("nope")

    def test_get_latest_data_dispatches(self):
        assert list(ri.get_latest_data("questions").columns) == ri.QUESTION_COLUMNS


# --- Offline parser and validation tests -----------------------------------------------------


INDEX_HEADER = ["Group", "% who felt respected", "% who did not feel respected", "Sample size"]
QUESTIONS_HEADER = ["Question", "Never (%)", "Occasionally (%)", "Monthly or more often (%)", "Sample size"]


def _index_grid(tables, *, title_prefix="Worksheet 1: Respect Index for 2016-2017"):
    """Build the index worksheet: tables side by side, one blank column apart.

    ``tables`` maps a year to ``[(group, pct_respected, sample_size), ...]``.
    """
    n_rows = 5 + max(len(rows) for rows in tables.values())
    grid = [[None] * (5 * len(tables) - 1) for _ in range(n_rows)]
    grid[0][0] = title_prefix
    for i, (year, rows) in enumerate(tables.items()):
        col = 5 * i
        grid[3][col] = f"Table {i + 1}: Respect Index {year}"
        for k, head in enumerate(INDEX_HEADER):
            grid[4][col + k] = head
        for r, (group, pct, size) in enumerate(rows):
            grid[5 + r][col] = group
            grid[5 + r][col + 1] = pct
            grid[5 + r][col + 2] = 100 - pct
            grid[5 + r][col + 3] = size
    return pd.DataFrame(grid)


def _questions_grid(tables):
    """Build the questions worksheet: tables stacked vertically with spacer rows."""
    grid = [["Worksheet 2: Responses to the individual questions on the Everyday Discrimination Scale"] + [None] * 4]
    for i, (year, rows) in enumerate(tables.items()):
        grid.append([None] * 5)
        grid.append([f"Source: Northern Ireland Life and Times Survey {year}"] + [None] * 4)
        grid.append(
            [f"Table {i + 1}: Responses to the individual questions on the Everyday Discrimination Scale in {year}"]
            + [None] * 4
        )
        grid.append(list(QUESTIONS_HEADER))
        for question, never, occasionally, monthly, size in rows:
            grid.append([question, never, occasionally, monthly, size])
    return pd.DataFrame(grid)


def _write_workbook(path, sheets):
    with pd.ExcelWriter(path) as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    return path


SAMPLE_GROUPS = [("All", 25.0, 1000), ("Male", 24.0, 480), ("Female", 26.0, 520), ("18-24 years", 10.0, 90)]


class TestParsers:
    @pytest.fixture
    def workbook(self, tmp_path):
        return _write_workbook(
            tmp_path / "data-tables.xlsx",
            {
                "Cover_sheet": pd.DataFrame([["The Executive Office"]]),
                "1": _index_grid({2016: SAMPLE_GROUPS, 2017: SAMPLE_GROUPS}),
                "2": _questions_grid(
                    {
                        2024: [("How often are you treated with less courtesy?", 26.0, 52.0, 22.0, 1193)],
                        2025: [("How often are you treated with less courtesy?", 49.0, 40.0, 11.0, 1236)],
                    }
                ),
            },
        )

    def test_index_tables_are_found_by_title_across_side_by_side_blocks(self, workbook):
        df = ri.parse_respect_index(workbook)
        assert list(df.columns) == ri.INDEX_COLUMNS
        assert sorted(df["year"].unique()) == [2016, 2017]
        assert len(df) == 8
        row = df[(df["year"] == 2017) & (df["group"] == "Female")].iloc[0]
        assert row["pct_respected"] == 26.0
        assert row["pct_not_respected"] == 74.0
        assert row["sample_size"] == 520
        assert row["group_type"] == "sex"
        assert ri.validate_data(df) is True

    def test_worksheets_are_found_by_title_not_name_or_position(self, tmp_path):
        path = _write_workbook(
            tmp_path / "swapped.xlsx",
            {
                "Notes": pd.DataFrame([["Nothing to see"]]),
                "Questions": _questions_grid({2025: [("Q?", 49.0, 40.0, 11.0, 1236)]}),
                "Index": _index_grid({2025: SAMPLE_GROUPS}),
            },
        )
        assert sorted(ri.parse_respect_index(path)["year"].unique()) == [2025]
        assert ri.parse_question_responses(path)["year"].tolist() == [2025]

    def test_unrecognised_group_is_labelled_other_and_logged(self, tmp_path, caplog):
        path = _write_workbook(
            tmp_path / "other.xlsx",
            {"1": _index_grid({2025: [("All", 20.0, 1000), ("Gay, lesbian or bisexual", 15.0, 90)]})},
        )
        with caplog.at_level(logging.WARNING, logger="bolster.data_sources.nisra.respect_index"):
            df = ri.parse_respect_index(path)
        assert df.loc[df["group"] == "Gay, lesbian or bisexual", "group_type"].iloc[0] == "other"
        assert "Unrecognised group" in caplog.text

    def test_missing_index_worksheet_raises(self, tmp_path):
        path = _write_workbook(tmp_path / "none.xlsx", {"Cover_sheet": pd.DataFrame([["The Executive Office"]])})
        with pytest.raises(NISRADataNotFoundError, match="No worksheet titled"):
            ri.parse_respect_index(path)

    def test_worksheet_without_tables_raises(self, tmp_path):
        path = _write_workbook(
            tmp_path / "empty.xlsx",
            {"1": pd.DataFrame([["Worksheet 1: Respect Index for 2016-2025"], ["No tables here"]])},
        )
        with pytest.raises(NISRADataNotFoundError, match="No 'Respect Index <year>' tables"):
            ri.parse_respect_index(path)

    def test_changed_header_raises(self, tmp_path):
        grid = _index_grid({2025: SAMPLE_GROUPS})
        grid.iloc[4, 1] = "% who felt valued"
        path = _write_workbook(tmp_path / "header.xlsx", {"1": grid})
        with pytest.raises(NISRADataNotFoundError, match="header"):
            ri.parse_respect_index(path)

    def test_duplicate_year_raises(self, tmp_path):
        grid = _index_grid({2025: SAMPLE_GROUPS, 2026: SAMPLE_GROUPS})
        grid.iloc[3, 5] = "Table 2: Respect Index 2025"
        path = _write_workbook(tmp_path / "dupe.xlsx", {"1": grid})
        with pytest.raises(NISRAValidationError, match="more than once"):
            ri.parse_respect_index(path)

    @pytest.mark.parametrize("bad", ["suppressed", None])
    def test_non_numeric_or_missing_value_raises(self, tmp_path, bad):
        grid = _index_grid({2025: SAMPLE_GROUPS})
        grid.iloc[6, 1] = bad
        path = _write_workbook(tmp_path / "text.xlsx", {"1": grid})
        with pytest.raises(NISRAValidationError, match="Non-numeric or missing"):
            ri.parse_respect_index(path)

    def test_question_tables_are_stacked_and_found_by_title(self, workbook):
        df = ri.parse_question_responses(workbook)
        assert list(df.columns) == ri.QUESTION_COLUMNS
        assert df["year"].tolist() == [2024, 2025]
        assert df["pct_never"].tolist() == [26.0, 49.0]
        assert ri.validate_question_responses(df) is True

    def test_missing_questions_worksheet_raises(self, tmp_path):
        path = _write_workbook(tmp_path / "index-only.xlsx", {"1": _index_grid({2025: SAMPLE_GROUPS})})
        with pytest.raises(NISRADataNotFoundError, match="Responses to the individual questions"):
            ri.parse_question_responses(path)


def _valid_index():
    return pd.DataFrame(
        {
            "year": [2016, 2016, 2017, 2017],
            "group": ["All", "Male", "All", "Male"],
            "group_type": ["all", "sex", "all", "sex"],
            "pct_respected": [28.0, 25.0, 36.0, 30.0],
            "pct_not_respected": [72.0, 75.0, 64.0, 70.0],
            "sample_size": [1200, 520, 1197, 518],
        }
    )


class TestValidateData:
    def test_valid_frame_passes(self):
        assert ri.validate_data(_valid_index()) is True

    def test_empty_frame_fails(self):
        assert ri.validate_data(pd.DataFrame()) is False

    def test_missing_column_fails(self):
        assert ri.validate_data(_valid_index().drop(columns=["sample_size"])) is False

    def test_percentage_out_of_range_fails(self):
        df = _valid_index()
        df.loc[0, "pct_respected"] = 101.0
        assert ri.validate_data(df) is False

    def test_percentages_not_adding_to_100_fails(self):
        df = _valid_index()
        df.loc[0, "pct_not_respected"] = 60.0
        assert ri.validate_data(df) is False

    def test_non_positive_sample_fails(self):
        df = _valid_index()
        df.loc[1, "sample_size"] = 0
        assert ri.validate_data(df) is False

    def test_gap_in_years_fails(self):
        df = _valid_index()
        df["year"] = [2016, 2016, 2018, 2018]
        assert ri.validate_data(df) is False

    def test_year_without_an_all_adult_row_fails(self):
        df = _valid_index()
        df.loc[2, "group_type"] = "sex"
        assert ri.validate_data(df) is False


def _valid_questions():
    return pd.DataFrame(
        {
            "year": [2024, 2025],
            "question": ["Q1", "Q1"],
            "pct_never": [26.0, 49.0],
            "pct_occasionally": [52.0, 40.0],
            "pct_monthly_or_more": [22.0, 11.0],
            "sample_size": [1193, 1236],
        }
    )


class TestValidateQuestionResponses:
    def test_valid_frame_passes(self):
        assert ri.validate_question_responses(_valid_questions()) is True

    def test_empty_frame_fails(self):
        assert ri.validate_question_responses(pd.DataFrame()) is False

    def test_missing_column_fails(self):
        assert ri.validate_question_responses(_valid_questions().drop(columns=["pct_never"])) is False

    def test_percentage_out_of_range_fails(self):
        df = _valid_questions()
        df.loc[0, "pct_never"] = -1.0
        assert ri.validate_question_responses(df) is False

    def test_answers_not_adding_to_100_fails(self):
        df = _valid_questions()
        df.loc[0, "pct_occasionally"] = 10.0
        assert ri.validate_question_responses(df) is False

    def test_non_positive_sample_fails(self):
        df = _valid_questions()
        df.loc[0, "sample_size"] = 0
        assert ri.validate_question_responses(df) is False
