"""Data-integrity and validation tests for :mod:`bolster.data_sources.boe_base_rate`.

Integrity tests hit the live Bank of England spreadsheet (no mocks) and use
``scope="class"`` fixtures so the workbook is downloaded once per class.
Validation tests are pure-Python edge cases that need no network access.
"""

import pandas as pd
import pytest

from bolster.data_sources import boe_base_rate
from bolster.data_sources.boe_base_rate import BoEDataError, BoEValidationError


class _StubWorkbook:
    """Minimal stand-in for ``pandas.ExcelFile`` exposing ``parse(sheet_name)``.

    Lets the parse/coalesce branches be exercised without an xls writer (xlrd
    can only read .xls and there is no .xls writer in the dev environment).
    """

    def __init__(self, sheets: dict[str, pd.DataFrame]):
        self._sheets = sheets

    def parse(self, sheet_name, header=0):  # noqa: ARG002 - header ignored; frames pre-shaped
        return self._sheets[sheet_name]


class TestDataIntegrity:
    """Live-data checks against the published BoE base-rate workbook."""

    @pytest.fixture(scope="class")
    def monthly_data(self):
        return boe_base_rate.get_latest_data(resolution="monthly")

    @pytest.fixture(scope="class")
    def daily_data(self):
        return boe_base_rate.get_latest_data(resolution="daily")

    @pytest.fixture(scope="class")
    def rate_changes(self):
        return boe_base_rate.get_rate_changes()

    def test_schema_columns(self, monthly_data):
        assert list(monthly_data.columns) == boe_base_rate.SCHEMA_COLUMNS

    def test_not_empty(self, monthly_data):
        assert len(monthly_data) > 0

    def test_geography_is_uk(self, monthly_data):
        assert set(monthly_data["geography"].unique()) == {"UK"}

    def test_source_is_boe(self, monthly_data):
        assert set(monthly_data["source"].unique()) == {"BoE"}

    def test_series_is_base_rate(self, monthly_data):
        assert set(monthly_data["series"].unique()) == {"base_rate"}

    def test_unit_is_percent(self, monthly_data):
        assert set(monthly_data["unit"].unique()) == {"%"}

    def test_rate_reasonable_range(self, monthly_data):
        # The UK base rate has stayed between 0% and 20% across modern history.
        assert monthly_data["value"].min() >= 0
        assert monthly_data["value"].max() <= 20

    def test_value_is_float(self, monthly_data):
        assert pd.api.types.is_float_dtype(monthly_data["value"])

    def test_no_null_values(self, monthly_data):
        assert not monthly_data["value"].isna().any()

    def test_monthly_has_month_no_quarter(self, monthly_data):
        assert monthly_data["month"].notna().all()
        assert monthly_data["quarter"].isna().all()

    def test_dates_are_period_start(self, monthly_data):
        # Monthly observations are dated to the first of the month.
        assert (monthly_data["date"].dt.day == 1).all()

    def test_historical_coverage(self, daily_data):
        # Daily data must reach back to at least 1973 and forward to recent years.
        assert daily_data["date"].min() <= pd.Timestamp("1973-01-01")
        assert daily_data["date"].max() >= pd.Timestamp("2020-01-01")

    def test_daily_resolution_label(self, daily_data):
        assert set(daily_data["resolution"].unique()) == {"daily"}
        assert daily_data["quarter"].isna().all()
        assert daily_data["month"].isna().all()

    def test_resolutions_available(self):
        for resolution in ("daily", "monthly", "quarterly", "annual"):
            df = boe_base_rate.get_latest_data(resolution=resolution)
            assert len(df) > 0
            assert set(df["resolution"].unique()) == {resolution}
            assert boe_base_rate.validate_data(df)

    def test_quarterly_labels(self):
        df = boe_base_rate.get_latest_data(resolution="quarterly")
        assert set(df["quarter"].dropna().unique()) <= {"Q1", "Q2", "Q3", "Q4"}
        assert df["month"].isna().all()

    def test_coarser_resolution_has_fewer_rows(self, monthly_data, daily_data):
        annual = boe_base_rate.get_latest_data(resolution="annual")
        assert len(annual) < len(monthly_data) < len(daily_data)

    def test_invalid_resolution_raises(self):
        with pytest.raises(ValueError):
            boe_base_rate.get_latest_data(resolution="weekly")

    def test_rate_changes_schema(self, rate_changes):
        assert list(rate_changes.columns) == boe_base_rate.RATE_CHANGES_COLUMNS

    def test_rate_changes_historical_depth(self, rate_changes):
        # The event history extends back to the 1694 founding-era rate.
        assert rate_changes["date"].min() <= pd.Timestamp("1700-01-01")
        assert len(rate_changes) > 500

    def test_rate_changes_sorted_and_valued(self, rate_changes):
        assert rate_changes["date"].is_monotonic_increasing
        assert not rate_changes["value"].isna().any()
        assert rate_changes["value"].between(0, 20).all()
        assert set(rate_changes["geography"].unique()) == {"UK"}
        assert set(rate_changes["source"].unique()) == {"BoE"}

    def test_schema_compatible_with_ons_cpi(self, monthly_data):
        # The two macro modules must share identical schema columns so they can
        # be concatenated without realigning/introducing NaN columns.
        ons_like = pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "year": pd.array([2024], dtype="Int64"),
                "quarter": [pd.NA],
                "month": pd.array([1], dtype="Int64"),
                "resolution": ["monthly"],
                "series": ["D7G7"],
                "value": [3.4],
                "unit": ["%"],
                "geography": ["UK"],
                "source": ["ONS"],
            }
        )
        combined = pd.concat([monthly_data, ons_like], ignore_index=True)
        assert list(combined.columns) == boe_base_rate.SCHEMA_COLUMNS
        assert len(combined) == len(monthly_data) + 1

    def test_validate_live_data(self, monthly_data):
        assert boe_base_rate.validate_data(monthly_data) is True


