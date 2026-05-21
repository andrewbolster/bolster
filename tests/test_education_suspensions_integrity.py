"""Data integrity tests for Education NI pupil suspensions module.

All tests use real data fetched from education-ni.gov.uk.
No mocks – the fixture is scoped to "class" to avoid repeated downloads.
"""

import pandas as pd
import pytest

from bolster.data_sources import education_suspensions as edu

pytestmark = pytest.mark.network


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------


class TestPublicationURLDiscovery:
    """Tests for XLSX URL discovery from education-ni.gov.uk."""

    def test_url_is_string(self):
        """get_suspensions_publication_url should return a non-empty string."""
        url = edu.get_suspensions_publication_url()
        assert isinstance(url, str)
        assert len(url) > 0

    def test_url_is_xlsx(self):
        """Discovered URL must point to an XLSX file."""
        url = edu.get_suspensions_publication_url()
        assert url.lower().endswith(".xlsx") or url.lower().endswith(".xls")

    def test_url_is_education_ni(self):
        """Discovered URL should come from education-ni.gov.uk."""
        url = edu.get_suspensions_publication_url()
        assert "education-ni.gov.uk" in url

    def test_invalid_base_raises(self):
        """Passing a bad URL should raise EducationSuspensionsNotFoundError."""
        # Patch the module-level constant temporarily
        original = edu.ARTICLES_URL
        edu.ARTICLES_URL = "https://example.com/nonexistent-page-xyz"
        try:
            with pytest.raises(edu.EducationSuspensionsNotFoundError):
                edu.get_suspensions_publication_url()
        finally:
            edu.ARTICLES_URL = original


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------


class TestSuspensionsDataIntegrity:
    """Tests for structural and statistical integrity of the tidy DataFrame."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        """Fetch the latest suspensions data once for all tests in this class."""
        return edu.get_latest_suspensions()

    def test_returns_dataframe(self, latest_data):
        """get_latest_suspensions should return a pandas DataFrame."""
        assert isinstance(latest_data, pd.DataFrame)

    def test_required_columns_present(self, latest_data):
        """All required columns must be present."""
        for col in ("academic_year", "pupils_suspended", "pct_pupils_suspended"):
            assert col in latest_data.columns, f"Missing column: {col}"

    def test_not_empty(self, latest_data):
        """Dataset must contain at least one row."""
        assert len(latest_data) > 0

    def test_non_negative_counts(self, latest_data):
        """All pupils_suspended values must be non-negative."""
        assert (latest_data["pupils_suspended"].dropna() >= 0).all()

    def test_percentage_in_range(self, latest_data):
        """pct_pupils_suspended must be in [0, 1]."""
        pct = latest_data["pct_pupils_suspended"].dropna()
        assert (pct >= 0).all()
        assert (pct <= 1).all()

    def test_academic_year_format(self, latest_data):
        """academic_year column should match YYYY/YY pattern."""
        import re

        pattern = re.compile(r"^\d{4}/\d{2}$")
        for year in latest_data["academic_year"]:
            assert pattern.match(str(year)), f"Unexpected academic_year format: {year}"

    def test_recent_year_present(self, latest_data):
        """Dataset must include at least 2023/24 or later."""
        years = list(latest_data["academic_year"])
        recent = [y for y in years if y >= "2023/24"]
        assert len(recent) > 0, f"No recent year >= 2023/24 found; years = {years}"

    def test_historical_coverage(self, latest_data):
        """Dataset should start from at least 2011/12 (first year of series)."""
        years = list(latest_data["academic_year"])
        assert "2011/12" in years, "Expected 2011/12 as start of series"

    def test_minimum_row_count(self, latest_data):
        """Should have at least 10 rows (2011/12 through 2021/22 minimum)."""
        assert len(latest_data) >= 10

    def test_pupils_suspended_magnitude(self, latest_data):
        """Suspension counts should be in a plausible range (100–15,000)."""
        counts = latest_data["pupils_suspended"].dropna()
        assert counts.min() >= 100, f"Min count too low: {counts.min()}"
        assert counts.max() <= 15_000, f"Max count too high: {counts.max()}"


# ---------------------------------------------------------------------------
# Validation function
# ---------------------------------------------------------------------------


class TestValidation:
    """Unit tests for validate_suspensions_data — no network calls needed."""

    def test_validate_passes_good_data(self):
        """validate_suspensions_data should return True for valid data."""
        df = pd.DataFrame(
            {
                "academic_year": ["2023/24", "2024/25"],
                "pupils_suspended": [4500, 4756],
                "pct_pupils_suspended": [0.015, 0.016],
            }
        )
        assert edu.validate_suspensions_data(df) is True

    def test_validate_rejects_empty_dataframe(self):
        """validate_suspensions_data should raise ValueError for empty data."""
        df = pd.DataFrame(columns=["academic_year", "pupils_suspended", "pct_pupils_suspended"])
        with pytest.raises(ValueError, match="empty"):
            edu.validate_suspensions_data(df)

    def test_validate_rejects_missing_column(self):
        """validate_suspensions_data should raise ValueError when columns are missing."""
        df = pd.DataFrame({"academic_year": ["2024/25"], "pupils_suspended": [4756]})
        with pytest.raises(ValueError, match="Missing required columns"):
            edu.validate_suspensions_data(df)

    def test_validate_rejects_negative_counts(self):
        """validate_suspensions_data should raise ValueError for negative counts."""
        df = pd.DataFrame(
            {
                "academic_year": ["2024/25"],
                "pupils_suspended": [-1],
                "pct_pupils_suspended": [0.01],
            }
        )
        with pytest.raises(ValueError, match="negative"):
            edu.validate_suspensions_data(df)

    def test_validate_rejects_pct_out_of_range(self):
        """validate_suspensions_data should raise ValueError when percentage > 1."""
        df = pd.DataFrame(
            {
                "academic_year": ["2024/25"],
                "pupils_suspended": [4756],
                "pct_pupils_suspended": [1.5],
            }
        )
        with pytest.raises(ValueError, match="outside"):
            edu.validate_suspensions_data(df)
