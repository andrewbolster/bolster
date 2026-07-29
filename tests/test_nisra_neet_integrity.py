"""Data integrity tests for NISRA young people NEET statistics.

These tests validate the data returned by the ``neet`` module against real
data from NISRA (no mocks). They verify structural, numerical, and temporal
correctness of the parsed output.

Key validations:
- All required columns present across the four published tables
- Quarterly series is continuous from January-March 2013 with no gaps
- Counts are non-negative, rates lie within 0-100, confidence intervals bracket
  their point estimate
- Male and female counts sum to the published total
- Recent data available (2025 or later)
- ``validate_data`` rejects empty, malformed and out-of-range DataFrames
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra import neet
from bolster.data_sources.nisra._base import NISRADataNotFoundError


@pytest.mark.network
class TestQuarterlySeriesIntegrity:
    """Test suite for the quarterly NEET time series (sheet 2.40)."""

    @pytest.fixture(scope="class")
    def series(self) -> pd.DataFrame:
        """Fetch the quarterly NEET series once for the test class."""
        return neet.get_quarterly_series()

    def test_required_columns_present(self, series: pd.DataFrame) -> None:
        """Test that all required columns are present."""
        required = {
            "quarter",
            "period_start",
            "year",
            "quarter_code",
            "male_neet",
            "female_neet",
            "total_neet",
            "total_neet_lower",
            "total_neet_upper",
            "male_neet_rate_pct",
            "female_neet_rate_pct",
            "total_neet_rate_pct",
            "total_neet_rate_lower_pct",
            "total_neet_rate_upper_pct",
        }
        assert required.issubset(set(series.columns)), f"Missing columns: {required - set(series.columns)}"

    def test_dataframe_not_empty(self, series: pd.DataFrame) -> None:
        """Test that the series contains rows."""
        assert len(series) > 0, "Quarterly series is empty"

    def test_series_starts_in_2013(self, series: pd.DataFrame) -> None:
        """Test that the published series begins with January-March 2013."""
        assert series["period_start"].min() == pd.Timestamp("2013-01-01"), (
            f"Series starts at {series['period_start'].min()}, expected 2013-01-01"
        )

    def test_recent_data_available(self, series: pd.DataFrame) -> None:
        """Test that data for 2025 or later is present."""
        max_year = int(series["year"].max())
        assert max_year >= 2025, f"Most recent year is {max_year}, expected 2025 or later"

    def test_quarters_are_continuous(self, series: pd.DataFrame) -> None:
        """Test that there are no missing quarters in the series."""
        expected = pd.date_range(series["period_start"].min(), series["period_start"].max(), freq="QS-JAN")
        missing = set(expected) - set(series["period_start"])
        assert not missing, f"Missing quarters: {sorted(missing)}"

    def test_no_duplicate_quarters(self, series: pd.DataFrame) -> None:
        """Test that each quarter appears exactly once."""
        duplicates = series[series["period_start"].duplicated()]
        assert duplicates.empty, f"Duplicate quarters: {duplicates['quarter'].tolist()}"

    def test_quarter_codes_are_known(self, series: pd.DataFrame) -> None:
        """Test that quarter codes use the four expected labels."""
        assert set(series["quarter_code"]) <= {"Jan-Mar", "Apr-Jun", "Jul-Sep", "Oct-Dec"}, (
            f"Unexpected quarter codes: {sorted(set(series['quarter_code']))}"
        )

    def test_year_column_is_integer(self, series: pd.DataFrame) -> None:
        """Test that the year column contains integers."""
        assert pd.api.types.is_integer_dtype(series["year"]), f"'year' is not integer: {series['year'].dtype}"

    def test_count_columns_are_numeric(self, series: pd.DataFrame) -> None:
        """Test that all count columns are numeric."""
        for column in ("male_neet", "female_neet", "total_neet", "total_neet_lower", "total_neet_upper"):
            assert pd.api.types.is_numeric_dtype(series[column]), f"{column} is not numeric: {series[column].dtype}"

    def test_counts_are_non_negative(self, series: pd.DataFrame) -> None:
        """Test that no count column holds a negative value."""
        for column in ("male_neet", "female_neet", "total_neet", "total_neet_lower", "total_neet_upper"):
            bad = series[series[column] < 0]
            assert bad.empty, f"Negative values in {column}:\n{bad[['quarter', column]]}"

    def test_rates_within_valid_range(self, series: pd.DataFrame) -> None:
        """Test that all rate columns lie within 0-100 percent."""
        for column in [c for c in series.columns if c.endswith("_pct")]:
            bad = series[(series[column] < 0) | (series[column] > 100)]
            assert bad.empty, f"Rates outside [0, 100] in {column}:\n{bad[['quarter', column]]}"

    def test_no_null_values(self, series: pd.DataFrame) -> None:
        """Test that the series has no missing values."""
        nulls = series.isna().sum()
        assert nulls.sum() == 0, f"Null values found:\n{nulls[nulls > 0]}"

    def test_gender_counts_sum_to_total(self, series: pd.DataFrame) -> None:
        """Test that male and female NEET counts sum to the published total.

        Counts are published rounded to the nearest thousand, so allow one
        rounding unit of slack in either direction.
        """
        difference = (series["male_neet"] + series["female_neet"] - series["total_neet"]).abs()
        bad = series[difference > 1000]
        assert bad.empty, f"Gender counts do not sum to total:\n{bad[['quarter', 'male_neet', 'female_neet', 'total_neet']]}"

    def test_confidence_interval_brackets_total(self, series: pd.DataFrame) -> None:
        """Test that the count confidence interval contains its point estimate."""
        bad = series[(series["total_neet_lower"] > series["total_neet"]) | (series["total_neet_upper"] < series["total_neet"])]
        assert bad.empty, f"Count CI does not bracket estimate:\n{bad[['quarter', 'total_neet_lower', 'total_neet', 'total_neet_upper']]}"

    def test_rate_confidence_interval_brackets_rate(self, series: pd.DataFrame) -> None:
        """Test that the rate confidence interval contains its point estimate."""
        bad = series[
            (series["total_neet_rate_lower_pct"] > series["total_neet_rate_pct"])
            | (series["total_neet_rate_upper_pct"] < series["total_neet_rate_pct"])
        ]
        assert bad.empty, f"Rate CI does not bracket estimate:\n{bad['quarter'].tolist()}"

    def test_rates_are_plausible(self, series: pd.DataFrame) -> None:
        """Test that NEET rates stay within the historically observed band."""
        rates = series["total_neet_rate_pct"]
        assert 5 <= rates.min() and rates.max() <= 30, f"Implausible NEET rates: min={rates.min()}, max={rates.max()}"

    def test_validate_function_passes(self, series: pd.DataFrame) -> None:
        """Test that the module validator accepts its own output."""
        assert neet.validate_data(series, required_columns=["quarter", "total_neet", "total_neet_rate_pct"])


@pytest.mark.network
class TestLatestQuarterTables:
    """Test suite for the three latest-quarter snapshot tables (sheets 2.41-2.43)."""

    @pytest.fixture(scope="class")
    def status(self) -> pd.DataFrame:
        """Fetch the 16-24 labour market status breakdown."""
        return neet.get_labour_market_status()

    @pytest.fixture(scope="class")
    def uk(self) -> pd.DataFrame:
        """Fetch the NI versus UK comparison."""
        return neet.get_uk_comparison()

    @pytest.fixture(scope="class")
    def composition(self) -> pd.DataFrame:
        """Fetch the NEET composition breakdown."""
        return neet.get_neet_composition()

    def test_status_columns(self, status: pd.DataFrame) -> None:
        """Test that the status table has the expected columns."""
        assert set(status.columns) == {"status", "count"}, f"Unexpected columns: {list(status.columns)}"

    def test_status_categories_present(self, status: pd.DataFrame) -> None:
        """Test that the expected labour market status categories are present."""
        expected = {"In employment", "Unemployed", "Economically inactive"}
        missing = expected - set(status["status"])
        assert not missing, f"Missing status categories: {missing}"

    def test_status_counts_non_negative(self, status: pd.DataFrame) -> None:
        """Test that all status counts are non-negative."""
        assert (status["count"] >= 0).all(), f"Negative counts:\n{status[status['count'] < 0]}"

    def test_status_total_row_present(self, status: pd.DataFrame) -> None:
        """Test that the total 16-24 population row is present and largest."""
        totals = status[status["status"].str.startswith("Total population")]
        assert len(totals) == 1, f"Expected one total row, got {len(totals)}"
        assert totals["count"].iloc[0] == status["count"].max(), "Total row is not the largest value"

    def test_uk_columns(self, uk: pd.DataFrame) -> None:
        """Test that the UK comparison has the expected columns."""
        assert set(uk.columns) == {"country", "neet_rate_pct"}, f"Unexpected columns: {list(uk.columns)}"

    def test_uk_countries(self, uk: pd.DataFrame) -> None:
        """Test that the comparison covers exactly Northern Ireland and the UK."""
        assert sorted(uk["country"]) == ["NI", "UK"], f"Unexpected countries: {sorted(uk['country'])}"

    def test_uk_rates_plausible(self, uk: pd.DataFrame) -> None:
        """Test that both comparison rates lie in a plausible band."""
        assert uk["neet_rate_pct"].between(5, 30).all(), f"Implausible rates:\n{uk}"

    def test_composition_columns(self, composition: pd.DataFrame) -> None:
        """Test that the composition table has the expected columns."""
        assert set(composition.columns) == {"status", "count"}, f"Unexpected columns: {list(composition.columns)}"

    def test_composition_categories_present(self, composition: pd.DataFrame) -> None:
        """Test that both NEET components and the total are present."""
        labels = " ".join(composition["status"])
        assert "Unemployed" in labels, f"Unemployed component missing: {composition['status'].tolist()}"
        assert "Economically inactive" in labels, f"Inactive component missing: {composition['status'].tolist()}"
        assert "Total NEET" in labels, f"Total NEET row missing: {composition['status'].tolist()}"

    def test_composition_components_sum_to_total(self, composition: pd.DataFrame) -> None:
        """Test that the two NEET components sum to the published total."""
        total = composition[composition["status"].str.startswith("Total NEET")]["count"].iloc[0]
        components = composition[~composition["status"].str.startswith("Total NEET")]["count"].sum()
        assert abs(components - total) <= 1000, f"Components {components} do not sum to total {total}"


@pytest.mark.network
class TestModuleApi:
    """Test suite for the module's dispatch and derived-table helpers."""

    def test_list_tables(self) -> None:
        """Test that all four tables are advertised with descriptions."""
        tables = neet.list_tables()
        assert set(tables["table"]) == {"quarterly", "status", "uk", "composition"}
        assert tables["description"].str.len().gt(0).all(), "Empty description found"

    def test_get_latest_data_dispatch(self) -> None:
        """Test that every advertised table is retrievable via get_latest_data."""
        for table in neet.list_tables()["table"]:
            df = neet.get_latest_data(table)
            assert not df.empty, f"Table {table!r} returned no rows"

    def test_get_latest_data_rejects_unknown_table(self) -> None:
        """Test that an unknown table name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown table"):
            neet.get_latest_data("not-a-table")

    def test_gender_gap_columns(self) -> None:
        """Test that the derived gender gap table has the expected columns."""
        gap = neet.get_gender_gap()
        required = {"quarter", "period_start", "year", "male_neet_rate_pct", "female_neet_rate_pct", "gap_pp"}
        assert required.issubset(set(gap.columns)), f"Missing columns: {required - set(gap.columns)}"

    def test_gender_gap_matches_rate_difference(self) -> None:
        """Test that gap_pp equals the male minus female rate difference."""
        gap = neet.get_gender_gap()
        expected = (gap["male_neet_rate_pct"] - gap["female_neet_rate_pct"]).round(1)
        assert (gap["gap_pp"] - expected).abs().max() < 0.05, "gap_pp does not match rate difference"

    def test_publication_url_is_neet_workbook(self) -> None:
        """Test that discovery returns a NEET workbook on the NISRA domain."""
        url = neet.get_latest_publication_url()
        assert url.startswith("https://www.nisra.gov.uk/"), f"Unexpected host: {url}"
        assert "NEET" in url, f"URL does not reference NEET: {url}"
        assert url.endswith(".xlsx"), f"Not an xlsx file: {url}"


class TestValidation:
    """Test suite for validate_data and the pure parsing helpers."""

    def test_validate_rejects_empty_dataframe(self) -> None:
        """Test that an empty DataFrame fails validation."""
        assert neet.validate_data(pd.DataFrame()) is False

    def test_validate_rejects_none(self) -> None:
        """Test that None fails validation."""
        assert neet.validate_data(None) is False

    def test_validate_rejects_missing_columns(self) -> None:
        """Test that a missing required column fails validation."""
        df = pd.DataFrame({"quarter": ["January to March 2026"]})
        assert neet.validate_data(df, required_columns=["total_neet"]) is False

    def test_validate_rejects_negative_counts(self) -> None:
        """Test that negative counts fail validation."""
        assert neet.validate_data(pd.DataFrame({"total_neet": [-1]})) is False

    def test_validate_rejects_rates_above_100(self) -> None:
        """Test that rates above 100 percent fail validation."""
        assert neet.validate_data(pd.DataFrame({"total_neet_rate_pct": [101.0]})) is False

    def test_validate_accepts_valid_frame(self) -> None:
        """Test that a well-formed frame passes validation."""
        df = pd.DataFrame({"quarter": ["January to March 2026"], "total_neet": [23000], "total_neet_rate_pct": [11.6]})
        assert neet.validate_data(df, required_columns=["quarter", "total_neet"]) is True

    def test_validate_ignores_unrelated_columns(self) -> None:
        """Test that columns outside the count/rate naming scheme are not range-checked."""
        assert neet.validate_data(pd.DataFrame({"year": [-2013]})) is True

    @pytest.mark.parametrize(
        ("label", "expected_start", "expected_code"),
        [
            ("January to March 2026", "2026-01-01", "Jan-Mar"),
            ("April to June 2020", "2020-04-01", "Apr-Jun"),
            ("July to September 2013", "2013-07-01", "Jul-Sep"),
            ("October to December 2019", "2019-10-01", "Oct-Dec"),
        ],
    )
    def test_parse_quarter(self, label: str, expected_start: str, expected_code: str) -> None:
        """Test that each published quarter label parses to the right period."""
        start, year, code = neet._parse_quarter(label)
        assert start == pd.Timestamp(expected_start)
        assert year == int(expected_start[:4])
        assert code == expected_code

    def test_parse_quarter_tolerates_whitespace(self) -> None:
        """Test that surrounding whitespace in a quarter label is ignored."""
        start, _, _ = neet._parse_quarter("  January to March 2026  ")
        assert start == pd.Timestamp("2026-01-01")

    @pytest.mark.parametrize("label", ["Q1 2026", "January 2026", "February to April 2026", "", "not a quarter"])
    def test_parse_quarter_rejects_bad_labels(self, label: str) -> None:
        """Test that unrecognised quarter labels raise rather than silently parse."""
        with pytest.raises(NISRADataNotFoundError, match="Unrecognised quarter label"):
            neet._parse_quarter(label)

    def test_header_row_locates_header(self) -> None:
        """Test that the header row is found past a variable-length preamble."""
        sheet = pd.DataFrame({0: ["Title", "Note", "Quarter", "January to March 2013"], 1: [None, None, "Total", 1]})
        assert neet._header_row(sheet, "Quarter") == 2

    def test_header_row_raises_when_absent(self) -> None:
        """Test that a missing header row raises rather than returning a wrong index."""
        sheet = pd.DataFrame({0: ["Title", "Note"], 1: [None, None]})
        with pytest.raises(NISRADataNotFoundError, match="Could not locate header row"):
            neet._header_row(sheet, "Quarter")

    def test_labelled_table_strips_note_markers(self) -> None:
        """Test that footnote markers are removed from category labels."""
        sheet = pd.DataFrame({0: ["Title", "Country", "NI [Note 1]", "UK"], 1: [None, "Rate", 11.6, 12.7]})
        df = neet._labelled_table(sheet, "Country", "Rate")
        assert df["Country"].tolist() == ["NI", "UK"]
        assert df["Rate"].tolist() == [11.6, 12.7]

    def test_labelled_table_drops_non_numeric_rows(self) -> None:
        """Test that trailing source/footnote rows are dropped."""
        sheet = pd.DataFrame({0: ["Country", "NI", "Source"], 1: ["Rate", 11.6, "NISRA"]})
        df = neet._labelled_table(sheet, "Country", "Rate")
        assert df["Country"].tolist() == ["NI"]
