"""Integrity tests for NISRA Homelessness Bulletin module.

Validates real data quality, structure, and consistency for NI homelessness
statistics published by the Department for Communities NI (DfC) / NIHE.

Data is sourced from Excel workbooks downloaded directly from:
https://www.communities-ni.gov.uk/articles/northern-ireland-homelessness-bulletin

Coverage: biannual (Apr–Sep and Oct–Mar), 2018/19 to present.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.nisra import homelessness
from bolster.data_sources.nisra._base import NISRAValidationError

_ELEVEN_LGDS = {
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

# Known Apr–Sep 2025 figures from the DfC bulletin
_NI_APR_SEP_2025_PRESENTATIONS = 8_217
_NI_APR_SEP_2025_ACCEPTANCES = 5_366
_ANCHOR_TOLERANCE = 0.05  # ±5%


class TestPresentationsIntegrity:
    """Integrity tests for homelessness presentations data."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return homelessness.get_latest_data(section="presentations")

    def test_returns_dataframe(self, df: pd.DataFrame) -> None:
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_required_columns(self, df: pd.DataFrame) -> None:
        assert {"year", "period", "lgd", "presentations", "rate_per_1000"}.issubset(set(df.columns))

    def test_ni_total_present(self, df: pd.DataFrame) -> None:
        assert "Northern Ireland" in df["lgd"].values

    def test_eleven_lgds_present(self, df: pd.DataFrame) -> None:
        names = set(df["lgd"].unique())
        missing = _ELEVEN_LGDS - names
        assert not missing, f"Missing LGDs: {missing}"

    def test_covers_both_periods(self, df: pd.DataFrame) -> None:
        periods = set(df["period"].unique())
        assert "Apr-Sep" in periods
        assert "Oct-Mar" in periods

    def test_historical_coverage_from_2018(self, df: pd.DataFrame) -> None:
        years = set(df["year"].unique())
        assert any(y.startswith("2018") for y in years), f"No 2018/19 data in: {sorted(years)}"

    def test_no_negative_presentations(self, df: pd.DataFrame) -> None:
        assert (df["presentations"].dropna() >= 0).all()

    def test_ni_total_apr_sep_2025_anchor(self, df: pd.DataFrame) -> None:
        """NI total Apr–Sep 2025 presentations should be ~8,217."""
        ni_row = df[(df["lgd"] == "Northern Ireland") & (df["year"] == "2025/26") & (df["period"] == "Apr-Sep")]
        if ni_row.empty:
            pytest.skip("Apr–Sep 2025/26 data not present")
        count = ni_row["presentations"].iloc[0]
        assert abs(count - _NI_APR_SEP_2025_PRESENTATIONS) / _NI_APR_SEP_2025_PRESENTATIONS <= _ANCHOR_TOLERANCE, (
            f"NI presentations {count:,} not within 5% of expected {_NI_APR_SEP_2025_PRESENTATIONS:,}"
        )

    def test_belfast_is_largest_lgd(self, df: pd.DataFrame) -> None:
        """Belfast should have the highest presentations among individual LGDs."""
        lgd_only = df[df["lgd"] != "Northern Ireland"]
        by_lgd = lgd_only.groupby("lgd")["presentations"].sum()
        if by_lgd.empty:
            pytest.skip("No LGD data")
        assert by_lgd.idxmax() == "Belfast", f"Expected Belfast largest, got {by_lgd.idxmax()}"

    def test_validation_passes(self, df: pd.DataFrame) -> None:
        assert homelessness.validate_data(df, section="presentations") is True


