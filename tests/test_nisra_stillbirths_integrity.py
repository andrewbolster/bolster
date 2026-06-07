"""Data integrity tests for NISRA annual stillbirths and infant deaths statistics.

Tests validate the structure and consistency of data fetched from the NISRA
PxStat API (matrices SBAIDHSCT and SBAIDLGD).
"""

import pytest

from bolster.data_sources.nisra import stillbirths


class TestHSCTStillbirthsIntegrity:
    """Test suite for HSCT-level stillbirths data (primary breakdown, data from 1974)."""

    @pytest.fixture(scope="class")
    def latest_stillbirths(self):
        """Fetch HSCT stillbirths data once for the test class."""
        return stillbirths.get_latest_stillbirths(dimension="hsct")

    def test_not_empty(self, latest_stillbirths):
        assert len(latest_stillbirths) > 0

    def test_required_columns(self, latest_stillbirths):
        required = {"year", "geography_code", "geography", "stillbirths", "infant_deaths"}
        assert required.issubset(set(latest_stillbirths.columns))

    def test_no_negative_stillbirths(self, latest_stillbirths):
        non_null = latest_stillbirths["stillbirths"].dropna()
        assert (non_null >= 0).all()

    def test_no_negative_infant_deaths(self, latest_stillbirths):
        non_null = latest_stillbirths["infant_deaths"].dropna()
        assert (non_null >= 0).all()

    def test_historical_coverage_from_1974(self, latest_stillbirths):
        """HSCT series starts from 1974."""
        assert latest_stillbirths["year"].min() <= 1974

    def test_recent_data(self, latest_stillbirths):
        assert latest_stillbirths["year"].max() >= 2023

    def test_ni_total_present(self, latest_stillbirths):
        assert "Northern Ireland" in latest_stillbirths["geography"].values

    def test_five_trusts_plus_ni(self, latest_stillbirths):
        geographies = set(latest_stillbirths["geography"].unique())
        trusts = geographies - {"Northern Ireland"}
        assert len(trusts) == 5, f"Expected 5 trusts, got {len(trusts)}: {trusts}"

    def test_chronological_order(self, latest_stillbirths):
        ni = latest_stillbirths[latest_stillbirths["geography"] == "Northern Ireland"]
        years = ni["year"].tolist()
        assert years == sorted(years)

    def test_annual_totals_plausible(self, latest_stillbirths):
        """NI stillbirths per year should be within plausible bounds."""
        ni = latest_stillbirths[latest_stillbirths["geography"] == "Northern Ireland"]
        # Pre-2000 values can be much higher (hundreds); post-2010 typically ~60-120
        assert (ni["stillbirths"] >= 0).all()
        assert (ni["stillbirths"] < 500).all(), f"Implausibly high: {ni['stillbirths'].max()}"

    def test_2024_ni_stillbirths(self, latest_stillbirths):
        """2024 NI total stillbirths should be 60 based on PxStat data."""
        ni_2024 = latest_stillbirths[
            (latest_stillbirths["geography"] == "Northern Ireland") & (latest_stillbirths["year"] == 2024)
        ]
        assert len(ni_2024) == 1
        assert int(ni_2024["stillbirths"].iloc[0]) == 60

    def test_downward_trend_over_decades(self, latest_stillbirths):
        """NI stillbirths have declined sharply from the 1970s."""
        ni = latest_stillbirths[latest_stillbirths["geography"] == "Northern Ireland"]
        avg_1974_1980 = ni[ni["year"] <= 1980]["stillbirths"].mean()
        avg_2015_2024 = ni[ni["year"] >= 2015]["stillbirths"].mean()
        assert avg_2015_2024 < avg_1974_1980, (
            f"Expected recent average ({avg_2015_2024:.0f}) < early average ({avg_1974_1980:.0f})"
        )

    def test_validate_function(self, latest_stillbirths):
        assert stillbirths.validate_stillbirths_data(latest_stillbirths)

    def test_get_stillbirths_by_year(self, latest_stillbirths):
        df_2024 = stillbirths.get_stillbirths_by_year(latest_stillbirths, 2024)
        assert (df_2024["year"] == 2024).all()
        assert len(df_2024) > 0

    def test_annual_summary(self, latest_stillbirths):
        summary = stillbirths.get_annual_summary(latest_stillbirths)
        assert "year" in summary.columns
        assert "total_stillbirths" in summary.columns
        assert "yoy_change" in summary.columns
        assert "yoy_pct_change" in summary.columns
        ni_years = latest_stillbirths[latest_stillbirths["geography"] == "Northern Ireland"]["year"].nunique()
        assert len(summary) == ni_years


