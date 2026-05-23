"""Integrity tests for PSNI PACE Statistics module.

Tests use real data downloaded from PSNI and cache it via the normal
CachedDownloader mechanism. No mocks — all tests hit the real source
(or the local cache on subsequent runs).
"""

import pandas as pd
import pytest

from bolster.data_sources.psni import pace
from bolster.data_sources.psni._base import PSNIValidationError


class TestStopSearchIntegrity:
    """Real-data integrity tests for the stop & search breakdown."""

    @pytest.fixture(scope="class")
    def stop_search_data(self):
        return pace.get_latest_pace(breakdown="stop_search")

    def test_required_columns(self, stop_search_data):
        required = {"financial_year", "year", "month", "reason", "metric", "count"}
        assert required.issubset(set(stop_search_data.columns))

    def test_not_empty(self, stop_search_data):
        assert len(stop_search_data) > 0

    def test_counts_non_negative(self, stop_search_data):
        assert (stop_search_data["count"] >= 0).all()

    def test_counts_positive_for_searches(self, stop_search_data):
        searches = stop_search_data[stop_search_data["metric"] == "Searches"]
        assert searches["count"].sum() > 0

    def test_multiple_reasons_present(self, stop_search_data):
        reasons = stop_search_data["reason"].unique()
        assert len(reasons) >= 4, f"Expected at least 4 search reasons, got: {reasons}"

    def test_known_reasons_present(self, stop_search_data):
        reasons = set(str(r) for r in stop_search_data["reason"].unique())
        assert any("Stolen" in r for r in reasons), "Expected 'Stolen Articles' reason"
        assert any("Fireworks" in r for r in reasons), "Expected 'Fireworks' reason"

    def test_all_months_present(self, stop_search_data):
        months = set(str(m) for m in stop_search_data["month"].unique())
        expected = {"Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"}
        assert expected == months, f"Missing months: {expected - months}"

    def test_financial_year_format(self, stop_search_data):
        for fy in stop_search_data["financial_year"].unique():
            assert "/" in str(fy), f"Expected 'YYYY/YY' format, got: {fy}"

    def test_year_is_integer(self, stop_search_data):
        assert stop_search_data["year"].dtype in (int, "int64", "int32")

    def test_metric_values(self, stop_search_data):
        metrics = set(str(m) for m in stop_search_data["metric"].unique())
        assert "Searches" in metrics
        assert "Arrests" in metrics

    def test_total_searches_reasonable(self, stop_search_data):
        """Annual searches should be in a plausible range (100–50,000 for NI)."""
        total_searches = stop_search_data[stop_search_data["metric"] == "Searches"]["count"].sum()
        assert 100 <= total_searches <= 50_000, f"Unexpected total searches: {total_searches}"

    def test_validate_passes(self, stop_search_data):
        assert pace.validate_pace(stop_search_data, "stop_search") is True


