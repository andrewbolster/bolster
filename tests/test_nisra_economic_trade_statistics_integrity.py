"""NISRA Economic Trade Statistics (NIETS) data integrity tests.

These tests validate the real NIETS matrices fetched from the PxStat API: schema, coverage, and the
arithmetic relationships that hold between cuts (destination totals, goods plus services, size bands,
industry sections). Every relationship asserted here was derived from the published data before it was
written down. The relationships that do NOT hold are asserted too, so a future change that makes them
hold (or stops them holding) is noticed: the 11 districts do not add up to the NI total.

Network calls are made in module-scoped fixtures so each matrix is downloaded once (the industry and
SIC 2007 matrices are 15-20 MB).
"""

import numpy as np
import pandas as pd
import pytest

from bolster.data_sources.nisra import economic_trade_statistics as niets

# Published values are exact to float precision apart from the source's own rounding of the last digit.
TOLERANCE = 0.01  # GBP million

LGD_CODES = [f"N09000{n:03d}" for n in range(1, 12)]
INDUSTRY_SECTIONS = set("ABCDEFGHIJLMNPQRS")


def _wide(df: pd.DataFrame, index: list[str], column: str = "destination") -> pd.DataFrame:
    """Value of trade with one column per ``column`` code, one row per ``index`` combination."""
    return df.pivot_table(index=index, columns=column, values="value_gbp_m", aggfunc="first", dropna=False)


@pytest.fixture(scope="module")
def partner() -> pd.DataFrame:
    return niets.get_by_partner()


@pytest.fixture(scope="module")
def size_band() -> pd.DataFrame:
    return niets.get_by_size_band()


@pytest.fixture(scope="module")
def lgd() -> pd.DataFrame:
    return niets.get_by_lgd()


@pytest.fixture(scope="module")
def industry() -> pd.DataFrame:
    return niets.get_by_industry()


@pytest.fixture(scope="module")
def sic2() -> pd.DataFrame:
    return niets.get_by_sic2()


@pytest.fixture(scope="module")
def industry_totals(industry: pd.DataFrame) -> pd.DataFrame:
    """All-industry, all-transaction value by destination, one row per year and flow."""
    totals = industry[(industry["industry_code"] == "ALL") & (industry["transaction"] == "ALL")]
    return _wide(totals, ["year", "flow"])


class TestPartnerIntegrity:
    def test_required_columns(self, partner):
        required = {
            "year",
            "flow",
            "flow_label",
            "country_code",
            "country",
            "value_gbp_m",
            "ci_lower_gbp_m",
            "ci_upper_gbp_m",
            "cv_pct",
        }
        assert required <= set(partner.columns)

    def test_validates(self, partner):
        assert niets.validate_data(partner, "partner")

    def test_history_starts_in_2011_and_is_contiguous(self, partner):
        years = sorted(partner["year"].unique())
        assert years[0] == 2011
        assert years == list(range(years[0], years[-1] + 1))

    def test_latest_year_is_recent(self, partner):
        assert niets.latest_year(partner) >= 2025

    def test_both_flows_present(self, partner):
        assert set(partner["flow"]) == {"SALES", "PURCH"}

    def test_countries_are_iso_alpha3_codes(self, partner):
        codes = partner["country_code"].unique()
        assert len(codes) > 50
        assert all(len(code) == 3 and code.isupper() for code in codes)

    def test_each_country_appears_once_per_year_and_flow(self, partner):
        assert not partner.duplicated(["year", "flow", "country_code"]).any()

    def test_the_largest_sales_partner_is_the_usa(self, partner):
        latest = partner[(partner["year"] == niets.latest_year(partner)) & (partner["flow"] == "SALES")]
        assert latest.nlargest(1, "value_gbp_m")["country_code"].iloc[0] == "USA"

    def test_suppressed_cells_are_present_not_dropped(self, partner):
        assert partner["value_gbp_m"].isna().any()


