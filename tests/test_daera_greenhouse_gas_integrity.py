"""Integrity tests for the DAERA NI Greenhouse Gas Inventory module.

Validates real data quality, structure, and consistency using live downloads
from the DAERA article and bulletin pages.  All tests use real data (no mocks)
with ``scope="class"`` fixtures to minimise network calls.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pandas as pd
import pytest

from bolster.data_sources.daera_greenhouse_gas import (
    DAERADataNotFoundError,
    DAERAValidationError,
    get_annual_totals,
    get_available_years,
    get_bulletin_pages,
    get_emissions_by_gas_and_sector,
    get_emissions_by_sector,
    get_gas_changes,
    get_inventory_revisions,
    get_latest_year,
    get_national_communication_sectors,
    get_pfg_progress,
    get_sector_changes,
    get_tes_categories,
    get_uk_emissions_by_gas_and_sector,
    get_uk_emissions_by_sector,
    get_workbook_url,
    validate_data,
)

NI_SECTORS = {
    "Agriculture",
    "Buildings and product uses",
    "Domestic transport",
    "Electricity supply",
    "Fuel supply",
    "Industry",
    "LULUCF",
    "Waste",
}


# ── Source discovery ─────────────────────────────────────────────────────────


@pytest.mark.network
class TestSourceDiscovery:
    """Live discovery of bulletin pages and the data workbook."""

    @pytest.fixture(scope="class")
    def pages(self) -> dict[int, str]:
        return get_bulletin_pages()

    def test_multiple_editions_published(self, pages: dict[int, str]):
        assert len(pages) >= 10

    def test_keys_are_plausible_inventory_years(self, pages: dict[int, str]):
        assert all(2005 <= year <= 2100 for year in pages)

    def test_urls_are_daera_domain(self, pages: dict[int, str]):
        assert all("daera-ni.gov.uk" in url for url in pages.values())

    def test_pages_sorted_ascending(self, pages: dict[int, str]):
        assert list(pages) == sorted(pages)

    def test_workbook_url_is_spreadsheet(self):
        url = get_workbook_url()
        host = urlparse(url).hostname
        assert host is not None
        assert host == "daera-ni.gov.uk" or host.endswith(".daera-ni.gov.uk")
        assert url.lower().endswith(".xlsx")

    def test_unknown_edition_raises(self):
        with pytest.raises(DAERADataNotFoundError):
            get_workbook_url(year=1066)


# ── Time series coverage ─────────────────────────────────────────────────────


@pytest.mark.network
class TestTimeSeriesCoverage:
    """The published NI time series and its coverage."""

    @pytest.fixture(scope="class")
    def years(self) -> list[int]:
        return get_available_years()

    def test_starts_at_1990(self, years: list[int]):
        assert years[0] == 1990

    def test_years_sorted_and_unique(self, years: list[int]):
        assert years == sorted(set(years))

    def test_latest_year_is_recent(self, years: list[int]):
        assert years[-1] >= 2022

    def test_get_latest_year_matches_series(self, years: list[int]):
        assert get_latest_year() == years[-1]

    def test_recent_years_are_contiguous(self, years: list[int]):
        recent = [year for year in years if year >= 1998]
        assert recent == list(range(1998, recent[-1] + 1))


# ── NI emissions by sector (Table 1c) ────────────────────────────────────────


@pytest.mark.network
class TestEmissionsBySector:
    """Full NI time series broken down by sector."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_emissions_by_sector()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["sector", "year", "emissions_ktco2e"]

    def test_not_empty(self, df: pd.DataFrame):
        assert len(df) > 100

    def test_all_ni_sectors_present(self, df: pd.DataFrame):
        assert NI_SECTORS.issubset(set(df["sector"]))

    def test_total_row_present(self, df: pd.DataFrame):
        assert "Total" in set(df["sector"])

    def test_years_are_integers(self, df: pd.DataFrame):
        assert pd.api.types.is_integer_dtype(df["year"])

    def test_emissions_numeric_and_finite(self, df: pd.DataFrame):
        assert pd.api.types.is_numeric_dtype(df["emissions_ktco2e"])
        assert df["emissions_ktco2e"].notna().all()

    def test_no_duplicate_sector_years(self, df: pd.DataFrame):
        assert not df.duplicated(subset=["sector", "year"]).any()

    def test_sector_total_matches_component_sum(self, df: pd.DataFrame):
        latest = df[df["year"] == df["year"].max()]
        components = latest[latest["sector"] != "Total"]["emissions_ktco2e"].sum()
        total = latest[latest["sector"] == "Total"]["emissions_ktco2e"].iloc[0]
        assert total == pytest.approx(components, rel=0.001)

    def test_emissions_have_fallen_since_1990(self, df: pd.DataFrame):
        totals = df[df["sector"] == "Total"].set_index("year")["emissions_ktco2e"]
        assert totals.loc[totals.index.max()] < totals.loc[1990]

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert validate_data(df, "emissions_ktco2e") is True


