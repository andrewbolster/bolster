"""Integrity tests for DAERA NI LAC Municipal Waste Statistics module.

Validates real data quality, structure, and consistency using live
downloads from the DAERA publications page.  All tests use real data
(no mocks) with ``scope="class"`` fixtures to minimise network calls.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.daera_waste import (
    DAERAValidationError,
    NI_COUNCILS_POST_2015,
    get_latest_waste_statistics,
    get_waste_publication_url,
    validate_waste_data,
)


# ── Publication discovery ────────────────────────────────────────────────────


class TestPublicationDiscovery:
    """Live discovery of the DAERA waste statistics file URL."""

    @pytest.fixture(scope="class")
    def csv_url(self) -> str:
        return get_waste_publication_url(prefer="csv")

    def test_csv_url_is_string(self, csv_url: str):
        assert isinstance(csv_url, str)
        assert len(csv_url) > 0

    def test_csv_url_is_daera_domain(self, csv_url: str):
        assert "daera-ni.gov.uk" in csv_url

    def test_csv_url_ends_with_csv(self, csv_url: str):
        assert csv_url.lower().endswith(".csv")

    def test_csv_url_contains_lac_waste(self, csv_url: str):
        assert "lac-municipal-waste" in csv_url.lower()

    def test_xlsx_url_discoverable(self):
        url = get_waste_publication_url(prefer="xlsx")
        assert "daera-ni.gov.uk" in url
        assert url.lower().endswith(".xlsx")


# ── Data integrity ───────────────────────────────────────────────────────────


class TestWasteDataIntegrity:
    """Integrity tests for the parsed waste statistics DataFrame."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return get_latest_waste_statistics(force_refresh=False)

    def test_returns_dataframe(self, df):
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_required_columns_present(self, df):
        required = {
            "financial_year",
            "quarter_code",
            "quarter_name",
            "area_code",
            "council_area",
            "waste_management_group",
            "data_status",
            "lac_waste_arisings_tonnes",
            "hh_waste_arisings_tonnes",
        }
        assert required.issubset(set(df.columns)), (
            f"Missing: {required - set(df.columns)}"
        )

    def test_no_negative_lac_arisings(self, df):
        vals = df["lac_waste_arisings_tonnes"].dropna()
        assert (vals >= 0).all(), "Negative values in lac_waste_arisings_tonnes"

    def test_no_negative_hh_arisings(self, df):
        vals = df["hh_waste_arisings_tonnes"].dropna()
        assert (vals >= 0).all(), "Negative values in hh_waste_arisings_tonnes"

    def test_ni_councils_present(self, df):
        councils = set(df["council_area"].unique())
        missing = NI_COUNCILS_POST_2015 - councils
        assert not missing, f"Missing NI councils: {missing}"

    def test_northern_ireland_aggregate_present(self, df):
        assert "Northern Ireland" in df["council_area"].values

    def test_year_range_starts_from_2006_07(self, df):
        assert "2006/07" in df["financial_year"].values

    def test_year_range_includes_recent_data(self, df):
        # Data should include at least up to 2023/24
        years = df["financial_year_start"].dropna()
        assert years.max() >= 2023

    def test_minimum_row_count(self, df):
        # 37 area names * 4 quarters * ~19 years = well over 1,000 rows
        assert len(df) >= 1000

    def test_quarter_codes_valid(self, df):
        valid = {"Q1", "Q2", "Q3", "Q4"}
        assert set(df["quarter_code"].unique()).issubset(valid)

    def test_quarter_names_valid(self, df):
        valid = {"April to June", "July to September", "October to December", "January to March"}
        assert set(df["quarter_name"].unique()).issubset(valid)

    def test_data_status_values(self, df):
        valid = {"Finalised", "Provisional"}
        assert set(df["data_status"].dropna().unique()).issubset(valid)

    def test_lac_recycling_rate_in_range(self, df):
        if "lac_dry_recycling_composting_rate_pct" in df.columns:
            rates = df["lac_dry_recycling_composting_rate_pct"].dropna()
            assert (rates >= 0).all()
            assert (rates <= 100).all()

    def test_hh_landfill_rate_in_range(self, df):
        if "hh_landfill_rate_pct" in df.columns:
            rates = df["hh_landfill_rate_pct"].dropna()
            assert (rates >= 0).all()
            assert (rates <= 100).all()

    def test_financial_year_start_column_present(self, df):
        assert "financial_year_start" in df.columns

    def test_financial_year_start_numeric(self, df):
        starts = df["financial_year_start"].dropna()
        assert (starts >= 2006).all()
        assert (starts <= 2030).all()

    def test_hh_arisings_le_lac_arisings(self, df):
        # Household waste is a subset of LAC waste
        sub = df.dropna(subset=["hh_waste_arisings_tonnes", "lac_waste_arisings_tonnes"])
        # Allow a 1% tolerance for rounding/categorisation differences
        sub = sub[sub["lac_waste_arisings_tonnes"] > 0]
        ratio = sub["hh_waste_arisings_tonnes"] / sub["lac_waste_arisings_tonnes"]
        assert (ratio <= 1.05).all(), "Household arisings exceed LAC arisings (>5% tolerance)"

    def test_validate_passes_on_real_data(self, df):
        assert validate_waste_data(df) is True


