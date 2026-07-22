"""Integrity tests for the NI electricity consumption and renewable generation module."""

import pandas as pd
import pytest

from bolster.data_sources import electricity_renewables


class TestDataIntegrity:
    @pytest.fixture(scope="class")
    def latest_data(self):
        return electricity_renewables.get_latest_data()

    @pytest.fixture(scope="class")
    def renewable_pct(self, latest_data):
        return latest_data["renewable_pct"]

    @pytest.fixture(scope="class")
    def consumption(self, latest_data):
        return latest_data["consumption"]

    @pytest.fixture(scope="class")
    def generation_by_technology(self, latest_data):
        return latest_data["generation_by_technology"]

    @pytest.fixture(scope="class")
    def generation_monthly(self, latest_data):
        return latest_data["generation_monthly"]

    def test_returns_all_keys(self, latest_data):
        assert set(latest_data.keys()) == {
            "renewable_pct",
            "consumption",
            "generation_by_technology",
            "generation_monthly",
        }

    # ── renewable_pct ─────────────────────────────────────────────────────────

    def test_renewable_pct_required_columns(self, renewable_pct):
        assert {"date", "renewable_pct_rolling_12m", "renewable_pct_monthly"}.issubset(
            renewable_pct.columns
        )

    def test_renewable_pct_date_type(self, renewable_pct):
        assert pd.api.types.is_datetime64_any_dtype(renewable_pct["date"])

    def test_renewable_pct_historical_coverage(self, renewable_pct):
        assert renewable_pct["date"].min() <= pd.Timestamp("2019-03-01")
        assert renewable_pct["date"].max() >= pd.Timestamp("2025-01-01")

    def test_renewable_pct_min_rows(self, renewable_pct):
        assert len(renewable_pct) >= 10

    def test_renewable_pct_rolling_range(self, renewable_pct):
        pct = renewable_pct["renewable_pct_rolling_12m"].dropna()
        assert (pct >= 0).all()
        assert (pct <= 100).all()

    def test_renewable_pct_plausible_values(self, renewable_pct):
        # NI has been 40–55% renewable for recent years
        pct = renewable_pct["renewable_pct_rolling_12m"].dropna()
        assert pct.max() >= 40
        assert pct.min() >= 20

    def test_renewable_pct_latest_approximately_48pct(self, renewable_pct):
        # As of March 2026 rolling 12-month = 48%
        latest = renewable_pct.sort_values("date").iloc[-1]["renewable_pct_rolling_12m"]
        assert 30 <= latest <= 70

    def test_renewable_pct_monthly_range(self, renewable_pct):
        monthly = renewable_pct["renewable_pct_monthly"].dropna()
        assert (monthly >= 0).all()
        assert (monthly <= 100).all()

    # ── consumption ───────────────────────────────────────────────────────────

    def test_consumption_required_columns(self, consumption):
        assert {
            "date",
            "total_consumption_gwh",
            "renewable_generation_gwh",
            "non_renewable_generation_gwh",
        }.issubset(consumption.columns)

    def test_consumption_non_negative(self, consumption):
        for col in ("total_consumption_gwh", "renewable_generation_gwh"):
            assert (consumption[col].dropna() >= 0).all(), f"{col} has negative values"

    def test_consumption_plausible_total(self, consumption):
        # NI annual electricity consumption typically 8 000–10 000 GWh rolling 12-month
        median_total = consumption["total_consumption_gwh"].dropna().median()
        assert 5000 <= median_total <= 15000

    def test_consumption_historical_coverage(self, consumption):
        assert consumption["date"].min() <= pd.Timestamp("2019-03-01")
        assert consumption["date"].max() >= pd.Timestamp("2025-01-01")

    def test_consumption_latest_total_gwh(self, consumption):
        # Rolling 12m ending March 2026 = 8818 GWh (allow ±10%)
        latest = consumption.sort_values("date").iloc[-1]["total_consumption_gwh"]
        assert 7000 <= latest <= 12000

    # ── generation_by_technology ──────────────────────────────────────────────

    def test_technology_required_columns(self, generation_by_technology):
        assert {"date", "wind_gwh", "solar_pv_gwh"}.issubset(
            generation_by_technology.columns
        )

    def test_technology_all_non_negative(self, generation_by_technology):
        tech_cols = ["wind_gwh", "hydro_gwh", "bioenergy_gwh", "landfill_gas_gwh", "solar_pv_gwh"]
        for col in tech_cols:
            vals = generation_by_technology[col].dropna()
            assert (vals >= 0).all(), f"{col} has negative values"

    def test_technology_wind_dominates(self, generation_by_technology):
        # Wind is the largest NI renewable technology
        latest = generation_by_technology.sort_values("date").iloc[-1]
        assert latest["wind_gwh"] > latest["solar_pv_gwh"]
        assert latest["wind_gwh"] > latest["hydro_gwh"]

    def test_technology_historical_coverage(self, generation_by_technology):
        assert generation_by_technology["date"].min() <= pd.Timestamp("2019-03-01")
        assert generation_by_technology["date"].max() >= pd.Timestamp("2025-01-01")

    # ── generation_monthly ────────────────────────────────────────────────────

    def test_monthly_required_columns(self, generation_monthly):
        assert {
            "date",
            "renewable_generation_gwh",
            "non_renewable_generation_gwh",
        }.issubset(generation_monthly.columns)

    def test_monthly_historical_coverage(self, generation_monthly):
        # Monthly data goes back to February 2018
        assert generation_monthly["date"].min() <= pd.Timestamp("2018-04-01")
        assert generation_monthly["date"].max() >= pd.Timestamp("2025-01-01")

    def test_monthly_non_negative(self, generation_monthly):
        for col in ("renewable_generation_gwh", "non_renewable_generation_gwh"):
            assert (generation_monthly[col].dropna() >= 0).all()

    def test_monthly_has_more_rows_than_rolling(self, generation_monthly, renewable_pct):
        # Monthly goes back further (2018) while rolling 12m starts 2019
        assert len(generation_monthly) >= len(renewable_pct)

    def test_year_month_helper_columns(self, generation_monthly):
        assert "year" in generation_monthly.columns
        assert "month" in generation_monthly.columns
        assert generation_monthly["year"].min() <= 2018
        assert generation_monthly["month"].between(1, 12).all()