# ── Annual totals convenience view ───────────────────────────────────────────


@pytest.mark.network
class TestAnnualTotals:
    """The ``get_annual_totals`` headline series."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_annual_totals()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["year", "emissions_ktco2e"]

    def test_one_row_per_year(self, df: pd.DataFrame):
        assert not df["year"].duplicated().any()

    def test_sorted_by_year(self, df: pd.DataFrame):
        assert df["year"].is_monotonic_increasing

    def test_totals_positive(self, df: pd.DataFrame):
        assert (df["emissions_ktco2e"] > 0).all()

    def test_plausible_magnitude(self, df: pd.DataFrame):
        # NI total emissions sit in the high teens to high twenties MtCO2e.
        assert df["emissions_ktco2e"].between(10_000, 40_000).all()


# ── Change tables (Tables 1a/1b, 2a/2b) ──────────────────────────────────────


@pytest.mark.network
class TestChangeTables:
    """Sector and gas change summaries in MtCO2e."""

    @pytest.fixture(scope="class")
    def sectors(self) -> pd.DataFrame:
        return get_sector_changes()

    @pytest.fixture(scope="class")
    def gases(self) -> pd.DataFrame:
        return get_gas_changes()

    def test_sector_columns(self, sectors: pd.DataFrame):
        for column in (
            "sector",
            "base_year_mtco2e",
            "latest_year_mtco2e",
            "change_from_base_mtco2e",
        ):
            assert column in sectors.columns

    def test_sector_rows_cover_all_sectors(self, sectors: pd.DataFrame):
        assert NI_SECTORS.issubset(set(sectors["sector"]))

    def test_sector_change_is_consistent(self, sectors: pd.DataFrame):
        delta = sectors["latest_year_mtco2e"] - sectors["base_year_mtco2e"]
        assert delta.values == pytest.approx(sectors["change_from_base_mtco2e"].values, abs=0.01)

    def test_gas_rows(self, gases: pd.DataFrame):
        assert {"CO2", "CH4", "N2O", "Total"}.issubset(set(gases["gas"]))

    def test_gas_subscripts_normalised(self, gases: pd.DataFrame):
        assert not gases["gas"].str.contains("₂").any()

    def test_gas_total_matches_components(self, gases: pd.DataFrame):
        components = gases[gases["gas"] != "Total"]["latest_year_mtco2e"].sum()
        total = gases[gases["gas"] == "Total"]["latest_year_mtco2e"].iloc[0]
        assert total == pytest.approx(components, rel=0.001)

    def test_gas_change_is_consistent(self, gases: pd.DataFrame):
        delta = gases["latest_year_mtco2e"] - gases["base_year_mtco2e"]
        assert delta.values == pytest.approx(gases["change_from_base_mtco2e"].values, abs=0.01)


# ── Gas within sector (Table 3) ──────────────────────────────────────────────


@pytest.mark.network
class TestEmissionsByGasAndSector:
    """NI emissions cross-tabulated by gas and sector."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_emissions_by_gas_and_sector()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["sector", "gas", "emissions_mtco2e"]

    def test_gases_present(self, df: pd.DataFrame):
        assert {"CO2", "CH4", "N2O", "HFCs", "PFCs", "SF6"}.issubset(set(df["gas"]))

    def test_sectors_present(self, df: pd.DataFrame):
        assert NI_SECTORS.issubset(set(df["sector"]))

    def test_no_duplicate_pairs(self, df: pd.DataFrame):
        assert not df.duplicated(subset=["sector", "gas"]).any()

    def test_agriculture_dominated_by_methane(self, df: pd.DataFrame):
        agriculture = df[df["sector"] == "Agriculture"].set_index("gas")["emissions_mtco2e"]
        assert agriculture["CH4"] > agriculture["CO2"]

    def test_gas_column_totals_match_total_row(self, df: pd.DataFrame):
        pivot = df.pivot(index="sector", columns="gas", values="emissions_mtco2e")
        components = pivot.drop(index="Total").sum()
        assert pivot.loc["Total"].values == pytest.approx(components[pivot.columns].values, abs=0.01)


