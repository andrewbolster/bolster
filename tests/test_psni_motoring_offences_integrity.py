"""Integrity tests for PSNI Motoring Offences module.

Tests use real data downloaded from PSNI and cached via the normal
CachedDownloader mechanism. No mocks — all tests hit the real source
(or the local cache on subsequent runs).
"""

import pandas as pd
import pytest

from bolster.data_sources.psni import motoring_offences
from bolster.data_sources.psni._base import PSNIDataNotFoundError, PSNIValidationError


@pytest.mark.network
class TestAnnualTrends:
    """Annual disposal-type series back to 1998."""

    @pytest.fixture(scope="class")
    def trends(self):
        return motoring_offences.get_annual_trends()

    def test_required_columns(self, trends):
        assert {"year", "disposal_type", "offences"}.issubset(trends.columns)

    def test_not_empty(self, trends):
        assert len(trends) > 0

    def test_starts_1998(self, trends):
        assert trends["year"].min() == 1998

    def test_reaches_recent_year(self, trends):
        assert trends["year"].max() >= 2024

    def test_years_contiguous(self, trends):
        years = sorted(trends["year"].unique())
        assert years == list(range(years[0], years[-1] + 1))

    def test_counts_non_negative(self, trends):
        assert (trends["offences"].dropna() >= 0).all()

    def test_fpn_present_every_year(self, trends):
        fpn = trends[trends["disposal_type"].str.contains("Fixed Penalty", case=False)]
        assert set(fpn["year"]) == set(trends["year"])

    def test_validate_passes(self, trends):
        assert motoring_offences.validate_data(trends)


@pytest.mark.network
class TestDisposalType:
    """Latest-year disposal type breakdown."""

    @pytest.fixture(scope="class")
    def disposals(self):
        return motoring_offences.get_offences_by_disposal_type()

    def test_required_columns(self, disposals):
        assert {"disposal_type", "year", "offences"}.issubset(disposals.columns)

    def test_not_empty(self, disposals):
        assert len(disposals) > 0

    def test_two_year_comparison(self, disposals):
        assert disposals["year"].nunique() == 2

    def test_one_row_per_disposal_per_year(self, disposals):
        assert not disposals.duplicated(subset=["disposal_type", "year"]).any()

    def test_counts_positive(self, disposals):
        assert disposals["offences"].sum() > 0


@pytest.mark.network
class TestByMonth:
    """Offence group counts by month."""

    @pytest.fixture(scope="class")
    def by_month(self):
        return motoring_offences.get_offences_by_month()

    def test_required_columns(self, by_month):
        assert {"offence_group", "month", "offences"}.issubset(by_month.columns)

    def test_month_is_datetime(self, by_month):
        assert pd.api.types.is_datetime64_any_dtype(by_month["month"])

    def test_twelve_months(self, by_month):
        assert by_month["month"].nunique() == 12

    def test_multiple_offence_groups(self, by_month):
        assert by_month["offence_group"].nunique() >= 5

    def test_counts_non_negative(self, by_month):
        assert (by_month["offences"].dropna() >= 0).all()


@pytest.mark.network
class TestAgeGender:
    """Age and gender breakdowns stacked into one frame."""

    @pytest.fixture(scope="class")
    def age_gender(self):
        return motoring_offences.get_offences_by_age_gender()

    def test_required_columns(self, age_gender):
        assert {"offence_group", "breakdown", "category", "offences"}.issubset(age_gender.columns)

    def test_both_breakdowns_present(self, age_gender):
        assert set(age_gender["breakdown"].unique()) == {"gender", "age"}

    def test_gender_categories(self, age_gender):
        gender = age_gender[age_gender["breakdown"] == "gender"]
        assert {"Male", "Female"}.issubset(set(gender["category"]))

    def test_age_categories(self, age_gender):
        age = age_gender[age_gender["breakdown"] == "age"]
        assert {"Under 18", "70+"}.issubset(set(age["category"]))

    def test_counts_non_negative(self, age_gender):
        assert (age_gender["offences"].dropna() >= 0).all()


@pytest.mark.network
class TestDistrict:
    """Policing district breakdown with population rates."""

    @pytest.fixture(scope="class")
    def district(self):
        return motoring_offences.get_offences_by_district()

    def test_required_columns(self, district):
        assert {"district", "lgd_code", "total", "population_16_plus", "rate_per_10000"}.issubset(district.columns)

    def test_eleven_districts(self, district):
        assert len(district) == 11

    def test_all_lgd_codes_resolved(self, district):
        assert district["lgd_code"].notna().all(), sorted(district[district["lgd_code"].isna()]["district"])

    def test_lgd_codes_unique(self, district):
        assert not district["lgd_code"].duplicated().any()

    def test_lgd_code_format(self, district):
        assert district["lgd_code"].str.match(r"N09\d{6}").all()

    def test_totals_positive(self, district):
        assert (district["total"] > 0).all()

    def test_population_positive(self, district):
        assert (district["population_16_plus"] > 0).all()

    def test_rate_consistent_with_total(self, district):
        computed = district["total"] / district["population_16_plus"] * 10_000
        assert ((computed - district["rate_per_10000"]).abs() < 1.0).all()


