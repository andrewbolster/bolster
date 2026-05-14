"""Integrity tests for NISRA Planning Activity Statistics module.

Validates real data quality, structure and consistency for the
NI planning statistics module (Department for Infrastructure).
"""

from __future__ import annotations

import pandas as pd
import pytest

from bolster.data_sources.nisra import planning_statistics
from bolster.data_sources.nisra._base import NISRAValidationError

ELEVEN_COUNCILS = {
    "Antrim & Newtownabbey",
    "Ards & North Down",
    "Armagh City, Banbridge & Craigavon",
    "Belfast",
    "Causeway Coast & Glens",
    "Derry City & Strabane",
    "Fermanagh & Omagh",
    "Lisburn & Castlereagh",
    "Mid & East Antrim",
    "Mid Ulster",
    "Newry, Mourne & Down",
}


class TestPlanningPublicationDiscovery:
    """Live discovery of the latest planning statistics publication."""

    @pytest.fixture(scope="class")
    def latest_publication_url(self) -> str:
        return planning_statistics.get_latest_publication_url()

    def test_publication_url_shape(self, latest_publication_url: str):
        assert latest_publication_url.startswith(
            "https://www.infrastructure-ni.gov.uk/publications/"
        )
        assert "planning-statistics" in latest_publication_url.lower()

    def test_xlsx_url_shape(self, latest_publication_url: str):
        url = planning_statistics.get_latest_xlsx_url(latest_publication_url)
        assert url.lower().endswith(".xlsx")
        assert "planning" in url.lower()


class TestPlanningNIWideIntegrity:
    """Integrity tests for NI-wide quarterly applications (sheet 1.1)."""

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
            "quarter",
            "year",
            "applications_received",
            "applications_decided",
            "applications_approved",
            "applications_withdrawn",
            "approval_rate",
            "mid_year_population",
            "applications_per_10k",
        }
        assert required.issubset(set(df.columns))

    def test_column_types(self, df):
        assert pd.api.types.is_datetime64_any_dtype(df["date"])
        assert df["quarter"].dtype == object
        assert df["financial_year"].dtype == object
        assert pd.api.types.is_integer_dtype(df["year"])

    def test_quarter_values_valid(self, df):
        assert set(df["quarter"].unique()) == {"Q1", "Q2", "Q3", "Q4"}

    def test_history_starts_2002_03(self, df):
        first = df.iloc[0]
        assert first["financial_year"] == "2002/03"
        assert first["quarter"] == "Q1"
        assert first["date"] == pd.Timestamp("2002-04-01")

    def test_chronological_order(self, df):
        assert df["date"].is_monotonic_increasing

    def test_minimum_coverage(self, df):
        # 23+ full financial years since 2002/03 = ~90 quarters
        assert len(df) >= 90

    def test_recent_data_available(self, df):
        latest_year = df["year"].max()
        assert latest_year >= 2024

    def test_application_counts_positive(self, df):
        for col in ("applications_received", "applications_decided", "applications_approved"):
            vals = df[col].dropna()
            assert (vals >= 0).all(), f"Negative values in {col}"

    def test_application_volumes_plausible(self, df):
        # Quarterly applications received historically 2,000-9,000
        received = df["applications_received"].dropna()
        assert received.min() > 1_000
        assert received.max() < 20_000

    def test_approval_rate_in_range(self, df):
        rates = df["approval_rate"].dropna()
        assert rates.between(0, 1.0001).all()
        # Mean approval rate has historically been ~90%+
        assert rates.mean() > 0.80

    def test_approved_le_decided(self, df):
        sub = df.dropna(subset=["applications_approved", "applications_decided"])
        assert (sub["applications_approved"] <= sub["applications_decided"]).all()

    def test_population_plausible(self, df):
        pop = df["mid_year_population"].dropna()
        # NI mid-year population is ~1.7m-1.95m across the series
        assert (pop > 1_600_000).all()
        assert (pop < 2_100_000).all()

    def test_date_aligns_with_fy_quarter(self, df):
        for _, row in df.head(20).iterrows():
            q = row["quarter"]
            expected_month = {"Q1": 4, "Q2": 7, "Q3": 10, "Q4": 1}[q]
            assert row["date"].month == expected_month
            assert row["date"].day == 1

    def test_validate_passes_on_real_data(self, df):
        assert planning_statistics.validate_data(df) is True


class TestPlanningCouncilIntegrity:
    """Integrity tests for council-area data (sheet 1.2)."""

    @pytest.fixture(scope="class")
    def cdf(self) -> pd.DataFrame:
        return planning_statistics.get_latest_council_data(force_refresh=False)

    def test_required_columns(self, cdf):
        required = {
            "date",
            "financial_year",
            "quarter",
            "year",
            "council",
            "applications_received",
            "applications_decided",
            "applications_approved",
            "applications_withdrawn",
            "approval_rate",
        }
        assert required.issubset(set(cdf.columns))

    def test_all_eleven_councils_present(self, cdf):
        councils = set(cdf["council"].unique())
        missing = ELEVEN_COUNCILS - councils
        assert not missing, f"Missing councils: {missing}"

    def test_council_data_non_empty(self, cdf):
        assert len(cdf) > 0
        # At least 11 councils * 4 quarters in the latest financial year
        assert len(cdf) >= 44

    def test_council_quarter_values_valid(self, cdf):
        assert set(cdf["quarter"].unique()).issubset({"Q1", "Q2", "Q3", "Q4"})

    def test_council_received_plausible(self, cdf):
        # Most councils receive 100-500 applications per quarter
        # Take just the 11 named councils to avoid Strategic Planning Div / NI total
        sub = cdf[cdf["council"].isin(ELEVEN_COUNCILS)]
        vals = sub["applications_received"].dropna()
        assert vals.min() >= 0
        assert vals.max() < 2_000

    def test_council_approval_rate_in_range(self, cdf):
        rates = cdf["approval_rate"].dropna()
        assert rates.between(0, 1.0001).all()