class TestInternals:
    """Unit tests for parse/coalesce helpers using stub workbooks (no network)."""

    def test_coalesce_takes_rightmost_non_null(self):
        raw = pd.DataFrame(
            {
                "Date": pd.to_datetime(["1973-01-01", "2003-02-06", "2024-01-01"]),
                "Bank Rate": [9.0, None, None],
                "Min Lending Rate": [None, None, None],
                "Min Band 1 Dealing Rate": [None, None, None],
                "Repo Rate": [None, 3.75, None],
                "Official Bank Rate": [None, None, 5.25],
            }
        )
        wb = _StubWorkbook({boe_base_rate.RAW_DATA_SHEET: raw})
        daily = boe_base_rate._coalesce_daily(wb)
        assert daily["value"].tolist() == [9.0, 3.75, 5.25]
        assert pd.api.types.is_float_dtype(daily["value"])

    def test_coalesce_missing_date_column_raises(self):
        raw = pd.DataFrame({"Bank Rate": [9.0]})
        wb = _StubWorkbook({boe_base_rate.RAW_DATA_SHEET: raw})
        with pytest.raises(BoEDataError, match="Date"):
            boe_base_rate._coalesce_daily(wb)

    def test_coalesce_no_rate_columns_raises(self):
        raw = pd.DataFrame({"Date": pd.to_datetime(["1973-01-01"]), "Zero line": [0]})
        wb = _StubWorkbook({boe_base_rate.RAW_DATA_SHEET: raw})
        with pytest.raises(BoEDataError, match="rate columns"):
            boe_base_rate._coalesce_daily(wb)

    def test_coalesce_all_null_rows_raises(self):
        raw = pd.DataFrame(
            {
                "Date": pd.to_datetime([None, None]),
                "Bank Rate": [None, None],
                "Official Bank Rate": [None, None],
            }
        )
        wb = _StubWorkbook({boe_base_rate.RAW_DATA_SHEET: raw})
        with pytest.raises(BoEDataError, match="No usable rows"):
            boe_base_rate._coalesce_daily(wb)

    def test_empty_frame_has_schema_and_dtypes(self):
        df = boe_base_rate._empty_frame()
        assert list(df.columns) == boe_base_rate.SCHEMA_COLUMNS
        assert len(df) == 0
        assert pd.api.types.is_datetime64_any_dtype(df["date"])
        assert pd.api.types.is_float_dtype(df["value"])

    def test_attach_schema_daily(self):
        src = pd.DataFrame({"date": pd.to_datetime(["2024-06-15"]), "value": [5.25]})
        out = boe_base_rate._attach_schema(src, "daily")
        assert list(out.columns) == boe_base_rate.SCHEMA_COLUMNS
        assert out.loc[0, "resolution"] == "daily"
        assert pd.isna(out.loc[0, "quarter"])
        assert pd.isna(out.loc[0, "month"])

    def test_attach_schema_quarterly(self):
        src = pd.DataFrame({"date": pd.to_datetime(["2024-04-01"]), "value": [5.0]})
        out = boe_base_rate._attach_schema(src, "quarterly")
        assert out.loc[0, "quarter"] == "Q2"
        assert pd.isna(out.loc[0, "month"])