@pytest.mark.network
class TestOffenceByDisposal:
    """Offence group crossed with disposal type."""

    @pytest.fixture(scope="class")
    def crosstab(self):
        return motoring_offences.get_offences_by_offence_and_disposal()

    def test_required_columns(self, crosstab):
        assert {"offence_group", "disposal_type", "offences"}.issubset(crosstab.columns)

    def test_multiple_disposal_types(self, crosstab):
        assert crosstab["disposal_type"].nunique() >= 4

    def test_counts_non_negative(self, crosstab):
        assert (crosstab["offences"].dropna() >= 0).all()


@pytest.mark.network
class TestOffenceTrends:
    """Per-offence annual series."""

    @pytest.mark.parametrize("offence", ["speeding", "mobile-phone", "careless-driving", "drink-drug-driving"])
    def test_series_shape(self, offence):
        df = motoring_offences.get_offence_trends(offence)
        assert {"year", "disposal_type", "offences"}.issubset(df.columns)
        assert len(df) > 0
        assert df["year"].min() >= 2011
        assert (df["offences"].dropna() >= 0).all()

    def test_unknown_offence_raises(self):
        with pytest.raises(PSNIDataNotFoundError, match="Unknown offence"):
            motoring_offences.get_offence_trends("joyriding")

    def test_list_offence_series(self):
        series = motoring_offences.list_offence_series()
        assert "speeding" in series
        assert len(series) == 4


@pytest.mark.network
class TestSpeeding:
    """Speeding-specific sub-tables."""

    @pytest.fixture(scope="class")
    def top_speeds(self):
        return motoring_offences.get_top_speeds()

    @pytest.fixture(scope="class")
    def speeding_district(self):
        return motoring_offences.get_speeding_by_district()

    def test_top_speeds_columns(self, top_speeds):
        assert {"speed_limit_mph", "highest_speed_mph", "location"}.issubset(top_speeds.columns)

    def test_top_speeds_exceed_limits(self, top_speeds):
        assert (top_speeds["highest_speed_mph"] > top_speeds["speed_limit_mph"]).all()

    def test_top_speeds_limits_plausible(self, top_speeds):
        assert top_speeds["speed_limit_mph"].between(20, 70).all()

    def test_speeding_district_columns(self, speeding_district):
        assert {"district", "lgd_code", "offences", "rate_per_10000"}.issubset(speeding_district.columns)

    def test_speeding_district_count(self, speeding_district):
        assert len(speeding_district) == 11

    def test_speeding_district_codes_resolved(self, speeding_district):
        assert speeding_district["lgd_code"].notna().all()


@pytest.mark.network
class TestDispatcher:
    """The table dispatcher exposed to the CLI."""

    def test_list_tables_non_empty(self):
        assert len(motoring_offences.list_tables()) >= 10

    def test_every_table_returns_data(self):
        for table in motoring_offences.list_tables():
            df = motoring_offences.get_latest_data(table)
            assert not df.empty, f"{table} returned an empty frame"

    def test_unknown_table_raises(self):
        with pytest.raises(PSNIDataNotFoundError, match="Unknown table"):
            motoring_offences.get_latest_data("nonsense")

    def test_publication_url_is_xlsx(self):
        assert motoring_offences.get_latest_publication_url().endswith(".xlsx")


class TestValidation:
    """Pure validation logic — no network access required."""

    def test_empty_raises(self):
        with pytest.raises(PSNIValidationError, match="empty"):
            motoring_offences.validate_data(pd.DataFrame())

    def test_missing_columns_raises(self):
        with pytest.raises(PSNIValidationError, match="Missing required columns"):
            motoring_offences.validate_data(pd.DataFrame({"year": [2025]}), required_columns=["offences"])

    def test_negative_counts_raise(self):
        with pytest.raises(PSNIValidationError, match="negative"):
            motoring_offences.validate_data(pd.DataFrame({"offences": [1, -1]}))

    def test_valid_frame_passes(self):
        assert motoring_offences.validate_data(pd.DataFrame({"offences": [1, 2]}), required_columns=["offences"])