class TestAnnualTotals:
    """Tests for annual financial-year aggregation."""

    @pytest.fixture(scope="class")
    def df(self) -> pd.DataFrame:
        return planning_statistics.get_latest_data(force_refresh=False)

    def test_annual_totals_structure(self, df):
        ann = planning_statistics.get_annual_totals(df)
        assert "financial_year" in ann.columns
        assert "applications_received" in ann.columns
        assert "approval_rate" in ann.columns
        # 2002/03 through latest in-progress year = 23+ rows
        assert len(ann) >= 23

    def test_complete_years_have_4_quarters(self, df):
        ann = planning_statistics.get_annual_totals(df)
        # All but the latest in-progress year should have 4 quarters
        full = ann[ann["quarters"] == 4]
        assert len(full) >= 22

    def test_annual_received_consistent_with_quarterly(self, df):
        ann = planning_statistics.get_annual_totals(df)
        # 2002/03 had 29,561 applications received according to the source data
        first = ann.iloc[0]
        assert first["financial_year"] == "2002/03"
        assert first["applications_received"] == df[df["financial_year"] == "2002/03"][
            "applications_received"
        ].sum()


class TestCouncilSummary:
    """Tests for council summary aggregation."""

    @pytest.fixture(scope="class")
    def cdf(self) -> pd.DataFrame:
        return planning_statistics.get_latest_council_data(force_refresh=False)

    def test_summary_default(self, cdf):
        s = planning_statistics.get_council_summary(cdf)
        assert "council" in s.columns
        assert "applications_received" in s.columns
        # Should include the 11 councils at minimum
        assert ELEVEN_COUNCILS.issubset(set(s["council"]))

    def test_summary_filtered_by_fy(self, cdf):
        s = planning_statistics.get_council_summary(cdf, financial_year="2024/25")
        # Belfast is consistently one of the highest-volume councils
        belfast = s[s["council"] == "Belfast"]
        assert len(belfast) == 1
        assert belfast["applications_received"].iloc[0] > 0


class TestValidationEdgeCases:
    """Unit tests for validate_data() edge cases - no network calls."""

    def _make_base_df(self) -> pd.DataFrame:
        # Build a minimal 40-quarter valid frame
        rows = []
        for i in range(40):
            year = 2002 + i // 4
            quarter = f"Q{(i % 4) + 1}"
            month = {"Q1": 4, "Q2": 7, "Q3": 10, "Q4": 1}[quarter]
            cal_year = year if quarter != "Q4" else year + 1
            rows.append(
                {
                    "date": pd.Timestamp(year=cal_year, month=month, day=1),
                    "financial_year": f"{year}/{str(year + 1)[-2:]}",
                    "quarter": quarter,
                    "year": cal_year,
                    "applications_received": 3000,
                    "applications_decided": 2800,
                    "applications_approved": 2600,
                    "applications_withdrawn": 100,
                    "approval_rate": 0.93,
                    "mid_year_population": 1_800_000,
                    "applications_per_10k": 16.6,
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
        df = self._make_base_df().iloc[:10].copy()
        with pytest.raises(NISRAValidationError, match="Too few quarters"):
            planning_statistics.validate_data(df)

    def test_validate_bad_quarter_value(self):
        df = self._make_base_df()
        df.loc[0, "quarter"] = "Q5"
        with pytest.raises(NISRAValidationError, match="Unexpected quarter"):
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
    """Unit tests for internal helpers - no network calls."""

    def test_parse_fy_quarter_q1(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_fy_quarter_to_date

        assert _parse_fy_quarter_to_date("2024/25", "Q1") == pd.Timestamp("2024-04-01")

    def test_parse_fy_quarter_q4(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_fy_quarter_to_date

        assert _parse_fy_quarter_to_date("2024/25", "Q4") == pd.Timestamp("2025-01-01")

    def test_parse_fy_quarter_bad_year(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_fy_quarter_to_date

        assert _parse_fy_quarter_to_date("not a year", "Q1") is None

    def test_parse_fy_quarter_bad_quarter(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_fy_quarter_to_date

        assert _parse_fy_quarter_to_date("2024/25", "Q9") is None

    def test_parse_fy_quarter_non_string(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_fy_quarter_to_date

        assert _parse_fy_quarter_to_date(2024, "Q1") is None  # type: ignore[arg-type]

    def test_parse_council_label_valid(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_council_date_label

        result = _parse_council_date_label("Apr-Jun 2025")
        assert result is not None
        ts, fy, q = result
        assert ts == pd.Timestamp("2025-04-01")
        assert fy == "2025/26"
        assert q == "Q1"

    def test_parse_council_label_q4_fy_rollover(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_council_date_label

        result = _parse_council_date_label("Jan-Mar 2025")
        assert result is not None
        ts, fy, q = result
        assert ts == pd.Timestamp("2025-01-01")
        assert fy == "2024/25"
        assert q == "Q4"

    def test_parse_council_label_invalid(self):
        from bolster.data_sources.nisra.planning_statistics import _parse_council_date_label

        assert _parse_council_date_label("Year to date 2025/26") is None
        assert _parse_council_date_label("") is None
        assert _parse_council_date_label(None) is None  # type: ignore[arg-type]
