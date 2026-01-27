"""Tests for NISRA base utilities.

These tests validate the shared utility functions in the NISRA _base module.
"""

import pandas as pd
import pytest

from bolster.data_sources.nisra._base import (
    add_date_columns,
    make_absolute_url,
    parse_month_year,
)


class TestMakeAbsoluteUrl:
    """Tests for make_absolute_url utility."""

    def test_relative_url_with_leading_slash(self):
        """Test converting relative URL starting with /."""
        result = make_absolute_url("/publications/file.xlsx", "https://www.nisra.gov.uk")
        assert result == "https://www.nisra.gov.uk/publications/file.xlsx"

    def test_relative_url_without_leading_slash(self):
        """Test converting relative URL without leading /."""
        result = make_absolute_url("publications/file.xlsx", "https://www.nisra.gov.uk")
        assert result == "https://www.nisra.gov.uk/publications/file.xlsx"

    def test_absolute_url_unchanged(self):
        """Test that absolute URLs are returned unchanged."""
        url = "https://example.com/file.xlsx"
        result = make_absolute_url(url, "https://www.nisra.gov.uk")
        assert result == url

    def test_http_url_unchanged(self):
        """Test that http:// URLs are returned unchanged."""
        url = "http://example.com/file.xlsx"
        result = make_absolute_url(url, "https://www.nisra.gov.uk")
        assert result == url

    def test_different_base_urls(self):
        """Test with different base URLs."""
        result = make_absolute_url("/data/stats.xlsx", "https://www.health-ni.gov.uk")
        assert result == "https://www.health-ni.gov.uk/data/stats.xlsx"


class TestParseMonthYear:
    """Tests for parse_month_year utility."""

    def test_full_month_name(self):
        """Test parsing full month names."""
        result = parse_month_year("April 2008")
        assert result == pd.Timestamp("2008-04-01")

    def test_various_months(self):
        """Test parsing various month names."""
        test_cases = [
            ("January 2020", pd.Timestamp("2020-01-01")),
            ("February 2021", pd.Timestamp("2021-02-01")),
            ("December 2019", pd.Timestamp("2019-12-01")),
            ("March 2025", pd.Timestamp("2025-03-01")),
        ]
        for input_str, expected in test_cases:
            result = parse_month_year(input_str)
            assert result == expected, f"Failed for {input_str}"

    def test_abbreviated_month_with_custom_format(self):
        """Test parsing abbreviated month names with custom format."""
        result = parse_month_year("Jan 2024", format="%b %Y")
        assert result == pd.Timestamp("2024-01-01")

    def test_invalid_string_returns_none(self):
        """Test that invalid strings return None."""
        result = parse_month_year("not a date")
        assert result is None

    def test_empty_string_returns_none(self):
        """Test that empty string returns None."""
        result = parse_month_year("")
        assert result is None

    def test_none_input_returns_none(self):
        """Test that None input returns None."""
        result = parse_month_year(None)
        assert result is None

    def test_partial_match_returns_none(self):
        """Test that partial matches return None."""
        result = parse_month_year("April")  # Missing year
        assert result is None


class TestAddDateColumns:
    """Tests for add_date_columns utility."""

    def test_adds_required_columns(self):
        """Test that all required columns are added."""
        df = pd.DataFrame({"treatment_month": ["April 2008", "May 2008"]})
        result = add_date_columns(df, "treatment_month")

        assert "date" in result.columns
        assert "year" in result.columns
        assert "month" in result.columns

    def test_date_column_is_datetime(self):
        """Test that date column is datetime type."""
        df = pd.DataFrame({"treatment_month": ["April 2008", "May 2008"]})
        result = add_date_columns(df, "treatment_month")

        assert pd.api.types.is_datetime64_any_dtype(result["date"])

    def test_year_column_is_integer(self):
        """Test that year column is integer type."""
        df = pd.DataFrame({"treatment_month": ["April 2008", "May 2008"]})
        result = add_date_columns(df, "treatment_month")

        assert result["year"].dtype == int

    def test_month_column_contains_full_names(self):
        """Test that month column contains full month names."""
        df = pd.DataFrame({"treatment_month": ["April 2008", "December 2020"]})
        result = add_date_columns(df, "treatment_month")

        assert result["month"].tolist() == ["April", "December"]

    def test_drops_invalid_dates(self):
        """Test that rows with invalid dates are dropped."""
        df = pd.DataFrame({
            "treatment_month": ["April 2008", "invalid", "May 2008", ""]
        })
        result = add_date_columns(df, "treatment_month")

        assert len(result) == 2
        assert result["month"].tolist() == ["April", "May"]

    def test_preserves_other_columns(self):
        """Test that other columns are preserved."""
        df = pd.DataFrame({
            "treatment_month": ["April 2008", "May 2008"],
            "value": [100, 200],
            "category": ["A", "B"],
        })
        result = add_date_columns(df, "treatment_month")

        assert "value" in result.columns
        assert "category" in result.columns
        assert result["value"].tolist() == [100, 200]

    def test_custom_date_column_name(self):
        """Test using a custom name for the date column."""
        df = pd.DataFrame({"month_seen": ["April 2008", "May 2008"]})
        result = add_date_columns(df, "month_seen", date_col="seen_date")

        assert "seen_date" in result.columns
        assert "date" not in result.columns

    def test_does_not_modify_original(self):
        """Test that the original DataFrame is not modified."""
        df = pd.DataFrame({"treatment_month": ["April 2008", "May 2008"]})
        original_columns = df.columns.tolist()

        add_date_columns(df, "treatment_month")

        assert df.columns.tolist() == original_columns

    def test_handles_all_invalid_dates(self):
        """Test handling when all dates are invalid."""
        df = pd.DataFrame({"treatment_month": ["invalid", "also invalid"]})
        result = add_date_columns(df, "treatment_month")

        assert len(result) == 0

    def test_correct_year_extraction(self):
        """Test that years are correctly extracted."""
        df = pd.DataFrame({
            "treatment_month": ["January 2008", "December 2024", "June 2015"]
        })
        result = add_date_columns(df, "treatment_month")

        assert result["year"].tolist() == [2008, 2024, 2015]
