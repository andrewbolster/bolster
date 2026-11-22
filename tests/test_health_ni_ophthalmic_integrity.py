"""Integrity tests for the General Ophthalmic Services module (live BSO/FPS and PxStat data).

The quarterly tables and the PxStat annual cubes are separate publications of the same
claims, so they must agree exactly: four quarters add up to the year, and the areas plus
the ``Unknown`` row add up to Northern Ireland. A break in either is a parsing defect.
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import ophthalmic_services as gos
from bolster.data_sources.health_ni._base import NISRAValidationError

TRUSTS = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}
LGDS = {
    "Antrim and Newtownabbey",
    "Ards and North Down",
    "Armagh City, Banbridge and Craigavon",
    "Belfast",
    "Causeway Coast and Glens",
    "Derry City and Strabane",
    "Fermanagh and Omagh",
    "Lisburn and Castlereagh",
    "Mid Ulster",
    "Mid and East Antrim",
    "Newry, Mourne and Down",
}
ANNUAL_NAMES = {
    "sight_tests": "Sight Tests",
    "vouchers": "Vouchers",
    "repairs_replacements": "Repairs & Replacements",
}


class TestArguments:
    """Bad arguments are rejected before anything is downloaded."""

    def test_unknown_measure(self):
        with pytest.raises(ValueError, match="Unknown measure"):
            gos.get_quarterly_activity("glasses", "trust")

    def test_unknown_level(self):
        with pytest.raises(ValueError, match="Unknown level"):
            gos.get_quarterly_activity("sight_tests", "assembly_area")

    def test_practices_level(self):
        with pytest.raises(ValueError, match="Unknown level"):
            gos.get_quarterly_practices("age_sex")

    def test_annual_level(self):
        with pytest.raises(ValueError, match="Unknown geography level"):
            gos.get_annual_activity("region")


class TestDiscovery:
    def test_finds_a_workbook(self):
        assert gos.find_latest_quarterly_url().lower().endswith(".xlsx")


class TestQuarterlyWorkbook:
    @pytest.fixture(scope="class")
    def raw(self):
        return gos.get_latest_quarterly_data()

    def test_columns(self, raw):
        assert {"sheet", "sheet_title", "table_id", "row_label", "column", "value", "period", "provisional"} <= set(
            raw.columns
        )

    def test_includes_enhanced_services(self, raw):
        titles = " ".join(raw.sheet_title.dropna().unique())
        assert "NI PEARS" in titles
        assert "Glaucoma" in titles

    def test_provisional_flag_is_boolean(self, raw):
        assert raw.provisional.dtype == bool

    def test_enhanced_service_table_found_by_title(self):
        out = gos.get_quarterly_table(r"Number of Assessments at Northern Ireland Primary Eyecare", level="trust")
        assert "Northern Ireland" in set(out.trust)
        assert out.period.min() == pd.Timestamp("2018-03-31")


class TestQuarterlyActivity:
    @pytest.fixture(scope="class", params=sorted(gos.MEASURES))
    def measure(self, request):
        return request.param

    @pytest.fixture(scope="class")
    def trust(self, measure):
        return gos.get_quarterly_activity(measure, "trust")

    @pytest.fixture(scope="class")
    def lgd(self, measure):
        return gos.get_quarterly_activity(measure, "lgd")

    def test_validates(self, trust, lgd):
        assert gos.validate_data(trust)
        assert gos.validate_data(lgd)

    def test_columns(self, trust, measure):
        assert list(trust.columns) == [
            "measure",
            "period",
            "financial_year",
            "quarter",
            "trust",
            "value",
            "is_total",
            "provisional",
        ]
        assert set(trust.measure) == {measure}

    def test_history_runs_from_2017_18(self, trust):
        assert trust.period.min() == pd.Timestamp("2017-06-30")
        assert trust.period.max() >= pd.Timestamp("2026-03-31")
        assert trust.period.nunique() >= 38

    def test_quarters_are_contiguous(self, trust):
        periods = sorted(trust.period.unique())
        gaps = pd.Series(periods).diff().dropna().dt.days
        assert gaps.between(88, 93).all()

    def test_trust_areas(self, trust):
        assert set(trust.trust) == TRUSTS | {"Unknown", "Northern Ireland"}

    def test_lgd_areas(self, lgd):
        assert set(lgd.lgd) == LGDS | {"Unknown", "Northern Ireland"}

    def test_areas_plus_unknown_equal_northern_ireland(self, trust, lgd):
        for frame in (trust, lgd):
            gap = frame.groupby("period").apply(lambda d: d[d.is_total].value.sum() - d[~d.is_total].value.sum())
            assert (gap == 0).all()

    def test_one_total_row_per_quarter(self, trust):
        assert (trust.groupby("period").is_total.sum() == 1).all()


class TestAgeAndSex:
    @pytest.fixture(scope="class")
    def sight(self):
        return gos.get_quarterly_activity("sight_tests", "age_sex")

    def test_categories(self, sight):
        assert set(sight.sex) == {"Male", "Female", "Unknown", "All"}
        assert {"0-5", "6-15", "16-18", "19-44", "45-59", "60-74", "75+", "Total"} <= set(sight.age_group)

    def test_age_bands_add_to_total(self, sight):
        everyone = sight[sight.sex == "All"]
        bands = everyone[everyone.age_group != "Total"].groupby("period").value.sum()
        totals = everyone[everyone.age_group == "Total"].set_index("period").value
        assert (bands == totals).all()

    def test_sexes_add_to_all_persons(self, sight):
        totals = sight[sight.age_group == "Total"].pivot(index="period", columns="sex", values="value")
        assert (totals["Male"] + totals["Female"] + totals["Unknown"] == totals["All"]).all()

    def test_all_persons_equal_the_trust_table_total(self, sight):
        trust = gos.get_quarterly_activity("sight_tests", "trust")
        national = trust[trust.is_total].set_index("period").value
        everyone = sight[(sight.sex == "All") & (sight.age_group == "Total")].set_index("period").value
        assert (everyone == national).all()


class TestPracticesAndPractitioners:
    @pytest.mark.parametrize("level", ["trust", "lgd"])
    def test_practices_add_to_northern_ireland(self, level):
        practices = gos.get_quarterly_practices(level)
        assert gos.validate_data(practices)
        gap = practices.groupby("period").apply(lambda d: d[d.is_total].value.sum() - d[~d.is_total].value.sum())
        assert (gap == 0).all()
        latest = practices[(practices.period == practices.period.max()) & practices.is_total].value.iloc[0]
        assert 150 < latest < 500

    def test_practices_trust_and_lgd_agree(self):
        by_trust = gos.get_quarterly_practices("trust")
        by_lgd = gos.get_quarterly_practices("lgd")
        national = lambda d: d[d.is_total].set_index("period").value  # noqa: E731
        assert (national(by_trust) == national(by_lgd)).all()

    def test_practitioner_types_add_to_total(self):
        people = gos.get_quarterly_practitioners()
        assert set(people.practitioner_type) == {"Ophthalmic Medical Practitioners", "Optometrists", "Total"}
        wide = people.pivot(index="period", columns="practitioner_type", values="value")
        assert (wide["Ophthalmic Medical Practitioners"] + wide["Optometrists"] == wide["Total"]).all()


class TestAnnualActivity:
    @pytest.fixture(scope="class")
    def trust(self):
        return gos.get_annual_activity("trust")

    def test_columns_and_measures(self, trust):
        assert {"financial_year", "period", "area_code", "trust", "measure", "value", "is_total"} <= set(trust.columns)
        assert set(trust.measure) == {"Sight Tests", "Domiciliary Sight Tests", "Vouchers", "Repairs & Replacements"}

    def test_history(self, trust):
        assert trust.financial_year.min() == "2017/18"
        assert trust.financial_year.max() >= "2025/26"

    @pytest.mark.parametrize("level", ["trust", "lgd", "assembly_area", "dea"])
    def test_every_geography_has_a_total_row(self, level):
        frame = gos.get_annual_activity(level)
        assert gos.validate_data(frame)
        assert frame.is_total.any()
        assert (frame[frame.is_total].groupby(["financial_year", "measure"]).size() == 1).all()

    def test_unallocated_is_small_and_never_negative(self):
        for level in ("trust", "lgd", "assembly_area"):
            gap = gos.get_annual_unallocated(level)
            assert (gap.unallocated >= 0).all()
            assert (gap.unallocated / gap.total < 0.05).all()

    def test_gap_is_the_same_whichever_geography_is_used(self):
        gaps = {
            level: gos.get_annual_unallocated(level).set_index(["financial_year", "measure"]).unallocated
            for level in ("trust", "lgd", "assembly_area")
        }
        assert gaps["trust"].equals(gaps["lgd"])
        assert gaps["trust"].equals(gaps["assembly_area"])

    def test_annual_practices(self):
        practices = gos.get_annual_practices("trust")
        assert practices.financial_year.min() == "2013/14"
        assert set(practices.measure) == {"Ophthalmic Practices"}
        assert practices[practices.is_total].value.between(150, 500).all()


class TestQuarterlyAgreesWithAnnual:
    """The two publications describe the same claims, so they must reconcile exactly."""

    @pytest.fixture(scope="class")
    def annual(self):
        frame = gos.get_annual_activity("trust")
        return frame[frame.is_total].set_index(["financial_year", "measure"]).value

    @pytest.mark.parametrize("measure", sorted(gos.MEASURES))
    def test_four_quarters_equal_the_year(self, annual, measure):
        quarterly = gos.get_quarterly_activity(measure, "trust")
        national = quarterly[quarterly.is_total]
        counts = national.groupby("financial_year").size()
        complete = counts[counts == 4].index
        sums = national[national.financial_year.isin(complete)].groupby("financial_year").value.sum()
        years = [y for y in sums.index if (y, ANNUAL_NAMES[measure]) in annual.index]
        assert len(years) >= 8
        for year in years:
            assert sums[year] == annual[(year, ANNUAL_NAMES[measure])], f"{measure} {year}"

    def test_quarterly_unknown_is_never_smaller_than_the_annual_unallocated_amount(self):
        """Both publications agree on the Northern Ireland total in every year, but the annual cubes
        place slightly more activity in an area than the quarterly tables do, so the quarterly
        ``Unknown`` is at least as large; the two agree exactly in the most recent years."""
        quarterly = gos.get_quarterly_activity("sight_tests", "trust")
        unknown = quarterly[quarterly.trust == "Unknown"]
        counts = unknown.groupby("financial_year").size()
        sums = unknown[unknown.financial_year.isin(counts[counts == 4].index)].groupby("financial_year").value.sum()
        gap = gos.get_annual_unallocated("trust")
        gap = gap[gap.measure == "Sight Tests"].set_index("financial_year").unallocated
        years = [y for y in sums.index if y in gap.index]
        assert len(years) >= 8
        for year in years:
            assert sums[year] >= gap[year], year
            assert (sums[year] - gap[year]) / gap[year] < 0.05, year
        latest = sorted(years)[-3:]
        for year in latest:
            assert sums[year] == gap[year], year


class TestValidation:
    def test_rejects_empty(self):
        with pytest.raises(NISRAValidationError):
            gos.validate_data(pd.DataFrame(columns=["period", "value"]))

    def test_rejects_negative_counts(self):
        with pytest.raises(NISRAValidationError, match="negative"):
            gos.validate_data(pd.DataFrame({"period": [pd.Timestamp("2026-03-31")], "value": [-5.0]}))
