"""Data integrity tests for NISRA economic output indexes (IOP and IOS).

Tests validate structure and consistency of the Index of Production and
Index of Services quarterly series using real data from NISRA publications.
"""

import datetime

import pytest

from bolster.data_sources.nisra import index_of_production as iop
from bolster.data_sources.nisra import index_of_services as ios


class TestIndexOfProductionIntegrity:
    """Test suite for NI Index of Production data."""

    @pytest.fixture(scope="class")
    def latest_iop(self):
        return iop.get_latest_iop(force_refresh=False)

    def test_not_empty(self, latest_iop):
        assert len(latest_iop) > 0

    def test_required_columns(self, latest_iop):
        required = {"date", "year", "quarter", "quarter_label", "ni_index", "uk_index"}
        assert required.issubset(set(latest_iop.columns))

    def test_historical_coverage(self, latest_iop):
        assert latest_iop["year"].min() <= 2005

    def test_recent_data(self, latest_iop):
        current_year = datetime.datetime.now().year
        assert latest_iop["year"].max() >= current_year - 1

    def test_84_quarters(self, latest_iop):
        # Q1 2005 to Q4 2025 = 84 quarters (update as new quarters land)
        assert len(latest_iop) >= 80

    def test_four_quarters_per_year(self, latest_iop):
        # Every complete year should have exactly 4 quarters
        complete_years = latest_iop.groupby("year")["quarter"].count()
        complete = complete_years[complete_years.index < datetime.datetime.now().year]
        assert (complete == 4).all(), f"Missing quarters: {complete[complete != 4]}"

    def test_chronological_order(self, latest_iop):
        assert latest_iop["date"].is_monotonic_increasing

    def test_no_negative_values(self, latest_iop):
        assert (latest_iop["ni_index"] > 0).all()
        assert (latest_iop["uk_index"] > 0).all()

    def test_index_plausible_range(self, latest_iop):
        # Index values should be between 50 and 150 for a 2020=100 series
        assert (latest_iop["ni_index"] > 50).all()
        assert (latest_iop["ni_index"] < 150).all()

    def test_validate_function(self, latest_iop):
        assert iop.validate_iop_data(latest_iop)

    def test_validate_rejects_empty(self):
        import pandas as pd

        with pytest.raises(iop.NISRAValidationError):
            iop.validate_iop_data(pd.DataFrame())

    def test_get_iop_by_year(self, latest_iop):
        df_2024 = iop.get_iop_by_year(latest_iop, 2024)
        assert len(df_2024) == 4
        assert (df_2024["year"] == 2024).all()

    def test_growth_rates(self, latest_iop):
        growth = iop.get_iop_growth(latest_iop)
        assert "ni_yoy" in growth.columns
        assert "ni_qoq" in growth.columns
        assert "uk_yoy" in growth.columns
        # First 4 rows have no YoY (no prior year)
        assert growth["ni_yoy"].iloc[:4].isna().all()
        # Rest should have values
        assert growth["ni_yoy"].iloc[4:].notna().all()

    def test_ni_outperforms_uk_production_recent(self, latest_iop):
        # NI production has been above UK index in recent quarters
        recent = latest_iop[latest_iop["year"] >= 2024]
        ni_avg = recent["ni_index"].mean()
        uk_avg = recent["uk_index"].mean()
        assert ni_avg > uk_avg, f"NI ({ni_avg:.1f}) should exceed UK ({uk_avg:.1f}) production index recently"


class TestIndexOfServicesIntegrity:
    """Test suite for NI Index of Services data."""

    @pytest.fixture(scope="class")
    def latest_ios(self):
        return ios.get_latest_ios(force_refresh=False)

    def test_not_empty(self, latest_ios):
        assert len(latest_ios) > 0

    def test_required_columns(self, latest_ios):
        required = {"date", "year", "quarter", "quarter_label", "ni_index", "uk_index"}
        assert required.issubset(set(latest_ios.columns))

    def test_historical_coverage(self, latest_ios):
        assert latest_ios["year"].min() <= 2005

    def test_recent_data(self, latest_ios):
        current_year = datetime.datetime.now().year
        assert latest_ios["year"].max() >= current_year - 1

    def test_four_quarters_per_year(self, latest_ios):
        complete_years = latest_ios.groupby("year")["quarter"].count()
        complete = complete_years[complete_years.index < datetime.datetime.now().year]
        assert (complete == 4).all(), f"Missing quarters: {complete[complete != 4]}"

    def test_chronological_order(self, latest_ios):
        assert latest_ios["date"].is_monotonic_increasing

    def test_no_negative_values(self, latest_ios):
        assert (latest_ios["ni_index"] > 0).all()
        assert (latest_ios["uk_index"] > 0).all()

    def test_index_plausible_range(self, latest_ios):
        # Index values should be between 50 and 150 for a 2020=100 series
        assert (latest_ios["ni_index"] > 50).all()
        assert (latest_ios["ni_index"] < 150).all()

    def test_validate_function(self, latest_ios):
        assert ios.validate_ios_data(latest_ios)

    def test_validate_rejects_missing_columns(self):
        import pandas as pd

        bad = pd.DataFrame({"year": [2024], "quarter": [1]})
        with pytest.raises(ios.NISRAValidationError):
            ios.validate_ios_data(bad)

    def test_get_ios_by_year(self, latest_ios):
        df_2024 = ios.get_ios_by_year(latest_ios, 2024)
        assert len(df_2024) == 4
        assert (df_2024["year"] == 2024).all()

    def test_growth_rates(self, latest_ios):
        growth = ios.get_ios_growth(latest_ios)
        assert "ni_yoy" in growth.columns
        assert growth["ni_yoy"].iloc[:4].isna().all()
        assert growth["ni_yoy"].iloc[4:].notna().all()

    def test_covid_dip_visible(self, latest_ios):
        # Q2 2020 should show the sharpest dip (lockdown quarter)
        df_2020 = latest_ios[latest_ios["year"] == 2020]
        q2_ni = df_2020[df_2020["quarter"] == 2]["ni_index"].values[0]
        # Q2 2020 NI services should be well below 100
        assert q2_ni < 90, f"Q2 2020 NI services ({q2_ni:.1f}) should show COVID dip"


class TestIopIosAlignment:
    """Cross-validate that IOP and IOS cover the same date range."""

    @pytest.fixture(scope="class")
    def both(self):
        return iop.get_latest_iop(force_refresh=False), ios.get_latest_ios(force_refresh=False)

    def test_same_date_range(self, both):
        df_iop, df_ios = both
        assert df_iop["year"].min() == df_ios["year"].min()
        assert df_iop["year"].max() == df_ios["year"].max()
        assert df_iop["quarter"].iloc[-1] == df_ios["quarter"].iloc[-1]

    def test_same_row_count(self, both):
        df_iop, df_ios = both
        assert len(df_iop) == len(df_ios)
