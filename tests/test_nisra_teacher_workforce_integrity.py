"""Integrity and validation tests for nisra.teacher_workforce.

Network tests use real data from the NISRA PxStat API.  Validation unit
tests run entirely in-process (no network calls).
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import teacher_workforce as tw

LGD_COUNT = 11


class TestHeadcountIntegrity:
    """Integration tests against the live teacher headcount matrix."""

    @pytest.fixture(scope="class")
    def headcount(self) -> pd.DataFrame:
        return tw.get_headcount()

    def test_required_columns(self, headcount: pd.DataFrame) -> None:
        required = {
            "academic_year",
            "year_start",
            "geography_code",
            "geography",
            "statistic",
            "value",
        }
        assert required <= set(headcount.columns), f"Missing: {required - set(headcount.columns)}"

    def test_not_empty(self, headcount: pd.DataFrame) -> None:
        assert len(headcount) > 0

    def test_all_statistics_present(self, headcount: pd.DataFrame) -> None:
        assert set(tw.list_statistics()) == set(headcount["statistic"].unique())

    def test_eleven_lgds_plus_ni(self, headcount: pd.DataFrame) -> None:
        geographies = set(headcount["geography"].unique())
        assert tw.NI_GEOGRAPHY in geographies
        assert len(geographies - {tw.NI_GEOGRAPHY}) == LGD_COUNT

    def test_lgd_code_format(self, headcount: pd.DataFrame) -> None:
        codes = set(headcount["geography_code"].unique())
        assert all(code.startswith("N") and len(code) == 9 for code in codes)

    def test_coverage_from_2015_16(self, headcount: pd.DataFrame) -> None:
        assert headcount["year_start"].min() == 2015

    def test_sufficient_years(self, headcount: pd.DataFrame) -> None:
        assert headcount["academic_year"].nunique() >= 8

    def test_values_non_negative(self, headcount: pd.DataFrame) -> None:
        assert (headcount["value"].dropna() >= 0).all()

    def test_no_missing_values(self, headcount: pd.DataFrame) -> None:
        assert headcount["value"].isna().sum() == 0

    def test_sex_breakdown_sums_to_total(self, headcount: pd.DataFrame) -> None:
        """Male + female headcount must reconcile with the all-teachers total."""
        wide = headcount.pivot_table(index=["academic_year", "geography"], columns="statistic", values="value")
        assert (wide["male"] + wide["female"] - wide["all_teachers"]).abs().max() == 0

    def test_working_pattern_sums_to_total(self, headcount: pd.DataFrame) -> None:
        wide = headcount.pivot_table(index=["academic_year", "geography"], columns="statistic", values="value")
        assert (wide["full_time"] + wide["part_time"] - wide["all_teachers"]).abs().max() == 0

    def test_age_bands_sum_to_total(self, headcount: pd.DataFrame) -> None:
        wide = headcount.pivot_table(index=["academic_year", "geography"], columns="statistic", values="value")
        age_sum = wide["aged_29_and_under"] + wide["aged_30_to_59"] + wide["aged_60_and_over"]
        assert (age_sum - wide["all_teachers"]).abs().max() == 0

    def test_ni_total_exceeds_every_lgd(self, headcount: pd.DataFrame) -> None:
        totals = headcount[headcount["statistic"] == "all_teachers"]
        ni = totals[totals["geography"] == tw.NI_GEOGRAPHY].set_index("academic_year")["value"]
        lgds = totals[totals["geography"] != tw.NI_GEOGRAPHY]
        assert (lgds["value"] < lgds["academic_year"].map(ni)).all()

    def test_ni_headcount_plausible(self, headcount: pd.DataFrame) -> None:
        ni = headcount[(headcount["geography"] == tw.NI_GEOGRAPHY) & (headcount["statistic"] == "all_teachers")]
        assert ni["value"].between(15_000, 30_000).all()

    def test_2022_23_ni_all_teachers(self, headcount: pd.DataFrame) -> None:
        """Ground truth: 21,416 teachers in NI grant-aided schools in 2022/23."""
        row = headcount[
            (headcount["academic_year"] == "2022/23")
            & (headcount["geography"] == tw.NI_GEOGRAPHY)
            & (headcount["statistic"] == "all_teachers")
        ]
        assert row["value"].iloc[0] == 21416

    def test_teaching_is_female_majority(self, headcount: pd.DataFrame) -> None:
        wide = headcount.pivot_table(index=["academic_year", "geography"], columns="statistic", values="value")
        assert (wide["female"] > wide["male"]).all()

    def test_validation_passes(self, headcount: pd.DataFrame) -> None:
        assert tw.validate_data(headcount)


class TestFTEIntegrity:
    """Integration tests against the live FTE matrix."""

    @pytest.fixture(scope="class")
    def fte(self) -> pd.DataFrame:
        return tw.get_fte()

    def test_required_columns(self, fte: pd.DataFrame) -> None:
        required = {
            "academic_year",
            "year_start",
            "geography_code",
            "geography",
            "school_type",
            "school_type_label",
            "measure",
            "value",
        }
        assert required <= set(fte.columns), f"Missing: {required - set(fte.columns)}"

    def test_measure_column(self, fte: pd.DataFrame) -> None:
        assert set(fte["measure"]) == {"fte"}

    def test_all_school_types_present(self, fte: pd.DataFrame) -> None:
        assert set(tw.list_school_types()) == set(fte["school_type"].unique())

    def test_eleven_lgds_plus_ni(self, fte: pd.DataFrame) -> None:
        geographies = set(fte["geography"].unique())
        assert len(geographies - {tw.NI_GEOGRAPHY}) == LGD_COUNT

    def test_values_non_negative(self, fte: pd.DataFrame) -> None:
        assert (fte["value"].dropna() >= 0).all()

    def test_all_type_exceeds_components(self, fte: pd.DataFrame) -> None:
        """The 'all' school type must be at least as large as any single type."""
        wide = fte.pivot_table(index=["academic_year", "geography"], columns="school_type", values="value")
        components = [c for c in wide.columns if c != "all"]
        assert (wide["all"] >= wide[components].max(axis=1)).all()

    def test_fte_below_headcount(self, fte: pd.DataFrame) -> None:
        """FTE accounts for part-time working, so it cannot exceed headcount."""
        ni_fte = fte[(fte["geography"] == tw.NI_GEOGRAPHY) & (fte["school_type"] == "all")]
        ni_fte = ni_fte.set_index("academic_year")["value"]
        headcount = tw.get_headcount()
        ni_head = headcount[
            (headcount["geography"] == tw.NI_GEOGRAPHY) & (headcount["statistic"] == "all_teachers")
        ].set_index("academic_year")["value"]
        assert (ni_fte < ni_head.reindex(ni_fte.index)).all()

    def test_primary_largest_sector(self, fte: pd.DataFrame) -> None:
        """Primary schools employ more FTE teachers than any other single sector."""
        ni = fte[(fte["geography"] == tw.NI_GEOGRAPHY) & (fte["academic_year"] == "2022/23")]
        ni = ni.set_index("school_type")["value"].drop("all")
        assert ni.idxmax() == "primary"

    def test_validation_passes(self, fte: pd.DataFrame) -> None:
        assert tw.validate_data(fte)


class TestPupilTeacherRatioIntegrity:
    """Integration tests against the live pupil:teacher ratio matrix."""

    @pytest.fixture(scope="class")
    def ptr(self) -> pd.DataFrame:
        return tw.get_pupil_teacher_ratios()

    def test_measure_column(self, ptr: pd.DataFrame) -> None:
        assert set(ptr["measure"]) == {"ptr"}

    def test_all_school_types_present(self, ptr: pd.DataFrame) -> None:
        assert set(tw.list_school_types()) == set(ptr["school_type"].unique())

    def test_ratios_plausible(self, ptr: pd.DataFrame) -> None:
        """Zeros mark LGDs with no school of that type; real ratios sit below 40."""
        assert ptr["value"].between(0, 40).all()

    def test_nonzero_ratios_above_four(self, ptr: pd.DataFrame) -> None:
        """Special schools bottom out around 4 pupils per teacher."""
        non_zero = ptr[ptr["value"] > 0]["value"]
        assert non_zero.min() >= 4

    def test_special_schools_lowest_ratio(self, ptr: pd.DataFrame) -> None:
        """Special schools have the smallest class sizes of any sector."""
        ni = ptr[(ptr["geography"] == tw.NI_GEOGRAPHY) & (ptr["academic_year"] == "2022/23")]
        ni = ni.set_index("school_type")["value"].drop("all")
        assert ni.idxmin() == "special"

    def test_zero_ratios_are_preparatory_only(self, ptr: pd.DataFrame) -> None:
        """Preparatory departments are attached to grammar schools and absent from most LGDs."""
        assert set(ptr[ptr["value"] == 0]["school_type"].unique()) == {"preparatory"}

    def test_validation_passes(self, ptr: pd.DataFrame) -> None:
        assert tw.validate_data(ptr)


class TestAggregateAccessors:
    """Tests for the combined accessors."""

    def test_get_latest_data_all(self) -> None:
        data = tw.get_latest_data("all")
        assert sorted(data.keys()) == ["fte", "headcount", "ptr"]
        assert all(len(df) > 0 for df in data.values())

    @pytest.mark.parametrize("dimension", ["headcount", "fte", "ptr"])
    def test_get_latest_data_single(self, dimension: str) -> None:
        df = tw.get_latest_data(dimension)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_get_latest_data_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="dimension must be one of"):
            tw.get_latest_data("nonsense")

    def test_ni_summary_covers_all_measures(self) -> None:
        summary = tw.get_ni_summary()
        assert sorted(summary["measure"].unique()) == ["fte", "headcount", "ptr"]
        assert set(summary.columns) == {"academic_year", "year_start", "measure", "category", "value"}

    def test_ni_summary_is_ni_only(self) -> None:
        """Row count matches the NI slice of each contributing matrix."""
        summary = tw.get_ni_summary()
        years = summary["academic_year"].nunique()
        expected = years * (len(tw.list_statistics()) + 2 * len(tw.list_school_types()))
        assert len(summary) == expected


class TestListHelpers:
    """Unit tests for the label listing helpers (no network)."""

    def test_list_statistics(self) -> None:
        assert {"all_teachers", "male", "female", "full_time", "part_time"} <= set(tw.list_statistics())

    def test_list_school_types(self) -> None:
        assert {"nursery", "primary", "grammar", "special", "all"} <= set(tw.list_school_types())


class TestAcademicYearParsing:
    """Unit tests for academic year handling (no network)."""

    def test_extracts_start_year(self) -> None:
        result = tw._academic_year_start(pd.Series(["2015/16", "2019/20", "2022/23"]))
        assert result.tolist() == [2015, 2019, 2022]

    def test_returns_integers(self) -> None:
        result = tw._academic_year_start(pd.Series(["2015/16"]))
        assert result.dtype.kind == "i"


class TestValidation:
    """Unit tests for validate_data (no network)."""

    @pytest.fixture
    def valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "academic_year": [f"20{y}/{y + 1}" for y in range(15, 23)],
                "year_start": list(range(2015, 2023)),
                "geography": [tw.NI_GEOGRAPHY] * 8,
                "value": [100.0] * 8,
            }
        )

    def test_accepts_valid_frame(self, valid_frame: pd.DataFrame) -> None:
        assert tw.validate_data(valid_frame)

    def test_rejects_none(self) -> None:
        assert not tw.validate_data(None)

    def test_rejects_empty(self) -> None:
        assert not tw.validate_data(pd.DataFrame())

    def test_rejects_missing_columns(self, valid_frame: pd.DataFrame) -> None:
        assert not tw.validate_data(valid_frame.drop(columns=["geography"]))

    def test_rejects_negative_values(self, valid_frame: pd.DataFrame) -> None:
        valid_frame.loc[0, "value"] = -1
        assert not tw.validate_data(valid_frame)

    def test_rejects_too_few_years(self, valid_frame: pd.DataFrame) -> None:
        assert not tw.validate_data(valid_frame.head(3))

    def test_tolerates_null_values(self, valid_frame: pd.DataFrame) -> None:
        valid_frame.loc[0, "value"] = None
        assert tw.validate_data(valid_frame)

    def test_min_years_is_configurable(self, valid_frame: pd.DataFrame) -> None:
        assert tw.validate_data(valid_frame.head(3), min_years=3)
