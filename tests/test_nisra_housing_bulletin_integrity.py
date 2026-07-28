"""Data integrity tests for the NI Housing Bulletin module.

These tests hit the live DfC publication — no mocks. Network-dependent classes
are marked so they skip cleanly when SSL certs aren't configured.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.nisra import housing_bulletin as hb
from bolster.data_sources.nisra._base import NISRAValidationError

_QUARTERS = {"Apr-Jun", "Jul-Sep", "Oct-Dec", "Jan-Mar"}

_LGDS = {
    "Antrim and Newtownabbey",
    "Ards and North Down",
    "Armagh City, Banbridge and Craigavon",
    "Belfast",
    "Causeway Coast and Glens",
    "Derry City and Strabane",
    "Fermanagh and Omagh",
    "Lisburn and Castlereagh",
    "Mid and East Antrim",
    "Mid Ulster",
    "Newry, Mourne and Down",
}


class TestParsingHelpers:
    """Pure-function tests for the label normalisers — no network required."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2021-22", "2021/22"),
            ("2010/11", "2010/11"),
            ("Year 2005-06", "2005/06"),
            ("  2024 - 25 ", "2024/25"),
            ("Apr - Jun", None),
            ("Total", None),
            (None, None),
        ],
    )
    def test_normalise_financial_year(self, raw, expected):
        assert hb.normalise_financial_year(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Apr - Jun", "Apr-Jun"),
            ("Apr-Jun", "Apr-Jun"),
            ("Jul - Sept", "Jul-Sep"),
            ("Oct-Dec(R)", "Oct-Dec"),
            ("Jan - Mar 2008", "Jan-Mar"),
            ("Jan - Mar 2026(P)", "Jan-Mar"),
            ("2021-22", None),
            ("Total", None),
            (None, None),
        ],
    )
    def test_normalise_quarter(self, raw, expected):
        assert hb.normalise_quarter(raw) == expected

    def test_normalise_quarter_corrects_source_typo(self):
        """The 2021-22 rows of table 2.1 mislabel Q3 as 'Sep - Dec'."""
        assert hb.normalise_quarter("Sep - Dec") == "Oct-Dec"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Ards & North Down", "Ards and North Down"),
            ("Derry City & Strabane", "Derry City and Strabane"),
            ("Belfast", "Belfast"),
            ("Total", "Northern Ireland"),
            ("Total allocations", "Northern Ireland"),
            ("Northern Ireland", "Northern Ireland"),
            ("Belfast2", "Belfast"),
            ("Mid & East Antrim 1", "Mid and East Antrim"),
        ],
    )
    def test_normalise_lgd(self, raw, expected):
        assert hb.normalise_lgd(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1,234", 1234.0),
            ("£5,000", 5000.0),
            ("0", 0.0),
            ("-", None),
            ("..", None),
            ("", None),
            (None, None),
            (float("nan"), None),
            ("not a number", None),
        ],
    )
    def test_clean_number(self, raw, expected):
        assert hb._clean_number(raw) == expected

    @pytest.mark.parametrize(
        ("label", "quarter", "expected"),
        [
            ("Apr - Jun 2007", "Apr-Jun", "2007/08"),
            ("Oct - Dec 2007", "Oct-Dec", "2007/08"),
            ("Jan - Mar 2008", "Jan-Mar", "2007/08"),
            ("Jan - Mar 2000", "Jan-Mar", "1999/00"),
            ("Year 2007-08", None, "2007/08"),
            ("Nothing here", None, None),
            ("Apr - Jun", "Apr-Jun", None),
        ],
    )
    def test_financial_year_of(self, label, quarter, expected):
        assert hb._financial_year_of(label, quarter) == expected

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Oct - Dec 2025(R)", "revised"),
            ("Jan - Mar 2026(P)", "provisional"),
            ("Apr - Jun 2025", "final"),
        ],
    )
    def test_revision_status(self, label, expected):
        assert hb._revision_status(label) == expected


