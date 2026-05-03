"""Data integrity tests for NISRA monthly stillbirths statistics.

Tests validate the structure and consistency of stillbirth registration data
using real data from NISRA monthly publications.
"""

import datetime

import pytest

from bolster.data_sources.nisra import stillbirths


class TestStillbirthsIntegrity:
    """Test suite for stillbirths data structure and quality."""

    @pytest.fixture(scope="class")
    def latest_stillbirths(self):
        """Fetch latest stillbirths data once for the test class."""
        return stillbirths.get_latest_stillbirths(force_refresh=False)

    def test_not_empty(self, latest_stillbirths):
        assert len(latest_stillbirths) > 0

    def test_required_columns(self, latest_stillbirths):
        required = {"date", "year", "month", "stillbirths"}
        assert required.issubset(set(latest_stillbirths.columns))

    def test_no_negative_values(self, latest_stillbirths):
        assert (latest_stillbirths["stillbirths"] >= 0).all()

    def test_historical_coverage(self, latest_stillbirths):
        assert latest_stillbirths["year"].min() <= 2006

    def test_recent_data(self, latest_stillbirths):
        current_year = datetime.datetime.now().year
        assert latest_stillbirths["year"].max() >= current_year - 1

    def test_chronological_order(self, latest_stillbirths):
        dates = latest_stillbirths["date"].tolist()
        assert dates == sorted(dates)

    def test_twelve_months_per_complete_year(self, latest_stillbirths):
        # 2023 should have all 12 months (complete, non-provisional year)
        df_2023 = latest_stillbirths[latest_stillbirths["year"] == 2023]
        assert len(df_2023) == 12

    def test_annual_totals_plausible(self, latest_stillbirths):
        # NI stillbirths typically 50-130 per year
        annual = latest_stillbirths.groupby("year")["stillbirths"].sum()
        complete_years = annual[annual.index < datetime.datetime.now().year - 1]
        assert (complete_years >= 30).all(), f"Annual totals suspiciously low: {complete_years[complete_years < 30]}"
        assert (complete_years <= 200).all(), f"Annual totals suspiciously high: {complete_years[complete_years > 200]}"

    def test_validate_function(self, latest_stillbirths):
        assert stillbirths.validate_stillbirths_data(latest_stillbirths)

    def test_validate_rejects_negatives(self):
        import pandas as pd

        bad = pd.DataFrame({
            "date": [pd.Timestamp("2024-01-01")],
            "year": [2024],
            "month": ["January"],
            "stillbirths": [-1],
        })
        with pytest.raises(stillbirths.NISRAValidationError):
            stillbirths.validate_stillbirths_data(bad)

    def test_validate_rejects_missing_columns(self):
        import pandas as pd

        bad = pd.DataFrame({"year": [2024], "month": ["January"]})
        with pytest.raises(stillbirths.NISRAValidationError):
            stillbirths.validate_stillbirths_data(bad)

    def test_get_stillbirths_by_year(self, latest_stillbirths):
        df_2023 = stillbirths.get_stillbirths_by_year(latest_stillbirths, 2023)
        assert len(df_2023) == 12
        assert (df_2023["year"] == 2023).all()

    def test_annual_summary(self, latest_stillbirths):
        summary = stillbirths.get_annual_summary(latest_stillbirths)
        assert "year" in summary.columns
        assert "total_stillbirths" in summary.columns
        assert "yoy_change" in summary.columns
        assert "yoy_pct_change" in summary.columns
        assert len(summary) == latest_stillbirths["year"].nunique()

    def test_downward_trend_recent_years(self, latest_stillbirths):
        # NI stillbirths have declined from ~100+/year pre-2018 to ~60/year recently
        annual = latest_stillbirths.groupby("year")["stillbirths"].sum()
        avg_early = annual[annual.index.isin(range(2006, 2015))].mean()
        avg_recent = annual[annual.index.isin(range(2020, 2025))].mean()
        assert avg_recent < avg_early, (
            f"Expected recent average ({avg_recent:.0f}) < early average ({avg_early:.0f})"
        )