class TestSizeBandIntegrity:
    def test_has_five_bands(self, size_band):
        assert set(size_band["size_band"]) == {"0_9", "10_49", "50_249", "250+", "ALL"}

    def test_validates(self, size_band):
        assert niets.validate_data(size_band, "size_band")

    def test_the_four_bands_add_up_to_all(self, size_band):
        wide = _wide(size_band, ["year", "flow", "transaction", "destination"], "size_band")
        complete = wide.dropna(subset=["0_9", "10_49", "50_249", "250+", "ALL"])
        assert len(complete) > 100
        residual = complete[["0_9", "10_49", "50_249", "250+"]].sum(axis=1) - complete["ALL"]
        assert residual.abs().max() < TOLERANCE

    def test_goods_plus_services_equal_all_transactions(self, size_band):
        everyone = size_band[(size_band["size_band"] == "ALL") & (size_band["destination"] == "ALL")]
        wide = _wide(everyone, ["year", "flow"], "transaction").dropna()
        assert len(wide) > 20
        assert (wide["GOODS"] + wide["SERVICES"] - wide["ALL"]).abs().max() < TOLERANCE

    def test_business_counts_are_positive_estimates(self, size_band):
        counts = size_band["n_businesses"].dropna()
        assert len(counts) > 0
        assert (counts > 0).all()


class TestLgdIntegrity:
    def test_has_the_eleven_districts_with_ons_codes(self, lgd):
        assert sorted(lgd["lgd_code"].unique()) == LGD_CODES

    def test_no_ni_total_row_is_included(self, lgd):
        assert "Northern Ireland" not in set(lgd["lgd"])

    def test_validates(self, lgd):
        assert niets.validate_data(lgd, "lgd")

    def test_within_a_district_all_is_ni_plus_external(self, lgd):
        wide = _wide(lgd, ["year", "flow", "lgd_code"]).dropna(subset=["ALL", "NI", "EXTERN"])
        assert len(wide) > 100
        assert (wide["ALL"] - wide["NI"] - wide["EXTERN"]).abs().max() < TOLERANCE

    def test_within_a_district_external_is_the_sum_of_its_parts(self, lgd):
        wide = _wide(lgd, ["year", "flow", "lgd_code"]).dropna(subset=["EXTERN", "GB", "IE", "REU", "ROW"])
        assert len(wide) > 100
        assert (wide["EXTERN"] - wide[["GB", "IE", "REU", "ROW"]].sum(axis=1)).abs().max() < TOLERANCE


class TestIndustryIntegrity:
    def test_has_seventeen_sections_and_a_total(self, industry):
        assert set(industry["industry_code"]) == INDUSTRY_SECTIONS | {"ALL"}

    def test_validates(self, industry):
        assert niets.validate_data(industry, "industry")

    def test_undefined_combinations_are_not_present(self, industry):
        pairs = set(zip(industry["flow"], industry["destination"], strict=True))
        assert ("SALES", "EXPORT") in pairs
        assert ("PURCH", "IMPORT") in pairs
        assert ("PURCH", "EXPORT") not in pairs
        assert ("SALES", "IMPORT") not in pairs

    def test_sales_all_is_ni_plus_external(self, industry_totals):
        sales = industry_totals.xs("SALES", level="flow").dropna(subset=["ALL", "NI", "EXTERN"])
        assert len(sales) >= 15
        assert (sales["ALL"] - sales["NI"] - sales["EXTERN"]).abs().max() < TOLERANCE

    def test_sales_external_includes_great_britain(self, industry_totals):
        sales = industry_totals.xs("SALES", level="flow").dropna(subset=["EXTERN", "GB", "IE", "REU", "ROW"])
        assert (sales["EXTERN"] - sales[["GB", "IE", "REU", "ROW"]].sum(axis=1)).abs().max() < TOLERANCE

    def test_exports_are_external_sales_outside_the_uk(self, industry_totals):
        sales = industry_totals.xs("SALES", level="flow").dropna(subset=["EXPORT", "IE", "REU", "ROW"])
        assert (sales["EXPORT"] - sales[["IE", "REU", "ROW"]].sum(axis=1)).abs().max() < TOLERANCE
        assert (sales["EXPORT"] < sales["EXTERN"]).all()

    def test_imports_are_external_purchases_outside_the_uk(self, industry_totals):
        purchases = industry_totals.xs("PURCH", level="flow").dropna(subset=["IMPORT", "IE", "REU", "ROW"])
        assert len(purchases) >= 15
        assert (purchases["IMPORT"] - purchases[["IE", "REU", "ROW"]].sum(axis=1)).abs().max() < TOLERANCE

    def test_goods_plus_services_equal_all_transactions(self, industry):
        everyone = industry[(industry["industry_code"] == "ALL") & (industry["destination"] == "ALL")]
        wide = _wide(everyone, ["year", "flow"], "transaction").dropna()
        assert len(wide) >= 20
        assert (wide["GOODS"] + wide["SERVICES"] - wide["ALL"]).abs().max() < TOLERANCE

    def test_industry_sections_add_up_to_the_total_in_the_latest_year(self, industry):
        latest = industry[
            (industry["year"] == niets.latest_year(industry))
            & (industry["flow"] == "SALES")
            & (industry["destination"] == "ALL")
            & (industry["transaction"] == "ALL")
        ]
        sections = latest[latest["industry_code"] != "ALL"]
        assert sections["value_gbp_m"].notna().all()
        total = latest.loc[latest["industry_code"] == "ALL", "value_gbp_m"].iloc[0]
        assert abs(sections["value_gbp_m"].sum() - total) < TOLERANCE

    def test_confidence_intervals_bracket_published_values(self, industry):
        published = industry.dropna(subset=["value_gbp_m", "ci_lower_gbp_m", "ci_upper_gbp_m"])
        assert len(published) > 1000
        assert (published["ci_lower_gbp_m"] <= published["value_gbp_m"]).all()
        assert (published["ci_upper_gbp_m"] >= published["value_gbp_m"]).all()

    def test_a_published_value_always_comes_with_its_interval(self, industry):
        has_value = industry["value_gbp_m"].notna()
        assert industry.loc[has_value, ["ci_lower_gbp_m", "ci_upper_gbp_m", "cv_pct"]].notna().all().all()