class TestValidation:
    """Unit tests for validation edge cases — no network calls needed."""

    def test_validate_empty_dataframe(self):
        with pytest.raises(electricity_renewables.ElectricityValidationError, match="empty"):
            electricity_renewables.validate_data(pd.DataFrame(), "renewable_pct")

    def test_validate_missing_required_columns(self):
        df = pd.DataFrame({"date": pd.date_range("2020-01", periods=15, freq="ME")})
        with pytest.raises(
            electricity_renewables.ElectricityValidationError, match="missing required"
        ):
            electricity_renewables.validate_data(df, "renewable_pct")

    def test_validate_too_few_rows(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2020-01", periods=5, freq="ME"),
                "renewable_pct_rolling_12m": [40.0] * 5,
                "renewable_pct_monthly": [38.0] * 5,
            }
        )
        with pytest.raises(
            electricity_renewables.ElectricityValidationError, match="rows"
        ):
            electricity_renewables.validate_data(df, "renewable_pct")

    def test_validate_pct_out_of_range(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2019-01", periods=12, freq="ME"),
                "renewable_pct_rolling_12m": [150.0] * 12,
                "renewable_pct_monthly": [38.0] * 12,
            }
        )
        with pytest.raises(
            electricity_renewables.ElectricityValidationError, match="outside"
        ):
            electricity_renewables.validate_data(df, "renewable_pct")

    def test_validate_pct_implausibly_low(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2019-01", periods=12, freq="ME"),
                "renewable_pct_rolling_12m": [5.0] * 12,
                "renewable_pct_monthly": [5.0] * 12,
            }
        )
        with pytest.raises(
            electricity_renewables.ElectricityValidationError, match="implausibly low"
        ):
            electricity_renewables.validate_data(df, "renewable_pct")

    def test_validate_negative_consumption(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2019-01", periods=12, freq="ME"),
                "total_consumption_gwh": [-100.0] * 12,
                "renewable_generation_gwh": [4000.0] * 12,
                "non_renewable_generation_gwh": [4000.0] * 12,
                "net_imports_gwh": [800.0] * 12,
            }
        )
        with pytest.raises(
            electricity_renewables.ElectricityValidationError, match="negative"
        ):
            electricity_renewables.validate_data(df, "consumption")

    def test_validate_implausibly_low_consumption(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2019-01", periods=12, freq="ME"),
                "total_consumption_gwh": [100.0] * 12,
                "renewable_generation_gwh": [50.0] * 12,
                "non_renewable_generation_gwh": [50.0] * 12,
                "net_imports_gwh": [0.0] * 12,
            }
        )
        with pytest.raises(
            electricity_renewables.ElectricityValidationError, match="implausibly low"
        ):
            electricity_renewables.validate_data(df, "consumption")

    def test_validate_valid_data_returns_true(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2019-01", periods=12, freq="ME"),
                "renewable_pct_rolling_12m": [45.0] * 12,
                "renewable_pct_monthly": [42.0] * 12,
            }
        )
        assert electricity_renewables.validate_data(df, "renewable_pct") is True

    def test_validate_unknown_key_passes_basic_checks(self):
        df = pd.DataFrame(
            {
                "date": pd.date_range("2019-01", periods=12, freq="ME"),
                "some_col": [1.0] * 12,
            }
        )
        assert electricity_renewables.validate_data(df, "unknown_key") is True
