"""Data integrity and validation tests for the ONS CPI/CPIH/RPI module.

Integrity tests hit the live ONS time-series API (no mocks, per project
standards) using ``scope="class"`` fixtures so each resolution is fetched once.
Validation tests construct in-memory frames and need no network access.
"""

import pandas as pd
import pytest

from bolster.data_sources import ons_cpi
from bolster.data_sources.ons_cpi import ONSValidationError

SCHEMA_COLUMNS = [
    "date",
    "year",
    "quarter",
    "month",
    "resolution",
    "series",
    "value",
    "unit",
    "geography",
    "source",
]


def _valid_frame() -> pd.DataFrame:
    """A minimal schema-conformant frame for validation tests."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "year": [2024, 2024],
            "quarter": [pd.NA, pd.NA],
            "month": [1, 1],
            "resolution": ["monthly", "monthly"],
            "series": ["D7G7", "L55O"],
            "value": [4.0, 4.2],
            "unit": ["%", "%"],
            "geography": ["UK", "UK"],
            "source": ["ONS", "ONS"],
        }
    )


class TestDataIntegrity:
    """Tests against live ONS data at annual resolution."""

    @pytest.fixture(scope="class")
    def latest_data(self):
        return ons_cpi.get_latest_data(resolution="annual")

    def test_required_columns(self, latest_data):
        assert not latest_data.empty
        for col in SCHEMA_COLUMNS:
            assert col in latest_data.columns

    def test_schema_columns(self, latest_data):
        # Exactly the canonical schema columns, no more, no less.
        assert sorted(latest_data.columns) == sorted(SCHEMA_COLUMNS)

    def test_all_series_present(self, latest_data):
        assert set(latest_data["series"].unique()) == set(ons_cpi.SERIES)

    def test_geography_is_uk(self, latest_data):
        assert set(latest_data["geography"].unique()) == {"UK"}

    def test_source_is_ons(self, latest_data):
        assert set(latest_data["source"].unique()) == {"ONS"}

    def test_resolution_is_annual(self, latest_data):
        assert set(latest_data["resolution"].unique()) == {"annual"}

    def test_annual_has_no_quarter_or_month(self, latest_data):
        assert latest_data["quarter"].isna().all()
        assert latest_data["month"].isna().all()

    def test_value_is_numeric(self, latest_data):
        assert pd.api.types.is_numeric_dtype(latest_data["value"])
        assert not latest_data["value"].isna().any()

    def test_cpi_annual_rate_reasonable(self, latest_data):
        # Annual-rate series should sit within a plausible historical band.
        rate_codes = [c for c, m in ons_cpi.SERIES.items() if m["unit"] == "%"]
        rates = latest_data[latest_data["series"].isin(rate_codes)]
        assert not rates.empty
        assert rates["value"].between(-5, 30).all()

    def test_index_values_positive(self, latest_data):
        index_codes = [c for c, m in ons_cpi.SERIES.items() if m["unit"].startswith("Index")]
        indices = latest_data[latest_data["series"].isin(index_codes)]
        assert not indices.empty
        assert (indices["value"] > 0).all()

    def test_historical_coverage(self, latest_data):
        # RPI annual-rate (CZBH) is the longest annual run; back to the 1940s/50s.
        rpi = latest_data[latest_data["series"] == "CZBH"]
        assert not rpi.empty
        assert rpi["year"].min() <= 1950

    def test_rpi_monthly_back_to_1948(self):
        # Monthly/quarterly RPI runs back to 1948.
        rpi_monthly = ons_cpi.get_series("CZBH", resolution="monthly")
        assert int(rpi_monthly["year"].min()) <= 1948

    def test_validate_live_data(self, latest_data):
        assert ons_cpi.validate_data(latest_data) is True


class TestResolutions:
    """Each resolution returns well-formed, distinct data."""

    def test_resolutions_available(self):
        for resolution in ("monthly", "quarterly", "annual"):
            df = ons_cpi.get_series("D7G7", resolution=resolution)
            assert not df.empty
            assert set(df["resolution"].unique()) == {resolution}

    def test_monthly_has_month_not_quarter(self):
        df = ons_cpi.get_series("D7G7", resolution="monthly")
        assert df["month"].notna().all()
        assert df["quarter"].isna().all()
        assert df["month"].between(1, 12).all()

    def test_quarterly_has_quarter_not_month(self):
        df = ons_cpi.get_series("D7G7", resolution="quarterly")
        assert df["quarter"].notna().all()
        assert df["month"].isna().all()
        assert set(df["quarter"].unique()).issubset({"Q1", "Q2", "Q3", "Q4"})

    def test_date_is_period_start(self):
        df = ons_cpi.get_series("D7G7", resolution="monthly")
        # date month must match the integer month column for monthly data.
        assert (df["date"].dt.month == df["month"]).all()
        assert (df["date"].dt.day == 1).all()

    def test_quarterly_date_is_quarter_start(self):
        df = ons_cpi.get_series("D7G7", resolution="quarterly")
        quarter_start_month = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}
        expected = df["quarter"].map(quarter_start_month)
        assert (df["date"].dt.month == expected).all()


class TestErrors:
    """Argument-handling and error paths."""

    def test_unknown_series_raises(self):
        with pytest.raises(ValueError):
            ons_cpi.get_series("NOPE", resolution="annual")

    def test_unknown_resolution_raises(self):
        with pytest.raises(ValueError):
            ons_cpi.get_series("D7G7", resolution="weekly")

    def test_get_latest_unknown_resolution_raises(self):
        with pytest.raises(ValueError):
            ons_cpi.get_latest_data(resolution="weekly")

    def test_series_code_case_insensitive(self):
        df = ons_cpi.get_series("d7g7", resolution="annual")
        assert set(df["series"].unique()) == {"D7G7"}


class TestRowParsing:
    """Unit tests for the row->record converter (no network)."""

    def test_skips_missing_value(self):
        row = {"value": "", "year": "2024", "month": "January"}
        assert ons_cpi._row_to_record(row, "monthly", "D7G7", "%") is None

    def test_skips_placeholder_value(self):
        row = {"value": "-", "year": "2024", "month": "January"}
        assert ons_cpi._row_to_record(row, "monthly", "D7G7", "%") is None

    def test_skips_unparseable_value(self):
        row = {"value": "n/a", "year": "2024", "month": "January"}
        assert ons_cpi._row_to_record(row, "monthly", "D7G7", "%") is None

    def test_skips_bad_year(self):
        row = {"value": "4.0", "year": "", "month": "January"}
        assert ons_cpi._row_to_record(row, "monthly", "D7G7", "%") is None

    def test_skips_bad_month(self):
        row = {"value": "4.0", "year": "2024", "month": "Smarch"}
        assert ons_cpi._row_to_record(row, "monthly", "D7G7", "%") is None

    def test_skips_bad_quarter(self):
        row = {"value": "4.0", "year": "2024", "quarter": "Q5"}
        assert ons_cpi._row_to_record(row, "quarterly", "D7G7", "%") is None

    def test_monthly_record(self):
        row = {"value": "4.0", "year": "2024", "month": "March"}
        rec = ons_cpi._row_to_record(row, "monthly", "D7G7", "%")
        assert rec["month"] == 3
        assert rec["quarter"] is pd.NA
        assert rec["date"] == pd.Timestamp("2024-03-01")

    def test_quarterly_record(self):
        row = {"value": "4.0", "year": "2024", "quarter": "Q3"}
        rec = ons_cpi._row_to_record(row, "quarterly", "D7G7", "%")
        assert rec["quarter"] == "Q3"
        assert rec["month"] is pd.NA
        assert rec["date"] == pd.Timestamp("2024-07-01")

    def test_annual_record(self):
        row = {"value": "4.0", "year": "2024"}
        rec = ons_cpi._row_to_record(row, "annual", "D7G7", "%")
        assert rec["quarter"] is pd.NA
        assert rec["month"] is pd.NA
        assert rec["date"] == pd.Timestamp("2024-01-01")


class TestValidation:
    """Validation edge cases — no network calls needed."""

    def test_validate_valid_frame(self):
        assert ons_cpi.validate_data(_valid_frame()) is True

    def test_validate_empty_dataframe(self):
        df = pd.DataFrame(columns=SCHEMA_COLUMNS)
        with pytest.raises(ONSValidationError):
            ons_cpi.validate_data(df)

    def test_validate_missing_columns(self):
        df = _valid_frame().drop(columns=["unit"])
        with pytest.raises(ONSValidationError):
            ons_cpi.validate_data(df)

    def test_validate_wrong_geography(self):
        df = _valid_frame()
        df.loc[0, "geography"] = "NI"
        with pytest.raises(ONSValidationError):
            ons_cpi.validate_data(df)

    def test_validate_wrong_source(self):
        df = _valid_frame()
        df.loc[0, "source"] = "NISRA"
        with pytest.raises(ONSValidationError):
            ons_cpi.validate_data(df)

    def test_validate_bad_resolution(self):
        df = _valid_frame()
        df.loc[0, "resolution"] = "weekly"
        with pytest.raises(ONSValidationError):
            ons_cpi.validate_data(df)

    def test_validate_non_numeric_value(self):
        df = _valid_frame()
        df["value"] = df["value"].astype(str)
        with pytest.raises(ONSValidationError):
            ons_cpi.validate_data(df)

    def test_validate_null_value(self):
        df = _valid_frame()
        df.loc[0, "value"] = None
        with pytest.raises(ONSValidationError):
            ons_cpi.validate_data(df)
