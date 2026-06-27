"""Integrity and validation tests for nisra.business_register.

Network tests download the live IDBR publication Excel file from NISRA.
Validation unit tests run entirely in-process (no network calls).
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import business_register
from bolster.data_sources.nisra._base import NISRAValidationError


class TestIndustryIntegrity:
    """Integration tests against the live IDBR Table 1.1 (industry group)."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return business_register.get_businesses_by_industry()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        assert {"year", "industry_group", "businesses"} <= set(latest_data.columns)

    def test_not_empty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0

    def test_historical_coverage_back_to_2010(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["year"].min() <= 2010

    def test_multiple_industries_present(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["industry_group"].nunique() >= 10

    def test_businesses_non_negative(self, latest_data: pd.DataFrame) -> None:
        assert (latest_data["businesses"].dropna() >= 0).all()

    def test_validate_data_passes(self, latest_data: pd.DataFrame) -> None:
        assert business_register.validate_data(latest_data, level="industry") is True


class TestLegalStatusIntegrity:
    """Integration tests against the live IDBR Table 2.1 (legal status)."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return business_register.get_businesses_by_legal_status()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        assert {"year", "legal_status", "sector", "businesses"} <= set(latest_data.columns)

    def test_not_empty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0

    def test_multiple_legal_statuses_present(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["legal_status"].nunique() >= 5

    def test_validate_data_passes(self, latest_data: pd.DataFrame) -> None:
        assert business_register.validate_data(latest_data, level="legal_status") is True


class TestLgdIntegrity:
    """Integration tests against the live IDBR Table 3.1 (LGD)."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return business_register.get_businesses_by_lgd()

    def test_required_columns(self, latest_data: pd.DataFrame) -> None:
        assert {"year", "lgd", "businesses"} <= set(latest_data.columns)

    def test_not_empty(self, latest_data: pd.DataFrame) -> None:
        assert len(latest_data) > 0

    def test_historical_coverage_back_to_2013(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["year"].min() <= 2013

    def test_lgds_present(self, latest_data: pd.DataFrame) -> None:
        assert latest_data["lgd"].nunique() >= 11

    def test_validate_data_passes(self, latest_data: pd.DataFrame) -> None:
        assert business_register.validate_data(latest_data, level="lgd") is True


class TestGetLatestData:
    """Tests for the get_latest_data dispatcher."""

    def test_default_level_is_industry(self) -> None:
        data = business_register.get_latest_data()
        assert "industry_group" in data.columns

    def test_level_legal_status(self) -> None:
        data = business_register.get_latest_data(level="legal_status")
        assert "legal_status" in data.columns

    def test_level_lgd(self) -> None:
        data = business_register.get_latest_data(level="lgd")
        assert "lgd" in data.columns

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(ValueError, match="level must be"):
            business_register.get_latest_data(level="bogus")


class TestValidation:
    """Unit tests for validation edge cases - no network calls needed."""

    def _industry_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "year": [2010, 2011, 2012, 2013],
                "industry_group": ["Retail", "Construction", "Production", "Wholesale"],
                "businesses": [6630.0, 11495.0, 4455.0, 3385.0],
            }
        )

    def test_validate_empty_dataframe(self) -> None:
        df = self._industry_df().iloc[0:0]
        with pytest.raises(NISRAValidationError, match="empty"):
            business_register.validate_data(df, level="industry")

    def test_validate_missing_columns(self) -> None:
        df = self._industry_df().drop(columns=["businesses"])
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            business_register.validate_data(df, level="industry")

    def test_validate_negative_values(self) -> None:
        df = self._industry_df()
        df.loc[0, "businesses"] = -5
        with pytest.raises(NISRAValidationError, match="negative values"):
            business_register.validate_data(df, level="industry")

    def test_validate_too_few_categories(self) -> None:
        df = self._industry_df().iloc[:2]
        with pytest.raises(NISRAValidationError, match="Too few distinct"):
            business_register.validate_data(df, level="industry")

    def test_validate_late_coverage_start(self) -> None:
        df = self._industry_df()
        df["year"] = df["year"] + 20
        with pytest.raises(NISRAValidationError, match="Expected coverage"):
            business_register.validate_data(df, level="industry")

    def test_validate_invalid_level_raises(self) -> None:
        with pytest.raises(ValueError, match="level must be"):
            business_register.validate_data(self._industry_df(), level="bogus")

    def test_validate_valid_data_passes(self) -> None:
        assert business_register.validate_data(self._industry_df(), level="industry") is True
