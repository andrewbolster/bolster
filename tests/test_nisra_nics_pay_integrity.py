"""Data integrity tests for NI Civil Service pay statistics (NISRA datavis report).

The report is an interactive datavis page whose figures embed real .xlsx files; these tests
run against the live publication.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import nics_pay
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError
from bolster.utils.datavis import DatavisTable


class TestPublicationDiscovery:
    @pytest.fixture(scope="class")
    def url(self):
        return nics_pay.get_latest_publication_url()

    def test_url_is_a_datavis_report(self, url):
        assert url.startswith("https://datavis.nisra.gov.uk/")
        assert url.endswith(".html")

    @pytest.fixture(scope="class")
    def tables(self):
        return nics_pay.get_tables()

    def test_report_embeds_all_figures(self, tables):
        assert len(tables) >= 7
        assert all(t.title for t in tables.values()), "xlsx-embedded tables carry a title"


class TestPayByGrade:
    @pytest.fixture(scope="class")
    def df(self):
        return nics_pay.get_pay_by_grade()

    def test_columns_and_types(self, df):
        assert list(df.columns) == ["grade", "median_pay", "lower_quartile", "upper_quartile", "year"]
        assert all(pd.api.types.is_float_dtype(df[c]) for c in ["median_pay", "lower_quartile", "upper_quartile"])

    def test_includes_overall_and_senior_grades(self, df):
        grades = set(df["grade"])
        assert {"NICS Overall", "AA", "AO", "G7", "Perm Sec"} <= grades

    def test_quartiles_bracket_median(self, df):
        assert (df["lower_quartile"] <= df["median_pay"]).all()
        assert (df["median_pay"] <= df["upper_quartile"]).all()

    def test_pay_is_plausible(self, df):
        assert df["median_pay"].between(10_000, 500_000).all()
        overall = df.loc[df["grade"] == "NICS Overall", "median_pay"].iloc[0]
        assert 25_000 < overall < 60_000

    def test_reference_year_is_recent(self, df):
        assert df["year"].nunique() == 1
        assert df["year"].iloc[0] >= 2025

    def test_validates(self, df):
        assert nics_pay.validate_data(df) is True


class TestPayTrend:
    @pytest.fixture(scope="class")
    def trend(self):
        return nics_pay.get_pay_trend()

    def test_contiguous_years_from_2016(self, trend):
        assert trend["year"].iloc[0] == 2016
        assert trend["year"].diff().dropna().eq(1).all()

    def test_pay_grows_over_the_decade(self, trend):
        assert trend["median_pay"].iloc[-1] > trend["median_pay"].iloc[0]

    def test_latest_year_matches_pay_by_grade_overall(self, trend):
        by_grade = nics_pay.get_pay_by_grade()
        overall = by_grade.loc[by_grade["grade"] == "NICS Overall", "median_pay"].iloc[0]
        latest = trend.loc[trend["year"] == by_grade["year"].iloc[0], "median_pay"].iloc[0]
        assert latest == overall


class TestPayHistoryByGrade:
    @pytest.fixture(scope="class")
    def history(self):
        return nics_pay.get_pay_history_by_grade()

    def test_long_form_columns(self, history):
        assert list(history.columns) == ["grade", "year", "median_pay"]
        assert history["median_pay"].notna().all()

    def test_grades_have_a_decade_of_history(self, history):
        aa = history[history["grade"] == "AA"]
        assert aa["year"].min() == 2016
        assert len(aa) >= 10

    def test_grade_labels_match_pay_by_grade_exactly(self, history):
        assert set(history["grade"]) == set(nics_pay.get_pay_by_grade()["grade"])
        assert not history["grade"].str.contains(r"\s{2,}|\n").any()

    def test_agrees_with_pay_by_grade_for_latest_year(self, history):
        by_grade_df = nics_pay.get_pay_by_grade()
        by_grade = by_grade_df.set_index("grade")["median_pay"]
        latest = history[history["year"] == int(by_grade_df["year"].iloc[0])].set_index("grade")["median_pay"]
        assert set(latest.index) == set(by_grade.index)
        assert (latest[by_grade.index] == by_grade).all()


class TestPayGaps:
    @pytest.fixture(scope="class")
    def gender(self):
        return nics_pay.get_gender_pay_gap_by_grade()

    @pytest.fixture(scope="class")
    def community(self):
        return nics_pay.get_community_background_pay_gap_by_grade()

    def test_gender_columns(self, gender):
        assert {"grade", "male_median_pay", "female_median_pay", "gender_pay_gap", "year"} <= set(gender.columns)

    def test_gender_gap_is_percentage_of_male_pay(self, gender):
        both = gender.dropna(subset=["male_median_pay", "female_median_pay", "gender_pay_gap"])
        expected = (both["male_median_pay"] - both["female_median_pay"]) / both["male_median_pay"] * 100
        assert (expected - both["gender_pay_gap"]).abs().max() < 0.1

    def test_community_columns(self, community):
        assert {"protestant_median_pay", "catholic_median_pay", "community_background_pay_gap"} <= set(
            community.columns
        )

    def test_community_gap_is_percentage_of_protestant_pay(self, community):
        both = community.dropna(subset=["protestant_median_pay", "catholic_median_pay", "community_background_pay_gap"])
        expected = (both["protestant_median_pay"] - both["catholic_median_pay"]) / both["protestant_median_pay"] * 100
        assert (expected - both["community_background_pay_gap"]).abs().max() < 0.1


class TestUKComparison:
    def test_has_a_column_per_nation(self):
        df = nics_pay.get_uk_pay_comparison()
        assert {"northern_ireland_median_pay", "england_median_pay", "scotland_median_pay", "wales_median_pay"} <= set(
            df.columns
        )
        assert len(df) >= 5


def _table(title: str, rows: dict) -> DatavisTable:
    return DatavisTable("Figure 1", title, pd.DataFrame(rows))


class TestHelpers:
    """Unit tests for lookup and validation edge cases - no network calls needed."""

    def test_find_table_matches_title_case_insensitively(self):
        tables = {"Figure 9": _table("Figure 9: NICS Median Pay Trend, 2016-2026", {"year": ["2016"]})}
        assert nics_pay._find_table(tables, "trend").label == "Figure 1"

    def test_find_table_requires_every_keyword(self):
        tables = {"Figure 5": _table("Figure 5: Pay Gap by Grade and Sex", {"a": [1]})}
        with pytest.raises(NISRADataNotFoundError):
            nics_pay._find_table(tables, "community")

    def test_grade_labels_have_whitespace_collapsed(self):
        table = _table(
            "Figure 5: Pay Gap by Sex, March 2026", {"analogous_grade": ["NICS\nOverall", " Perm   Sec "], "v": [1, 2]}
        )
        assert nics_pay._grade_table(table)["grade"].tolist() == ["NICS Overall", "Perm Sec"]

    def test_reference_year_takes_last_year_in_title(self):
        assert nics_pay._reference_year("Figure 1: Pay, 2016-2026, at March 2026") == 2026

    def test_reference_year_missing_raises(self):
        with pytest.raises(NISRAValidationError):
            nics_pay._reference_year("Figure 1: no year here")

    def test_grade_table_coerces_numbers_and_percentages(self):
        table = _table(
            "Figure 5: Pay Gap by Sex, March 2026", {"analogous_grade": [" AA ", "AO"], "gap": ["3.4%", "-1%"]}
        )
        df = nics_pay._grade_table(table)
        assert df["grade"].tolist() == ["AA", "AO"]
        assert df["gap"].tolist() == [3.4, -1.0]
        assert df["year"].tolist() == [2026, 2026]

    @staticmethod
    def _valid(n=12):
        return pd.DataFrame(
            {
                "grade": [f"G{i}" for i in range(n - 1)] + ["NICS Overall"],
                "median_pay": [30000.0] * n,
                "lower_quartile": [25000.0] * n,
                "upper_quartile": [40000.0] * n,
                "year": [2026] * n,
            }
        )

    def test_validate_accepts_valid_frame(self):
        assert nics_pay.validate_data(self._valid()) is True

    def test_validate_missing_columns(self):
        with pytest.raises(NISRAValidationError, match="Missing expected columns"):
            nics_pay.validate_data(self._valid().drop(columns=["year"]))

    def test_validate_too_few_grades(self):
        with pytest.raises(NISRAValidationError, match="Too few"):
            nics_pay.validate_data(self._valid(5))

    def test_validate_requires_overall_row(self):
        df = self._valid()
        df["grade"] = [f"G{i}" for i in range(len(df))]
        with pytest.raises(NISRAValidationError, match="Overall"):
            nics_pay.validate_data(df)

    def test_validate_rejects_negative_or_missing_pay(self):
        df = self._valid()
        df.loc[0, "median_pay"] = -1.0
        with pytest.raises(NISRAValidationError, match="non-negative"):
            nics_pay.validate_data(df)
        df = self._valid()
        df.loc[0, "lower_quartile"] = float("nan")
        with pytest.raises(NISRAValidationError, match="non-negative"):
            nics_pay.validate_data(df)

    def test_validate_quartiles_must_bracket_median(self):
        df = self._valid()
        df.loc[1, "median_pay"] = 50000.0
        with pytest.raises(NISRAValidationError, match="bracket"):
            nics_pay.validate_data(df)
