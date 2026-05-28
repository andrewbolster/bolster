"""Integrity tests for the NICTS Mortgages Action for Possession module.

Tests use real data downloaded from justice-ni.gov.uk (no mocks). Network
calls are made once per class via ``scope="class"`` fixtures and cached for
the duration of the test session. Validation edge cases are covered by
network-free unit tests.
"""

import pandas as pd
import pytest

from bolster.data_sources.justice import mortgages
from bolster.data_sources.justice.mortgages import (
    MortgagesDataNotFoundError,
    MortgagesValidationError,
)


class TestCasesReceivedIntegrity:
    """Integrity tests for the cases-received table (Table 1)."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return mortgages.get_cases_received()

    def test_required_columns(self, latest_data):
        expected = {"year", "quarter", "period", "applications", "annual_total", "annual_pct_change"}
        assert expected.issubset(set(latest_data.columns))

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_quarter_values(self, latest_data):
        assert set(latest_data["quarter"].unique()) == {"Q1", "Q2", "Q3", "Q4"}

    def test_value_ranges(self, latest_data):
        values = latest_data["applications"].dropna()
        assert (values >= 0).all()
        # Peak quarter was ~1100; allow generous headroom but catch parse errors
        assert values.max() < 5000

    def test_historical_coverage_from_2007(self, latest_data):
        assert latest_data["year"].min() == 2007

    def test_recent_coverage(self, latest_data):
        assert latest_data["year"].max() >= 2024

    def test_year_dtype_integer(self, latest_data):
        assert pd.api.types.is_integer_dtype(latest_data["year"])

    def test_period_dtype(self, latest_data):
        assert isinstance(latest_data["period"].dtype, pd.PeriodDtype)

    def test_2009_peak_year(self, latest_data):
        """2009 was the documented peak year (~3,906 annual applications)."""
        peak = latest_data.groupby("year")["annual_total"].first().idxmax()
        assert peak == 2009

    def test_validate_passes(self, latest_data):
        assert mortgages.validate_data(latest_data) is True


class TestCasesDisposedIntegrity:
    """Integrity tests for the cases-disposed table (Table 2)."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return mortgages.get_cases_disposed()

    def test_required_columns(self, latest_data):
        expected = {"year", "quarter", "period", "applications", "annual_total", "annual_pct_change"}
        assert expected.issubset(set(latest_data.columns))

    def test_value_ranges(self, latest_data):
        values = latest_data["applications"].dropna()
        assert (values >= 0).all()

    def test_historical_coverage_from_2007(self, latest_data):
        assert latest_data["year"].min() == 2007

    def test_validate_passes(self, latest_data):
        assert mortgages.validate_data(latest_data) is True


