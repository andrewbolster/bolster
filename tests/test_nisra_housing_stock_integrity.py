"""Integrity tests for NISRA Housing Stock module.

Validates real data quality, structure, and consistency for the NI Housing
Stock statistics published by the Department of Finance / Land and Property
Services (LPS).

Data is sourced from Excel workbooks downloaded directly from:
https://www.finance-ni.gov.uk/topics/housing-stock-statistics

Coverage: annual, 2008–2026.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.nisra import housing_stock
from bolster.data_sources.nisra._base import NISRAValidationError

# The 11 LGDs used since the 2014 boundary reform
ELEVEN_LGDS = {
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

# NI 2026 total from the source file (Table 1.19 / Table 1.20 NI row)
_NI_TOTAL_2026 = 848_541
_NI_TOTAL_TOLERANCE = 0.05  # ±5 %


class TestHousingStockLGDIntegrity:
    """Integrity tests for LGD-level housing stock data."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return housing_stock.get_latest_housing_stock(geo="lgd", force_refresh=False)

    # ── Structure ────────────────────────────────────────────────────────────

    def test_returns_dataframe(self, df: pd.DataFrame) -> None:
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_required_columns(self, df: pd.DataFrame) -> None:
        required = {
            "year",
            "lgd_code",
            "lgd_name",
            "converted_apartment",
            "purpose_built_apartment",
            "detached",
            "semi_detached",
            "terrace",
            "total",
        }
        assert required.issubset(set(df.columns))

    def test_year_column_is_numeric(self, df: pd.DataFrame) -> None:
        assert pd.api.types.is_numeric_dtype(df["year"])

    # ── Geographic coverage ──────────────────────────────────────────────────

    def test_eleven_lgds_present(self, df: pd.DataFrame) -> None:
        """All 11 LGDs must appear in the data."""
        names = set(df["lgd_name"].dropna().unique())
        missing = ELEVEN_LGDS - names
        assert not missing, f"Missing LGDs: {missing}"

    def test_ni_total_row_present(self, df: pd.DataFrame) -> None:
        """A Northern Ireland aggregate row must be present each year."""
        assert "Northern Ireland" in df["lgd_name"].values

    def test_twelve_rows_per_year(self, df: pd.DataFrame) -> None:
        """Each year should have exactly 12 rows (11 LGDs + NI total)."""
        counts = df.groupby("year")["lgd_name"].count()
        bad_years = counts[counts != 12]
        assert bad_years.empty, f"Years with row count ≠ 12: {bad_years.to_dict()}"

    # ── Temporal coverage ────────────────────────────────────────────────────

    def test_historical_start_2008(self, df: pd.DataFrame) -> None:
        assert 2008 in df["year"].values

    def test_covers_2024(self, df: pd.DataFrame) -> None:
        assert df["year"].max() >= 2024

    def test_at_least_17_years(self, df: pd.DataFrame) -> None:
        """Data should span at least 2008–2024 (17 years)."""
        assert df["year"].nunique() >= 17

    # ── Value integrity ──────────────────────────────────────────────────────

    def test_no_negative_values(self, df: pd.DataFrame) -> None:
        count_cols = [
            "converted_apartment",
            "purpose_built_apartment",
            "detached",
            "semi_detached",
            "terrace",
            "total",
        ]
        for col in count_cols:
            vals = df[col].dropna()
            assert (vals >= 0).all(), f"Negative values in column '{col}'"

    def test_ni_total_sums_match_lgds(self, df: pd.DataFrame) -> None:
        """NI total row 'total' should equal (or closely approximate) sum of the 11 LGD totals."""
        for year, grp in df.groupby("year"):
            lgd_rows = grp[grp["lgd_name"] != "Northern Ireland"]
            ni_row = grp[grp["lgd_name"] == "Northern Ireland"]
            if ni_row.empty or lgd_rows.empty:
                continue
            lgd_sum = lgd_rows["total"].sum()
            ni_total = ni_row["total"].iloc[0]
            assert abs(lgd_sum - ni_total) <= ni_total * 0.01, (
                f"Year {year}: LGD sum ({lgd_sum:,}) differs from NI total ({ni_total:,}) by >1%"
            )

    def test_2026_ni_total_approx(self, df: pd.DataFrame) -> None:
        """2026 NI total should be approximately 848,541 (within 5%)."""
        ni_2026 = df[(df["year"] == 2026) & (df["lgd_name"] == "Northern Ireland")]
        if ni_2026.empty:
            pytest.skip("2026 data not present")
        total = ni_2026["total"].iloc[0]
        assert abs(total - _NI_TOTAL_2026) / _NI_TOTAL_2026 <= _NI_TOTAL_TOLERANCE, (
            f"2026 NI total {total:,} not within 5% of expected {_NI_TOTAL_2026:,}"
        )

    def test_total_gte_subtypes_sum(self, df: pd.DataFrame) -> None:
        """Total column should be >= sum of dwelling subtypes for each row."""
        subtype_cols = [
            "converted_apartment",
            "purpose_built_apartment",
            "detached",
            "semi_detached",
            "terrace",
        ]
        sub = df.dropna(subset=subtype_cols + ["total"])
        computed = sub[subtype_cols].sum(axis=1)
        bad = sub[sub["total"] < computed * 0.95]
        assert bad.empty, f"{len(bad)} rows where 'total' < 95% of subtypes sum"

    # ── Validation function ──────────────────────────────────────────────────

    def test_validate_passes_on_real_data(self, df: pd.DataFrame) -> None:
        assert housing_stock.validate_housing_stock(df) is True