# ── Validation edge cases (no network calls) ─────────────────────────────────


class TestValidationEdgeCases:
    """Unit tests for validate_waste_data() edge cases — no network calls."""

    def _make_valid_df(self) -> pd.DataFrame:
        """Build a minimal valid DataFrame (11 councils, 5 financial years)."""
        rows = []
        councils = list(NI_COUNCILS_POST_2015) + ["Northern Ireland"]
        for year_start in range(2006, 2011):  # 5 years
            fy = f"{year_start}/{str(year_start + 1)[-2:]}"
            for qcode in ("Q1", "Q2", "Q3", "Q4"):
                qnames = {
                    "Q1": "April to June",
                    "Q2": "July to September",
                    "Q3": "October to December",
                    "Q4": "January to March",
                }
                for council in councils:
                    rows.append(
                        {
                            "financial_year": fy,
                            "financial_year_start": year_start,
                            "quarter_code": qcode,
                            "quarter_name": qnames[qcode],
                            "area_code": "NI",
                            "council_area": council,
                            "waste_management_group": "-",
                            "data_status": "Finalised",
                            "lac_waste_arisings_tonnes": 50_000,
                            "hh_waste_arisings_tonnes": 45_000,
                        }
                    )
        return pd.DataFrame(rows)

    def test_validate_empty_dataframe(self):
        with pytest.raises(DAERAValidationError, match="empty"):
            validate_waste_data(pd.DataFrame())

    def test_validate_none(self):
        with pytest.raises(DAERAValidationError, match="empty"):
            validate_waste_data(None)  # type: ignore[arg-type]

    def test_validate_missing_columns(self):
        df = self._make_valid_df().drop(columns=["lac_waste_arisings_tonnes"])
        with pytest.raises(DAERAValidationError, match="Missing required columns"):
            validate_waste_data(df)

    def test_validate_negative_lac_arisings(self):
        df = self._make_valid_df()
        df.loc[0, "lac_waste_arisings_tonnes"] = -1
        with pytest.raises(DAERAValidationError, match="Negative"):
            validate_waste_data(df)

    def test_validate_negative_hh_arisings(self):
        df = self._make_valid_df()
        df.loc[0, "hh_waste_arisings_tonnes"] = -100
        with pytest.raises(DAERAValidationError, match="Negative"):
            validate_waste_data(df)

    def test_validate_missing_council(self):
        df = self._make_valid_df()
        # Remove all rows for Belfast
        df = df[df["council_area"] != "Belfast"].copy()
        with pytest.raises(DAERAValidationError, match="Missing expected NI councils"):
            validate_waste_data(df)

    def test_validate_too_few_years(self):
        df = self._make_valid_df()
        # Truncate to only 1 financial year
        df = df[df["financial_year"] == "2006/07"].copy()
        with pytest.raises(DAERAValidationError, match="Too few financial years"):
            validate_waste_data(df)

    def test_validate_passes_on_synthetic_valid_data(self):
        assert validate_waste_data(self._make_valid_df()) is True