class TestAcceptancesIntegrity:
    """Integrity tests for homelessness acceptances data."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return homelessness.get_latest_data(section="acceptances")

    def test_returns_dataframe(self, df: pd.DataFrame) -> None:
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_required_columns(self, df: pd.DataFrame) -> None:
        assert {"year", "period", "lgd", "acceptances", "rate_per_1000"}.issubset(set(df.columns))

    def test_ni_total_present(self, df: pd.DataFrame) -> None:
        assert "Northern Ireland" in df["lgd"].values

    def test_no_negative_acceptances(self, df: pd.DataFrame) -> None:
        assert (df["acceptances"].dropna() >= 0).all()

    def test_ni_total_apr_sep_2025_anchor(self, df: pd.DataFrame) -> None:
        """NI total Apr–Sep 2025 acceptances should be ~5,366."""
        ni_row = df[(df["lgd"] == "Northern Ireland") & (df["year"] == "2025/26") & (df["period"] == "Apr-Sep")]
        if ni_row.empty:
            pytest.skip("Apr–Sep 2025/26 data not present")
        count = ni_row["acceptances"].iloc[0]
        assert abs(count - _NI_APR_SEP_2025_ACCEPTANCES) / _NI_APR_SEP_2025_ACCEPTANCES <= _ANCHOR_TOLERANCE, (
            f"NI acceptances {count:,} not within 5% of expected {_NI_APR_SEP_2025_ACCEPTANCES:,}"
        )

    def test_acceptances_lte_presentations(self, df: pd.DataFrame) -> None:
        """NI-level acceptances must not exceed presentations in any period."""
        pres = homelessness.get_latest_data(section="presentations")
        ni_pres = pres[pres["lgd"] == "Northern Ireland"].set_index(["year", "period"])["presentations"]
        ni_acc = df[df["lgd"] == "Northern Ireland"].set_index(["year", "period"])["acceptances"]
        shared = ni_pres.index.intersection(ni_acc.index)
        for idx in shared:
            assert ni_acc[idx] <= ni_pres[idx], (
                f"{idx}: acceptances ({ni_acc[idx]:,}) > presentations ({ni_pres[idx]:,})"
            )

    def test_validation_passes(self, df: pd.DataFrame) -> None:
        assert homelessness.validate_data(df, section="acceptances") is True


class TestCombinedIntegrity:
    """Integrity tests for section='all' combined output."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return homelessness.get_latest_data(section="all")

    def test_has_section_column(self, df: pd.DataFrame) -> None:
        assert "section" in df.columns

    def test_both_sections_present(self, df: pd.DataFrame) -> None:
        assert set(df["section"].unique()) == {"presentations", "acceptances"}

    def test_count_column_present(self, df: pd.DataFrame) -> None:
        assert "count" in df.columns

    def test_no_negative_counts(self, df: pd.DataFrame) -> None:
        assert (df["count"].dropna() >= 0).all()


class TestValidationEdgeCases:
    """Unit tests for validate_data() edge cases — no network calls."""

    def _make_base_df(self, section: str = "presentations") -> pd.DataFrame:
        rows = []
        lgds = list(_ELEVEN_LGDS) + ["Northern Ireland"]
        for year in ("2023/24", "2024/25", "2025/26"):
            for period in ("Apr-Sep", "Oct-Mar"):
                for lgd in lgds:
                    rows.append({"year": year, "period": period, "lgd": lgd, section: 500, "rate_per_1000": 1.5})
        return pd.DataFrame(rows)

    def test_validate_empty_dataframe(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            homelessness.validate_data(pd.DataFrame())

    def test_validate_none(self) -> None:
        with pytest.raises(NISRAValidationError, match="empty"):
            homelessness.validate_data(None)  # type: ignore[arg-type]

    def test_validate_missing_columns(self) -> None:
        df = self._make_base_df().drop(columns=["lgd"])
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            homelessness.validate_data(df)

    def test_validate_too_few_rows(self) -> None:
        df = self._make_base_df().head(3)
        with pytest.raises(NISRAValidationError, match="Too few rows"):
            homelessness.validate_data(df)

    def test_validate_missing_ni_total(self) -> None:
        df = self._make_base_df()
        df = df[df["lgd"] != "Northern Ireland"].copy()
        with pytest.raises(NISRAValidationError, match="Northern Ireland"):
            homelessness.validate_data(df)

    def test_validate_negative_values(self) -> None:
        df = self._make_base_df()
        df.loc[0, "presentations"] = -1
        with pytest.raises(NISRAValidationError, match="Negative"):
            homelessness.validate_data(df)

    def test_validate_implausibly_low_ni_total(self) -> None:
        df = self._make_base_df()
        # Set all NI rows to 1 — well below the >1000 sanity threshold
        df.loc[df["lgd"] == "Northern Ireland", "presentations"] = 1
        with pytest.raises(NISRAValidationError, match="implausibly low"):
            homelessness.validate_data(df)

    def test_validate_invalid_section(self) -> None:
        with pytest.raises(ValueError):
            homelessness.get_latest_data(section="invalid")

    def test_validate_passes_on_synthetic_data(self) -> None:
        df = self._make_base_df()
        # NI rows need to be > 1000 to pass the sanity check
        df.loc[df["lgd"] == "Northern Ireland", "presentations"] = 5000
        assert homelessness.validate_data(df, section="presentations") is True


class TestNormalisePeriod:
    """Unit tests for _normalise_period() — no network calls."""

    def test_april_september(self) -> None:
        assert homelessness._normalise_period("April-September") == "Apr-Sep"

    def test_october_march(self) -> None:
        assert homelessness._normalise_period("October-March") == "Oct-Mar"

    def test_jul_dec(self) -> None:
        assert homelessness._normalise_period("July-December") == "Jul-Dec"

    def test_jan_jun(self) -> None:
        assert homelessness._normalise_period("January-June") == "Jan-Jun"

    def test_footnote_stripped(self) -> None:
        assert homelessness._normalise_period("April-September¹") == "Apr-Sep"

    def test_apr_jun_financial_year(self) -> None:
        result = homelessness._normalise_period("Apr-Jun (Financial year Q1)")
        assert result == "Apr-Jun"

    def test_passthrough_unknown(self) -> None:
        result = homelessness._normalise_period("Unknown Period")
        assert result == "Unknown Period"