class TestArrestsIntegrity:
    """Real-data integrity tests for the arrests breakdown."""

    @pytest.fixture(scope="class")
    def arrests_data(self):
        return pace.get_latest_pace(breakdown="arrests")

    def test_required_columns(self, arrests_data):
        required = {"financial_year", "year", "quarter", "category", "count"}
        assert required.issubset(set(arrests_data.columns))

    def test_not_empty(self, arrests_data):
        assert len(arrests_data) > 0

    def test_counts_non_negative(self, arrests_data):
        assert (arrests_data["count"] >= 0).all()

    def test_gender_categories_present(self, arrests_data):
        categories = set(str(c) for c in arrests_data["category"].unique())
        assert "Male" in categories, f"Expected 'Male' category, got: {categories}"
        assert "Female" in categories, f"Expected 'Female' category, got: {categories}"

    def test_total_category_present(self, arrests_data):
        categories = set(str(c) for c in arrests_data["category"].unique())
        assert "Total" in categories

    def test_solicitor_category_present(self, arrests_data):
        categories = set(str(c) for c in arrests_data["category"].unique())
        assert any("solicitor" in c.lower() for c in categories), f"Expected solicitor category, got: {categories}"

    def test_all_quarters_present(self, arrests_data):
        quarters = set(str(q) for q in arrests_data["quarter"].unique())
        for q in ("Q1", "Q2", "Q3", "Q4"):
            assert any(q in qstr for qstr in quarters), f"Missing quarter {q} in {quarters}"

    def test_annual_total_present(self, arrests_data):
        quarters = set(str(q) for q in arrests_data["quarter"].unique())
        assert any("Annual" in q for q in quarters), f"Expected annual total row, got: {quarters}"

    def test_gender_totals_consistent(self, arrests_data):
        """Male + Female + Unknown should roughly equal Total (within each quarter)."""
        for quarter in arrests_data["quarter"].unique():
            q_data = arrests_data[arrests_data["quarter"] == quarter]

            def _get(cat):
                row = q_data[q_data["category"] == cat]
                return int(row["count"].iloc[0]) if not row.empty else 0

            total = _get("Total")
            male = _get("Male")
            female = _get("Female")
            other = _get("Unknown / Other")
            if total > 0:
                assert male + female + other == total, (
                    f"Gender totals don't add up for {quarter}: "
                    f"{male} + {female} + {other} = {male+female+other} != {total}"
                )

    def test_total_arrests_reasonable(self, arrests_data):
        """Annual total arrests should be in a plausible range for NI."""
        annual = arrests_data[arrests_data["quarter"].astype(str).str.contains("Annual")]
        total_row = annual[annual["category"] == "Total"]
        if not total_row.empty:
            total = int(total_row["count"].iloc[0])
            assert 5_000 <= total <= 100_000, f"Unexpected annual total: {total}"

    def test_validate_passes(self, arrests_data):
        assert pace.validate_pace(arrests_data, "arrests") is True


class TestValidation:
    """Unit tests for validate_pace edge cases — no network calls."""

    def test_validate_empty_dataframe_raises(self):
        with pytest.raises(PSNIValidationError, match="empty"):
            pace.validate_pace(pd.DataFrame(), "stop_search")

    def test_validate_missing_columns_stop_search(self):
        df = pd.DataFrame({"financial_year": ["2025/26"], "count": [1]})
        with pytest.raises(PSNIValidationError, match="missing required columns"):
            pace.validate_pace(df, "stop_search")

    def test_validate_missing_columns_arrests(self):
        df = pd.DataFrame({"financial_year": ["2025/26"], "count": [1]})
        with pytest.raises(PSNIValidationError, match="missing required columns"):
            pace.validate_pace(df, "arrests")

    def test_validate_negative_counts_raises(self):
        df = pd.DataFrame(
            {
                "financial_year": ["2025/26"],
                "year": [2025],
                "month": ["Apr"],
                "reason": ["Fireworks"],
                "metric": ["Searches"],
                "count": [-1],
            }
        )
        with pytest.raises(PSNIValidationError, match="negative counts"):
            pace.validate_pace(df, "stop_search")

    def test_validate_unknown_breakdown_raises(self):
        df = pd.DataFrame({"financial_year": ["2025/26"], "count": [1]})
        with pytest.raises(PSNIValidationError, match="Unknown breakdown"):
            pace.validate_pace(df, "unknown_type")

    def test_validate_valid_stop_search_passes(self):
        df = pd.DataFrame(
            {
                "financial_year": ["2025/26"],
                "year": [2025],
                "month": ["Apr"],
                "reason": ["Fireworks"],
                "metric": ["Searches"],
                "count": [3],
            }
        )
        assert pace.validate_pace(df, "stop_search") is True

    def test_validate_valid_arrests_passes(self):
        df = pd.DataFrame(
            {
                "financial_year": ["2025/26"],
                "year": [2025],
                "quarter": ["Q1 (Apr–Jun)"],
                "category": ["Total"],
                "count": [5105],
            }
        )
        assert pace.validate_pace(df, "arrests") is True

    def test_get_latest_pace_url_returns_string(self):
        url = pace.get_latest_pace_url()
        assert isinstance(url, str)
        assert url.startswith("https://")

    def test_pace_urls_dict_populated(self):
        assert len(pace.PACE_URLS) >= 2
        for fy, url in pace.PACE_URLS.items():
            assert "/" in fy, f"Expected 'YYYY/YY' format for key: {fy}"
            assert url.startswith("https://"), f"Expected https URL for {fy}"

    def test_invalid_breakdown_raises_value_error(self):
        with pytest.raises(ValueError, match="breakdown must be"):
            pace.get_latest_pace(breakdown="invalid")
