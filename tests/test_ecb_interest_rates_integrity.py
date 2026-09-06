"""Data-integrity and validation tests for :mod:`bolster.data_sources.ecb_interest_rates`.

Integrity tests hit the live ECB Data Portal SDMX-JSON API (no mocks) and use
``scope="class"`` fixtures so each series is downloaded once per class.
Validation tests are pure-Python edge cases that need no network access.
"""

import pandas as pd
import pytest

from bolster.data_sources import ecb_interest_rates
from bolster.data_sources.ecb_interest_rates import ECBDataError, ECBValidationError


class TestDataIntegrity:
    """Live-data checks against the published ECB key interest rate series."""

    @pytest.fixture(scope="class")
    def monthly_all(self):
        return ecb_interest_rates.get_latest_data(rate="all", resolution="monthly")

    @pytest.fixture(scope="class")
    def dfr_annual(self):
        return ecb_interest_rates.get_series("dfr", resolution="annual")

    @pytest.fixture(scope="class")
    def dfr_changes(self):
        return ecb_interest_rates.get_rate_changes("dfr")

    def test_schema_columns(self, monthly_all):
        assert list(monthly_all.columns) == ecb_interest_rates.SCHEMA_COLUMNS

    def test_not_empty(self, monthly_all):
        assert len(monthly_all) > 0

    def test_geography_is_eurozone(self, monthly_all):
        assert set(monthly_all["geography"].unique()) == {"Eurozone"}

    def test_source_is_ecb(self, monthly_all):
        assert set(monthly_all["source"].unique()) == {"ECB"}

    def test_all_three_series_present(self, monthly_all):
        assert set(monthly_all["series"].unique()) == {"mrr_fr", "dfr", "mlfr"}

    def test_unit_is_percent(self, monthly_all):
        assert set(monthly_all["unit"].unique()) == {"%"}

    def test_rate_reasonable_range(self, monthly_all):
        # ECB rates have ranged from -0.5% (DFR, negative-rate era) to 5.75% (MLFR peak).
        assert monthly_all["value"].min() >= -1
        assert monthly_all["value"].max() <= 10

    def test_value_is_float(self, monthly_all):
        assert pd.api.types.is_float_dtype(monthly_all["value"])

    def test_no_null_values(self, monthly_all):
        assert not monthly_all["value"].isna().any()

    def test_monthly_has_month_no_quarter(self, monthly_all):
        assert monthly_all["month"].notna().all()
        assert monthly_all["quarter"].isna().all()

    def test_dates_are_period_start(self, monthly_all):
        assert (monthly_all["date"].dt.day == 1).all()

    def test_historical_coverage(self, dfr_annual):
        # All three rates run back to the euro's 1999 introduction.
        assert dfr_annual["date"].min() <= pd.Timestamp("1999-01-01")

    def test_extends_to_current_period(self, monthly_all):
        # Forward-filled to today, not just to the last recorded rate change.
        assert monthly_all["date"].max() >= pd.Timestamp.now().normalize().replace(day=1) - pd.DateOffset(months=2)

    def test_resolutions_available(self):
        for resolution in ("monthly", "quarterly", "annual"):
            df = ecb_interest_rates.get_latest_data(rate="mrr_fr", resolution=resolution)
            assert len(df) > 0
            assert set(df["resolution"].unique()) == {resolution}
            assert ecb_interest_rates.validate_data(df)

    def test_quarterly_labels(self):
        df = ecb_interest_rates.get_series("mlfr", resolution="quarterly")
        assert set(df["quarter"].dropna().unique()) <= {"Q1", "Q2", "Q3", "Q4"}
        assert df["month"].isna().all()

    def test_coarser_resolution_has_fewer_rows(self, monthly_all):
        annual = ecb_interest_rates.get_latest_data(rate="dfr", resolution="annual")
        monthly = ecb_interest_rates.get_series("dfr", resolution="monthly")
        assert len(annual) < len(monthly)

    def test_invalid_resolution_raises(self):
        with pytest.raises(ValueError):
            ecb_interest_rates.get_series("dfr", resolution="weekly")

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError):
            ecb_interest_rates.get_series("made_up_rate")

    def test_invalid_rate_in_get_latest_data_raises(self):
        with pytest.raises(ValueError):
            ecb_interest_rates.get_latest_data(rate="made_up_rate")

    def test_rate_changes_schema(self, dfr_changes):
        assert list(dfr_changes.columns) == ecb_interest_rates.RATE_CHANGES_COLUMNS

    def test_rate_changes_historical_depth(self, dfr_changes):
        assert dfr_changes["date"].min() <= pd.Timestamp("1999-02-01")
        assert len(dfr_changes) > 20

    def test_rate_changes_sorted_and_valued(self, dfr_changes):
        assert dfr_changes["date"].is_monotonic_increasing
        assert not dfr_changes["value"].isna().any()
        assert dfr_changes["value"].between(-1, 10).all()
        assert set(dfr_changes["geography"].unique()) == {"Eurozone"}
        assert set(dfr_changes["source"].unique()) == {"ECB"}
        assert set(dfr_changes["series"].unique()) == {"dfr"}

    def test_dfr_includes_negative_rate_era(self, dfr_changes):
        # DFR went negative from mid-2014 to mid-2022.
        assert (dfr_changes["value"] < 0).any()

    def test_schema_compatible_with_boe_base_rate(self, monthly_all):
        # The three macro modules must share identical schema columns so they
        # can be concatenated without realigning/introducing NaN columns.
        boe_like = pd.DataFrame(
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
        combined = pd.concat([monthly_all, boe_like], ignore_index=True)
        assert list(combined.columns) == ecb_interest_rates.SCHEMA_COLUMNS
        assert len(combined) == len(monthly_all) + 1

    def test_validate_live_data(self, monthly_all):
        assert ecb_interest_rates.validate_data(monthly_all) is True


class TestInternals:
    """Unit tests for the parse/fill helpers using stub SDMX-JSON (no network)."""

    def _stub_response(self, dates: list[str], values: list[float | None]):
        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "dataSets": [
                        {"series": {"0:0:0:0:0:0:0": {"observations": {str(i): [v] for i, v in enumerate(values)}}}}
                    ],
                    "structure": {"dimensions": {"observation": [{"values": [{"id": d} for d in dates]}]}},
                }

        return _Resp()

    def test_fetch_change_events_parses_observations(self, monkeypatch):
        resp = self._stub_response(["1999-01-01", "1999-01-04"], [3.0, 2.5])
        monkeypatch.setattr(ecb_interest_rates.session, "get", lambda *a, **k: resp)
        events = ecb_interest_rates._fetch_change_events("mrr_fr")
        assert events["value"].tolist() == [3.0, 2.5]
        assert pd.api.types.is_float_dtype(events["value"])

    def test_fetch_change_events_skips_null_observations(self, monkeypatch):
        resp = self._stub_response(["1999-01-01", "1999-01-04"], [3.0, None])
        monkeypatch.setattr(ecb_interest_rates.session, "get", lambda *a, **k: resp)
        events = ecb_interest_rates._fetch_change_events("dfr")
        assert len(events) == 1
        assert events["value"].tolist() == [3.0]

    def test_fetch_change_events_no_observations_raises(self, monkeypatch):
        resp = self._stub_response(["1999-01-01"], [None])
        monkeypatch.setattr(ecb_interest_rates.session, "get", lambda *a, **k: resp)
        with pytest.raises(ECBDataError, match="No observations"):
            ecb_interest_rates._fetch_change_events("dfr")

    def test_fetch_change_events_unexpected_shape_raises(self, monkeypatch):
        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"unexpected": "shape"}

        monkeypatch.setattr(ecb_interest_rates.session, "get", lambda *a, **k: _Resp())
        with pytest.raises(ECBDataError, match="Unexpected SDMX-JSON shape"):
            ecb_interest_rates._fetch_change_events("dfr")

    def test_fetch_change_events_invalid_rate_raises(self):
        with pytest.raises(ValueError, match="Unknown rate"):
            ecb_interest_rates._fetch_change_events("not_a_rate")

    def test_fetch_change_events_download_failure_wrapped(self, monkeypatch):
        def _raise(*a, **k):
            raise ConnectionError("boom")

        monkeypatch.setattr(ecb_interest_rates.session, "get", _raise)
        with pytest.raises(ECBDataError, match="Failed to fetch"):
            ecb_interest_rates._fetch_change_events("dfr")

    def test_daily_filled_forward_fills_and_extends_to_today(self):
        events = pd.DataFrame({"date": pd.to_datetime(["2020-01-01", "2020-01-10"]), "value": [1.0, 2.0]})
        daily = ecb_interest_rates._daily_filled(events)
        assert daily.index.max() == pd.Timestamp.now().normalize()
        assert daily.loc["2020-01-05"] == 1.0
        assert daily.loc["2020-01-15"] == 2.0
        assert daily.iloc[-1] == 2.0

    def test_attach_schema_monthly(self):
        src = pd.DataFrame({"date": pd.to_datetime(["2024-06-01"]), "value": [3.75]})
        out = ecb_interest_rates._attach_schema(src, "monthly", "mrr_fr")
        assert list(out.columns) == ecb_interest_rates.SCHEMA_COLUMNS
        assert out.loc[0, "resolution"] == "monthly"
        assert out.loc[0, "series"] == "mrr_fr"
        assert out.loc[0, "month"] == 6
        assert pd.isna(out.loc[0, "quarter"])

    def test_attach_schema_quarterly(self):
        src = pd.DataFrame({"date": pd.to_datetime(["2024-04-01"]), "value": [2.0]})
        out = ecb_interest_rates._attach_schema(src, "quarterly", "dfr")
        assert out.loc[0, "quarter"] == "Q2"
        assert pd.isna(out.loc[0, "month"])

    def test_attach_schema_annual(self):
        src = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "value": [3.25]})
        out = ecb_interest_rates._attach_schema(src, "annual", "mlfr")
        assert pd.isna(out.loc[0, "quarter"])
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
                "series": ["dfr"],
                "value": [2.25],
                "unit": ["%"],
                "geography": ["Eurozone"],
                "source": ["ECB"],
            }
        )

    def test_validate_valid_frame(self):
        assert ecb_interest_rates.validate_data(self._valid_frame()) is True

    def test_validate_negative_but_plausible_value(self):
        df = self._valid_frame()
        df["value"] = -0.5
        assert ecb_interest_rates.validate_data(df) is True

    def test_validate_empty_dataframe(self):
        df = self._valid_frame().iloc[0:0]
        with pytest.raises(ECBValidationError, match="empty"):
            ecb_interest_rates.validate_data(df)

    def test_validate_missing_columns(self):
        df = self._valid_frame().drop(columns=["value"])
        with pytest.raises(ECBValidationError, match="Missing required columns"):
            ecb_interest_rates.validate_data(df)

    def test_validate_bad_geography(self):
        df = self._valid_frame()
        df["geography"] = "UK"
        with pytest.raises(ECBValidationError, match="geography"):
            ecb_interest_rates.validate_data(df)

    def test_validate_bad_source(self):
        df = self._valid_frame()
        df["source"] = "BoE"
        with pytest.raises(ECBValidationError, match="source"):
            ecb_interest_rates.validate_data(df)

    def test_validate_bad_series(self):
        df = self._valid_frame()
        df["series"] = "base_rate"
        with pytest.raises(ECBValidationError, match="series"):
            ecb_interest_rates.validate_data(df)

    def test_validate_bad_unit(self):
        df = self._valid_frame()
        df["unit"] = "bps"
        with pytest.raises(ECBValidationError, match="unit"):
            ecb_interest_rates.validate_data(df)

    def test_validate_bad_resolution(self):
        df = self._valid_frame()
        df["resolution"] = "daily"
        with pytest.raises(ECBValidationError, match="resolution"):
            ecb_interest_rates.validate_data(df)

    def test_validate_non_numeric_value(self):
        df = self._valid_frame()
        df["value"] = "high"
        with pytest.raises(ECBValidationError, match="numeric"):
            ecb_interest_rates.validate_data(df)

    def test_validate_null_value(self):
        df = self._valid_frame()
        df["value"] = pd.array([None], dtype="Float64").astype("float64")
        with pytest.raises(ECBValidationError, match="nulls"):
            ecb_interest_rates.validate_data(df)

    def test_validate_implausibly_negative_value(self):
        df = self._valid_frame()
        df["value"] = -5.0
        with pytest.raises(ECBValidationError, match="-1% to 25%"):
            ecb_interest_rates.validate_data(df)

    def test_validate_implausibly_high_value(self):
        df = self._valid_frame()
        df["value"] = 99.0
        with pytest.raises(ECBValidationError, match="-1% to 25%"):
            ecb_interest_rates.validate_data(df)