class TestValidation:
    """Validation edge cases — no network required."""

    def test_rejects_empty_dataframe(self):
        with pytest.raises(NISRAValidationError, match="empty"):
            hb.validate_data(pd.DataFrame())

    def test_rejects_none(self):
        with pytest.raises(NISRAValidationError, match="empty"):
            hb.validate_data(None)

    def test_rejects_missing_columns(self):
        df = pd.DataFrame({"lgd": ["Belfast"]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            hb.validate_data(df, {"lgd", "total_stock"})

    def test_rejects_negative_values(self):
        df = pd.DataFrame({"lgd": ["Belfast"], "total_stock": [-1]})
        with pytest.raises(NISRAValidationError, match="negative"):
            hb.validate_data(df, {"lgd", "total_stock"})

    def test_rejects_unknown_lgd(self):
        df = pd.DataFrame({"lgd": ["Atlantis"], "total_stock": [1]})
        with pytest.raises(NISRAValidationError, match="Unknown Local Government"):
            hb.validate_data(df)

    def test_accepts_valid_frame(self):
        df = pd.DataFrame({"lgd": ["Belfast", "Northern Ireland"], "total_stock": [1.0, 2.0]})
        assert hb.validate_data(df, {"lgd", "total_stock"}) is True

    def test_tolerates_nan_numerics(self):
        df = pd.DataFrame({"lgd": ["Belfast"], "total_stock": [float("nan")]})
        assert hb.validate_data(df) is True


@pytest.mark.network
class TestPublicationDiscovery:
    def test_returns_absolute_spreadsheet_url(self):
        url = hb.get_latest_publication_url()
        assert url.startswith("https://www.communities-ni.gov.uk/")
        assert url.lower().endswith((".ods", ".xlsx"))

    def test_url_mentions_housing_bulletin(self):
        assert "housing-bulletin" in hb.get_latest_publication_url().lower()


@pytest.mark.network
class TestSocialHousingSupply:
    @pytest.fixture(scope="class")
    def starts(self):
        return hb.get_social_housing_starts()

    @pytest.fixture(scope="class")
    def completions(self):
        return hb.get_social_housing_completions()

    def test_starts_columns(self, starts):
        assert set(starts.columns) == {
            "financial_year",
            "period",
            "tenure",
            "housing_type",
            "starts",
        }

    def test_completions_columns(self, completions):
        assert set(completions.columns) == {
            "financial_year",
            "period",
            "tenure",
            "housing_type",
            "completions",
        }

    def test_validates(self, starts, completions):
        assert hb.validate_data(starts, {"financial_year", "starts"}) is True
        assert hb.validate_data(completions, {"financial_year", "completions"}) is True

    def test_tenure_categories(self, starts):
        assert set(starts["tenure"]) == {"Shared", "Self-Contained", "All"}

    def test_housing_types_include_new_build(self, starts):
        assert "New Build" in set(starts["housing_type"])

    def test_periods_are_quarters_or_total(self, starts):
        assert set(starts["period"]) <= _QUARTERS | {"Total"}

    def test_history_reaches_back_to_2010(self, starts):
        assert starts["financial_year"].min() == "2010/11"

    def test_financial_years_well_formed(self, completions):
        assert completions["financial_year"].str.match(r"^\d{4}/\d{2}$").all()

    def test_covers_at_least_fifteen_years(self, completions):
        assert completions["financial_year"].nunique() >= 15

    def test_totals_row_present_for_every_year(self, completions):
        totals = completions[(completions["housing_type"] == "Totals") & (completions["period"] == "Total")]
        assert totals["financial_year"].nunique() == completions["financial_year"].nunique()

    def test_subtotals_sum_to_totals(self, completions):
        """Shared + Self-Contained sub-totals must reconcile with the Totals row."""
        annual = completions[completions["period"] == "Total"]
        subtotals = (
            annual[annual["housing_type"] == "Sub-total"].groupby("financial_year")["completions"].sum().dropna()
        )
        totals = annual[annual["housing_type"] == "Totals"].set_index("financial_year")["completions"].dropna()
        common = subtotals.index.intersection(totals.index)
        assert len(common) >= 15
        pd.testing.assert_series_equal(
            subtotals.loc[common],
            totals.loc[common],
            check_names=False,
        )

    def test_components_sum_to_subtotal(self, completions):
        """Individual housing types must sum to their tenure block sub-total."""
        annual = completions[(completions["period"] == "Total") & (completions["tenure"] != "All")]
        components = (
            annual[~annual["housing_type"].isin({"Sub-total", "Totals"})]
            .groupby(["financial_year", "tenure"])["completions"]
            .sum()
        )
        subtotals = annual[annual["housing_type"] == "Sub-total"].set_index(["financial_year", "tenure"])[
            "completions"
        ]
        common = components.index.intersection(subtotals.dropna().index)
        assert len(common) >= 20
        pd.testing.assert_series_equal(
            components.loc[common],
            subtotals.loc[common],
            check_names=False,
        )

    def test_completions_are_non_trivial(self, completions):
        annual = completions[(completions["period"] == "Total") & (completions["housing_type"] == "Totals")]
        assert annual["completions"].max() > 1000

    def test_current_year_has_quarterly_detail(self, starts):
        quarterly = starts[starts["period"].isin(_QUARTERS)]
        assert not quarterly.empty
        assert quarterly["financial_year"].nunique() == 1


@pytest.mark.network
class TestDwellingStock:
    @pytest.fixture(scope="class")
    def stock(self):
        return hb.get_dwelling_stock_by_tenure()

    def test_columns(self, stock):
        assert set(stock.columns) == {
            "lgd",
            "total_stock",
            "occupied_stock",
            "owner_occupied",
            "private_rented",
            "social_rented",
            "rent_free",
        }

    def test_validates(self, stock):
        assert hb.validate_data(stock, {"lgd", "total_stock"}) is True

    def test_covers_all_districts_plus_ni(self, stock):
        assert set(stock["lgd"]) == _LGDS | {"Northern Ireland"}

    def test_ni_total_matches_district_sum(self, stock):
        indexed = stock.set_index("lgd")
        ni = indexed.loc["Northern Ireland", "total_stock"]
        districts = indexed.drop(index="Northern Ireland")["total_stock"].sum()
        # Source figures are rounded to the nearest 100 before publication.
        assert abs(ni - districts) <= 0.005 * ni

    def test_tenures_sum_to_occupied_stock(self, stock):
        tenures = stock[["owner_occupied", "private_rented", "social_rented", "rent_free"]].sum(axis=1)
        assert ((tenures - stock["occupied_stock"]).abs() <= 0.02 * stock["occupied_stock"]).all()

    def test_occupied_not_greater_than_total(self, stock):
        assert (stock["occupied_stock"] <= stock["total_stock"]).all()

    def test_ni_stock_is_plausible(self, stock):
        ni = stock.set_index("lgd").loc["Northern Ireland", "total_stock"]
        assert 700_000 < ni < 1_000_000

    def test_belfast_is_largest_social_rented(self, stock):
        districts = stock[stock["lgd"] != "Northern Ireland"].set_index("lgd")
        assert districts["social_rented"].idxmax() == "Belfast"


@pytest.mark.network
class TestWaitingListAndAllocations:
    @pytest.fixture(scope="class")
    def trend(self):
        return hb.get_waiting_list_trend()

    @pytest.fixture(scope="class")
    def by_district(self):
        return hb.get_waiting_list_by_district()

    @pytest.fixture(scope="class")
    def allocations(self):
        return hb.get_allocations_by_district()

    def test_trend_columns(self, trend):
        assert set(trend.columns) == {
            "financial_year",
            "quarter",
            "total_applicants",
            "applicants_in_housing_stress",
            "applicants_with_fda_status",
            "allocations_to_applicants",
            "allocations_to_nihe_transfers",
            "allocations_to_housing_association_transfers",
            "total_allocations",
        }

    def test_trend_validates(self, trend):
        assert hb.validate_data(trend, {"financial_year", "quarter", "total_applicants"}) is True

    def test_trend_quarters_complete(self, trend):
        assert set(trend["quarter"]) == _QUARTERS

    def test_trend_starts_2021(self, trend):
        assert trend["financial_year"].min() == "2021/22"

    def test_trend_has_no_duplicate_periods(self, trend):
        assert not trend.duplicated(subset=["financial_year", "quarter"]).any()

    def test_housing_stress_subset_of_applicants(self, trend):
        assert (trend["applicants_in_housing_stress"] <= trend["total_applicants"]).all()

    def test_fda_subset_of_housing_stress(self, trend):
        known = trend.dropna(subset=["applicants_with_fda_status"])
        assert not known.empty
        assert (known["applicants_with_fda_status"] <= known["applicants_in_housing_stress"]).all()

    def test_trend_allocation_components_sum_to_total(self, trend):
        components = trend[
            [
                "allocations_to_applicants",
                "allocations_to_nihe_transfers",
                "allocations_to_housing_association_transfers",
            ]
        ].sum(axis=1)
        pd.testing.assert_series_equal(components, trend["total_allocations"], check_names=False)

    def test_waiting_list_is_substantial(self, trend):
        assert trend["total_applicants"].min() > 20_000

    def test_district_waiting_list_columns(self, by_district):
        assert set(by_district.columns) == {
            "lgd",
            "total_applicants",
            "applicants_in_housing_stress",
            "applicants_with_fda_status",
        }

    def test_district_waiting_list_covers_all_lgds(self, by_district):
        assert set(by_district["lgd"]) == _LGDS | {"Northern Ireland"}

    def test_district_waiting_list_sums_to_ni(self, by_district):
        indexed = by_district.set_index("lgd")
        ni = indexed.loc["Northern Ireland", "total_applicants"]
        assert indexed.drop(index="Northern Ireland")["total_applicants"].sum() == ni

    def test_belfast_has_largest_waiting_list(self, by_district):
        districts = by_district[by_district["lgd"] != "Northern Ireland"].set_index("lgd")
        assert districts["total_applicants"].idxmax() == "Belfast"

    def test_allocations_columns(self, allocations):
        assert set(allocations.columns) == {
            "lgd",
            "allocations_to_applicants",
            "allocations_to_nihe_transfers",
            "allocations_to_housing_association_transfers",
            "total_allocations",
        }

    def test_allocations_validate(self, allocations):
        assert hb.validate_data(allocations, {"lgd", "total_allocations"}) is True

    def test_allocations_components_sum_to_total(self, allocations):
        components = allocations[
            [
                "allocations_to_applicants",
                "allocations_to_nihe_transfers",
                "allocations_to_housing_association_transfers",
            ]
        ].sum(axis=1)
        pd.testing.assert_series_equal(components, allocations["total_allocations"], check_names=False)

    def test_allocations_sum_to_ni(self, allocations):
        indexed = allocations.set_index("lgd")
        ni = indexed.loc["Northern Ireland", "total_allocations"]
        assert indexed.drop(index="Northern Ireland")["total_allocations"].sum() == ni

    def test_waiting_list_exceeds_annual_allocations(self, by_district, allocations):
        """Demand persistently outstrips supply — the defining feature of this series."""
        waiting = by_district.set_index("lgd")["total_applicants"]
        allocated = allocations.set_index("lgd")["total_allocations"]
        assert (waiting > allocated).all()


@pytest.mark.network
class TestNewDwellingSales:
    @pytest.fixture(scope="class")
    def sales(self):
        return hb.get_new_dwelling_sales()

    @pytest.fixture(scope="class")
    def by_district(self):
        return hb.get_new_dwelling_sales_by_district()

    def test_columns(self, sales):
        assert set(sales.columns) == {"financial_year", "period", "sales", "average_price", "status"}

    def test_validates(self, sales):
        assert hb.validate_data(sales, {"financial_year", "sales", "average_price"}) is True

    def test_history_reaches_back_to_2005(self, sales):
        assert sales["financial_year"].min() == "2005/06"

    def test_covers_at_least_twenty_years(self, sales):
        assert sales["financial_year"].nunique() >= 20

    def test_periods_are_quarters_or_total(self, sales):
        assert set(sales["period"]) <= _QUARTERS | {"Total"}

    def test_status_values(self, sales):
        assert set(sales["status"]) <= {"final", "provisional", "revised"}

    def test_no_duplicate_periods(self, sales):
        assert not sales.duplicated(subset=["financial_year", "period"]).any()

    def test_quarterly_sales_sum_to_annual(self, sales):
        quarterly = sales[sales["period"].isin(_QUARTERS)].groupby("financial_year")["sales"].agg(["sum", "count"])
        annual = sales[sales["period"] == "Total"].set_index("financial_year")["sales"]
        complete = quarterly[quarterly["count"] == 4].index.intersection(annual.index)
        assert len(complete) >= 15
        pd.testing.assert_series_equal(
            quarterly.loc[complete, "sum"],
            annual.loc[complete],
            check_names=False,
        )

    def test_prices_are_plausible(self, sales):
        prices = sales["average_price"].dropna()
        assert prices.min() > 50_000
        assert prices.max() < 1_000_000

    def test_financial_crash_visible_in_prices(self, sales):
        """New dwelling prices peaked in 2007/08 and had not recovered by 2015/16."""
        annual = sales[sales["period"] == "Total"].set_index("financial_year")["average_price"]
        assert annual["2007/08"] > annual["2015/16"]

    def test_district_columns(self, by_district):
        assert set(by_district.columns) == {"lgd", "sector", "quarter", "sales", "average_price"}

    def test_district_sectors(self, by_district):
        assert set(by_district["sector"]) == {"Private", "Public", "All"}

    def test_district_quarter_is_a_quarter(self, by_district):
        assert set(by_district["quarter"]) <= _QUARTERS

    def test_district_covers_all_lgds(self, by_district):
        assert set(by_district["lgd"]) == _LGDS | {"Northern Ireland"}

    def test_district_sectors_sum_to_all(self, by_district):
        wide = by_district.pivot(index="lgd", columns="sector", values="sales")
        pd.testing.assert_series_equal(
            wide["Private"] + wide["Public"],
            wide["All"],
            check_names=False,
        )

    def test_district_sales_sum_to_ni(self, by_district):
        all_sector = by_district[by_district["sector"] == "All"].set_index("lgd")["sales"]
        ni = all_sector.loc["Northern Ireland"]
        assert all_sector.drop(index="Northern Ireland").sum() == ni

    def test_district_prices_in_pounds(self, by_district):
        prices = by_district["average_price"].dropna()
        assert not prices.empty
        assert prices.min() > 50_000


@pytest.mark.network
class TestAffordableWarmth:
    @pytest.fixture(scope="class")
    def warmth(self):
        return hb.get_affordable_warmth()

    def test_columns(self, warmth):
        assert set(warmth.columns) == {
            "financial_year",
            "quarter",
            "approvals",
            "approvals_value",
            "homes_improved",
            "measures_installed",
            "annual_spend_to_date",
        }

    def test_validates(self, warmth):
        assert hb.validate_data(warmth, {"financial_year", "quarter", "approvals"}) is True

    def test_quarters_complete(self, warmth):
        assert set(warmth["quarter"]) == _QUARTERS

    def test_no_duplicate_periods(self, warmth):
        assert not warmth.duplicated(subset=["financial_year", "quarter"]).any()

    def test_covers_multiple_years(self, warmth):
        assert warmth["financial_year"].nunique() >= 2

    def test_measures_exceed_homes(self, warmth):
        """Each improved home typically receives more than one measure."""
        known = warmth.dropna(subset=["homes_improved", "measures_installed"])
        assert (known["measures_installed"] >= known["homes_improved"]).all()

    def test_annual_spend_is_cumulative_within_year(self, warmth):
        order = {q: i for i, q in enumerate(["Apr-Jun", "Jul-Sep", "Oct-Dec", "Jan-Mar"])}
        ordered = warmth.assign(_q=warmth["quarter"].map(order)).sort_values(["financial_year", "_q"])
        for _, group in ordered.groupby("financial_year"):
            spend = group["annual_spend_to_date"].dropna()
            assert spend.is_monotonic_increasing

    def test_approval_value_per_approval_is_plausible(self, warmth):
        known = warmth[warmth["approvals"] > 0]
        per_approval = known["approvals_value"] / known["approvals"]
        assert per_approval.between(1_000, 20_000).all()
