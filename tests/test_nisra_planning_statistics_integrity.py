"""Integrity tests for NISRA Planning Activity Statistics module.

Validates real data quality, structure and consistency for the
NI planning statistics module (Department for Infrastructure).

Data is sourced from the NISRA PxStat API (PALGD, PADAA matrices),
which provides annual coverage from 2015/16 onwards.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.nisra import planning_statistics
from bolster.data_sources.nisra._base import NISRAValidationError

# Council names as returned by the PxStat API (LGD2014 label format)
ELEVEN_COUNCILS = {
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


class TestPlanningNIWideIntegrity:
    """Integrity tests for NI-wide annual planning applications (PALGD)."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return planning_statistics.get_latest_data(force_refresh=False)

    def test_returns_dataframe(self, df):
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_required_columns(self, df):
        required = {
            "date",
            "financial_year",
            "year",
            "council",
            "applications_received",
            "applications_decided",
            "applications_approved",
            "applications_withdrawn",
            "approval_rate",
        }
        assert required.issubset(set(df.columns))

    def test_column_types(self, df):
        assert pd.api.types.is_datetime64_any_dtype(df["date"])
        assert df["financial_year"].dtype == object
        assert pd.api.types.is_integer_dtype(df["year"])

    def test_history_starts_2015_16(self, df):
        """PxStat API coverage begins at 2015/16."""
        assert "2015/16" in df["financial_year"].values

    def test_recent_data_available(self, df):
        """Data should cover at least up to 2023/24."""
        years = set(df["financial_year"].values)
        assert any(y >= "2023/24" for y in years), f"Latest financial year not recent enough: {sorted(years)[-1]}"

    def test_minimum_coverage(self, df):
        """At least 8 financial years (2015/16 through 2023/24)."""
        assert df["financial_year"].nunique() >= 8

    def test_ni_wide_total_present(self, df):
        """NI-wide aggregate row should be present."""
        assert "Northern Ireland" in df["council"].values

    def test_all_eleven_councils_present(self, df):
        councils = set(df["council"].unique())
        missing = ELEVEN_COUNCILS - councils
        assert not missing, f"Missing councils: {missing}"

    def test_application_counts_positive(self, df):
        for col in ("applications_received", "applications_decided", "applications_approved"):
            vals = df[col].dropna()
            assert (vals >= 0).all(), f"Negative values in {col}"

    def test_approved_le_decided(self, df):
        sub = df.dropna(subset=["applications_approved", "applications_decided"])
        assert (sub["applications_approved"] <= sub["applications_decided"]).all()

    def test_approval_rate_in_range(self, df):
        rates = df["approval_rate"].dropna()
        assert rates.between(0, 1.0001).all()
        # NI approval rate has historically been ~85%+
        ni = df[df["council"] == "Northern Ireland"]
        assert ni["approval_rate"].mean() > 0.80

    def test_date_aligns_with_financial_year(self, df):
        """Date column should be April 1 of the start year."""
        for _, row in df.head(10).iterrows():
            assert row["date"].month == 4
            assert row["date"].day == 1
            start_year = int(row["financial_year"].split("/")[0])
            assert row["date"].year == start_year

    def test_validate_passes_on_real_data(self, df):
        assert planning_statistics.validate_data(df) is True


class TestPlanningCouncilIntegrity:
    """Integrity tests for council-area data (get_latest_council_data)."""

    @pytest.fixture(scope="class")
    def cdf(self) -> pd.DataFrame:
        return planning_statistics.get_latest_council_data(force_refresh=False)

    def test_required_columns(self, cdf):
        required = {
            "date",
            "financial_year",
            "year",
            "council",
            "applications_received",
            "applications_decided",
            "applications_approved",
            "applications_withdrawn",
            "approval_rate",
        }
        assert required.issubset(set(cdf.columns))

    def test_ni_aggregate_excluded(self, cdf):
        """NI-wide aggregate should be excluded from council data."""
        assert "Northern Ireland" not in cdf["council"].values

    def test_all_eleven_councils_present(self, cdf):
        councils = set(cdf["council"].unique())
        missing = ELEVEN_COUNCILS - councils
        assert not missing, f"Missing councils: {missing}"

    def test_council_data_non_empty(self, cdf):
        assert len(cdf) > 0
        # At least 11 councils * 8 years minimum
        assert len(cdf) >= 88

    def test_council_received_plausible(self, cdf):
        sub = cdf[cdf["council"].isin(ELEVEN_COUNCILS)]
        vals = sub["applications_received"].dropna()
        assert vals.min() >= 0
        # Annual volumes: most councils see <3,000 applications per year
        assert vals.max() < 10_000

    def test_council_approval_rate_in_range(self, cdf):
        rates = cdf["approval_rate"].dropna()
        assert rates.between(0, 1.0001).all()


