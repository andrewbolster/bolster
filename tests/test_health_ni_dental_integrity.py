"""Integrity tests for the General Dental Services module (live BSO/FPS and PxStat data).

The quarterly tables and the PxStat annual cubes are separate publications of the same
claims, so where they describe the same quantity they must agree exactly: four quarters of
treatments add up to the year, and the March-quarter registrations and dentist counts equal
the annual figures. A break in either is a parsing defect.
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import dental_services as gds
from bolster.data_sources.health_ni._base import NISRAValidationError

TRUSTS = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}
ANNUAL_NAMES = {"fillings": "Fillings", "extractions": "Extractions", "x_rays": "XRays", "crowns": "Crowns"}
QUARTERLY_AGES = {"0-4", "5-12", "13-17", "18-44", "45-59", "60-74", "75+", "Total"}
ANNUAL_AGES = {"Age 0 to 2", "Age 3 to 5", "Age 6 to 17", "Age 18+", "All Registrations"}


def _gap(frame: pd.DataFrame) -> pd.Series:
    """Northern Ireland minus the sum of the other rows, per quarter."""
    return frame.groupby("period").apply(lambda d: d[d.is_total].value.sum() - d[~d.is_total].value.sum())


class TestArguments:
    """Bad arguments are rejected before anything is downloaded."""

    def test_unknown_measure(self):
        with pytest.raises(ValueError, match="Unknown measure"):
            gds.get_quarterly_treatments("whitening", "trust")

    def test_treatments_have_no_assembly_area_table(self):
        with pytest.raises(ValueError, match="Unknown level"):
            gds.get_quarterly_treatments("fillings", "assembly_area")

    def test_registrations_level(self):
        with pytest.raises(ValueError, match="Unknown level"):
            gds.get_quarterly_registrations("region")

    @pytest.mark.parametrize("fn", [gds.get_quarterly_practices, gds.get_quarterly_dentists])
    def test_staffing_level(self, fn):
        with pytest.raises(ValueError, match="Unknown level"):
            fn("age_sex")

    def test_annual_level(self):
        with pytest.raises(ValueError, match="Unknown geography level"):
            gds.get_annual_treatments("region")

    def test_annual_series(self):
        with pytest.raises(ValueError, match="Unknown series"):
            gds.get_annual_unallocated("whitening", "trust")


class TestDiscovery:
    def test_finds_a_workbook(self):
        assert gds.find_latest_quarterly_url().lower().endswith(".xlsx")


class TestQuarterlyWorkbook:
    @pytest.fixture(scope="class")
    def raw(self):
        return gds.get_latest_quarterly_data()

    def test_columns(self, raw):
        assert {"sheet", "sheet_title", "table_id", "row_label", "column", "value", "period", "provisional"} <= set(
            raw.columns
        )

    def test_includes_the_monthly_payment_tables(self, raw):
        assert raw.sheet_title.dropna().str.contains("Monthly Breakdown of Claims").any()

    def test_provisional_flag_is_boolean(self, raw):
        assert raw.provisional.dtype == bool


class TestQuarterlyRegistrations:
    @pytest.fixture(scope="class", params=["trust", "lgd", "assembly_area"])
    def level(self, request):
        return request.param

    @pytest.fixture(scope="class")
    def frame(self, level):
        return gds.get_quarterly_registrations(level)

    def test_validates(self, frame):
        assert gds.validate_data(frame)

    def test_columns(self, frame, level):
        assert list(frame.columns) == ["period", "financial_year", "quarter", level, "value", "is_total", "provisional"]

    def test_history_runs_from_2017_18(self, frame):
        assert frame.period.min() == pd.Timestamp("2017-06-30")
        assert frame.period.max() >= pd.Timestamp("2026-03-31")
        assert frame.period.nunique() >= 38

    def test_quarters_are_contiguous(self, frame):
        gaps = pd.Series(sorted(frame.period.unique())).diff().dropna().dt.days
        assert gaps.between(88, 93).all()

    def test_areas_plus_unknown_equal_northern_ireland(self, frame):
        assert (_gap(frame) == 0).all()

    def test_one_total_row_per_quarter(self, frame):
        assert (frame.groupby("period").is_total.sum() == 1).all()

    def test_area_counts(self, frame, level):
        areas = set(frame[level]) - {"Unknown", "Northern Ireland"}
        assert len(areas) == {"trust": 5, "lgd": 11, "assembly_area": 18}[level]
        if level == "trust":
            assert areas == TRUSTS


@pytest.mark.parametrize("measure", sorted(gds.MEASURES))
class TestQuarterlyTreatments:
    @pytest.mark.parametrize("level", ["trust", "lgd"])
    def test_areas_plus_unknown_equal_northern_ireland(self, measure, level):
        frame = gds.get_quarterly_treatments(measure, level)
        assert gds.validate_data(frame)
        assert set(frame.measure) == {measure}
        assert frame.period.min() == pd.Timestamp("2017-06-30")
        assert (_gap(frame) == 0).all()

    def test_trust_and_lgd_agree_on_the_national_total(self, measure):
        trust = gds.get_quarterly_treatments(measure, "trust")
        lgd = gds.get_quarterly_treatments(measure, "lgd")
        national = lambda d: d[d.is_total].set_index("period").value  # noqa: E731
        assert (national(trust) == national(lgd)).all()


class TestAgeAndSex:
    @pytest.fixture(scope="class")
    def registrations(self):
        return gds.get_quarterly_registrations("age_sex")

    @pytest.fixture(scope="class")
    def fillings(self):
        return gds.get_quarterly_treatments("fillings", "age_sex")

    def test_categories(self, registrations):
        assert set(registrations.sex) == {"Male", "Female", "Unknown", "All"}
        assert set(registrations.age_group) == QUARTERLY_AGES

    def test_sexes_add_to_all_persons(self, registrations, fillings):
        for frame in (registrations, fillings):
            totals = frame[frame.age_group == "Total"].pivot(index="period", columns="sex", values="value")
            assert (totals["Male"] + totals["Female"] + totals["Unknown"] == totals["All"]).all()

    def test_fillings_age_bands_add_to_total(self, fillings):
        everyone = fillings[fillings.sex == "All"]
        bands = everyone[everyone.age_group != "Total"].groupby("period").value.sum()
        totals = everyone[everyone.age_group == "Total"].set_index("period").value
        assert (bands == totals).all()

    def test_registration_age_bands_add_to_total_within_rounding(self, registrations):
        everyone = registrations[registrations.sex == "All"]
        bands = everyone[everyone.age_group != "Total"].groupby("period").value.sum()
        totals = everyone[everyone.age_group == "Total"].set_index("period").value
        assert ((bands - totals).abs() <= 3).all()

    def test_all_persons_equal_the_trust_table_total(self, registrations):
        trust = gds.get_quarterly_registrations("trust")
        national = trust[trust.is_total].set_index("period").value
        everyone = (
            registrations[(registrations.sex == "All") & (registrations.age_group == "Total")].set_index("period").value
        )
        assert (everyone == national).all()


class TestPracticesAndDentists:
    @pytest.mark.parametrize("level", ["trust", "lgd", "assembly_area"])
    def test_practices_add_to_northern_ireland(self, level):
        practices = gds.get_quarterly_practices(level)
        assert gds.validate_data(practices)
        assert practices.period.min() == pd.Timestamp("2020-06-30")
        assert (_gap(practices) == 0).all()
        latest = practices[(practices.period == practices.period.max()) & practices.is_total].value.iloc[0]
        assert 200 < latest < 600

    @pytest.mark.parametrize("level", ["trust", "lgd", "assembly_area"])
    def test_dentists_add_to_northern_ireland_within_rounding(self, level):
        """Dentists who work in several places are proportioned across them, so areas hold fractions."""
        dentists = gds.get_quarterly_dentists(level)
        assert gds.validate_data(dentists)
        assert (_gap(dentists).abs() < 0.1).all()
        latest = dentists[(dentists.period == dentists.period.max()) & dentists.is_total].value.iloc[0]
        assert 800 < latest < 2000

    def test_dentists_in_an_area_can_be_fractional_but_the_total_is_whole(self):
        dentists = gds.get_quarterly_dentists("trust")
        assert (dentists[dentists.is_total].value % 1 == 0).all()
        assert (dentists[~dentists.is_total].value % 1 != 0).any()


class TestAnnual:
    @pytest.fixture(scope="class")
    def registrations(self):
        return gds.get_annual_registrations("trust")

    def test_registration_columns_and_ages(self, registrations):
        assert {"financial_year", "period", "area_code", "trust", "measure", "age_group", "value", "is_total"} <= set(
            registrations.columns
        )
        assert set(registrations.age_group) == ANNUAL_AGES
        assert registrations.financial_year.min() == "2013/14"

    def test_annual_age_bands_are_not_the_quarterly_age_bands(self):
        assert ANNUAL_AGES.isdisjoint(QUARTERLY_AGES)

    def test_age_bands_add_to_all_registrations(self, registrations):
        """Exact from 2018/19; the early years are out by one or two."""
        national = registrations[registrations.is_total]
        bands = national[national.age_group != "All Registrations"].groupby("financial_year").value.sum()
        everyone = national[national.age_group == "All Registrations"].set_index("financial_year").value
        gap = (bands - everyone).abs()
        assert (gap <= 2).all()
        assert (gap[gap.index >= "2018/19"] == 0).all()

    def test_treatment_measures(self):
        assert set(gds.get_annual_treatments("trust").measure) == {"Fillings", "Extractions", "Crowns", "XRays"}

    def test_dentists_and_surgeries_measures(self):
        assert set(gds.get_annual_dentists_and_surgeries("trust").measure) == {"Dentists", "Dental surgeries"}

    @pytest.mark.parametrize("level", ["trust", "lgd", "assembly_area", "dea"])
    def test_every_geography_has_one_total_row_per_series(self, level):
        frame = gds.get_annual_treatments(level)
        assert gds.validate_data(frame)
        assert (frame[frame.is_total].groupby(["financial_year", "measure"]).size() == 1).all()

    def test_surgeries_are_published_as_zero_before_the_series_began(self):
        """PxStat holds 0 (not a missing value) for every area, and for Northern Ireland, in 2013/14-2016/17.
        The module returns what is published, so callers must treat those zeros as missing."""
        frame = gds.get_annual_dentists_and_surgeries("trust")
        surgeries = frame[(frame.measure == "Dental surgeries") & frame.is_total].set_index("financial_year").value
        assert (surgeries[surgeries.index < "2017/18"] == 0).all()
        assert (surgeries[surgeries.index >= "2017/18"] > 300).all()

    @pytest.mark.parametrize("series", ["treatments", "registrations", "dentists_and_surgeries"])
    def test_unallocated_is_small_and_never_negative(self, series):
        gap = gds.get_annual_unallocated(series, "trust")
        gap = gap[gap.total > 0]  # surgeries are published as 0 before 2017/18
        assert (gap.unallocated >= -2).all()
        assert (gap.unallocated / gap.total < 0.05).all()


class TestQuarterlyAgreesWithAnnual:
    """The two publications describe the same claims, so they must reconcile exactly."""

    @pytest.mark.parametrize("measure", sorted(gds.MEASURES))
    def test_four_quarters_equal_the_year(self, measure):
        annual = gds.get_annual_treatments("trust")
        annual = annual[annual.is_total].set_index(["financial_year", "measure"]).value
        quarterly = gds.get_quarterly_treatments(measure, "trust")
        national = quarterly[quarterly.is_total]
        counts = national.groupby("financial_year").size()
        sums = national[national.financial_year.isin(counts[counts == 4].index)].groupby("financial_year").value.sum()
        years = [y for y in sums.index if (y, ANNUAL_NAMES[measure]) in annual.index]
        assert len(years) >= 8
        for year in years:
            assert sums[year] == annual[(year, ANNUAL_NAMES[measure])], f"{measure} {year}"

    def test_march_quarter_registrations_equal_the_annual_figure(self):
        annual = gds.get_annual_registrations("trust")
        annual = annual[annual.is_total & (annual.age_group == "All Registrations")].set_index("financial_year").value
        quarterly = gds.get_quarterly_registrations("trust")
        march = quarterly[quarterly.is_total & (quarterly.quarter == 4)].set_index("financial_year").value
        years = [y for y in march.index if y in annual.index]
        assert len(years) >= 8
        for year in years:
            assert march[year] == annual[year], year

    def test_quarterly_registrations_are_not_additive(self):
        """Adding four quarters of registrations gives about four times the annual figure."""
        quarterly = gds.get_quarterly_registrations("trust")
        four = quarterly[quarterly.is_total & (quarterly.financial_year == "2024/25")].value.sum()
        annual = gds.get_annual_registrations("trust")
        annual = annual[
            annual.is_total & (annual.age_group == "All Registrations") & (annual.financial_year == "2024/25")
        ].value.iloc[0]
        assert four > 3 * annual

    def test_march_quarter_dentists_equal_the_annual_count(self):
        annual = gds.get_annual_dentists_and_surgeries("trust")
        annual = annual[annual.is_total & (annual.measure == "Dentists")].set_index("financial_year").value
        quarterly = gds.get_quarterly_dentists("trust")
        march = quarterly[quarterly.is_total & (quarterly.quarter == 4)].set_index("financial_year").value
        years = [y for y in march.index if y in annual.index]
        assert len(years) >= 5
        for year in years:
            assert march[year] == annual[year], year

    def test_quarterly_unknown_is_never_smaller_than_the_annual_unallocated_amount(self):
        """Both agree on the Northern Ireland total, but the annual cubes place slightly more activity
        in an area than the quarterly tables do; the two agree exactly in the latest year."""
        quarterly = gds.get_quarterly_treatments("fillings", "trust")
        unknown = quarterly[quarterly.trust == "Unknown"]
        counts = unknown.groupby("financial_year").size()
        sums = unknown[unknown.financial_year.isin(counts[counts == 4].index)].groupby("financial_year").value.sum()
        gap = gds.get_annual_unallocated("treatments", "trust")
        gap = gap[gap.measure == "Fillings"].set_index("financial_year").unallocated
        years = sorted(y for y in sums.index if y in gap.index)
        assert len(years) >= 8
        for year in years:
            assert sums[year] >= gap[year], year
        assert sums[years[-1]] == gap[years[-1]]


class TestValidation:
    def test_rejects_empty(self):
        with pytest.raises(NISRAValidationError):
            gds.validate_data(pd.DataFrame(columns=["period", "value"]))

    def test_rejects_negative_counts(self):
        with pytest.raises(NISRAValidationError, match="negative"):
            gds.validate_data(pd.DataFrame({"period": [pd.Timestamp("2026-03-31")], "value": [-5.0]}))
