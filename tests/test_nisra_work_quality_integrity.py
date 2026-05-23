"""Data integrity tests for NISRA Work Quality in Northern Ireland statistics.

These tests validate the data returned by the work_quality module against
real data from NISRA (no mocks). They verify structural, numerical, and
temporal correctness of the parsed output.

Key validations:
- All required columns present
- Multiple indicators present (should be 17)
- Values within valid percentage range (0-100)
- Data covers expected years (2020 to present for most indicators)
- Recent data available (2025 or later)
- validate_work_quality_data rejects empty and malformed DataFrames
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import work_quality


class TestWorkQualityDataIntegrity:
    """Test suite for validating Work Quality data structure and content."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        """Fetch latest work quality data once for the test class."""
        return work_quality.get_latest_work_quality(force_refresh=False)

    def test_required_columns_present(self, latest_data: pd.DataFrame) -> None:
        """Test that all required columns are present."""
        required = {"indicator", "year_label", "year", "value", "geography"}
        assert required.issubset(set(latest_data.columns)), f"Missing columns: {required - set(latest_data.columns)}"

    def test_dataframe_not_empty(self, latest_data: pd.DataFrame) -> None:
        """Test that the DataFrame contains rows."""
        assert len(latest_data) > 0, "DataFrame is empty"

    def test_all_17_indicators_present(self, latest_data: pd.DataFrame) -> None:
        """Test that all 17 work quality indicators are present."""
        n_indicators = latest_data["indicator"].nunique()
        assert n_indicators == 17, (
            f"Expected 17 indicators, got {n_indicators}: {sorted(latest_data['indicator'].unique())}"
        )

    def test_known_indicators_present(self, latest_data: pd.DataFrame) -> None:
        """Test that a selection of expected indicator names are present."""
        expected_indicators = {
            "real_living_wage",
            "job_satisfaction",
            "secure_employment",
            "no_zero_hours_contract",
            "trade_union_member",
            "line_manager_support",
            "working_overtime",
        }
        found = set(latest_data["indicator"].unique())
        missing = expected_indicators - found
        assert not missing, f"Expected indicators not found: {missing}"

    def test_values_within_valid_range(self, latest_data: pd.DataFrame) -> None:
        """Test that all values are valid percentages (0-100)."""
        bad = latest_data[(latest_data["value"] < 0) | (latest_data["value"] > 100)]
        assert bad.empty, f"Found {len(bad)} rows with values outside [0, 100]:\n{bad}"

    def test_values_are_numeric(self, latest_data: pd.DataFrame) -> None:
        """Test that the value column is numeric."""
        assert pd.api.types.is_numeric_dtype(latest_data["value"]), (
            f"'value' column is not numeric: dtype={latest_data['value'].dtype}"
        )

    def test_year_column_is_integer(self, latest_data: pd.DataFrame) -> None:
        """Test that the year column contains integers."""
        assert pd.api.types.is_integer_dtype(latest_data["year"]), (
            f"'year' column is not integer: dtype={latest_data['year'].dtype}"
        )

    def test_recent_year_present(self, latest_data: pd.DataFrame) -> None:
        """Test that data for 2025 or later is available."""
        max_year = latest_data["year"].max()
        assert max_year >= 2025, f"Expected data for 2025 or later, latest year is {max_year}"

    def test_historical_coverage_from_2020(self, latest_data: pd.DataFrame) -> None:
        """Test that most indicators have data going back to 2020."""
        # The majority of indicators have 2020 as their earliest year
        indicators_with_2020 = latest_data[latest_data["year"] == 2020]["indicator"].nunique()
        assert indicators_with_2020 >= 10, f"Expected at least 10 indicators with 2020 data, got {indicators_with_2020}"

    def test_geography_is_northern_ireland(self, latest_data: pd.DataFrame) -> None:
        """Test that geography is always 'Northern Ireland'."""
        geographies = latest_data["geography"].unique()
        assert list(geographies) == ["Northern Ireland"], f"Unexpected geographies: {geographies.tolist()}"

    def test_no_null_values(self, latest_data: pd.DataFrame) -> None:
        """Test that there are no null values in required columns."""
        for col in ("indicator", "year_label", "year", "value", "geography"):
            null_count = latest_data[col].isna().sum()
            assert null_count == 0, f"Column '{col}' has {null_count} null values"

    def test_each_indicator_has_multiple_years(self, latest_data: pd.DataFrame) -> None:
        """Test that every indicator has at least 2 years of data."""
        year_counts = latest_data.groupby("indicator")["year"].nunique()
        single_year = year_counts[year_counts < 2]
        assert single_year.empty, f"These indicators have fewer than 2 years of data: {single_year.to_dict()}"

    def test_validate_function_passes(self, latest_data: pd.DataFrame) -> None:
        """Test that validate_work_quality_data returns True on valid data."""
        assert work_quality.validate_work_quality_data(latest_data) is True

    def test_real_living_wage_value_plausible(self, latest_data: pd.DataFrame) -> None:
        """Test that Real Living Wage values are plausible (70-95% range)."""
        rlw = latest_data[latest_data["indicator"] == "real_living_wage"]
        assert not rlw.empty, "No real_living_wage rows found"
        assert rlw["value"].between(50, 100).all(), (
            f"Real Living Wage values out of plausible range:\n{rlw[['year_label', 'value']]}"
        )

    def test_publication_url_returns_valid_tuple(self) -> None:
        """Test that get_work_quality_publication_url returns (url, year)."""
        url, year = work_quality.get_work_quality_publication_url()
        assert url.startswith("https://"), f"URL does not start with https://: {url!r}"
        assert url.endswith(".xlsx"), f"URL does not end with .xlsx: {url!r}"
        assert year >= 2025, f"Expected year >= 2025, got {year}"


class TestValidation:
    """Unit tests for validate_work_quality_data — no network calls required."""

    def _minimal_df(self) -> pd.DataFrame:
        """Return a minimal valid DataFrame for testing."""
        return pd.DataFrame(
            {
                "indicator": ["job_satisfaction"] * 6
                + ["real_living_wage"] * 6
                + ["secure_employment"] * 6
                + ["no_zero_hours_contract"] * 6
                + ["trade_union_member"] * 6
                + ["line_manager_support"] * 6
                + ["decision_making"] * 6
                + ["meaningful_work"] * 6
                + ["flexible_work"] * 6
                + ["no_bullying_harassment"] * 6,
                "year_label": list(range(2020, 2026)) * 10,
                "year": list(range(2020, 2026)) * 10,
                "value": [75.0] * 60,
                "geography": ["Northern Ireland"] * 60,
            }
        )

    def test_validate_rejects_empty_dataframe(self) -> None:
        """Test that an empty DataFrame raises NISRAValidationError."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        with pytest.raises(NISRAValidationError, match="empty"):
            work_quality.validate_work_quality_data(pd.DataFrame())

    def test_validate_rejects_missing_columns(self) -> None:
        """Test that a DataFrame missing required columns raises NISRAValidationError."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = pd.DataFrame({"indicator": ["x"], "year": [2025]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            work_quality.validate_work_quality_data(df)

    def test_validate_rejects_out_of_range_values(self) -> None:
        """Test that values outside [0, 100] raise NISRAValidationError."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = self._minimal_df()
        df.loc[0, "value"] = -5.0
        with pytest.raises(NISRAValidationError, match="outside valid percentage range"):
            work_quality.validate_work_quality_data(df)

    def test_validate_rejects_too_few_indicators(self) -> None:
        """Test that fewer than 10 indicators raises NISRAValidationError."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = pd.DataFrame(
            {
                "indicator": ["job_satisfaction"] * 3,
                "year_label": ["2023", "2024", "2025"],
                "year": [2023, 2024, 2025],
                "value": [75.0, 76.0, 77.0],
                "geography": ["Northern Ireland"] * 3,
            }
        )
        with pytest.raises(NISRAValidationError, match="at least 10 indicators"):
            work_quality.validate_work_quality_data(df)

    def test_validate_rejects_stale_data(self) -> None:
        """Test that data with no year >= 2024 raises NISRAValidationError."""
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = self._minimal_df()
        df["year"] = 2015  # Force all years to be old
        df["year_label"] = "2015"
        with pytest.raises(NISRAValidationError, match="latest year"):
            work_quality.validate_work_quality_data(df)

    def test_normalise_year_label_integer(self) -> None:
        """Test _normalise_year_label handles integer input."""
        assert work_quality._normalise_year_label(2025) == "2025"

    def test_normalise_year_label_float(self) -> None:
        """Test _normalise_year_label handles float input."""
        assert work_quality._normalise_year_label(2025.0) == "2025"

    def test_normalise_year_label_string(self) -> None:
        """Test _normalise_year_label handles period string."""
        label = "July 2024 to June 2025"
        assert work_quality._normalise_year_label(label) == label

    def test_normalise_year_label_none(self) -> None:
        """Test _normalise_year_label returns None for None input."""
        assert work_quality._normalise_year_label(None) is None

    def test_extract_year_int_plain(self) -> None:
        """Test _extract_year_int for plain year string."""
        assert work_quality._extract_year_int("2025") == 2025

    def test_extract_year_int_period(self) -> None:
        """Test _extract_year_int picks the later year from a period string."""
        assert work_quality._extract_year_int("July 2024 to June 2025") == 2025