# ── Validation unit tests (no network calls) ─────────────────────────────────


class TestValidationEdgeCases:
    """Unit tests for validate_housing_stock() edge cases — no network calls."""

    def _make_base_df(self) -> pd.DataFrame:
        """Return a minimal valid synthetic DataFrame."""
        rows = []
        lgds = list(ELEVEN_LGDS) + ["Northern Ireland"]
        for year in range(2008, 2026):
            for lgd in lgds:
                rows.append(
                    {
                        "year": year,
                        "lgd_code": "N09000001" if lgd != "Northern Ireland" else "Northern Ireland",
                        "lgd_name": lgd,
                        "converted_apartment": 200,
                        "purpose_built_apartment": 5000,
                        "detached": 18000,
                        "semi_detached": 14000,
                        "terrace": 16000,
                        "total": 53200,
                    }
                )
        return pd.DataFrame(rows)

    def test_validate_empty_dataframe(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            housing_stock.validate_housing_stock(pd.DataFrame())

    def test_validate_none(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            housing_stock.validate_housing_stock(None)  # type: ignore[arg-type]

    def test_validate_missing_columns(self) -> None:
        df = self._make_base_df().drop(columns=["total"])
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            housing_stock.validate_housing_stock(df)

    def test_validate_too_few_years(self) -> None:
        df = self._make_base_df()
        # Keep only 5 years
        df = df[df["year"].isin(range(2008, 2013))].copy()
        with pytest.raises(NISRAValidationError, match="Too few years"):
            housing_stock.validate_housing_stock(df)

    def test_validate_negative_values(self) -> None:
        df = self._make_base_df()
        df.loc[0, "detached"] = -1
        with pytest.raises(NISRAValidationError, match="Negative"):
            housing_stock.validate_housing_stock(df)

    def test_validate_total_lower_than_subtypes(self) -> None:
        df = self._make_base_df()
        # Make total implausibly low (well below 95% of sum of subtypes)
        df.loc[0, "total"] = 100
        with pytest.raises(NISRAValidationError, match="total.*lower"):
            housing_stock.validate_housing_stock(df)

    def test_validate_passes_on_synthetic_valid_data(self) -> None:
        assert housing_stock.validate_housing_stock(self._make_base_df()) is True


# ── Helper function unit tests ────────────────────────────────────────────────


class TestHelpers:
    """Unit tests for internal helper functions — no network calls."""

    def test_extract_year_from_title_april(self) -> None:
        from bolster.data_sources.nisra.housing_stock import _extract_year_from_title

        assert _extract_year_from_title("Number of Dwellings ... - April 2009") == 2009

    def test_extract_year_from_title_may(self) -> None:
        from bolster.data_sources.nisra.housing_stock import _extract_year_from_title

        assert _extract_year_from_title("Number of Dwellings ... - May 2008") == 2008

    def test_extract_year_from_title_no_year(self) -> None:
        from bolster.data_sources.nisra.housing_stock import _extract_year_from_title

        assert _extract_year_from_title("No year here") is None

    def test_get_latest_publication_url_invalid_geo(self) -> None:
        with pytest.raises(ValueError, match="Unknown geo type"):
            housing_stock.get_latest_publication_url("invalid")

    def test_get_latest_housing_stock_invalid_geo(self) -> None:
        with pytest.raises(ValueError, match="Unknown geo type"):
            housing_stock.get_latest_housing_stock(geo="invalid")