# ── Inventory revisions (Table 4) ────────────────────────────────────────────


@pytest.mark.network
class TestInventoryRevisions:
    """Restatements between consecutive inventory editions."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_inventory_revisions()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == [
            "sector",
            "period",
            "previous_edition_mtco2e",
            "current_edition_mtco2e",
            "revision_mtco2e",
        ]

    def test_base_year_period_present(self, df: pd.DataFrame):
        assert "Base Year" in set(df["period"])

    def test_two_periods_reported(self, df: pd.DataFrame):
        assert df["period"].nunique() == 2

    def test_revision_matches_difference(self, df: pd.DataFrame):
        delta = df["current_edition_mtco2e"] - df["previous_edition_mtco2e"]
        assert delta.values == pytest.approx(df["revision_mtco2e"].values, abs=0.001)

    def test_revisions_are_small(self, df: pd.DataFrame):
        # Methodological restatements should not move totals by whole megatonnes.
        assert df["revision_mtco2e"].abs().max() < 5


# ── Programme for Government (Table 5) ───────────────────────────────────────


@pytest.mark.network
class TestPfGProgress:
    """Progress against the Programme for Government emissions measure."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_pfg_progress()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["year", "emissions_mtco2e"]

    def test_includes_1990_baseline(self, df: pd.DataFrame):
        assert 1990 in set(df["year"])

    def test_values_in_megatonnes(self, df: pd.DataFrame):
        assert df["emissions_mtco2e"].between(5, 50).all()

    def test_latest_below_baseline(self, df: pd.DataFrame):
        indexed = df.set_index("year")["emissions_mtco2e"]
        assert indexed.loc[indexed.index.max()] < indexed.loc[1990]


# ── UK comparison tables (Tables 6, 7) ───────────────────────────────────────


@pytest.mark.network
class TestUKComparison:
    """UK-wide figures published alongside the NI inventory."""

    @pytest.fixture(scope="class")
    def by_gas(self) -> pd.DataFrame:
        return get_uk_emissions_by_gas_and_sector()

    @pytest.fixture(scope="class")
    def by_sector(self) -> pd.DataFrame:
        return get_uk_emissions_by_sector()

    def test_gas_columns(self, by_gas: pd.DataFrame):
        assert list(by_gas.columns) == ["sector", "gas", "emissions_ktco2e"]

    def test_percentage_row_excluded(self, by_gas: pd.DataFrame):
        assert "% of all gases" not in set(by_gas["sector"])

    def test_lulucf_co2_is_a_net_sink(self, by_gas: pd.DataFrame):
        lulucf = by_gas[(by_gas["sector"] == "LULUCF") & (by_gas["gas"] == "CO2")]
        assert lulucf["emissions_ktco2e"].iloc[0] < 0

    def test_sector_columns(self, by_sector: pd.DataFrame):
        assert list(by_sector.columns) == ["sector", "year", "emissions_ktco2e"]

    def test_uk_sectors_match_ni_sectors(self, by_sector: pd.DataFrame):
        assert NI_SECTORS.issubset(set(by_sector["sector"]))

    def test_uk_totals_far_exceed_ni(self, by_sector: pd.DataFrame):
        latest = by_sector["year"].max()
        uk_total = by_sector[(by_sector["sector"] == "Total") & (by_sector["year"] == latest)]
        assert uk_total["emissions_ktco2e"].iloc[0] > 200_000