class TestFinalOrdersIntegrity:
    """Integrity tests for the final-orders table (Table 3)."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return mortgages.get_final_orders()

    def test_required_columns(self, latest_data):
        expected = {"order_type", "year", "quarter", "period", "count"}
        assert expected.issubset(set(latest_data.columns))

    def test_not_empty(self, latest_data):
        assert not latest_data.empty

    def test_has_possession_order_type(self, latest_data):
        assert "Possession" in set(latest_data["order_type"])

    def test_has_total_row(self, latest_data):
        assert "Total" in set(latest_data["order_type"])

    def test_coverage_from_2017(self, latest_data):
        assert latest_data["year"].min() == 2017

    def test_counts_non_negative(self, latest_data):
        counts = latest_data["count"].dropna()
        assert (counts >= 0).all()


class TestCrossValidation:
    """Cross-checks between received/disposed datasets."""

    @pytest.fixture(scope="class")
    def all_data(self):
        return mortgages.get_latest_data()

    def test_received_and_disposed_share_years(self, all_data):
        received_years = set(all_data["received"]["year"])
        disposed_years = set(all_data["disposed"]["year"])
        assert received_years == disposed_years

    def test_received_and_disposed_same_shape(self, all_data):
        assert all_data["received"].shape[0] == all_data["disposed"].shape[0]

    def test_all_three_tables_present(self, all_data):
        assert {"received", "disposed", "final_orders"}.issubset(set(all_data))


class TestPublicationDiscovery:
    """Tests for locating the latest publication."""

    def test_latest_url_is_ods(self):
        url = mortgages.get_latest_publication_url()
        assert url.lower().endswith(".ods")
        assert url.startswith("https://")


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def _valid_frame(self, n_years: int = 15) -> pd.DataFrame:
        records = []
        for year in range(2007, 2007 + n_years):
            for q in ["Q1", "Q2", "Q3", "Q4"]:
                records.append(
                    {
                        "year": year,
                        "quarter": q,
                        "period": pd.Period(f"{year}{q}", freq="Q"),
                        "applications": 100,
                        "annual_total": 400,
                        "annual_pct_change": 0.0,
                    }
                )
        return pd.DataFrame.from_records(records)

    def test_validate_good_dataframe(self):
        assert mortgages.validate_data(self._valid_frame()) is True

    def test_validate_empty_dataframe(self):
        with pytest.raises(MortgagesValidationError, match="empty"):
            mortgages.validate_data(pd.DataFrame())

    def test_validate_none_dataframe(self):
        with pytest.raises(MortgagesValidationError, match="empty"):
            mortgages.validate_data(None)

    def test_validate_missing_columns(self):
        df = self._valid_frame().drop(columns=["applications"])
        with pytest.raises(MortgagesValidationError, match="Missing required columns"):
            mortgages.validate_data(df)

    def test_validate_too_few_records(self):
        df = self._valid_frame(n_years=2)  # only 8 rows
        with pytest.raises(MortgagesValidationError, match="Too few records"):
            mortgages.validate_data(df)

    def test_validate_negative_values(self):
        df = self._valid_frame()
        df.loc[0, "applications"] = -5
        with pytest.raises(MortgagesValidationError, match="Negative values"):
            mortgages.validate_data(df)

    def test_validate_year_out_of_bounds(self):
        df = self._valid_frame()
        df.loc[0, "year"] = 1990
        with pytest.raises(MortgagesValidationError, match="Year range out of bounds"):
            mortgages.validate_data(df)

    def test_validate_custom_value_col(self):
        df = self._valid_frame().rename(columns={"applications": "count"})
        assert mortgages.validate_data(df, value_col="count") is True


class TestPeriodLabelParsing:
    """Unit tests for the final-orders column label parser - no network."""

    def test_parse_quarterly_label(self):
        year, quarter, period = mortgages._parse_period_label("2025 Q1")
        assert (year, quarter) == (2025, "Q1")
        assert period == pd.Period("2025Q1", freq="Q")

    def test_parse_annual_label_int_like(self):
        year, quarter, period = mortgages._parse_period_label("2017")
        assert (year, quarter) == (2017, None)
        assert period == pd.Period("2017", freq="Y")

    def test_parse_annual_label_float_like(self):
        year, quarter, period = mortgages._parse_period_label("2018.0")
        assert (year, quarter) == (2018, None)

    def test_parse_unrecognised_label(self):
        assert mortgages._parse_period_label("Final Order") == (None, None, None)


class TestSafeConverters:
    """Unit tests for the safe cell converters - no network."""

    def test_safe_int_blank(self):
        assert mortgages._safe_int("") is None
        assert mortgages._safe_int("-") is None
        assert mortgages._safe_int(None) is None
        assert mortgages._safe_int(float("nan")) is None

    def test_safe_int_numeric(self):
        assert mortgages._safe_int("42") == 42
        assert mortgages._safe_int(42.0) == 42

    def test_safe_int_garbage(self):
        assert mortgages._safe_int("abc") is None

    def test_safe_float_blank(self):
        assert mortgages._safe_float("-") is None
        assert mortgages._safe_float(None) is None

    def test_safe_float_numeric(self):
        assert mortgages._safe_float("0.5") == 0.5

    def test_safe_float_garbage(self):
        assert mortgages._safe_float("xyz") is None


class TestErrorPaths:
    """Tests for error handling without heavy network use."""

    def test_get_final_orders_raises_when_absent(self, monkeypatch):
        """If a bulletin lacks final orders, get_final_orders should raise."""

        def fake_latest(force_refresh=False):
            return {"received": pd.DataFrame(), "disposed": pd.DataFrame()}

        monkeypatch.setattr(mortgages, "get_latest_data", fake_latest)
        with pytest.raises(MortgagesDataNotFoundError, match="not available"):
            mortgages.get_final_orders()