class TestSic2Integrity:
    def test_has_a_total_and_many_divisions(self, sic2):
        codes = set(sic2["sic2_code"])
        assert "ALL" in codes
        assert len(codes - {"ALL"}) > 80

    def test_validates(self, sic2):
        assert niets.validate_data(sic2, "sic2")

    def test_has_no_business_count_column(self, sic2):
        assert "n_businesses" not in sic2.columns

    def test_suppression_is_substantial_so_it_must_be_visible(self, sic2):
        divisions = sic2[sic2["sic2_code"] != "ALL"]
        assert divisions["value_gbp_m"].isna().mean() > 0.1

    def test_divisions_add_up_to_the_total_only_approximately(self, sic2):
        latest = sic2[
            (sic2["year"] == niets.latest_year(sic2)) & (sic2["flow"] == "SALES") & (sic2["destination"] == "ALL")
        ]
        total = latest.loc[latest["sic2_code"] == "ALL", "value_gbp_m"].iloc[0]
        published = latest.loc[latest["sic2_code"] != "ALL", "value_gbp_m"].dropna().sum()
        # Suppressed divisions are missing from the sum, so it is close to but not necessarily equal to the total.
        assert published <= total * 1.0001
        assert published >= total * 0.99


class TestCrossValidation:
    def test_size_band_totals_equal_the_industry_totals(self, size_band, industry_totals):
        everyone = size_band[
            (size_band["size_band"] == "ALL")
            & (size_band["transaction"] == "ALL")
            & (size_band["destination"] == "ALL")
        ]
        by_size = everyone.set_index(["year", "flow"])["value_gbp_m"]
        by_industry = industry_totals["ALL"]
        joined = pd.concat([by_size.rename("size"), by_industry.rename("industry")], axis=1).dropna()
        assert len(joined) >= 30
        assert np.allclose(joined["size"], joined["industry"], atol=TOLERANCE)

    def test_the_districts_do_not_add_up_to_the_ni_total(self, lgd, industry_totals):
        """The NIETS05 district cut covers only part of the NI total: never present its sum as NI."""
        districts = lgd[lgd["destination"] == "ALL"].groupby(["year", "flow"])["value_gbp_m"].sum()
        joined = pd.concat([districts.rename("districts"), industry_totals["ALL"].rename("ni")], axis=1).dropna()
        ratio = joined["districts"] / joined["ni"]
        assert len(joined) >= 30
        assert (ratio < 1.0).all(), "the district sum should be below the NI total in every year and flow"
        assert (ratio > 0.5).all(), f"the district sum is unexpectedly small: min ratio {ratio.min():.2f}"