class TestValidation:
    """Unit tests for :func:`validate_data` edge cases (no network calls)."""

    def _valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": [pd.Timestamp("2024-01-01")],
                "year": pd.array([2024], dtype="Int64"),
                "quarter": [pd.NA],
                "month": pd.array([1], dtype="Int64"),
                "resolution": ["monthly"],
                "series": ["base_rate"],
                "value": [5.25],
                "unit": ["%"],
                "geography": ["UK"],
                "source": ["BoE"],
            }
        )

    def test_validate_valid_frame(self):
        assert boe_base_rate.validate_data(self._valid_frame()) is True

    def test_validate_empty_dataframe(self):
        df = self._valid_frame().iloc[0:0]
        with pytest.raises(BoEValidationError, match="empty"):
            boe_base_rate.validate_data(df)

    def test_validate_missing_columns(self):
        df = self._valid_frame().drop(columns=["value"])
        with pytest.raises(BoEValidationError, match="Missing required columns"):
            boe_base_rate.validate_data(df)

    def test_validate_bad_geography(self):
        df = self._valid_frame()
        df["geography"] = "IE"
        with pytest.raises(BoEValidationError, match="geography"):
            boe_base_rate.validate_data(df)

    def test_validate_bad_source(self):
        df = self._valid_frame()
        df["source"] = "ECB"
        with pytest.raises(BoEValidationError, match="source"):
            boe_base_rate.validate_data(df)

    def test_validate_bad_series(self):
        df = self._valid_frame()
        df["series"] = "cpi"
        with pytest.raises(BoEValidationError, match="series"):
            boe_base_rate.validate_data(df)

    def test_validate_bad_unit(self):
        df = self._valid_frame()
        df["unit"] = "bps"
        with pytest.raises(BoEValidationError, match="unit"):
            boe_base_rate.validate_data(df)

    def test_validate_bad_resolution(self):
        df = self._valid_frame()
        df["resolution"] = "weekly"
        with pytest.raises(BoEValidationError, match="resolution"):
            boe_base_rate.validate_data(df)

    def test_validate_non_numeric_value(self):
        df = self._valid_frame()
        df["value"] = "high"
        with pytest.raises(BoEValidationError, match="numeric"):
            boe_base_rate.validate_data(df)

    def test_validate_null_value(self):
        df = self._valid_frame()
        df["value"] = pd.array([None], dtype="Float64").astype("float64")
        with pytest.raises(BoEValidationError, match="nulls"):
            boe_base_rate.validate_data(df)

    def test_validate_negative_values(self):
        df = self._valid_frame()
        df["value"] = -1.0
        with pytest.raises(BoEValidationError, match="0-25"):
            boe_base_rate.validate_data(df)

    def test_validate_implausibly_high_value(self):
        df = self._valid_frame()
        df["value"] = 99.0
        with pytest.raises(BoEValidationError, match="0-25"):
            boe_base_rate.validate_data(df)