# ── Alternative classifications (Tables 8, 9) ────────────────────────────────


@pytest.mark.network
class TestAlternativeClassifications:
    """National Communication and Territorial Emissions Statistics views."""

    @pytest.fixture(scope="class")
    def nc(self) -> pd.DataFrame:
        return get_national_communication_sectors()

    @pytest.fixture(scope="class")
    def tes(self) -> pd.DataFrame:
        return get_tes_categories()

    def test_nc_columns(self, nc: pd.DataFrame):
        assert list(nc.columns) == ["sector", "year", "emissions_ktco2e"]

    def test_nc_sectors(self, nc: pd.DataFrame):
        assert {"Agriculture", "Transport", "Waste Management", "Total"}.issubset(set(nc["sector"]))

    def test_nc_no_duplicates(self, nc: pd.DataFrame):
        assert not nc.duplicated(subset=["sector", "year"]).any()

    def test_tes_columns(self, tes: pd.DataFrame):
        assert list(tes.columns) == ["sector", "subsector", "category", "year", "emissions_ktco2e"]

    def test_tes_is_granular(self, tes: pd.DataFrame):
        assert tes["category"].nunique() > 50

    def test_tes_has_grand_total(self, tes: pd.DataFrame):
        assert "Grand Total" in set(tes["sector"])

    def test_tes_years_align_with_series(self, tes: pd.DataFrame):
        assert set(tes["year"]).issubset(set(get_available_years()))


# ── Validation helper ────────────────────────────────────────────────────────


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_accepts_negative_values(self):
        df = pd.DataFrame({"sector": ["LULUCF"], "emissions_ktco2e": [-1234.5]})
        assert validate_data(df, "emissions_ktco2e") is True

    def test_rejects_empty_frame(self):
        with pytest.raises(DAERAValidationError):
            validate_data(pd.DataFrame(), "emissions_ktco2e")

    def test_rejects_missing_column(self):
        with pytest.raises(DAERAValidationError):
            validate_data(pd.DataFrame({"sector": ["Waste"]}), "emissions_ktco2e")

    def test_rejects_implausible_year(self):
        df = pd.DataFrame({"year": [1066], "emissions_ktco2e": [1.0]})
        with pytest.raises(DAERAValidationError):
            validate_data(df)

    def test_infers_emissions_column(self):
        df = pd.DataFrame({"sector": ["Waste"], "emissions_mtco2e": [0.7]})
        assert validate_data(df) is True


