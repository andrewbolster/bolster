"""Data integrity tests for UK Gender Pay Gap reporting data.

These tests validate that the data is internally consistent and that the
module correctly fetches, parses, and filters the GPG CSV files.
They use real data from the GPG service (not mocked).

Key validations:
- Required columns are present and correctly typed
- NI employer filter (BT postcodes) works correctly
- Pay quartiles for each employer sum to ~100%
- Pay gap values are within plausible bounds
- Multi-year combination works correctly
- Validation function correctly detects bad data
"""

import pandas as pd
import pytest

from bolster.data_sources import gender_pay_gap


class TestGenderPayGapData:
    """Test suite for a single reporting year of GPG data."""

    @pytest.fixture(scope="class")
    def latest_year(self):
        """Return the most recent available year."""
        return max(gender_pay_gap.get_available_years())

    @pytest.fixture(scope="class")
    def uk_data(self, latest_year):
        """Fetch full UK dataset for the latest year once for the class."""
        return gender_pay_gap.get_data(year=latest_year)

    @pytest.fixture(scope="class")
    def ni_data(self, latest_year):
        """Fetch NI-only dataset for the latest year (BT postcode prefix)."""
        return gender_pay_gap.get_data(year=latest_year, postcode_prefix="BT")

    def test_required_columns_present(self, uk_data):
        """All expected columns must be present."""
        required = {
            "employer_name",
            "employer_id",
            "postcode",
            "diff_mean_hourly_percent",
            "diff_median_hourly_percent",
            "employer_size",
            "reporting_year",
            "male_lower_quartile",
            "female_lower_quartile",
        }
        missing = required - set(uk_data.columns)
        assert not missing, f"Missing columns: {missing}"

    def test_dataset_not_empty(self, uk_data):
        """Dataset must contain employer records."""
        assert len(uk_data) > 1000, f"Expected 1000+ employers, got {len(uk_data)}"

    def test_ni_employers_present(self, ni_data):
        """NI filter must return some employers."""
        assert len(ni_data) > 0, "No NI employers found (BT postcodes)"

    def test_ni_filter_only_bt_postcodes(self, ni_data):
        """All rows in NI-filtered data must have BT postcodes."""
        assert ni_data["postcode"].str.upper().str.startswith("BT").all(), "Non-BT postcodes in NI-filtered data"

    def test_ni_employers_subset_of_uk(self, uk_data, ni_data):
        """NI employer count must be less than full UK dataset."""
        assert len(ni_data) < len(uk_data)

    def test_postcode_prefix_filter_is_case_insensitive(self, latest_year):
        """postcode_prefix filter must work regardless of case."""
        upper = gender_pay_gap.get_data(year=latest_year, postcode_prefix="BT")
        lower = gender_pay_gap.get_data(year=latest_year, postcode_prefix="bt")
        assert len(upper) == len(lower), "Case-insensitive filter returned different row counts"

    def test_reporting_year_column(self, uk_data, latest_year):
        """reporting_year column must equal the requested year for all rows."""
        assert (uk_data["reporting_year"] == latest_year).all()

    def test_numeric_columns_are_numeric(self, uk_data):
        """Numeric pay gap columns must be float dtype."""
        numeric_cols = [
            "diff_mean_hourly_percent",
            "diff_median_hourly_percent",
            "male_lower_quartile",
            "female_lower_quartile",
        ]
        for col in numeric_cols:
            assert pd.api.types.is_numeric_dtype(uk_data[col]), f"Column {col} is not numeric"

    def test_pay_gap_plausible_range(self, uk_data):
        """Mean and median hourly pay gaps must be within plausible bounds.

        The service accepts values in the range -1000 to +100 (percent). Extreme
        negative values (e.g. -757%) are genuine submissions from employers with
        very skewed workforce compositions; they are real data, not errors.
        A value above 100% (men paid more than double women) would be implausible.
        """
        for col in ("diff_mean_hourly_percent", "diff_median_hourly_percent"):
            valid = uk_data[col].dropna()
            assert (valid >= -1000).all(), f"{col} has values below -1000%"
            assert (valid <= 100).all(), f"{col} has values above 100%"

    def test_quartile_columns_sum_to_100(self, uk_data):
        """Male + female proportions must sum to ~100 for each pay quartile."""
        quartile_pairs = [
            ("male_lower_quartile", "female_lower_quartile"),
            ("male_lower_middle_quartile", "female_lower_middle_quartile"),
            ("male_upper_middle_quartile", "female_upper_middle_quartile"),
            ("male_top_quartile", "female_top_quartile"),
        ]
        for male_col, female_col in quartile_pairs:
            totals = uk_data[male_col].fillna(0) + uk_data[female_col].fillna(0)
            mask = uk_data[male_col].notna() & uk_data[female_col].notna()
            if mask.any():
                bad_count = ((totals[mask] - 100).abs() > 1.5).sum()
                assert bad_count == 0, (
                    f"{male_col}+{female_col} don't sum to 100 for {bad_count} rows"
                )

    def test_employer_size_valid_values(self, uk_data):
        """Employer size bands must be recognised values.

        Note: the service has used both comma-formatted ("5000 to 19,999",
        "20,000 or more") and plain ("5000 to 19999", "20000 or more") variants
        across reporting years. Both forms are accepted here.
        """
        valid_sizes = {
            "Less than 250",
            "250 to 499",
            "500 to 999",
            "1000 to 4999",
            "5000 to 19999",
            "5000 to 19,999",
            "20000 or more",
            "20,000 or more",
            "Not Provided",
        }
        actual_sizes = set(uk_data["employer_size"].dropna().unique())
        unexpected = actual_sizes - valid_sizes
        assert not unexpected, f"Unexpected employer size values: {unexpected}"

    def test_submitted_after_deadline_is_bool(self, uk_data):
        """submitted_after_deadline must be boolean."""
        non_bool = uk_data["submitted_after_deadline"].dropna()
        assert non_bool.isin([True, False]).all(), "submitted_after_deadline contains non-boolean values"

    def test_date_submitted_is_datetime(self, uk_data):
        """date_submitted must be parsed as datetime."""
        assert pd.api.types.is_datetime64_any_dtype(uk_data["date_submitted"]), (
            "date_submitted is not datetime"
        )

    def test_employer_names_not_empty(self, uk_data):
        """employer_name must not be empty or null for any row."""
        assert uk_data["employer_name"].notna().all(), "Some employer_name values are null"
        assert (uk_data["employer_name"].str.strip() != "").all(), "Some employer_name values are empty strings"


