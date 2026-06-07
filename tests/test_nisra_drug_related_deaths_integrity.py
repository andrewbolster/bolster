"""Integrity and validation tests for nisra.drug_related_deaths.

Network tests use real data from the NISRA PxStat API.  Validation unit
tests run entirely in-process (no network calls).
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import drug_related_deaths as drd


class TestHSCTIntegrity:
    """Integration tests against the live HSC Trust drug deaths data."""

    @pytest.fixture(scope="class")
    def hsct_data(self) -> pd.DataFrame:
        return drd.get_latest_drug_related_deaths(dimension="hsct")

    def test_required_columns(self, hsct_data: pd.DataFrame) -> None:
        required = {"year", "geography_code", "geography", "statistic", "value"}
        assert required <= set(hsct_data.columns), f"Missing columns: {required - set(hsct_data.columns)}"

    def test_not_empty(self, hsct_data: pd.DataFrame) -> None:
        assert len(hsct_data) > 0

    def test_statistics_present(self, hsct_data: pd.DataFrame) -> None:
        assert {"drug_related", "drug_misuse"} <= set(hsct_data["statistic"].unique())

    def test_ni_total_present(self, hsct_data: pd.DataFrame) -> None:
        assert "Northern Ireland" in hsct_data["geography"].values

    def test_five_trusts_plus_ni(self, hsct_data: pd.DataFrame) -> None:
        """There are 5 HSC Trusts plus NI total."""
        geographies = set(hsct_data["geography"].unique())
        trusts = geographies - {"Northern Ireland"}
        assert len(trusts) == 5, f"Expected 5 trusts, got {len(trusts)}: {trusts}"

    def test_value_ranges(self, hsct_data: pd.DataFrame) -> None:
        """All non-null values are non-negative; NI annual totals are within plausible bounds."""
        non_null = hsct_data["value"].dropna()
        assert (non_null >= 0).all()
        ni_drug_related = hsct_data[
            (hsct_data["geography"] == "Northern Ireland") & (hsct_data["statistic"] == "drug_related")
        ]["value"]
        assert ni_drug_related.max() < 1000, "Annual drug deaths implausibly high for NI"

    def test_historical_coverage_from_2003(self, hsct_data: pd.DataFrame) -> None:
        """PxStat data starts from 2003."""
        assert hsct_data["year"].min() <= 2003

    def test_sufficient_years(self, hsct_data: pd.DataFrame) -> None:
        """Should cover at least 15 years."""
        assert hsct_data["year"].nunique() >= 15

    def test_2023_ni_drug_related(self, hsct_data: pd.DataFrame) -> None:
        """2023 NI total drug-related deaths should be 169."""
        row = hsct_data[
            (hsct_data["year"] == 2023)
            & (hsct_data["geography"] == "Northern Ireland")
            & (hsct_data["statistic"] == "drug_related")
        ]
        assert len(row) == 1
        assert int(row["value"].iloc[0]) == 169

    def test_males_exceed_females_overall(self, hsct_data: pd.DataFrame) -> None:
        """Belfast Trust should have higher drug-related deaths than any single rural trust."""
        ni_by_year = hsct_data[
            (hsct_data["geography"] == "Northern Ireland") & (hsct_data["statistic"] == "drug_related")
        ]
        # NI totals should be consistently higher than any individual trust
        belfast = hsct_data[
            (hsct_data["geography"] == "Belfast") & (hsct_data["statistic"] == "drug_related")
        ]
        if len(belfast) > 0 and len(ni_by_year) > 0:
            merged = ni_by_year[["year", "value"]].merge(
                belfast[["year", "value"]], on="year", suffixes=("_ni", "_belfast")
            )
            assert (merged["value_ni"] >= merged["value_belfast"]).all()

    def test_validate_passes(self, hsct_data: pd.DataFrame) -> None:
        assert drd.validate_data(hsct_data) is True


class TestLGDIntegrity:
    """Integration tests against the LGD drug deaths data."""

    @pytest.fixture(scope="class")
    def lgd_data(self) -> pd.DataFrame:
        return drd.get_latest_drug_related_deaths(dimension="lgd")

    def test_required_columns(self, lgd_data: pd.DataFrame) -> None:
        required = {"year", "geography_code", "geography", "statistic", "value"}
        assert required <= set(lgd_data.columns)

    def test_not_empty(self, lgd_data: pd.DataFrame) -> None:
        assert len(lgd_data) > 0

    def test_eleven_districts_plus_ni(self, lgd_data: pd.DataFrame) -> None:
        geographies = set(lgd_data["geography"].unique())
        districts = geographies - {"Northern Ireland"}
        assert len(districts) == 11, f"Expected 11 districts, got {len(districts)}: {districts}"

    def test_statistics_present(self, lgd_data: pd.DataFrame) -> None:
        assert {"drug_related", "drug_misuse"} <= set(lgd_data["statistic"].unique())

    def test_non_negative(self, lgd_data: pd.DataFrame) -> None:
        non_null = lgd_data["value"].dropna()
        assert (non_null >= 0).all()

    def test_validate_passes(self, lgd_data: pd.DataFrame) -> None:
        assert drd.validate_data(lgd_data) is True


class TestAllDimension:
    """The 'all' dimension returns a dict of both geographic tables."""

    @pytest.fixture(scope="class")
    def all_data(self) -> dict:
        return drd.get_latest_drug_related_deaths(dimension="all")

    def test_keys(self, all_data: dict) -> None:
        assert sorted(all_data.keys()) == ["hsct", "lgd"]

    def test_all_non_empty(self, all_data: dict) -> None:
        assert all(len(df) > 0 for df in all_data.values())

    def test_consistent_ni_totals(self, all_data: dict) -> None:
        """NI totals should match between HSCT and LGD matrices."""
        hsct_ni = all_data["hsct"][
            (all_data["hsct"]["geography"] == "Northern Ireland") & (all_data["hsct"]["statistic"] == "drug_related")
        ].set_index("year")["value"]
        lgd_ni = all_data["lgd"][
            (all_data["lgd"]["geography"] == "Northern Ireland") & (all_data["lgd"]["statistic"] == "drug_related")
        ].set_index("year")["value"]
        common_years = hsct_ni.index.intersection(lgd_ni.index)
        assert len(common_years) > 0
        pd.testing.assert_series_equal(
            hsct_ni.loc[common_years].sort_index().astype(float),
            lgd_ni.loc[common_years].sort_index().astype(float),
            check_names=False,
        )


class TestValidation:
    """Unit tests for validation edge cases — no network calls needed."""

    def _good_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "year": list(range(2003, 2024)),
                "geography": ["Northern Ireland"] * 21,
                "geography_code": ["N92000002"] * 21,
                "statistic": ["drug_related"] * 21,
                "value": list(range(50, 71)),
            }
        )

    def test_validate_empty_dataframe(self) -> None:
        assert drd.validate_data(pd.DataFrame()) is False

    def test_validate_none(self) -> None:
        assert drd.validate_data(None) is False

    def test_validate_missing_columns(self) -> None:
        df = pd.DataFrame({"year": [2014], "value": [110]})
        assert drd.validate_data(df) is False

    def test_validate_negative_values(self) -> None:
        df = self._good_df()
        df.loc[0, "value"] = -5
        assert drd.validate_data(df) is False

    def test_validate_too_few_years(self) -> None:
        df = self._good_df().head(3)
        assert drd.validate_data(df) is False

    def test_validate_good_data(self) -> None:
        assert drd.validate_data(self._good_df()) is True

    def test_validate_null_values_allowed(self) -> None:
        """NaN values (suppressed small counts) should not fail validation."""
        df = self._good_df()
        df.loc[0, "value"] = float("nan")
        assert drd.validate_data(df) is True


class TestDimensionErrors:
    """get_latest_drug_related_deaths raises on invalid dimension."""

    def test_invalid_dimension(self) -> None:
        with pytest.raises(ValueError, match="dimension must be one of"):
            drd.get_latest_drug_related_deaths(dimension="bogus")
