"""Integrity and validation tests for nisra.disease_prevalence.

Network tests use real data from the Department of Health Northern Ireland.
Validation unit tests run entirely in-process (no network calls).
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import disease_prevalence as dp


class TestNISummaryIntegrity:
    """Integration tests against the live/cached disease prevalence dataset."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return dp.get_latest_disease_prevalence()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"year", "financial_year", "register", "registered_patients", "prevalence_per_1000"}
        assert required <= set(latest_data.columns), (
            f"Missing columns: {required - set(latest_data.columns)}"
        )

    def test_not_empty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0, "DataFrame should not be empty"

    def test_multiple_registers_present(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["register"].nunique() >= 14, (
            f"Expected ≥ 14 registers, got {latest_data['register'].nunique()}"
        )

    def test_historical_coverage_back_to_2009(self, latest_data: pd.DataFrame) -> None:
        min_year = latest_data["year"].min()
        assert min_year <= 2009, f"Expected data from at least 2009, earliest is {min_year}"

    def test_financial_year_format(self, latest_data: pd.DataFrame) -> None:
        """Financial year labels should be in 'YYYY/YY' format."""
        sample = latest_data["financial_year"].dropna().head(10)
        for fy in sample:
            assert "/" in str(fy), f"Unexpected financial_year format: {fy!r}"
            left, right = str(fy).split("/")
            assert left.isdigit() and right.isdigit(), f"Non-numeric parts in {fy!r}"

    def test_year_is_integer(self, latest_data: pd.DataFrame) -> None:
        assert pd.api.types.is_integer_dtype(latest_data["year"]) or \
               all(isinstance(v, (int, float)) and not pd.isna(v) and v == int(v)
                   for v in latest_data["year"].dropna()), \
               "year column should contain integer values"

    def test_year_matches_financial_year_prefix(self, latest_data: pd.DataFrame) -> None:
        """year should equal the start year embedded in financial_year."""
        sample = latest_data.dropna(subset=["year", "financial_year"]).head(50)
        for _, row in sample.iterrows():
            expected = int(str(row["financial_year"]).split("/")[0])
            assert int(row["year"]) == expected, (
                f"year {row['year']} does not match financial_year {row['financial_year']!r}"
            )

    def test_prevalence_values_positive(self, latest_data: pd.DataFrame) -> None:
        prev = latest_data["prevalence_per_1000"].dropna()
        assert (prev >= 0).all(), "All prevalence_per_1000 values should be non-negative"

    def test_prevalence_values_below_1000(self, latest_data: pd.DataFrame) -> None:
        prev = latest_data["prevalence_per_1000"].dropna()
        assert (prev < 1000).all(), (
            f"Some prevalence_per_1000 values exceed 1000: {prev[prev >= 1000].head().tolist()}"
        )

    def test_registered_patients_positive(self, latest_data: pd.DataFrame) -> None:
        patients = latest_data["registered_patients"].dropna()
        assert (patients > 0).all(), "All registered_patients values should be positive"

    def test_validation_passes(self, latest_data: pd.DataFrame) -> None:
        assert dp.validate_disease_prevalence(latest_data) is True


class TestRegisterCoverage:
    """Check that key disease registers are present in the dataset."""

    @pytest.fixture(scope="class")
    def register_names_lower(self) -> set[str]:
        df = dp.get_latest_disease_prevalence()
        return {r.lower() for r in df["register"].unique()}

    @pytest.mark.parametrize(
        "keyword",
        [
            "hypertension",
            "diabetes",
            "copd",
            "coronary heart disease",
            "cancer",
        ],
    )
    def test_key_register_present(self, register_names_lower: set[str], keyword: str) -> None:
        assert any(keyword in name for name in register_names_lower), (
            f"Expected a register containing '{keyword}', found: {sorted(register_names_lower)}"
        )


class TestValidation:
    """Unit tests for validate_disease_prevalence — no network calls."""

    def _make_valid_df(self) -> pd.DataFrame:
        """Return a minimal valid DataFrame."""
        registers = ["Hypertension", "Diabetes", "COPD", "Cancer", "Asthma",
                     "Coronary Heart Disease", "Stroke/TIA", "Dementia",
                     "Atrial Fibrillation", "Asthma2"]
        years = list(range(2004, 2016))  # 12 years
        records = []
        for reg in registers:
            for yr in years:
                fy = f"{yr}/{str(yr + 1)[-2:]}"
                records.append({
                    "year": yr,
                    "financial_year": fy,
                    "register": reg,
                    "registered_patients": 50000.0,
                    "prevalence_per_1000": 100.0,
                })
        return pd.DataFrame(records)

    def test_validate_valid_dataframe(self) -> None:
        df = self._make_valid_df()
        assert dp.validate_disease_prevalence(df) is True

    def test_validate_empty_dataframe(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = pd.DataFrame(
            columns=["year", "financial_year", "register", "registered_patients", "prevalence_per_1000"]
        )
        with pytest.raises(NISRAValidationError, match="empty"):
            dp.validate_disease_prevalence(df)

    def test_validate_missing_columns(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = pd.DataFrame({"year": [2004], "register": ["Hypertension"]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            dp.validate_disease_prevalence(df)

    def test_validate_negative_prevalence(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = self._make_valid_df()
        df.loc[0, "prevalence_per_1000"] = -5.0
        with pytest.raises(NISRAValidationError, match="negative"):
            dp.validate_disease_prevalence(df)

    def test_validate_prevalence_above_1000(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = self._make_valid_df()
        df.loc[0, "prevalence_per_1000"] = 1001.0
        with pytest.raises(NISRAValidationError, match="1000"):
            dp.validate_disease_prevalence(df)

    def test_validate_negative_patients(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = self._make_valid_df()
        df.loc[0, "registered_patients"] = -1.0
        with pytest.raises(NISRAValidationError, match="negative"):
            dp.validate_disease_prevalence(df)

    def test_validate_too_few_registers(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = self._make_valid_df()
        df = df[df["register"] == "Hypertension"].reset_index(drop=True)
        with pytest.raises(NISRAValidationError, match="Too few disease registers"):
            dp.validate_disease_prevalence(df)

    def test_validate_too_few_years(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        df = self._make_valid_df()
        # Keep only 3 distinct financial years
        keep_fy = df["financial_year"].unique()[:3]
        df = df[df["financial_year"].isin(keep_fy)].reset_index(drop=True)
        with pytest.raises(NISRAValidationError, match="Too few financial years"):
            dp.validate_disease_prevalence(df)