class TestGenderPayGapAvailableYears:
    """Test the year availability logic."""

    def test_available_years_includes_2017(self):
        """2017 is the first year of mandatory reporting."""
        assert 2017 in gender_pay_gap.get_available_years()

    def test_available_years_is_sorted(self):
        """Years must be in ascending order."""
        years = gender_pay_gap.get_available_years()
        assert years == sorted(years)

    def test_available_years_no_future(self):
        """Must not include years beyond current year."""
        current_year = pd.Timestamp.now().year
        assert all(y <= current_year for y in gender_pay_gap.get_available_years())

    def test_invalid_year_raises(self):
        """Requesting an unavailable year must raise GenderPayGapDataNotFoundError."""
        with pytest.raises(gender_pay_gap.GenderPayGapDataNotFoundError):
            gender_pay_gap.get_data(year=2010)

    def test_future_year_raises(self):
        """Requesting a future year must raise GenderPayGapDataNotFoundError."""
        with pytest.raises(gender_pay_gap.GenderPayGapDataNotFoundError):
            gender_pay_gap.get_data(year=2099)


class TestGenderPayGapMultiYear:
    """Test multi-year combination."""

    @pytest.fixture(scope="class")
    def multi_year_data(self):
        """Fetch last 3 years combined — keeps test runtime reasonable."""
        import pandas as pd
        years = sorted(gender_pay_gap.get_available_years())[-3:]
        frames = [gender_pay_gap.get_data(year=y) for y in years]
        return pd.concat(frames, ignore_index=True), years

    def test_all_years_present(self, multi_year_data):
        df, years = multi_year_data
        assert set(df["reporting_year"].unique()) == set(years)

    def test_no_duplicate_columns(self, multi_year_data):
        df, _ = multi_year_data
        assert len(df.columns) == len(set(df.columns)), "Duplicate column names after concat"

    def test_row_count_increases_with_years(self, multi_year_data):
        df, years = multi_year_data
        for year in years:
            assert len(df[df["reporting_year"] == year]) > 0, f"No rows for year {year}"


class TestGenderPayGapValidation:
    """Test the validate_data function."""

    @pytest.fixture(scope="class")
    def valid_df(self):
        return gender_pay_gap.get_data(year=max(gender_pay_gap.get_available_years()))

    def test_validate_passes_on_real_data(self, valid_df):
        """Validation must pass on real downloaded data."""
        assert gender_pay_gap.validate_data(valid_df)

    def test_validate_fails_on_missing_columns(self, valid_df):
        """Validation must fail when required columns are missing."""
        bad_df = valid_df.drop(columns=["employer_name"])
        with pytest.raises(gender_pay_gap.GenderPayGapError):
            gender_pay_gap.validate_data(bad_df)

    def test_validate_fails_on_bad_quartiles(self, valid_df):
        """Validation must fail when quartile columns don't sum to 100."""
        bad_df = valid_df.copy()
        bad_df["male_lower_quartile"] = 200.0  # Forces sum >> 100
        with pytest.raises(gender_pay_gap.GenderPayGapError):
            gender_pay_gap.validate_data(bad_df)

    def test_validate_fails_on_implausible_pay_gap(self, valid_df):
        """Validation must fail when pay gap values exceed the plausible cap of 100%."""
        bad_df = valid_df.copy()
        bad_df.loc[bad_df.index[0], "diff_mean_hourly_percent"] = 9999.0
        with pytest.raises(gender_pay_gap.GenderPayGapError):
            gender_pay_gap.validate_data(bad_df)
