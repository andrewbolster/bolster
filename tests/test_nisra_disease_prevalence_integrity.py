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

    def test_validate_invalid_level(self) -> None:
        df = self._make_valid_df()
        with pytest.raises(ValueError, match="level must be"):
            dp.validate_disease_prevalence(df, level="bad")

    def test_validate_gp_level_valid(self) -> None:
        """GP-level validation passes on a minimal valid GP DataFrame."""
        records = []
        for i in range(120):
            pcode = f"Z{i:05d}"
            for reg in ["Hypertension", "Diabetes", "COPD", "Cancer", "Asthma"]:
                for yr in [2023, 2024, 2025]:
                    fy = f"{yr}/{str(yr + 1)[-2:]}"
                    records.append(
                        {
                            "practice_code": pcode,
                            "lcg": "Belfast",
                            "federation": None,
                            "financial_year": fy,
                            "year": yr,
                            "register": reg,
                            "registered_patients": 100.0,
                            "prevalence_per_1000": 50.0,
                        }
                    )
        df = pd.DataFrame(records)
        assert dp.validate_disease_prevalence(df, level="gp") is True

    def test_validate_gp_level_too_few_practices(self) -> None:
        from bolster.data_sources.nisra._base import NISRAValidationError

        records = []
        for i in range(5):
            pcode = f"Z{i:05d}"
            for reg in ["Hypertension", "Diabetes", "COPD", "Cancer", "Asthma"]:
                records.append(
                    {
                        "practice_code": pcode,
                        "lcg": "Belfast",
                        "federation": None,
                        "financial_year": "2025/26",
                        "year": 2025,
                        "register": reg,
                        "registered_patients": 100.0,
                        "prevalence_per_1000": 50.0,
                    }
                )
        df = pd.DataFrame(records)
        with pytest.raises(NISRAValidationError, match="Too few GP practices"):
            dp.validate_disease_prevalence(df, level="gp")


class TestGPPracticeIntegrity:
    """Integration tests for GP-practice-level disease prevalence data."""

    @pytest.fixture(scope="class")
    def gp_data(self) -> pd.DataFrame:
        return dp.get_latest_gp_prevalence()

    def test_required_columns(self, gp_data: pd.DataFrame) -> None:
        required = {
            "practice_code",
            "lcg",
            "federation",
            "financial_year",
            "year",
            "register",
            "registered_patients",
            "prevalence_per_1000",
        }
        assert required <= set(gp_data.columns), (
            f"Missing columns: {required - set(gp_data.columns)}"
        )

    def test_multiple_practices(self, gp_data: pd.DataFrame) -> None:
        n = gp_data["practice_code"].nunique()
        assert n > 300, f"Expected >300 GP practices, got {n}"

    def test_practice_codes_start_with_z(self, gp_data: pd.DataFrame) -> None:
        bad = gp_data.loc[gp_data["practice_code"].notna(), "practice_code"]
        bad = bad[~bad.str.startswith("Z")]
        assert bad.empty, f"Practice codes not starting with Z: {bad.head().tolist()}"

    def test_multiple_lcgs(self, gp_data: pd.DataFrame) -> None:
        n = gp_data["lcg"].nunique()
        assert n >= 5, f"Expected ≥ 5 LCGs, got {n}"

    def test_multiple_registers(self, gp_data: pd.DataFrame) -> None:
        n = gp_data["register"].nunique()
        assert n >= 10, f"Expected ≥ 10 registers, got {n}"

    def test_registered_patients_positive(self, gp_data: pd.DataFrame) -> None:
        patients = gp_data["registered_patients"].dropna()
        assert (patients >= 0).all(), "All registered_patients values should be non-negative"

    def test_prevalence_values_positive(self, gp_data: pd.DataFrame) -> None:
        prev = gp_data["prevalence_per_1000"].dropna()
        assert (prev >= 0).all(), "All prevalence_per_1000 values should be non-negative"

    def test_prevalence_values_below_1000(self, gp_data: pd.DataFrame) -> None:
        prev = gp_data["prevalence_per_1000"].dropna()
        assert (prev < 1000).all(), (
            f"Some prevalence_per_1000 values exceed 1000: {prev[prev >= 1000].head().tolist()}"
        )

    def test_multiple_years(self, gp_data: pd.DataFrame) -> None:
        n = gp_data["financial_year"].nunique()
        assert n >= 17, f"Expected ≥ 17 financial years, got {n}"

    def test_validation_passes(self, gp_data: pd.DataFrame) -> None:
        assert dp.validate_disease_prevalence(gp_data, level="gp") is True

    def test_financial_year_format(self, gp_data: pd.DataFrame) -> None:
        sample = gp_data["financial_year"].dropna().unique()
        for fy in sample:
            assert "/" in str(fy), f"Unexpected financial_year format: {fy!r}"

    def test_year_matches_financial_year_prefix(self, gp_data: pd.DataFrame) -> None:
        sample = gp_data.dropna(subset=["year", "financial_year"]).head(100)
        for _, row in sample.iterrows():
            expected = int(str(row["financial_year"]).split("/")[0])
            assert int(row["year"]) == expected, (
                f"year {row['year']} does not match financial_year {row['financial_year']!r}"
            )


class TestGPRegisterCoverage:
    """Check key register coverage across GP-practice data."""

    @pytest.fixture(scope="class")
    def gp_data(self) -> pd.DataFrame:
        return dp.get_latest_gp_prevalence()

    def test_hypertension_present_all_years(self, gp_data: pd.DataFrame) -> None:
        """Hypertension should appear in every financial year."""
        hyp = gp_data[gp_data["register"].str.contains("Hypertension", case=False, na=False)]
        assert not hyp.empty, "No Hypertension rows found"
        years_with_hyp = hyp["financial_year"].nunique()
        total_years = gp_data["financial_year"].nunique()
        assert years_with_hyp == total_years, (
            f"Hypertension present in {years_with_hyp}/{total_years} financial years"
        )

    def test_ndh_present_from_2022_23(self, gp_data: pd.DataFrame) -> None:
        """Non-Diabetic Hyperglycaemia should appear from 2022/23 onwards."""
        ndh = gp_data[
            gp_data["register"].str.contains("Non-Diabetic Hyperglycaemia", case=False, na=False)
        ]
        assert not ndh.empty, "No Non-Diabetic Hyperglycaemia rows found"
        # Should only appear from 2022/23
        early = ndh[ndh["year"] < 2022]
        assert early.empty, (
            f"NDH rows found before 2022/23 (years: {sorted(early['year'].unique())})"
        )
        recent_years = ndh["financial_year"].nunique()
        assert recent_years >= 3, (
            f"NDH should cover ≥ 3 recent years, got {recent_years}"
        )

    def test_copd_present(self, gp_data: pd.DataFrame) -> None:
        copd = gp_data[gp_data["register"].str.contains("Pulmonary", case=False, na=False)]
        assert not copd.empty, "No COPD (Chronic Obstructive Pulmonary Disease) rows found"

    def test_diabetes_present(self, gp_data: pd.DataFrame) -> None:
        diab = gp_data[gp_data["register"].str.contains("Diabetes", case=False, na=False)]
        assert not diab.empty, "No Diabetes rows found"