@pytest.mark.network
class TestCrossValidation:
    """Reconcile figures that appear in more than one workbook table."""

    @pytest.fixture(scope="class")
    def latest(self):
        return int(get_emissions_by_sector()["year"].max())

    @pytest.fixture(scope="class")
    def headline_ktco2e(self, latest):
        sectors = get_emissions_by_sector()
        row = sectors[(sectors["sector"] == "Total") & (sectors["year"] == latest)]
        return float(row["emissions_ktco2e"].iloc[0])

    def test_national_communication_total_matches_headline(self, latest, headline_ktco2e):
        """The alternative NC classification re-slices the same inventory."""
        nc = get_national_communication_sectors()
        row = nc[(nc["sector"] == "Total") & (nc["year"] == latest)]
        assert float(row["emissions_ktco2e"].iloc[0]) == pytest.approx(headline_ktco2e, rel=1e-6)

    def test_tes_grand_total_matches_headline(self, latest, headline_ktco2e):
        tes = get_tes_categories()
        row = tes[(tes["sector"] == "Grand Total") & (tes["year"] == latest)]
        assert float(row["emissions_ktco2e"].iloc[0]) == pytest.approx(headline_ktco2e, rel=1e-6)

    def test_pfg_progress_matches_headline(self, latest, headline_ktco2e):
        """PfG progress is the headline series expressed in MtCO2e."""
        pfg = get_pfg_progress()
        row = pfg[pfg["year"] == latest]
        assert float(row["emissions_mtco2e"].iloc[0]) == pytest.approx(headline_ktco2e / 1000, rel=1e-6)

    def test_gas_changes_total_matches_headline(self, headline_ktco2e):
        changes = get_gas_changes().set_index("gas")["latest_year_mtco2e"]
        assert float(changes["Total"]) == pytest.approx(headline_ktco2e / 1000, rel=1e-6)

    def test_gas_and_sector_totals_match_gas_changes(self):
        """Table of gases by sector must agree with the gas summary table."""
        by_gas = get_emissions_by_gas_and_sector()
        totals = by_gas[by_gas["sector"] == "Total"].set_index("gas")["emissions_mtco2e"]
        changes = get_gas_changes().set_index("gas")["latest_year_mtco2e"]

        for gas in ("CO2", "CH4", "N2O"):
            assert float(totals[gas]) == pytest.approx(float(changes[gas]), abs=0.01)

        f_gases = float(totals[["HFCs", "PFCs", "SF6", "NF3"]].sum())
        assert f_gases == pytest.approx(float(changes["F-gases"]), abs=0.01)

    def test_sector_changes_match_headline_series(self, latest, headline_ktco2e):
        changes = get_sector_changes().set_index("sector")["latest_year_mtco2e"]
        assert float(changes["Total"]) == pytest.approx(headline_ktco2e / 1000, rel=1e-6)

        sectors = get_emissions_by_sector()
        current = sectors[sectors["year"] == latest].set_index("sector")["emissions_ktco2e"]
        for sector in NI_SECTORS:
            assert float(changes[sector]) == pytest.approx(float(current[sector]) / 1000, abs=0.01), (
                f"{sector} disagrees between the change table and the time series"
            )

    def test_revisions_current_edition_matches_series(self):
        """Revision table's 'current edition' column is this year's inventory."""
        revisions = get_inventory_revisions()
        sectors = get_emissions_by_sector()

        dated = revisions[revisions["period"].str.fullmatch(r"\d{4}")]
        assert not dated.empty, "Expected at least one year-keyed revision period"

        for period, group in dated.groupby("period"):
            year = int(period)
            row = group[group["sector"] == "Total"]
            series = sectors[(sectors["sector"] == "Total") & (sectors["year"] == year)]
            assert float(row["current_edition_mtco2e"].iloc[0]) == pytest.approx(
                float(series["emissions_ktco2e"].iloc[0]) / 1000, abs=0.01
            )

    def test_uk_gas_and_sector_totals_match_uk_series(self, latest):
        """UK comparison tables must reconcile with each other."""
        uk_sectors = get_uk_emissions_by_sector()
        row = uk_sectors[(uk_sectors["sector"] == "Total") & (uk_sectors["year"] == latest)]
        uk_total = float(row["emissions_ktco2e"].iloc[0])

        by_gas = get_uk_emissions_by_gas_and_sector()
        gas_total = float(by_gas[by_gas["sector"] == "Total"]["emissions_ktco2e"].sum())
        assert gas_total == pytest.approx(uk_total, rel=1e-6)

    def test_ni_share_of_uk_is_plausible(self, latest, headline_ktco2e):
        """NI is roughly 3% of UK population and a few percent of emissions."""
        uk_sectors = get_uk_emissions_by_sector()
        row = uk_sectors[(uk_sectors["sector"] == "Total") & (uk_sectors["year"] == latest)]
        share = headline_ktco2e / float(row["emissions_ktco2e"].iloc[0])
        assert 0.02 < share < 0.10, f"NI share of UK emissions implausible: {share:.3%}"

    def test_annual_totals_match_sector_totals(self):
        """The convenience accessor must not diverge from the source table."""
        totals = get_annual_totals().set_index("year")["emissions_ktco2e"]
        sectors = get_emissions_by_sector()
        source = sectors[sectors["sector"] == "Total"].set_index("year")["emissions_ktco2e"]
        assert totals.index.tolist() == source.index.tolist()
        assert bool((totals - source).abs().lt(1e-6).all())
