"""Data integrity tests for NISRA Baby Names Northern Ireland statistics.

These tests validate that the data is internally consistent and structurally correct.
They use real data from NISRA (no mocks) and cover the full historical series (1997–present).

Key validations:
- Required columns present with correct types
- Both sexes present (Boys and Girls)
- Year range starts at 1997
- Rank starts at 1 for each sex/year
- All counts are positive
- Top name each year has rank 1
- validate_baby_names() rejects bad data
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import baby_names
from bolster.data_sources.nisra._base import NISRAValidationError


class TestBabyNamesDataIntegrity:
    """Test suite for validating internal consistency of NISRA baby names data."""

    @pytest.fixture(scope="class")
    def baby_names_data(self):
        """Fetch the full historical baby names data once for the test class."""
        return baby_names.get_baby_names(force_refresh=False)

    def test_required_columns_present(self, baby_names_data):
        """Test that all required columns are present."""
        required = {"year", "name", "sex", "rank", "count"}
        assert required.issubset(set(baby_names_data.columns)), (
            f"Missing columns: {required - set(baby_names_data.columns)}"
        )

    def test_no_null_values(self, baby_names_data):
        """Test that there are no null values in required columns."""
        for col in ("year", "name", "sex", "rank", "count"):
            null_count = baby_names_data[col].isnull().sum()
            assert null_count == 0, f"Column '{col}' has {null_count} null values"

    def test_both_sexes_present(self, baby_names_data):
        """Test that both Boys and Girls are present."""
        sexes = set(baby_names_data["sex"].unique())
        assert "Boys" in sexes, f"'Boys' not found in sex values: {sexes}"
        assert "Girls" in sexes, f"'Girls' not found in sex values: {sexes}"

    def test_year_range_starts_at_1997(self, baby_names_data):
        """Test that data starts at 1997 or earlier."""
        min_year = baby_names_data["year"].min()
        assert min_year <= 1997, f"Year range starts at {min_year}, expected 1997 or earlier"

    def test_year_range_current(self, baby_names_data):
        """Test that data covers recent years (at least up to 2020)."""
        max_year = baby_names_data["year"].max()
        assert max_year >= 2020, f"Year range only goes to {max_year}, expected at least 2020"

    def test_rank_starts_at_one(self, baby_names_data):
        """Test that rank 1 exists for each sex and year combination."""
        for (year, sex), group in baby_names_data.groupby(["year", "sex"]):
            min_rank = group["rank"].min()
            assert min_rank == 1, f"Minimum rank for {sex} {year} is {min_rank}, expected 1"

    def test_counts_positive(self, baby_names_data):
        """Test that all count values are positive (> 0)."""
        non_positive = (baby_names_data["count"] <= 0).sum()
        assert non_positive == 0, f"{non_positive} rows have non-positive count values"

    def test_ranks_positive(self, baby_names_data):
        """Test that all rank values are positive (> 0)."""
        non_positive = (baby_names_data["rank"] <= 0).sum()
        assert non_positive == 0, f"{non_positive} rows have non-positive rank values"

    def test_top_name_has_rank_one(self, baby_names_data):
        """Test that the name with the highest count in each year/sex has rank 1.

        Within each year and sex, the name with count == max(count) should have rank == 1.
        Ties at the top are allowed but at least one rank-1 row must exist.
        """
        for (year, sex), group in baby_names_data.groupby(["year", "sex"]):
            rank1_rows = group[group["rank"] == 1]
            assert len(rank1_rows) >= 1, f"No rank-1 name found for {sex} {year}"

            max_count = group["count"].max()
            rank1_max_count = rank1_rows["count"].max()

            # Rank-1 entry must have the highest (or joint-highest) count
            assert rank1_max_count == max_count, (
                f"{sex} {year}: rank-1 name has count {rank1_max_count} but max count is {max_count}"
            )

    def test_names_are_strings(self, baby_names_data):
        """Test that all name values are non-empty strings."""
        assert baby_names_data["name"].dtype == object, "name column should be string dtype"
        empty_names = (baby_names_data["name"].str.strip() == "").sum()
        assert empty_names == 0, f"{empty_names} rows have empty name strings"

    def test_year_dtype_integer(self, baby_names_data):
        """Test that year column contains integers."""
        assert pd.api.types.is_integer_dtype(baby_names_data["year"]), (
            f"year column dtype is {baby_names_data['year'].dtype}, expected integer"
        )

    def test_rank_dtype_integer(self, baby_names_data):
        """Test that rank column contains integers."""
        assert pd.api.types.is_integer_dtype(baby_names_data["rank"]), (
            f"rank column dtype is {baby_names_data['rank'].dtype}, expected integer"
        )

    def test_count_dtype_integer(self, baby_names_data):
        """Test that count column contains integers."""
        assert pd.api.types.is_integer_dtype(baby_names_data["count"]), (
            f"count column dtype is {baby_names_data['count'].dtype}, expected integer"
        )

    def test_historically_popular_names_present(self, baby_names_data):
        """Test that well-known historically popular NI names appear in early years.

        Matthew was the top boys' name in 1997, 1998, 1999.
        Chloe was the top girls' name in 1997, 1998, 1999.
        """
        boys_1997 = baby_names_data[(baby_names_data["year"] == 1997) & (baby_names_data["sex"] == "Boys")]
        top_boys_1997 = boys_1997[boys_1997["rank"] == 1]["name"].values
        assert "Matthew" in top_boys_1997, f"Expected Matthew as top boys name in 1997, got: {top_boys_1997}"

        girls_1997 = baby_names_data[(baby_names_data["year"] == 1997) & (baby_names_data["sex"] == "Girls")]
        top_girls_1997 = girls_1997[girls_1997["rank"] == 1]["name"].values
        assert "Chloe" in top_girls_1997, f"Expected Chloe as top girls name in 1997, got: {top_girls_1997}"

    def test_data_volume_reasonable(self, baby_names_data):
        """Test that the data contains a reasonable number of records.

        With ~29 years and hundreds of names per year per sex, we expect tens of thousands
        of records total.
        """
        assert len(baby_names_data) >= 10_000, f"Only {len(baby_names_data)} records — expected at least 10,000"

    def test_validate_passes(self, baby_names_data):
        """Test that validate_baby_names() passes on real data."""
        assert baby_names.validate_baby_names(baby_names_data)


class TestBabyNamesValidation:
    """Unit tests for validate_baby_names() — no network calls needed."""

    def _make_valid_df(self) -> pd.DataFrame:
        """Create a minimal valid DataFrame for testing."""
        return pd.DataFrame(
            {
                "year": [1997, 1997, 1997, 1997],
                "name": ["Matthew", "Ryan", "Chloe", "Shannon"],
                "sex": ["Boys", "Boys", "Girls", "Girls"],
                "rank": [1, 2, 1, 2],
                "count": [410, 381, 361, 313],
            }
        )

    def test_validate_rejects_empty_dataframe(self):
        """Test that validate_baby_names() raises on empty DataFrame."""
        with pytest.raises(NISRAValidationError, match="empty"):
            baby_names.validate_baby_names(pd.DataFrame())

    def test_validate_rejects_none(self):
        """Test that validate_baby_names() raises on None."""
        with pytest.raises(NISRAValidationError, match="empty"):
            baby_names.validate_baby_names(None)

    def test_validate_rejects_missing_columns(self):
        """Test that validate_baby_names() raises on missing required columns."""
        df = self._make_valid_df().drop(columns=["count"])
        with pytest.raises(NISRAValidationError, match="Missing required columns"):
            baby_names.validate_baby_names(df)

    def test_validate_rejects_missing_boys(self):
        """Test that validate_baby_names() raises when Boys sex is absent."""
        df = self._make_valid_df()
        df = df[df["sex"] == "Girls"]
        with pytest.raises(NISRAValidationError, match="Boys"):
            baby_names.validate_baby_names(df)

    def test_validate_rejects_missing_girls(self):
        """Test that validate_baby_names() raises when Girls sex is absent."""
        df = self._make_valid_df()
        df = df[df["sex"] == "Boys"]
        with pytest.raises(NISRAValidationError, match="Girls"):
            baby_names.validate_baby_names(df)

    def test_validate_rejects_negative_counts(self):
        """Test that validate_baby_names() raises on negative count values."""
        df = self._make_valid_df()
        df.loc[0, "count"] = -1
        with pytest.raises(NISRAValidationError, match="non-positive count"):
            baby_names.validate_baby_names(df)

    def test_validate_rejects_zero_counts(self):
        """Test that validate_baby_names() raises on zero count values."""
        df = self._make_valid_df()
        df.loc[0, "count"] = 0
        with pytest.raises(NISRAValidationError, match="non-positive count"):
            baby_names.validate_baby_names(df)

    def test_validate_rejects_negative_ranks(self):
        """Test that validate_baby_names() raises on negative rank values."""
        df = self._make_valid_df()
        df.loc[0, "rank"] = -1
        with pytest.raises(NISRAValidationError, match="non-positive rank"):
            baby_names.validate_baby_names(df)

    def test_validate_rejects_late_start_year(self):
        """Test that validate_baby_names() raises when year range starts too late."""
        df = self._make_valid_df()
        df["year"] = 2010  # No data before 2010
        with pytest.raises(NISRAValidationError, match="Year range"):
            baby_names.validate_baby_names(df)

    def test_validate_rejects_rank_not_starting_at_one(self):
        """Test that validate_baby_names() raises when minimum rank is not 1."""
        df = self._make_valid_df()
        df["rank"] = df["rank"] + 1  # Shift all ranks up by 1
        with pytest.raises(NISRAValidationError, match="rank"):
            baby_names.validate_baby_names(df)

    def test_validate_accepts_valid_data(self):
        """Test that validate_baby_names() returns True for valid data."""
        df = self._make_valid_df()
        assert baby_names.validate_baby_names(df) is True