class TestAssemblyAreaIntegrity:
    """Integrity tests for Assembly Area data (PADAA)."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return planning_statistics.parse_planning_by_assembly_area()

    def test_required_columns(self, df):
        required = {
            "financial_year",
            "date",
            "year",
            "assembly_area",
            "applications_received",
        }
        assert required.issubset(set(df.columns))

    def test_has_data(self, df):
        assert len(df) > 0

    def test_ni_wide_present(self, df):
        assert "Northern Ireland" in df["assembly_area"].values

    def test_application_counts_positive(self, df):
        vals = df["applications_received"].dropna()
        assert (vals >= 0).all()


class TestAnnualTotals:
    """Tests for annual financial-year totals."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return planning_statistics.get_latest_data(force_refresh=False)

    def test_annual_totals_structure(self, df):
        ann = planning_statistics.get_annual_totals(df)
        assert "financial_year" in ann.columns
        assert "applications_received" in ann.columns
        assert "approval_rate" in ann.columns
        assert len(ann) >= 8  # 2015/16 onwards

    def test_annual_received_from_ni_row(self, df):
        """get_annual_totals should use the NI aggregate row, not sum councils."""
        ann = planning_statistics.get_annual_totals(df)
        fy = "2023/24"
        if fy in df["financial_year"].values:
            expected = df[(df["financial_year"] == fy) & (df["council"] == "Northern Ireland")][
                "applications_received"
            ].iloc[0]
            actual = ann[ann["financial_year"] == fy]["applications_received"].iloc[0]
            assert actual == expected


class TestCouncilSummary:
    """Tests for council summary aggregation."""

    @pytest.fixture(scope="class")
    def cdf(self) -> pd.DataFrame:
        return planning_statistics.get_latest_council_data(force_refresh=False)

    def test_summary_default(self, cdf):
        s = planning_statistics.get_council_summary(cdf)
        assert "council" in s.columns
        assert "applications_received" in s.columns
        assert ELEVEN_COUNCILS.issubset(set(s["council"]))

    def test_summary_filtered_by_fy(self, cdf):
        available_years = sorted(cdf["financial_year"].unique())
        latest_fy = available_years[-1]
        s = planning_statistics.get_council_summary(cdf, financial_year=latest_fy)
        belfast = s[s["council"] == "Belfast"]
        assert len(belfast) == 1
        assert belfast["applications_received"].iloc[0] > 0


class TestGetLatestPlanningStatistics:
    """Tests for the unified get_latest_planning_statistics function."""

    def test_ni_dimension(self):
        df = planning_statistics.get_latest_planning_statistics(dimension="ni")
        assert "council" in df.columns
        assert set(df["council"].unique()) == {"Northern Ireland"}

    def test_council_dimension(self):
        df = planning_statistics.get_latest_planning_statistics(dimension="council")
        assert "council" in df.columns
        assert "Northern Ireland" not in df["council"].values

    def test_assembly_dimension(self):
        df = planning_statistics.get_latest_planning_statistics(dimension="assembly")
        assert "assembly_area" in df.columns
        assert "Northern Ireland" not in df["assembly_area"].values

    def test_financial_year_filter(self):
        df = planning_statistics.get_latest_planning_statistics(dimension="council", financial_year="2023/24")
        if len(df) > 0:
            assert (df["financial_year"] == "2023/24").all()

    def test_invalid_dimension_raises(self):
        with pytest.raises(ValueError, match="Unsupported dimension"):
            planning_statistics.get_latest_planning_statistics(dimension="invalid")


class TestValidationEdgeCases:
    """Unit tests for validate_data() edge cases — no network calls."""

    def _make_base_df(self) -> pd.DataFrame:
        rows = []
        for i in range(8):
            fy = f"{2015 + i}/{str(2016 + i)[-2:]}"
            rows.append(
                {
                    "financial_year": fy,
                    "date": pd.Timestamp(year=2015 + i, month=4, day=1),
                    "year": 2015 + i,
                    "council": "Northern Ireland",
                    "applications_received": 12000,
                    "applications_decided": 11000,
                    "applications_approved": 10000,
                    "applications_withdrawn": 400,
                    "approval_rate": 0.91,
                }
            )
        return pd.DataFrame(rows)

    def test_validate_empty_dataframe(self):
        with pytest.raises(NISRAValidationError, match="empty"):
            planning_statistics.validate_data(pd.DataFrame())

    def test_validate_none(self):
        with pytest.raises(NISRAValidationError, match="empty"):
            planning_statistics.validate_data(None)  # type: ignore[arg-type]

    def test_validate_missing_columns(self):
        df = self._make_base_df().drop(columns=["approval_rate"])
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            planning_statistics.validate_data(df)

    def test_validate_too_few_rows(self):
        df = self._make_base_df().iloc[:2].copy()
        with pytest.raises(NISRAValidationError, match="Too few records"):
            planning_statistics.validate_data(df)

    def test_validate_negative_received(self):
        df = self._make_base_df()
        df.loc[0, "applications_received"] = -1
        with pytest.raises(NISRAValidationError, match="Negative"):
            planning_statistics.validate_data(df)

    def test_validate_implausibly_high(self):
        df = self._make_base_df()
        df.loc[0, "applications_received"] = 999_999
        with pytest.raises(NISRAValidationError, match="Implausibly high"):
            planning_statistics.validate_data(df)

    def test_validate_approval_rate_out_of_range(self):
        df = self._make_base_df()
        df.loc[0, "approval_rate"] = 2.5
        with pytest.raises(NISRAValidationError, match="approval_rate"):
            planning_statistics.validate_data(df)

    def test_validate_passes_on_synthetic_valid_data(self):
        assert planning_statistics.validate_data(self._make_base_df()) is True


class TestHelperParsers:
    """Unit tests for internal helpers — no network calls."""

    def test_parse_financial_year_to_date(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_financial_year_to_date

        assert _parse_financial_year_to_date("2024/25") == pd.Timestamp("2024-04-01")
        assert _parse_financial_year_to_date("2015/16") == pd.Timestamp("2015-04-01")
