"""Data integrity tests for NISRA Quarterly Employment Survey (QES).

Tests validate structure and consistency of the QES quarterly employee
job series using real data from NISRA publications.
"""

import datetime

import pytest

from bolster.data_sources.nisra import quarterly_employment_survey as qes


class TestQESIntegrity:
    """Test suite for QES seasonally adjusted data."""

    @pytest.fixture(scope="class")
    def latest_qes(self):
        return qes.get_latest_qes(force_refresh=False, adjusted=True)

    def test_not_empty(self, latest_qes):
        assert len(latest_qes) > 0

    def test_required_columns(self, latest_qes):
        required = {
            "date", "year", "quarter", "quarter_label",
            "manufacturing_jobs", "construction_jobs",
            "services_jobs", "other_jobs", "total_jobs", "adjusted",
        }
        assert required.issubset(set(latest_qes.columns))

    def test_all_adjusted(self, latest_qes):
        assert latest_qes["adjusted"].all()

    def test_historical_coverage(self, latest_qes):
        assert latest_qes["year"].min() <= 2005

    def test_recent_data(self, latest_qes):
        current_year = datetime.datetime.now().year
        assert latest_qes["year"].max() >= current_year - 1

    def test_at_least_80_quarters(self, latest_qes):
        # Q1 2005 to Q4 2025 = 84 quarters
        assert len(latest_qes) >= 80

    def test_four_quarters_per_complete_year(self, latest_qes):
        complete_years = latest_qes.groupby("year")["quarter"].count()
        complete = complete_years[complete_years.index < datetime.datetime.now().year]
        assert (complete == 4).all(), f"Missing quarters: {complete[complete != 4]}"

    def test_chronological_order(self, latest_qes):
        assert latest_qes["date"].is_monotonic_increasing

    def test_no_negative_jobs(self, latest_qes):
        for col in ("manufacturing_jobs", "construction_jobs", "services_jobs",
                    "other_jobs", "total_jobs"):
            assert (latest_qes[col] >= 0).all(), f"Negative values in {col}"

    def test_total_jobs_plausible_range(self, latest_qes):
        # NI employee jobs: ~600k-900k across the series
        assert (latest_qes["total_jobs"] >= 550_000).all()
        assert (latest_qes["total_jobs"] <= 1_000_000).all()

    def test_sector_sum_equals_total(self, latest_qes):
        # manufacturing + construction + services + other == total
        computed = (
            latest_qes["manufacturing_jobs"]
            + latest_qes["construction_jobs"]
            + latest_qes["services_jobs"]
            + latest_qes["other_jobs"]
        )
        # Allow small rounding differences
        diff = (computed - latest_qes["total_jobs"]).abs()
        assert (diff <= 100).all(), f"Sector sum doesn't match total: max diff {diff.max()}"

    def test_services_dominant_sector(self, latest_qes):
        # Services should always be the largest sector (>70% of total)
        assert (latest_qes["services_jobs"] > latest_qes["manufacturing_jobs"]).all()
        assert (latest_qes["services_jobs"] > latest_qes["construction_jobs"]).all()

    def test_validate_function(self, latest_qes):
        assert qes.validate_qes_data(latest_qes)

    def test_growth_columns(self, latest_qes):
        growth = qes.get_qes_growth(latest_qes)
        assert "total_qoq" in growth.columns
        assert "total_yoy" in growth.columns
        assert "services_yoy" in growth.columns
        assert "manufacturing_yoy" in growth.columns
        # First 4 rows have no YoY (no prior year)
        assert growth["total_yoy"].iloc[:4].isna().all()
        assert growth["total_yoy"].iloc[4:].notna().all()

    def test_sector_shares(self, latest_qes):
        shares = qes.get_sector_shares(latest_qes)
        for sector in ("manufacturing", "construction", "services", "other"):
            assert f"{sector}_share" in shares.columns
        # All shares should sum to ~100
        total_share = (
            shares["manufacturing_share"]
            + shares["construction_share"]
            + shares["services_share"]
            + shares["other_share"]
        )
        assert ((total_share - 100).abs() <= 1).all(), "Sector shares don't sum to 100%"

    def test_record_high_recent(self, latest_qes):
        # Latest Dec 2025: 843,860 — series record; should be above 800k
        latest = latest_qes.iloc[-1]
        assert latest["total_jobs"] > 800_000, f"Expected >800k jobs, got {latest['total_jobs']}"

    def test_get_qes_by_year(self, latest_qes):
        df_2024 = qes.get_qes_by_year(latest_qes, 2024)
        assert len(df_2024) == 4
        assert (df_2024["year"] == 2024).all()

    def test_covid_dip_visible(self, latest_qes):
        # Q2 2020 should show dip from COVID — services at their lowest
        df_2020 = latest_qes[latest_qes["year"] == 2020]
        q2 = df_2020[df_2020["quarter"] == 2]
        if len(q2) > 0:
            q2_services = q2["services_jobs"].values[0]
            # Services normally >600k; Q2 2020 should be noticeably lower
            assert q2_services < 660_000, (
                f"Q2 2020 services ({q2_services:,}) should show COVID dip"
            )


class TestQESUnadjusted:
    """Spot-check unadjusted series."""

    @pytest.fixture(scope="class")
    def latest_unadjusted(self):
        return qes.get_latest_qes(force_refresh=False, adjusted=False)

    def test_not_adjusted(self, latest_unadjusted):
        assert not latest_unadjusted["adjusted"].any()

    def test_same_quarters_as_adjusted(self, latest_unadjusted):
        # Unadjusted should cover the same date range as adjusted
        adj = qes.get_latest_qes(force_refresh=False, adjusted=True)
        assert latest_unadjusted["year"].min() == adj["year"].min()
        assert latest_unadjusted["year"].max() == adj["year"].max()


class TestQESValidation:
    """Unit tests for validation edge cases — no network calls needed."""

    def test_validate_empty_dataframe(self):
        import pandas as pd

        with pytest.raises(qes.NISRAValidationError):
            qes.validate_qes_data(pd.DataFrame())

    def test_validate_missing_columns(self):
        import pandas as pd

        bad = pd.DataFrame({"year": [2024], "quarter": [1]})
        with pytest.raises(qes.NISRAValidationError):
            qes.validate_qes_data(bad)

    def test_validate_too_few_rows(self):
        import pandas as pd

        # Construct a minimal valid-looking df with too few rows
        data = {col: [700_000] * 5 for col in
                ("total_jobs", "manufacturing_jobs", "construction_jobs",
                 "services_jobs", "other_jobs")}
        data["date"] = pd.date_range("2024-01-01", periods=5, freq="QS")
        data["year"] = 2024
        data["quarter"] = 1
        with pytest.raises(qes.NISRAValidationError, match="Too few rows"):
            qes.validate_qes_data(pd.DataFrame(data))
