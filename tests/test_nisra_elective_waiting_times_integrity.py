"""Data integrity tests for NISRA elective/outpatient waiting times statistics.

These tests validate that the data is internally consistent, has plausible
shapes and value ranges, and that known trusts and specialties are present.
All tests use real downloaded data — no mocks.

Key validations:
- Required columns present with correct dtypes
- No negative patient counts
- All five main HSC Trusts present
- Historical data coverage back to 2007 (inpatient) / 2008 (outpatient)
- Recent data available (within last 2 years)
- Both waiting_type values present
"""

import datetime

import pandas as pd
import pytest

from bolster.data_sources.nisra import elective_waiting_times as ewt
from bolster.data_sources.nisra._base import NISRAValidationError


class TestElectiveWaitingTimesIntegrity:
    """Integration tests against the latest published data from health-ni.gov.uk."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        """Download and cache the latest elective waiting times data once per class."""
        return ewt.get_latest_elective_waiting_times(force_refresh=False)

    def test_required_columns_present(self, latest_data: pd.DataFrame):
        """All required columns must be present in the output DataFrame."""
        required = ewt.REQUIRED_COLUMNS
        missing = required - set(latest_data.columns)
        assert missing == set(), f"Missing columns: {missing}"

    def test_date_column_is_datetime(self, latest_data: pd.DataFrame):
        """The date column must be a datetime type."""
        assert pd.api.types.is_datetime64_any_dtype(latest_data["date"]), (
            f"Expected datetime, got {latest_data['date'].dtype}"
        )

    def test_year_column_is_integer(self, latest_data: pd.DataFrame):
        """The year column must be an integer type."""
        assert pd.api.types.is_integer_dtype(latest_data["year"]), (
            f"Expected integer, got {latest_data['year'].dtype}"
        )

    def test_patients_waiting_is_numeric(self, latest_data: pd.DataFrame):
        """The patients_waiting column must be numeric."""
        assert pd.api.types.is_numeric_dtype(latest_data["patients_waiting"]), (
            f"Expected numeric, got {latest_data['patients_waiting'].dtype}"
        )

    def test_no_negative_patients_waiting(self, latest_data: pd.DataFrame):
        """Patient counts must not be negative."""
        valid = latest_data["patients_waiting"].dropna()
        assert (valid >= 0).all(), (
            f"Negative patient counts found: min = {valid.min()}"
        )

    def test_both_waiting_types_present(self, latest_data: pd.DataFrame):
        """Both inpatient_day_case and outpatient types must be present."""
        types = set(latest_data["waiting_type"].unique())
        assert "inpatient_day_case" in types, "Missing waiting_type='inpatient_day_case'"
        assert "outpatient" in types, "Missing waiting_type='outpatient'"

    def test_known_trusts_present(self, latest_data: pd.DataFrame):
        """All five main HSC Trusts must appear in the data."""
        trusts = set(latest_data["trust"].unique())
        for expected in ewt.EXPECTED_TRUSTS:
            assert expected in trusts, f"Trust '{expected}' not found in data"

    def test_historical_coverage_inpatient(self, latest_data: pd.DataFrame):
        """Inpatient data must go back to at least 2007."""
        ip = latest_data[latest_data["waiting_type"] == "inpatient_day_case"]
        min_year = ip["year"].min()
        assert min_year <= 2007, f"Expected inpatient data from ≤ 2007, got {min_year}"

    def test_historical_coverage_outpatient(self, latest_data: pd.DataFrame):
        """Outpatient data must go back to at least 2008."""
        op = latest_data[latest_data["waiting_type"] == "outpatient"]
        min_year = op["year"].min()
        assert min_year <= 2008, f"Expected outpatient data from ≤ 2008, got {min_year}"

    def test_recent_data_available(self, latest_data: pd.DataFrame):
        """Data must include records from the last 2 years."""
        current_year = datetime.datetime.now().year
        max_year = latest_data["year"].max()
        assert max_year >= current_year - 2, (
            f"Latest data ({max_year}) is more than 2 years old"
        )

    def test_weeks_waited_band_not_empty(self, latest_data: pd.DataFrame):
        """weeks_waited_band must contain at least one non-null value."""
        non_null = latest_data["weeks_waited_band"].dropna()
        assert len(non_null) > 0, "weeks_waited_band column is entirely null"

    def test_specialty_column_not_empty(self, latest_data: pd.DataFrame):
        """specialty must contain at least one non-null, non-blank value."""
        non_blank = latest_data["specialty"].dropna()
        non_blank = non_blank[non_blank.str.strip() != ""]
        assert len(non_blank) > 0, "specialty column is entirely blank"

    def test_known_specialties_present(self, latest_data: pd.DataFrame):
        """A selection of common specialties must appear in the data."""
        expected = {"General Surgery", "Urology", "Cardiology"}
        actual = set(latest_data["specialty"].dropna().unique())
        overlap = expected & actual
        assert len(overlap) > 0, (
            f"None of the expected specialties {expected} found; sample: "
            f"{sorted(actual)[:10]}"
        )

    def test_date_year_consistency(self, latest_data: pd.DataFrame):
        """date and year columns must be internally consistent."""
        assert (latest_data["date"].dt.year == latest_data["year"]).all(), (
            "date and year columns are inconsistent"
        )

    def test_quarter_ending_equals_date(self, latest_data: pd.DataFrame):
        """quarter_ending and date columns must be equal."""
        assert (latest_data["quarter_ending"] == latest_data["date"]).all(), (
            "quarter_ending and date columns differ"
        )

    def test_validate_function_passes(self, latest_data: pd.DataFrame):
        """validate_elective_waiting_times must return True on real data."""
        assert ewt.validate_elective_waiting_times(latest_data) is True

    def test_large_dataset(self, latest_data: pd.DataFrame):
        """Combined dataset must contain a substantial number of rows."""
        assert len(latest_data) > 10_000, (
            f"Expected > 10,000 rows, got {len(latest_data)}"
        )


class TestValidation:
    """Unit tests for validation edge cases — no network calls needed."""

    def test_validate_empty_dataframe(self):
        """Validation must raise NISRAValidationError for an empty DataFrame."""
        empty = pd.DataFrame()
        with pytest.raises(NISRAValidationError, match="empty"):
            ewt.validate_elective_waiting_times(empty)

    def test_validate_none(self):
        """Validation must raise NISRAValidationError when passed None."""
        with pytest.raises(NISRAValidationError, match="empty"):
            ewt.validate_elective_waiting_times(None)

    def test_validate_missing_columns(self):
        """Validation must raise NISRAValidationError when required columns are absent."""
        # Build a minimal DataFrame that has some — but not all — required cols
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-12-31"]),
            "year": [2025],
            # deliberately omit: quarter_ending, trust, specialty, etc.
        })
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            ewt.validate_elective_waiting_times(df)

    def test_validate_negative_values(self):
        """Validation must raise NISRAValidationError when patients_waiting < 0."""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-12-31"]),
            "year": [2025],
            "quarter_ending": pd.to_datetime(["2025-12-31"]),
            "trust": ["Belfast"],
            "specialty": ["General Surgery"],
            "programme_of_care": ["Acute Services"],
            "weeks_waited_band": ["0 - 6 weeks"],
            "patients_waiting": [-1.0],
            "waiting_type": ["inpatient_day_case"],
        })
        with pytest.raises(NISRAValidationError, match="negative"):
            ewt.validate_elective_waiting_times(df)

    def test_validate_valid_dataframe_passes(self):
        """Validation must return True for a correctly structured DataFrame."""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-12-31", "2025-12-31"]),
            "year": [2025, 2025],
            "quarter_ending": pd.to_datetime(["2025-12-31", "2025-12-31"]),
            "trust": ["Belfast", "Northern"],
            "specialty": ["General Surgery", "Urology"],
            "programme_of_care": ["Acute Services", "Acute Services"],
            "weeks_waited_band": ["0 - 6 weeks", "> 6 - 13 weeks"],
            "patients_waiting": [100.0, 50.0],
            "waiting_type": ["inpatient_day_case", "outpatient"],
        })
        assert ewt.validate_elective_waiting_times(df) is True

    def test_validate_nan_patients_waiting_allowed(self):
        """NaN values in patients_waiting must not trigger the negative-values error."""
        import numpy as np

        df = pd.DataFrame({
            "date": pd.to_datetime(["2025-12-31"]),
            "year": [2025],
            "quarter_ending": pd.to_datetime(["2025-12-31"]),
            "trust": ["Belfast"],
            "specialty": ["General Surgery"],
            "programme_of_care": ["Acute Services"],
            "weeks_waited_band": ["0 - 6 weeks"],
            "patients_waiting": [np.nan],
            "waiting_type": ["inpatient_day_case"],
        })
        # Should not raise — NaN rows are excluded from the negative check
        assert ewt.validate_elective_waiting_times(df) is True