class TestLGDStillbirthsIntegrity:
    """Test suite for LGD-level stillbirths data (data from 2008)."""

    @pytest.fixture(scope="class")
    def lgd_stillbirths(self):
        return stillbirths.get_latest_stillbirths(dimension="lgd")

    def test_not_empty(self, lgd_stillbirths):
        assert len(lgd_stillbirths) > 0

    def test_required_columns(self, lgd_stillbirths):
        required = {"year", "geography_code", "geography", "stillbirths", "infant_deaths"}
        assert required.issubset(set(lgd_stillbirths.columns))

    def test_historical_coverage_from_2008(self, lgd_stillbirths):
        assert lgd_stillbirths["year"].min() <= 2008

    def test_eleven_districts_plus_ni(self, lgd_stillbirths):
        geographies = set(lgd_stillbirths["geography"].unique())
        districts = geographies - {"Northern Ireland"}
        assert len(districts) == 11, f"Expected 11 districts, got {len(districts)}: {districts}"

    def test_no_negative_values(self, lgd_stillbirths):
        assert (lgd_stillbirths["stillbirths"].dropna() >= 0).all()
        assert (lgd_stillbirths["infant_deaths"].dropna() >= 0).all()


class TestValidation:
    """Unit tests for validate_stillbirths_data — no network calls."""

    def test_validate_rejects_empty(self):
        import pandas as pd

        bad = pd.DataFrame({"year": [], "geography": [], "stillbirths": []})
        with pytest.raises(stillbirths.NISRAValidationError):
            stillbirths.validate_stillbirths_data(bad)

    def test_validate_rejects_negatives(self):
        import pandas as pd

        bad = pd.DataFrame(
            {
                "year": [2024],
                "geography_code": ["N92000002"],
                "geography": ["Northern Ireland"],
                "stillbirths": [-1],
                "infant_deaths": [80],
            }
        )
        with pytest.raises(stillbirths.NISRAValidationError):
            stillbirths.validate_stillbirths_data(bad)

    def test_validate_rejects_missing_columns(self):
        import pandas as pd

        bad = pd.DataFrame({"year": [2024], "geography": ["Northern Ireland"]})
        with pytest.raises(stillbirths.NISRAValidationError):
            stillbirths.validate_stillbirths_data(bad)

    def test_validate_rejects_implausibly_high(self):
        import pandas as pd

        bad = pd.DataFrame(
            {
                "year": [2024],
                "geography_code": ["N92000002"],
                "geography": ["Northern Ireland"],
                "stillbirths": [9999],
                "infant_deaths": [80],
            }
        )
        with pytest.raises(stillbirths.NISRAValidationError):
            stillbirths.validate_stillbirths_data(bad)

    def test_validate_accepts_valid_data(self):
        import pandas as pd

        good = pd.DataFrame(
            {
                "year": [2023, 2024],
                "geography_code": ["N92000002", "N92000002"],
                "geography": ["Northern Ireland", "Northern Ireland"],
                "stillbirths": [67, 60],
                "infant_deaths": [80, 88],
            }
        )
        assert stillbirths.validate_stillbirths_data(good) is True


class TestDimensionErrors:
    """get_latest_stillbirths raises on invalid dimension."""

    def test_invalid_dimension(self):
        with pytest.raises(ValueError, match="dimension must be one of"):
            stillbirths.get_latest_stillbirths(dimension="monthly")
