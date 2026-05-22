"""Data integrity tests for PSNI Stop and Search Statistics.

Tests cover:
- Required columns present and correctly typed
- Multiple financial years of data present (2017/18 onwards)
- Demographic columns have expected values
- Validation function edge cases (no network calls in TestValidation)
"""

import pandas as pd
import pytest

from bolster.data_sources.psni import stop_and_search
from bolster.data_sources.psni._base import PSNIValidationError


class TestStopAndSearchIntegrity:
    """Integration tests against the real dataset — requires network access."""

    @pytest.fixture(scope="class")
    def latest_data(self) -> pd.DataFrame:
        return stop_and_search.get_latest_stop_and_search()

    def test_required_columns_present(self, latest_data: pd.DataFrame) -> None:
        """All expected snake_case columns must be present."""
        expected = {
            "financial_year",
            "geographical_level",
            "legislation",
            "pace_reason_stolen_articles",
            "pace_reason_prohibited_articles",
            "pace_reason_blade_or_point",
            "pace_reason_fireworks",
            "quarter",
            "age_group",
            "gender",
        }
        missing = expected - set(latest_data.columns)
        assert not missing, f"Missing columns: {missing}"

    def test_row_count(self, latest_data: pd.DataFrame) -> None:
        """Dataset should have well over 100,000 records."""
        assert len(latest_data) > 100_000, f"Expected >100,000 rows, got {len(latest_data):,}"

    def test_multiple_financial_years(self, latest_data: pd.DataFrame) -> None:
        """Dataset must span multiple financial years."""
        years = latest_data["financial_year"].unique().tolist()
        assert len(years) >= 3, f"Expected ≥3 financial years, got {len(years)}: {years}"

    def test_data_from_2017_18(self, latest_data: pd.DataFrame) -> None:
        """Dataset must include records from 2017/18 (earliest year in series)."""
        year_strings = [str(y) for y in latest_data["financial_year"].unique()]
        assert "2017/18" in year_strings, f"2017/18 not found in years: {sorted(year_strings)}"

    def test_no_negative_counts(self, latest_data: pd.DataFrame) -> None:
        """There should be no numeric columns with negative values."""
        numeric_cols = latest_data.select_dtypes(include="number").columns
        for col in numeric_cols:
            min_val = latest_data[col].min()
            assert min_val >= 0, f"Column '{col}' has negative values (min={min_val})"

    def test_pace_columns_are_boolean(self, latest_data: pd.DataFrame) -> None:
        """PACE reason columns must be boolean with no nulls."""
        pace_cols = [
            "pace_reason_stolen_articles",
            "pace_reason_prohibited_articles",
            "pace_reason_blade_or_point",
            "pace_reason_fireworks",
        ]
        for col in pace_cols:
            assert latest_data[col].dtype == bool, f"Column '{col}' should be bool, got {latest_data[col].dtype}"
            assert latest_data[col].isna().sum() == 0, f"Column '{col}' has unexpected nulls"

    def test_gender_values(self, latest_data: pd.DataFrame) -> None:
        """Gender column should only contain expected values."""
        expected_genders = {"Male", "Female", "Other/Unknown"}
        actual_genders = set(latest_data["gender"].unique())
        unexpected = actual_genders - expected_genders
        assert not unexpected, f"Unexpected gender values: {unexpected}"

    def test_quarter_is_ordered_categorical(self, latest_data: pd.DataFrame) -> None:
        """Quarter column must be an ordered categorical."""
        assert hasattr(latest_data["quarter"], "cat"), "quarter must be a Categorical dtype"
        assert latest_data["quarter"].cat.ordered, "quarter Categorical must be ordered"

    def test_all_quarters_present(self, latest_data: pd.DataFrame) -> None:
        """All four quarters of the financial year must appear in the data."""
        expected_quarters = {
            "April to June",
            "July to September",
            "October to December",
            "January to March",
        }
        actual = set(latest_data["quarter"].unique())
        missing = expected_quarters - actual
        assert not missing, f"Missing quarters: {missing}"

    def test_age_group_ordered_categorical(self, latest_data: pd.DataFrame) -> None:
        """age_group column must be an ordered categorical."""
        assert hasattr(latest_data["age_group"], "cat"), "age_group must be Categorical"
        assert latest_data["age_group"].cat.ordered, "age_group Categorical must be ordered"

    def test_under_18_present(self, latest_data: pd.DataFrame) -> None:
        """Under-18 age group must be present (important demographic for reporting)."""
        age_groups = latest_data["age_group"].unique().tolist()
        assert "Under 18" in age_groups, f"'Under 18' not found in age groups: {age_groups}"

    def test_misuse_of_drugs_act_present(self, latest_data: pd.DataFrame) -> None:
        """Misuse of Drugs Act should be the predominant legislation (known from data)."""
        leg_counts = latest_data["legislation"].value_counts()
        top_legislation = leg_counts.index[0]
        assert "Misuse of Drugs Act" in top_legislation, (
            f"Expected Misuse of Drugs Act to be top legislation, got: {top_legislation}"
        )

    def test_validate_passes_on_real_data(self, latest_data: pd.DataFrame) -> None:
        """validate_stop_and_search must return True on the real dataset."""
        result = stop_and_search.validate_stop_and_search(latest_data)
        assert result is True

    def test_get_latest_dataset_url_returns_csv(self) -> None:
        """get_latest_dataset_url must return an https CSV URL."""
        url = stop_and_search.get_latest_dataset_url()
        assert url.startswith("https://"), f"URL should start with https://, got: {url}"
        assert url.endswith(".csv"), f"URL should end with .csv, got: {url}"


