"""Data integrity tests for teacher vacancies, sickness absence and substitution costs (DE datavis report).

Runs against the live publication; the report embeds each figure and table as a real .xlsx file.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import teacher_vacancies_absence as tva
from bolster.data_sources.nisra._base import NISRADataNotFoundError, NISRAValidationError
from bolster.utils.embedded_downloads import EmbeddedTable


class TestReport:
    @pytest.fixture(scope="class")
    def tables(self):
        return tva.get_tables()

    def test_url_is_a_de_datavis_report(self):
        url = tva.get_latest_publication_url()
        assert url.startswith("https://datavis.nisra.gov.uk/DEstatistics/")
        assert "vacancy" in url

    def test_report_has_figures_and_tables(self, tables):
        assert sum(label.startswith("Figure") for label in tables) >= 7
        assert sum(label.startswith("Table") for label in tables) >= 13
        assert all(t.title for t in tables.values())

    def test_no_table_is_empty(self, tables):
        """Regression: sheets with blank spacer rows once parsed to zero rows."""
        empty = [label for label, t in tables.items() if t.data.empty]
        assert not empty, f"empty tables: {empty}"

    def test_no_footnote_markers_in_column_names(self, tables):
        offenders = [(label, c) for label, t in tables.items() for c in t.data.columns if "[" in c or "]" in c]
        assert not offenders


class TestVacancies:
    @pytest.fixture(scope="class")
    def by_school_type(self):
        return tva.get_vacancies_by_school_type()

    @pytest.fixture(scope="class")
    def by_grade(self):
        return tva.get_vacancies_by_grade()

    @pytest.fixture(scope="class")
    def history(self):
        return tva.get_vacancies_history_by_grade()

    def test_by_school_type_shape_and_validity(self, by_school_type):
        assert list(by_school_type.columns) == ["school_type", "filled", "unfilled", "total", "year"]
        assert tva.validate_data(by_school_type) is True
        assert by_school_type["year"].iloc[0] >= 2024

    def test_by_school_type_sums_to_all(self, by_school_type):
        parts = by_school_type[by_school_type["school_type"] != "All"]
        assert len(parts) >= 3
        assert parts["total"].sum() == by_school_type.loc[by_school_type["school_type"] == "All", "total"].iloc[0]

    def test_by_grade_has_no_missing_school_types(self, by_grade):
        assert by_grade["school_type"].notna().all()
        assert by_grade["school_type"].nunique() >= 4
        assert {"Principal", "Classroom teacher", "All teachers"} <= set(by_grade["grade_of_teacher"])

    def test_by_grade_percentages_are_consistent(self, by_grade):
        for prefix in ("permanent", "temporary", "all"):
            filled, unfilled = by_grade[f"{prefix}_positions_filled"], by_grade[f"{prefix}_positions_unfilled"]
            expected = (filled / (filled + unfilled) * 100).dropna()
            actual = by_grade.loc[expected.index, f"pct_{prefix}_positions_filled"]
            assert (expected - actual).abs().max() < 0.2

    def test_figure_1_all_row_ties_to_table_1(self, by_school_type, by_grade):
        row = by_grade[
            (by_grade["school_type"] == "All grant-aided schools") & (by_grade["grade_of_teacher"] == "All teachers")
        ].iloc[0]
        all_row = by_school_type[by_school_type["school_type"] == "All"].iloc[0]
        assert row["all_positions_filled"] == all_row["filled"]
        assert row["all_positions_unfilled"] == all_row["unfilled"]

    def test_history_is_contiguous_for_every_group(self, history):
        for _, group in history.groupby(["school_type", "grade_of_teacher"]):
            assert group["year"].diff().dropna().eq(1).all()
        assert history["year"].nunique() >= 4

    def test_history_latest_year_ties_to_by_grade(self, history, by_grade):
        year = int(by_grade["year"].iloc[0])
        latest = history[history["year"] == year].set_index(["school_type", "grade_of_teacher"])
        current = by_grade.set_index(["school_type", "grade_of_teacher"])
        assert set(latest.index) == set(current.index)
        assert (latest["filled"] == current.loc[latest.index, "all_positions_filled"]).all()
        assert (latest["unfilled"] == current.loc[latest.index, "all_positions_unfilled"]).all()


class TestSicknessAbsence:
    @pytest.fixture(scope="class")
    def trend(self):
        return tva.get_sickness_absence_trend()

    @pytest.fixture(scope="class")
    def by_duration(self):
        return tva.get_sickness_absence_by_duration()

    def test_by_school_type(self):
        df = tva.get_sickness_absence_by_school_type()
        assert list(df.columns) == ["school_type", "avg_days_lost", "academic_year"]
        assert df["avg_days_lost"].between(2, 30).all()
        assert df["academic_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_trend_is_contiguous_academic_years(self, trend):
        starts = trend["academic_year"].str[:4].astype(int)
        assert starts.diff().dropna().eq(1).all()
        assert trend["avg_days_lost"].between(2, 30).all()

    def test_duration_shares_sum_to_100(self, by_duration):
        assert (by_duration.iloc[:, 1:].sum(axis=1) - 100).abs().max() < 0.5

    def test_duration_covers_the_same_years_as_trend(self, by_duration, trend):
        assert by_duration["academic_year"].tolist() == trend["academic_year"].tolist()


class TestSubstitution:
    @pytest.fixture(scope="class")
    def costs(self):
        return tva.get_substitution_costs()

    def test_costs_are_positive_and_contiguous(self, costs):
        assert (costs["total_cost"] > 1_000_000).all()
        assert costs["academic_year"].str[:4].astype(int).diff().dropna().eq(1).all()
        assert len(costs) >= 8

    def test_proportions_are_percentages(self):
        days = tva.get_substitution_days_proportion()
        retired = tva.get_retired_teacher_cover_proportion()
        assert days["pct_of_teaching_days"].between(0, 100).all()
        assert retired["pct_of_cover"].between(0, 100).all()
        assert days["academic_year"].tolist() == retired["academic_year"].tolist()


def _table(label: str, title: str) -> EmbeddedTable:
    return EmbeddedTable(label, title, pd.DataFrame({"a": [1]}))


class TestHelpers:
    """Unit tests for lookup, parsing and validation edge cases - no network calls needed."""

    def test_find_table_respects_kind_and_range(self):
        tables = {
            "Figure 2": _table("Figure 2", "Figure 2: Days lost per teacher, 2024/25"),
            "Figure 3": _table("Figure 3", "Figure 3: Days lost per teacher, 2020/21 - 2024/25"),
            "Table 1": _table("Table 1", "Table 1: Days lost per teacher, 2024"),
        }
        assert tva._find_table(tables, "days lost", kind="Figure", ranged=False).label == "Figure 2"
        assert tva._find_table(tables, "days lost", kind="Figure", ranged=True).label == "Figure 3"
        assert tva._find_table(tables, "days lost", kind="Table").label == "Table 1"

    def test_find_table_missing_raises(self):
        with pytest.raises(NISRADataNotFoundError):
            tva._find_table({"Figure 1": _table("Figure 1", "Figure 1: Something")}, "vacancies", kind="Figure")

    def test_year_parsing(self):
        assert tva._academic_year("Figure 2: Days lost, 2024/25") == "2024/25"
        assert tva._collection_year("Figure 1: Vacancies by school type, November 2024") == 2024
        with pytest.raises(NISRAValidationError):
            tva._academic_year("no year")
        with pytest.raises(NISRAValidationError):
            tva._collection_year("no year")

    @staticmethod
    def _valid():
        return pd.DataFrame(
            {
                "school_type": ["All", "A", "B"],
                "filled": [30.0, 10.0, 20.0],
                "unfilled": [15.0, 5.0, 10.0],
                "total": [45.0, 15.0, 30.0],
                "year": [2025, 2025, 2025],
            }
        )

    def test_validate_accepts_valid_frame(self):
        assert tva.validate_data(self._valid()) is True

    @pytest.mark.parametrize(
        ("mutate", "message"),
        [
            (lambda df: df.drop(columns=["year"]), "Missing expected columns"),
            (lambda df: df.assign(school_type=["X", "A", "B"]), "No 'All' row"),
            (lambda df: df.assign(filled=[30.0, -1.0, 20.0]), "non-negative"),
            (lambda df: df.assign(unfilled=[15.0, None, 10.0]), "non-negative"),
            (lambda df: df.assign(total=[45.0, 16.0, 30.0]), "does not equal total"),
            (lambda df: df.assign(filled=[31.0, 10.0, 20.0], total=[46.0, 15.0, 30.0]), "do not sum"),
        ],
    )
    def test_validate_rejects_bad_frames(self, mutate, message):
        with pytest.raises(NISRAValidationError, match=message):
            tva.validate_data(mutate(self._valid()))
