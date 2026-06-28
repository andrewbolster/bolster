"""Integrity and validation tests for nisra.deprivation.

Network tests download the live NIMDM2017 SOA-level results file from NISRA.
Validation unit tests run entirely in-process (no network calls).
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import deprivation
from bolster.data_sources.nisra._base import NISRAValidationError


class TestDeprivationIntegrity:
    """Integration tests against the live NIMDM2017 SOA results file."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return deprivation.get_latest_data()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        required = {
            "lgd",
            "urban_rural",
            "soa_code",
            "soa_name",
            "mdm_rank",
            "income_rank",
            "employment_rank",
            "health_disability_rank",
            "education_rank",
            "access_to_services_rank",
            "living_environment_rank",
            "crime_disorder_rank",
        }
        assert required <= set(latest_data.columns), f"Missing columns: {required - set(latest_data.columns)}"

    def test_not_empty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0

    def test_soa_count(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["soa_code"].nunique() >= 880, (
            f"Expected ~890 SOAs, got {latest_data['soa_code'].nunique()}"
        )

    def test_soa_codes_unique(self, latest_data: pd.DataFrame) -> None:
        assert not latest_data["soa_code"].duplicated().any()

    def test_mdm_rank_is_complete_permutation(self, latest_data: pd.DataFrame) -> None:
        ranks = sorted(latest_data["mdm_rank"].dropna().tolist())
        assert ranks == list(range(1, len(latest_data) + 1))

    def test_domain_ranks_within_range(self, latest_data: pd.DataFrame) -> None:
        n = len(latest_data)
        domain_cols = [
            "income_rank",
            "employment_rank",
            "health_disability_rank",
            "education_rank",
            "access_to_services_rank",
            "living_environment_rank",
            "crime_disorder_rank",
        ]
        for col in domain_cols:
            values = latest_data[col].dropna()
            assert values.min() >= 1
            assert values.max() <= n

    def test_multiple_lgds_present(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["lgd"].nunique() >= 8

    def test_validate_data_passes(self, latest_data: pd.DataFrame) -> None:
        assert deprivation.validate_data(latest_data) is True


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def _valid_df(self, n: int = 890) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "soa_code": [f"SOA{i:04d}" for i in range(n)],
                "soa_name": [f"Area_{i}" for i in range(n)],
                "lgd": ["Belfast"] * n,
                "urban_rural": ["Urban"] * n,
                "mdm_rank": list(range(1, n + 1)),
                "income_rank": list(range(1, n + 1)),
                "employment_rank": list(range(1, n + 1)),
                "health_disability_rank": list(range(1, n + 1)),
                "education_rank": list(range(1, n + 1)),
                "access_to_services_rank": list(range(1, n + 1)),
                "living_environment_rank": list(range(1, n + 1)),
                "crime_disorder_rank": list(range(1, n + 1)),
            }
        )

    def test_validate_empty_dataframe(self) -> None:
        df = self._valid_df(0)
        with pytest.raises(NISRAValidationError, match="empty"):
            deprivation.validate_data(df)

    def test_validate_missing_columns(self) -> None:
        df = self._valid_df().drop(columns=["mdm_rank"])
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            deprivation.validate_data(df)

    def test_validate_too_few_soas(self) -> None:
        df = self._valid_df(100)
        with pytest.raises(NISRAValidationError, match="Expected ~890 SOAs"):
            deprivation.validate_data(df)

    def test_validate_duplicate_soa_codes(self) -> None:
        df = self._valid_df()
        df.loc[1, "soa_code"] = df.loc[0, "soa_code"]
        with pytest.raises(NISRAValidationError, match="Duplicate soa_code"):
            deprivation.validate_data(df)

    def test_validate_rank_out_of_range(self) -> None:
        df = self._valid_df()
        df.loc[0, "mdm_rank"] = 0
        with pytest.raises(NISRAValidationError, match="outside the expected"):
            deprivation.validate_data(df)

    def test_validate_rank_above_range(self) -> None:
        df = self._valid_df()
        df.loc[0, "mdm_rank"] = len(df) + 100
        with pytest.raises(NISRAValidationError, match="outside the expected"):
            deprivation.validate_data(df)

    def test_validate_non_unique_ranks(self) -> None:
        df = self._valid_df()
        df["mdm_rank"] = 1
        with pytest.raises(NISRAValidationError, match="near-.unique ranks"):
            deprivation.validate_data(df)

    def test_validate_valid_data_passes(self) -> None:
        df = self._valid_df()
        assert deprivation.validate_data(df) is True
