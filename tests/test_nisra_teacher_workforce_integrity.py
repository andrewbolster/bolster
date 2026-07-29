"""Integrity tests for the teacher workforce module.

Tests use the real NISRA PxStat API (no mocks).  Network calls are made once
per class via ``scope="class"`` fixtures.  Validation and summary edge cases
are covered by network-free unit tests built from small in-memory frames.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import teacher_workforce as tw
from bolster.data_sources.nisra.teacher_workforce import TeacherWorkforceValidationError


@pytest.mark.network
class TestHeadcountIntegrity:
    """The headcount table should be complete and internally consistent."""

    @pytest.fixture(scope="class")
    def counts(self):
        return tw.get_teacher_counts()

    def test_required_columns(self, counts):
        expected = {"academic_year", "geography_code", "geography", *tw.HEADCOUNT_MEASURES.values()}
        assert expected <= set(counts.columns)

    def test_not_empty(self, counts):
        assert len(counts) > 0

    def test_academic_year_format(self, counts):
        assert counts["academic_year"].str.fullmatch(r"\d{4}/\d{2}").all()

    def test_covers_multiple_years(self, counts):
        assert counts["academic_year"].nunique() >= 5

    def test_all_districts_present_every_year(self, counts):
        per_year = counts.groupby("academic_year")["geography"].nunique()
        assert per_year.nunique() == 1, f"district count varies by year: {per_year.to_dict()}"
        assert per_year.iloc[0] == 12, "expected 11 districts plus the NI total"

    def test_ni_total_present(self, counts):
        assert tw.NI_TOTAL in set(counts["geography"])

    def test_no_missing_counts(self, counts):
        for column in tw.HEADCOUNT_MEASURES.values():
            assert counts[column].notna().all(), column

    def test_counts_are_non_negative(self, counts):
        for column in tw.HEADCOUNT_MEASURES.values():
            assert (counts[column] >= 0).all(), column

    def test_counts_are_integers(self, counts):
        for column in tw.HEADCOUNT_MEASURES.values():
            assert counts[column].dtype == "Int64", column

    def test_ni_headcount_is_plausible(self, counts):
        ni = counts[counts["geography"] == tw.NI_TOTAL]
        assert ni["all_teachers"].between(15000, 30000).all()

    def test_districts_are_smaller_than_ni(self, counts):
        for year, group in counts.groupby("academic_year"):
            ni = group[group["geography"] == tw.NI_TOTAL]["all_teachers"].iloc[0]
            districts = group[group["geography"] != tw.NI_TOTAL]["all_teachers"]
            assert (districts < ni).all(), year

    def test_sorted_by_year_then_geography(self, counts):
        assert counts.equals(counts.sort_values(["academic_year", "geography"]).reset_index(drop=True))

    def test_validation_passes(self, counts):
        assert tw.validate_teacher_workforce_data(counts) is True


@pytest.mark.network
class TestFTEIntegrity:
    """Full-time equivalent numbers should cover every school type."""

    @pytest.fixture(scope="class")
    def fte(self):
        return tw.get_fte_teachers()

    def test_required_columns(self, fte):
        assert set(fte.columns) == {
            "academic_year",
            "geography_code",
            "geography",
            "school_type",
            "fte_teachers",
        }

    def test_all_school_types_present(self, fte):
        assert set(fte["school_type"]) == set(tw.SCHOOL_TYPES)

    def test_values_are_non_negative(self, fte):
        assert (fte["fte_teachers"] >= 0).all()

    def test_no_missing_values(self, fte):
        assert fte["fte_teachers"].notna().all()

    def test_fte_can_be_fractional(self, fte):
        """Part-time staff mean FTE is genuinely a weighted measure."""
        assert (fte["fte_teachers"] % 1 != 0).any()

    def test_filter_by_school_type(self):
        primary = tw.get_fte_teachers("Primary")
        assert set(primary["school_type"]) == {"Primary"}
        assert len(primary) > 0

    def test_rejects_unknown_school_type(self):
        with pytest.raises(ValueError, match="school_type must be one of"):
            tw.get_fte_teachers("Polytechnic")


@pytest.mark.network
class TestPupilTeacherRatioIntegrity:
    """Ratios should sit in a plausible range for every reported combination."""

    @pytest.fixture(scope="class")
    def ratios(self):
        return tw.get_pupil_teacher_ratios()

    def test_required_columns(self, ratios):
        assert set(ratios.columns) == {
            "academic_year",
            "geography_code",
            "geography",
            "school_type",
            "pupil_teacher_ratio",
        }

    def test_all_school_types_present(self, ratios):
        assert set(ratios["school_type"]) == set(tw.SCHOOL_TYPES)

    def test_ratios_are_plausible(self, ratios):
        """Zero means no schools of that type; anything real sits well under 50."""
        reported = ratios[ratios["pupil_teacher_ratio"] > 0]["pupil_teacher_ratio"]
        assert reported.between(3, 50).all()

    def test_special_schools_are_the_best_staffed(self, ratios):
        """Special schools carry far smaller classes than mainstream ones."""
        reported = ratios[ratios["pupil_teacher_ratio"] > 0]
        special = reported[reported["school_type"] == "Special"]["pupil_teacher_ratio"]
        mainstream = reported[reported["school_type"].isin(["Primary", "Grammar"])]["pupil_teacher_ratio"]
        assert special.max() < mainstream.min()

    def test_all_schools_ratio_always_reported(self, ratios):
        overall = ratios[ratios["school_type"] == "All schools"]
        assert (overall["pupil_teacher_ratio"] > 0).all()

    def test_filter_by_school_type(self):
        grammar = tw.get_pupil_teacher_ratios("Grammar")
        assert set(grammar["school_type"]) == {"Grammar"}

    def test_rejects_unknown_school_type(self):
        with pytest.raises(ValueError, match="school_type must be one of"):
            tw.get_pupil_teacher_ratios("Kindergarten")


@pytest.mark.network
class TestWorkforceSummary:
    """The summary should describe the NI series, not the districts."""

    @pytest.fixture(scope="class")
    def summary(self):
        return tw.get_workforce_summary(tw.get_teacher_counts())

    def test_columns(self, summary):
        assert set(summary.columns) == {
            "academic_year",
            "all_teachers",
            "yoy_change",
            "yoy_pct_change",
            "female_pct",
            "part_time_pct",
        }

    def test_one_row_per_year(self, summary):
        assert summary["academic_year"].is_unique

    def test_first_year_has_no_change(self, summary):
        assert pd.isna(summary["yoy_change"].iloc[0])
        assert pd.isna(summary["yoy_pct_change"].iloc[0])

    def test_teaching_is_majority_female(self, summary):
        assert (summary["female_pct"] > 50).all()

    def test_part_time_share_is_a_minority(self, summary):
        assert summary["part_time_pct"].between(0, 50).all()

    def test_headcount_is_stable_year_on_year(self, summary):
        """A workforce this size should never move by more than a few percent."""
        assert summary["yoy_pct_change"].dropna().abs().max() < 10


class TestValidation:
    """Validation rules, exercised offline against hand-built frames."""

    def _frame(self, **overrides):
        row = {
            "academic_year": "2022/23",
            "geography": tw.NI_TOTAL,
            "all_teachers": 100,
            "female_teachers": 75,
            "male_teachers": 25,
            "full_time_teachers": 80,
            "part_time_teachers": 20,
            "teachers_under_30": 10,
            "teachers_30_to_59": 85,
            "teachers_60_and_over": 5,
        }
        row.update(overrides)
        return pd.DataFrame([row])

    def test_accepts_a_consistent_frame(self):
        assert tw.validate_teacher_workforce_data(self._frame()) is True

    def test_rejects_missing_columns(self):
        with pytest.raises(TeacherWorkforceValidationError, match="Missing required columns"):
            tw.validate_teacher_workforce_data(pd.DataFrame({"academic_year": ["2022/23"]}))

    def test_rejects_empty_frame(self):
        empty = pd.DataFrame(columns=["academic_year", "geography", "all_teachers"])
        with pytest.raises(TeacherWorkforceValidationError, match="DataFrame is empty"):
            tw.validate_teacher_workforce_data(empty)

    def test_rejects_negative_counts(self):
        with pytest.raises(TeacherWorkforceValidationError, match="Negative teacher counts"):
            tw.validate_teacher_workforce_data(self._frame(male_teachers=-25, female_teachers=125))

    def test_rejects_inconsistent_gender_split(self):
        with pytest.raises(TeacherWorkforceValidationError, match="Gender breakdown"):
            tw.validate_teacher_workforce_data(self._frame(female_teachers=70))

    def test_rejects_implausible_ni_headcount(self):
        frame = self._frame(all_teachers=60000, female_teachers=45000, male_teachers=15000)
        with pytest.raises(TeacherWorkforceValidationError, match="implausibly high"):
            tw.validate_teacher_workforce_data(frame)

    def test_ignores_implausible_district_headcount(self):
        """The plausibility ceiling is an NI-level check only."""
        frame = self._frame(geography="Belfast", all_teachers=60000, female_teachers=45000, male_teachers=15000)
        assert tw.validate_teacher_workforce_data(frame) is True


class TestSummaryArithmetic:
    """Summary maths, exercised offline so the numbers are known in advance."""

    @pytest.fixture
    def summary(self):
        frame = pd.DataFrame(
            [
                {
                    "academic_year": "2021/22",
                    "geography": tw.NI_TOTAL,
                    "all_teachers": 100,
                    "female_teachers": 75,
                    "part_time_teachers": 20,
                },
                {
                    "academic_year": "2022/23",
                    "geography": tw.NI_TOTAL,
                    "all_teachers": 110,
                    "female_teachers": 88,
                    "part_time_teachers": 22,
                },
                {
                    "academic_year": "2022/23",
                    "geography": "Belfast",
                    "all_teachers": 40,
                    "female_teachers": 30,
                    "part_time_teachers": 8,
                },
            ]
        )
        return tw.get_workforce_summary(frame)

    def test_excludes_districts(self, summary):
        assert len(summary) == 2

    def test_year_on_year_change(self, summary):
        assert summary["yoy_change"].iloc[1] == 10
        assert summary["yoy_pct_change"].iloc[1] == 10.0

    def test_percentage_columns(self, summary):
        assert summary["female_pct"].tolist() == [75.0, 80.0]
        assert summary["part_time_pct"].tolist() == [20.0, 20.0]
