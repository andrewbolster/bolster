"""Integrity and validation tests for nisra.disease_prevalence.

Network tests use real data from the NISRA PxStat API.
Validation unit tests run entirely in-process (no network calls).

The PxStat API (DISPREVNI / DISPREVLGD / DISPREVHSCT) provides annual
disease prevalence data from 2017/18 onwards with 17 disease registers.
"""

import pandas as pd
import pytest

from bolster.data_sources.health_ni import disease_prevalence as dp
from bolster.data_sources.health_ni._base import NISRAValidationError


class TestNISummaryIntegrity:
    """Integration tests against the live DISPREVNI API dataset."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return dp.get_latest_disease_prevalence()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {"year", "financial_year", "disease", "registered_patients", "prevalence_per_1000"}
        assert required <= set(latest_data.columns), f"Missing columns: {required - set(latest_data.columns)}"

    def test_not_empty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0, "DataFrame should not be empty"

    def test_multiple_diseases_present(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["disease"].nunique() >= 14, (
            f"Expected ≥ 14 diseases, got {latest_data['disease'].nunique()}"
        )

    def test_historical_coverage_back_to_2017(self, latest_data: pd.DataFrame) -> None:
        """PxStat API coverage begins at 2017/18."""
        min_year = latest_data["year"].min()
        assert min_year <= 2017, f"Expected data from at least 2017, earliest is {min_year}"

    def test_financial_year_format(self, latest_data: pd.DataFrame) -> None:
        """Financial year labels should be in 'YYYY/YY' format."""
        sample = latest_data["financial_year"].dropna().head(10)
        for fy in sample:
            assert "/" in str(fy), f"Unexpected financial_year format: {fy!r}"
            left, right = str(fy).split("/")
            assert left.isdigit() and right.isdigit(), f"Non-numeric parts in {fy!r}"

    def test_year_is_integer(self, latest_data: pd.DataFrame) -> None:
        assert pd.api.types.is_integer_dtype(latest_data["year"]) or all(
            isinstance(v, (int, float)) and not pd.isna(v) and v == int(v)
            for v in latest_data["year"].dropna()
        ), "year column should contain integer values"

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


class TestDiseaseRegisters:
    """Check that key disease registers are present in the dataset."""

    @pytest.fixture(scope="class")
    def disease_names_lower(self) -> set[str]:
        df = dp.get_latest_disease_prevalence()
        return {r.lower() for r in df["disease"].unique()}

    @pytest.mark.parametrize(
        "keyword",
        [
            "hypertension",
            "diabetes",
            "pulmonary",   # COPD: Chronic Obstructive Pulmonary Disease
            "coronary heart disease",
            "cancer",
        ],
    )
    def test_key_disease_present(self, disease_names_lower: set[str], keyword: str) -> None:
        assert any(keyword in name for name in disease_names_lower), (
            f"Expected a disease containing '{keyword}', found: {sorted(disease_names_lower)}"
        )


class TestLGDPrevalenceIntegrity:
    """Integration tests for LGD-level disease prevalence (DISPREVLGD)."""

    @pytest.fixture(scope="class")
    def lgd_data(self) -> pd.DataFrame:
        return dp.get_lgd_prevalence()

    def test_required_columns(self, lgd_data: pd.DataFrame) -> None:
        required = {"financial_year", "year", "lgd", "disease", "registered_patients", "prevalence_per_1000"}
        assert required <= set(lgd_data.columns), f"Missing columns: {required - set(lgd_data.columns)}"

    def test_has_data(self, lgd_data: pd.DataFrame) -> None:
        assert len(lgd_data) > 0

    def test_multiple_lgds(self, lgd_data: pd.DataFrame) -> None:
        n = lgd_data["lgd"].nunique()
        assert n >= 11, f"Expected ≥ 11 LGDs, got {n}"

    def test_multiple_diseases(self, lgd_data: pd.DataFrame) -> None:
        n = lgd_data["disease"].nunique()
        assert n >= 14, f"Expected ≥ 14 diseases, got {n}"

    def test_prevalence_values_positive(self, lgd_data: pd.DataFrame) -> None:
        prev = lgd_data["prevalence_per_1000"].dropna()
        assert (prev >= 0).all()

    def test_registered_patients_positive(self, lgd_data: pd.DataFrame) -> None:
        patients = lgd_data["registered_patients"].dropna()
        assert (patients >= 0).all()


class TestHSCTPrevalenceIntegrity:
    """Integration tests for HSC Trust level disease prevalence (DISPREVHSCT)."""

    @pytest.fixture(scope="class")
    def hsct_data(self) -> pd.DataFrame:
        return dp.get_hsct_prevalence()

    def test_required_columns(self, hsct_data: pd.DataFrame) -> None:
        required = {"financial_year", "year", "trust", "disease", "registered_patients", "prevalence_per_1000"}
        assert required <= set(hsct_data.columns), f"Missing columns: {required - set(hsct_data.columns)}"

    def test_five_trusts(self, hsct_data: pd.DataFrame) -> None:
        # HSCT matrix includes a 'Northern Ireland' aggregate row
        trusts = set(hsct_data["trust"].unique())
        individual_trusts = trusts - {"Northern Ireland"}
        assert len(individual_trusts) == 5, (
            f"Expected 5 individual HSC Trusts, got {len(individual_trusts)}: {sorted(individual_trusts)}"
        )

    def test_multiple_diseases(self, hsct_data: pd.DataFrame) -> None:
        assert hsct_data["disease"].nunique() >= 14


class TestGetLatestDiseasePrevLevel:
    """Tests for level parameter in get_latest_disease_prevalence."""

    def test_ni_level(self):
        df = dp.get_latest_disease_prevalence(level="ni")
        assert "lgd" not in df.columns
        assert "trust" not in df.columns

    def test_lgd_level(self):
        df = dp.get_latest_disease_prevalence(level="lgd")
        assert "lgd" in df.columns

    def test_trust_level(self):
        df = dp.get_latest_disease_prevalence(level="trust")
        assert "trust" in df.columns

    def test_lgd_filter_by_lcg(self):
        df = dp.get_latest_disease_prevalence(level="lgd", lcg="Belfast")
        assert (df["lgd"] == "Belfast").all()
        assert len(df) > 0

    def test_invalid_level_raises(self):
        with pytest.raises(ValueError, match="level must be"):
            dp.get_latest_disease_prevalence(level="bad")


class TestValidation:
    """Unit tests for validate_disease_prevalence — no network calls."""

    def _make_valid_df(self) -> pd.DataFrame:
        """Return a minimal valid DataFrame."""
        diseases = [
            "Hypertension", "Diabetes Mellitus", "Chronic Obstructive Pulmonary Disease",
            "Cancer", "Asthma", "Coronary Heart Disease", "Stroke & TIA", "Dementia",
            "Atrial Fibrillation", "Depression",
        ]
        years = list(range(2017, 2023))  # 6 years
        records = []
        for dis in diseases:
            for yr in years:
                fy = f"{yr}/{str(yr + 1)[-2:]}"
                records.append({
                    "year": yr,
                    "financial_year": fy,
                    "disease": dis,
                    "registered_patients": 50000.0,
                    "prevalence_per_1000": 100.0,
                })
        return pd.DataFrame(records)

    def test_validate_valid_dataframe(self) -> None:
        df = self._make_valid_df()
        assert dp.validate_disease_prevalence(df) is True

    def test_validate_empty_dataframe(self) -> None:
        df = pd.DataFrame(
            columns=["year", "financial_year", "disease", "registered_patients", "prevalence_per_1000"]
        )
        with pytest.raises(NISRAValidationError, match="empty"):
            dp.validate_disease_prevalence(df)

    def test_validate_missing_columns(self) -> None:
        df = pd.DataFrame({"year": [2017], "disease": ["Hypertension"]})
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            dp.validate_disease_prevalence(df)

    def test_validate_negative_prevalence(self) -> None:
        df = self._make_valid_df()
        df.loc[0, "prevalence_per_1000"] = -5.0
        with pytest.raises(NISRAValidationError, match="negative"):
            dp.validate_disease_prevalence(df)

    def test_validate_prevalence_above_1000(self) -> None:
        df = self._make_valid_df()
        df.loc[0, "prevalence_per_1000"] = 1001.0
        with pytest.raises(NISRAValidationError, match="1000"):
            dp.validate_disease_prevalence(df)

    def test_validate_negative_patients(self) -> None:
        df = self._make_valid_df()
        df.loc[0, "registered_patients"] = -1.0
        with pytest.raises(NISRAValidationError, match="negative"):
            dp.validate_disease_prevalence(df)

    def test_validate_too_few_diseases(self) -> None:
        df = self._make_valid_df()
        df = df[df["disease"] == "Hypertension"].reset_index(drop=True)
        with pytest.raises(NISRAValidationError, match="Too few disease registers"):
            dp.validate_disease_prevalence(df)

    def test_validate_too_few_years(self) -> None:
        df = self._make_valid_df()
        keep_fy = df["financial_year"].unique()[:3]
        df = df[df["financial_year"].isin(keep_fy)].reset_index(drop=True)
        with pytest.raises(NISRAValidationError, match="Too few financial years"):
            dp.validate_disease_prevalence(df)

    def test_validate_invalid_level(self) -> None:
        df = self._make_valid_df()
        with pytest.raises(ValueError, match="level must be"):
            dp.validate_disease_prevalence(df, level="bad")

    def test_validate_register_alias_accepted(self) -> None:
        """validate_disease_prevalence should accept 'register' as alias for 'disease'."""
        df = self._make_valid_df().rename(columns={"disease": "register"})
        # Should not raise
        assert dp.validate_disease_prevalence(df) is True

    def test_validate_gp_level_backward_compat(self) -> None:
        """level='gp' should be accepted for backward compatibility."""
        df = self._make_valid_df()
        assert dp.validate_disease_prevalence(df, level="gp") is True


class TestSheetToFinancialYear:
    """Unit tests for _sheet_to_financial_year — no network calls."""

    def test_standard_sheet_name(self) -> None:
        fy, year = dp._sheet_to_financial_year("Table 5a Prevalence 2026")
        assert fy == "2025/26"
        assert year == 2025

    def test_different_letter_suffix(self) -> None:
        fy, year = dp._sheet_to_financial_year("Table 5b Prevalence 2024")
        assert fy == "2023/24"
        assert year == 2023

    def test_early_year(self) -> None:
        fy, year = dp._sheet_to_financial_year("Table 5a Prevalence 2010")
        assert fy == "2009/10"
        assert year == 2009

    def test_invalid_sheet_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse year"):
            dp._sheet_to_financial_year("Table 5a Prevalence")


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
        assert required <= set(gp_data.columns), f"Missing columns: {required - set(gp_data.columns)}"

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

    def test_registered_patients_non_negative(self, gp_data: pd.DataFrame) -> None:
        patients = gp_data["registered_patients"].dropna()
        assert (patients >= 0).all(), "registered_patients has negative values"

    def test_prevalence_non_negative(self, gp_data: pd.DataFrame) -> None:
        prev = gp_data["prevalence_per_1000"].dropna()
        assert (prev >= 0).all(), "prevalence_per_1000 has negative values"

    def test_prevalence_below_1000(self, gp_data: pd.DataFrame) -> None:
        prev = gp_data["prevalence_per_1000"].dropna()
        assert (prev < 1000).all(), f"prevalence_per_1000 exceeds 1000: {prev[prev >= 1000].head().tolist()}"

    def test_multiple_years(self, gp_data: pd.DataFrame) -> None:
        n = gp_data["financial_year"].nunique()
        assert n >= 17, f"Expected ≥ 17 financial years, got {n}"

    def test_practice_name_populated(self, gp_data: pd.DataFrame) -> None:
        assert "practice_name" in gp_data.columns, "practice_name column missing"
        non_null = gp_data["practice_name"].notna().sum()
        assert non_null > 0, "practice_name is all-null; Table 4 join may have failed"
        latest_year = gp_data["year"].max()
        latest = gp_data[gp_data["year"] == latest_year]
        unique_codes = latest["practice_code"].nunique()
        named = latest.dropna(subset=["practice_name"])["practice_code"].nunique()
        fill_rate = named / unique_codes if unique_codes > 0 else 0.0
        assert fill_rate >= 0.8, (
            f"practice_name fill rate for {latest_year} is {fill_rate:.0%} ({named}/{unique_codes} practices)"
        )

    def test_financial_year_format(self, gp_data: pd.DataFrame) -> None:
        for fy in gp_data["financial_year"].dropna().unique():
            assert "/" in str(fy), f"Unexpected financial_year format: {fy!r}"

    def test_validation_passes(self, gp_data: pd.DataFrame) -> None:
        assert dp.validate_disease_prevalence(gp_data, level="gp") is True

    def test_get_latest_disease_prevalence_gp_level(self, gp_data: pd.DataFrame) -> None:
        """get_latest_disease_prevalence(level='gp') should return same data."""
        df = dp.get_latest_disease_prevalence(level="gp")
        assert "practice_code" in df.columns
        assert len(df) > 0


class TestGPRegisterCoverage:
    """Check key register coverage in GP-practice data."""

    @pytest.fixture(scope="class")
    def gp_data(self) -> pd.DataFrame:
        return dp.get_latest_gp_prevalence()

    def test_hypertension_present_all_years(self, gp_data: pd.DataFrame) -> None:
        hyp = gp_data[gp_data["register"].str.contains("Hypertension", case=False, na=False)]
        assert not hyp.empty, "No Hypertension rows found"
        assert hyp["financial_year"].nunique() == gp_data["financial_year"].nunique(), (
            "Hypertension not present in every financial year"
        )

    def test_copd_present(self, gp_data: pd.DataFrame) -> None:
        copd = gp_data[gp_data["register"].str.contains("Pulmonary", case=False, na=False)]
        assert not copd.empty, "No COPD rows found"

    def test_diabetes_present(self, gp_data: pd.DataFrame) -> None:
        diab = gp_data[gp_data["register"].str.contains("Diabetes", case=False, na=False)]
        assert not diab.empty, "No Diabetes rows found"
