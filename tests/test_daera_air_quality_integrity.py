"""Integrity tests for the DAERA NI Air Quality Statistics module.

Validates real data quality, structure, and consistency using live downloads
from the DAERA article and publication pages. All tests use real data (no
mocks) with ``scope="class"`` fixtures to minimise network calls.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pandas as pd
import pytest

from bolster.data_sources.daera_air_quality import (
    DAERADataNotFoundError,
    DAERAValidationError,
    get_all_pollutants,
    get_no2,
    get_pm10,
    get_pm25,
    get_report_pages,
    get_workbook_url,
    validate_data,
)

# ── Source discovery ─────────────────────────────────────────────────────────


@pytest.mark.network
class TestSourceDiscovery:
    """Live discovery of publication pages and the data-tables workbook."""

    @pytest.fixture(scope="class")
    def pages(self) -> dict[int, str]:
        return get_report_pages()

    def test_multiple_editions_published(self, pages: dict[int, str]):
        assert len(pages) >= 10

    def test_keys_are_plausible_report_years(self, pages: dict[int, str]):
        assert all(2005 <= year <= 2100 for year in pages)

    def test_urls_are_daera_domain(self, pages: dict[int, str]):
        for url in pages.values():
            host = urlparse(url).hostname
            assert host is not None
            assert host == "daera-ni.gov.uk" or host.endswith(".daera-ni.gov.uk")

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


# ── NO2 (Table 3.1a) ─────────────────────────────────────────────────────────


@pytest.mark.network
class TestNO2:
    """Annual mean nitrogen dioxide concentrations."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_no2()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["site_type", "year", "no2_ugm3"]

    def test_not_empty(self, df: pd.DataFrame):
        assert len(df) > 10

    def test_site_types_present(self, df: pd.DataFrame):
        assert {"Urban background sites mean", "Urban traffic sites mean"}.issubset(set(df["site_type"]))

    def test_starts_at_2011(self, df: pd.DataFrame):
        assert df["year"].min() == 2011

    def test_years_are_integers(self, df: pd.DataFrame):
        assert pd.api.types.is_integer_dtype(df["year"])

    def test_no_duplicate_site_years(self, df: pd.DataFrame):
        assert not df.duplicated(subset=["site_type", "year"]).any()

    def test_traffic_sites_exceed_background(self, df: pd.DataFrame):
        # Roadside NO2 is consistently higher than urban background across
        # the whole published series -- traffic is the dominant NO2 source.
        pivot = df.pivot(index="year", columns="site_type", values="no2_ugm3")
        assert (pivot["Urban traffic sites mean"] > pivot["Urban background sites mean"]).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert validate_data(df, "no2_ugm3") is True


# ── PM10 (Table 3.2) ─────────────────────────────────────────────────────────


@pytest.mark.network
class TestPM10:
    """Annual mean PM10 particulate matter concentrations."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_pm10()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["site_type", "year", "pm10_ugm3"]

    def test_site_types_present(self, df: pd.DataFrame):
        assert {"Urban sites mean", "Rural (Lough Navar)"}.issubset(set(df["site_type"]))

    def test_starts_at_2009(self, df: pd.DataFrame):
        assert df["year"].min() == 2009

    def test_no_duplicate_site_years(self, df: pd.DataFrame):
        assert not df.duplicated(subset=["site_type", "year"]).any()

    def test_urban_exceeds_rural(self, df: pd.DataFrame):
        pivot = df.pivot(index="year", columns="site_type", values="pm10_ugm3").dropna()
        assert (pivot["Urban sites mean"] > pivot["Rural (Lough Navar)"]).all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert validate_data(df, "pm10_ugm3") is True


# ── PM2.5 (Table 3.3) ────────────────────────────────────────────────────────


@pytest.mark.network
class TestPM25:
    """Annual mean PM2.5 fine particulate matter concentrations."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_pm25()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["site_type", "year", "pm25_ugm3"]

    def test_starts_at_2016(self, df: pd.DataFrame):
        assert df["year"].min() == 2016

    def test_site_count_row_excluded(self, df: pd.DataFrame):
        assert "Number of sites in urban calculations" not in set(df["site_type"])

    def test_only_urban_and_rural_site_types(self, df: pd.DataFrame):
        assert set(df["site_type"]) == {"Urban sites mean", "Rural (Lough Navar)"}

    def test_rural_monitoring_starts_later(self, df: pd.DataFrame):
        # Rural (Lough Navar) PM2.5 monitoring began in 2018, two years after
        # the urban series -- earlier rural years should be null, not absent.
        rural = df[df["site_type"] == "Rural (Lough Navar)"]
        assert rural[rural["year"] < 2019]["pm25_ugm3"].isna().all()
        assert rural[rural["year"] >= 2019]["pm25_ugm3"].notna().all()

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert validate_data(df, "pm25_ugm3") is True


# ── Combined view ────────────────────────────────────────────────────────────


@pytest.mark.network
class TestAllPollutants:
    """The ``get_all_pollutants`` combined tidy view."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_all_pollutants()

    def test_expected_columns(self, df: pd.DataFrame):
        assert list(df.columns) == ["pollutant", "site_type", "year", "value_ugm3"]

    def test_all_three_pollutants_present(self, df: pd.DataFrame):
        assert set(df["pollutant"]) == {"NO2", "PM10", "PM2.5"}

    def test_row_count_matches_components(self, df: pd.DataFrame):
        assert len(df) == len(get_no2()) + len(get_pm10()) + len(get_pm25())

    def test_no2_subset_matches_dedicated_accessor(self, df: pd.DataFrame):
        combined = df[df["pollutant"] == "NO2"].drop(columns="pollutant").reset_index(drop=True)
        dedicated = get_no2().rename(columns={"no2_ugm3": "value_ugm3"})
        pd.testing.assert_frame_equal(combined, dedicated)

    def test_validate_data_passes(self, df: pd.DataFrame):
        assert validate_data(df, "value_ugm3") is True


# ── Validation helper ────────────────────────────────────────────────────────


class TestValidateData:
    """Behaviour of the module's validation helper (no network required)."""

    def test_rejects_empty_frame(self):
        with pytest.raises(DAERAValidationError):
            validate_data(pd.DataFrame(), "no2_ugm3")

    def test_rejects_missing_column(self):
        with pytest.raises(DAERAValidationError):
            validate_data(pd.DataFrame({"site_type": ["Urban sites mean"]}), "no2_ugm3")

    def test_rejects_all_null_column(self):
        df = pd.DataFrame({"no2_ugm3": [None, None]})
        with pytest.raises(DAERAValidationError):
            validate_data(df, "no2_ugm3")

    def test_rejects_negative_concentration(self):
        df = pd.DataFrame({"no2_ugm3": [-1.0]})
        with pytest.raises(DAERAValidationError):
            validate_data(df, "no2_ugm3")

    def test_rejects_implausible_year(self):
        df = pd.DataFrame({"year": [1066], "no2_ugm3": [10.0]})
        with pytest.raises(DAERAValidationError):
            validate_data(df)

    def test_infers_concentration_column(self):
        df = pd.DataFrame({"site_type": ["Urban sites mean"], "pm10_ugm3": [15.0]})
        assert validate_data(df) is True