class TestValidation:
    """Unit tests for validate_stop_and_search edge cases — no network calls."""

    def _make_minimal_df(self) -> pd.DataFrame:
        """Create a minimal valid DataFrame for use in tests."""
        return pd.DataFrame(
            {
                "financial_year": pd.Categorical(["2017/18", "2023/24"]),
                "geographical_level": pd.Categorical(["Northern Ireland", "Northern Ireland"]),
                "legislation": pd.Categorical(["Misuse of Drugs Act S23", "Police and Criminal Evidence Order (PACE)"]),
                "pace_reason_stolen_articles": [False, True],
                "pace_reason_prohibited_articles": [False, False],
                "pace_reason_blade_or_point": [False, False],
                "pace_reason_fireworks": [False, False],
                "quarter": pd.Categorical(
                    ["April to June", "July to September"],
                    categories=[
                        "April to June",
                        "July to September",
                        "October to December",
                        "January to March",
                    ],
                    ordered=True,
                ),
                "age_group": pd.Categorical(
                    ["18 to 25", "26 to 35"],
                    categories=[
                        "Under 18",
                        "18 to 25",
                        "26 to 35",
                        "36 to 45",
                        "46 to 55",
                        "56 to 65",
                        "Over 65",
                        "Not Specified",
                    ],
                    ordered=True,
                ),
                "gender": pd.Categorical(["Male", "Female"]),
            }
        )

    def test_validate_empty_dataframe(self) -> None:
        """validate_stop_and_search must raise PSNIValidationError on empty DataFrame."""
        with pytest.raises(PSNIValidationError, match="empty"):
            stop_and_search.validate_stop_and_search(pd.DataFrame())

    def test_validate_missing_columns(self) -> None:
        """validate_stop_and_search must raise PSNIValidationError if columns are missing."""
        df = pd.DataFrame({"financial_year": ["2017/18"], "legislation": ["test"]})
        with pytest.raises(PSNIValidationError, match="Missing required columns"):
            stop_and_search.validate_stop_and_search(df)

    def test_validate_missing_2017_18(self) -> None:
        """validate_stop_and_search must raise PSNIValidationError if 2017/18 is absent."""
        df = self._make_minimal_df()
        # Replace with a year that doesn't include 2017/18
        df["financial_year"] = pd.Categorical(["2022/23", "2023/24"])
        with pytest.raises(PSNIValidationError, match="2017/18"):
            stop_and_search.validate_stop_and_search(df)

    def test_validate_single_year_fails(self) -> None:
        """validate_stop_and_search must raise PSNIValidationError if only one year present."""
        df = self._make_minimal_df()
        df["financial_year"] = pd.Categorical(["2017/18", "2017/18"])
        with pytest.raises(PSNIValidationError, match="multiple financial years"):
            stop_and_search.validate_stop_and_search(df)

    def test_validate_too_few_records(self) -> None:
        """validate_stop_and_search must raise PSNIValidationError if fewer than 50,000 rows."""
        df = self._make_minimal_df()
        # Minimal df has 2 rows — well below the 50k threshold
        with pytest.raises(PSNIValidationError, match="Too few records"):
            stop_and_search.validate_stop_and_search(df)

    def test_validate_null_pace_column(self) -> None:
        """validate_stop_and_search must raise PSNIValidationError if PACE column has nulls."""
        # Build a df large enough to pass the row count check
        rows = 60_000
        df = pd.DataFrame(
            {
                "financial_year": pd.Categorical(["2017/18"] * (rows // 2) + ["2023/24"] * (rows // 2)),
                "geographical_level": pd.Categorical(["Northern Ireland"] * rows),
                "legislation": pd.Categorical(["Misuse of Drugs Act S23"] * rows),
                "pace_reason_stolen_articles": [None] * rows,  # nulls — should fail
                "pace_reason_prohibited_articles": [False] * rows,
                "pace_reason_blade_or_point": [False] * rows,
                "pace_reason_fireworks": [False] * rows,
                "quarter": pd.Categorical(
                    ["April to June"] * rows,
                    categories=[
                        "April to June",
                        "July to September",
                        "October to December",
                        "January to March",
                    ],
                    ordered=True,
                ),
                "age_group": pd.Categorical(
                    ["18 to 25"] * rows,
                    categories=[
                        "Under 18",
                        "18 to 25",
                        "26 to 35",
                        "36 to 45",
                        "46 to 55",
                        "56 to 65",
                        "Over 65",
                        "Not Specified",
                    ],
                    ordered=True,
                ),
                "gender": pd.Categorical(["Male"] * rows),
            }
        )
        with pytest.raises(PSNIValidationError, match="null"):
            stop_and_search.validate_stop_and_search(df)
