"""Tests for NISRA base utilities.

These tests validate the shared utility functions in the NISRA _base module.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from bolster.data_sources.nisra._base import (
    NISRADataError,
    NISRADataNotFoundError,
    NISRAValidationError,
    add_date_columns,
    clear_cache,
    download_file,
    extract_column_mapping,
    find_header_row,
    find_publication_link,
    make_absolute_url,
    parse_age_breakdowns,
    parse_month_year,
    safe_float,
    safe_int,
    scrape_download_links,
)
from bolster.utils.cache import DownloadError
from bolster.utils.web import LinkNotFoundError


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
        df = pd.DataFrame({"treatment_month": ["April 2008", "invalid", "May 2008", ""]})
        result = add_date_columns(df, "treatment_month")

        assert len(result) == 2
        assert result["month"].tolist() == ["April", "May"]

    def test_preserves_other_columns(self):
        """Test that other columns are preserved."""
        df = pd.DataFrame(
            {
                "treatment_month": ["April 2008", "May 2008"],
                "value": [100, 200],
                "category": ["A", "B"],
            }
        )
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
        df = pd.DataFrame({"treatment_month": ["January 2008", "December 2024", "June 2015"]})
        result = add_date_columns(df, "treatment_month")

        assert result["year"].tolist() == [2008, 2024, 2015]


class TestExceptions:
    """Test NISRA exception classes."""

    def test_nisra_data_error_inheritance(self):
        """Test that NISRADataError inherits from Exception."""
        error = NISRADataError("test error")
        assert isinstance(error, Exception)
        assert str(error) == "test error"

    def test_nisra_data_not_found_error_inheritance(self):
        """Test that NISRADataNotFoundError inherits from NISRADataError."""
        error = NISRADataNotFoundError("file not found")
        assert isinstance(error, NISRADataError)
        assert isinstance(error, Exception)
        assert str(error) == "file not found"

    def test_nisra_validation_error_inheritance(self):
        """Test that NISRAValidationError inherits from NISRADataError."""
        error = NISRAValidationError("validation failed")
        assert isinstance(error, NISRADataError)
        assert isinstance(error, Exception)
        assert str(error) == "validation failed"


class TestDownloadFile:
    """Test download_file function to cover error handling."""

    @patch("bolster.data_sources.nisra._base._downloader")
    def test_download_file_success(self, mock_downloader):
        """Test successful download."""
        mock_path = Path("/tmp/test_file.xlsx")
        mock_downloader.download.return_value = mock_path

        result = download_file("https://example.com/file.xlsx")

        assert result == mock_path
        mock_downloader.download.assert_called_once_with(
            "https://example.com/file.xlsx", cache_ttl_hours=24, force_refresh=False
        )

    @patch("bolster.data_sources.nisra._base._downloader")
    def test_download_file_with_custom_params(self, mock_downloader):
        """Test download with custom parameters."""
        mock_path = Path("/tmp/test_file.xlsx")
        mock_downloader.download.return_value = mock_path

        result = download_file("https://example.com/file.xlsx", cache_ttl_hours=48, force_refresh=True)

        assert result == mock_path
        mock_downloader.download.assert_called_once_with(
            "https://example.com/file.xlsx", cache_ttl_hours=48, force_refresh=True
        )

    @patch("bolster.data_sources.nisra._base._downloader")
    def test_download_file_raises_nisra_error_on_download_error(self, mock_downloader):
        """Test that DownloadError is converted to NISRADataNotFoundError."""
        mock_downloader.download.side_effect = DownloadError("Network error")

        with pytest.raises(NISRADataNotFoundError, match="Network error"):
            download_file("https://example.com/file.xlsx")


class TestSafeConversions:
    """Test safe_int and safe_float functions."""

    def test_safe_int_valid_values(self):
        """Test safe_int with valid integer values."""
        assert safe_int(42) == 42
        assert safe_int("42") == 42
        assert safe_int(42.0) == 42
        assert safe_int(42.7) == 42  # Truncates float

    def test_safe_int_placeholder_values(self):
        """Test safe_int with placeholder values."""
        assert safe_int(None) is None
        assert safe_int("") is None
        assert safe_int("-") is None

    def test_safe_int_invalid_values(self):
        """Test safe_int with invalid values."""
        assert safe_int("not_a_number") is None
        assert safe_int("42.5.3") is None
        assert safe_int([1, 2, 3]) is None

    def test_safe_float_valid_values(self):
        """Test safe_float with valid float values."""
        assert safe_float(42.5) == 42.5
        assert safe_float("42.5") == 42.5
        assert safe_float(42) == 42.0
        assert safe_float("42") == 42.0

    def test_safe_float_placeholder_values(self):
        """Test safe_float with placeholder values."""
        assert safe_float(None) is None
        assert safe_float("") is None
        assert safe_float("-") is None

    def test_safe_float_invalid_values(self):
        """Test safe_float with invalid values - covers lines 141-142."""
        assert safe_float("not_a_number") is None
        assert safe_float("42.5.3") is None
        assert safe_float([1.5, 2.5]) is None


class TestScrapeDownloadLinks:
    """Test the NISRA wrapper around scrape_file_links.

    Link parsing itself is covered in tests/test_utils_web.py; all this wrapper
    adds is NISRA defaults and translation into NISRADataError.
    """

    @patch("bolster.data_sources.nisra._base.scrape_file_links")
    def test_passes_nisra_defaults_through(self, mock_scrape):
        mock_scrape.return_value = [{"url": "https://www.nisra.gov.uk/f.xlsx", "text": "F"}]

        result = scrape_download_links("https://www.nisra.gov.uk/data")

        assert result == [{"url": "https://www.nisra.gov.uk/f.xlsx", "text": "F"}]
        mock_scrape.assert_called_once_with(
            "https://www.nisra.gov.uk/data",
            file_extension=".xlsx",
            base_url="https://www.nisra.gov.uk",
        )

    @patch("bolster.data_sources.nisra._base.scrape_file_links")
    def test_network_error_becomes_nisra_data_error(self, mock_scrape):
        mock_scrape.side_effect = Exception("Network error")

        with pytest.raises(NISRADataError, match="Failed to fetch page.*Network error"):
            scrape_download_links("https://www.nisra.gov.uk/data")


class TestFindPublicationLink:
    """Test the NISRA wrapper around utils.web.find_publication_link.

    Two-hop discovery itself is covered in tests/test_utils_web.py; all this
    wrapper adds is NISRA defaults and translation into NISRADataNotFoundError.
    """

    @patch("bolster.data_sources.nisra._base._find_publication_link")
    def test_passes_nisra_defaults_through(self, mock_find):
        mock_find.return_value = "https://www.nisra.gov.uk/f.xlsx"

        result = find_publication_link("https://www.nisra.gov.uk/hub", pub_text_contains="Monthly Births")

        assert result == "https://www.nisra.gov.uk/f.xlsx"
        assert mock_find.call_args.kwargs["base_url"] == "https://www.nisra.gov.uk"
        assert mock_find.call_args.kwargs["file_extension"] == ".xlsx"

    @patch("bolster.data_sources.nisra._base._find_publication_link")
    def test_link_not_found_becomes_nisra_not_found(self, mock_find):
        mock_find.side_effect = LinkNotFoundError("No publication link found on hub")

        with pytest.raises(NISRADataNotFoundError, match="No publication link found on hub"):
            find_publication_link("https://www.nisra.gov.uk/hub")

    @patch("bolster.data_sources.nisra._base._find_publication_link")
    def test_network_error_becomes_nisra_not_found(self, mock_find):
        mock_find.side_effect = Exception("Network error")

        with pytest.raises(NISRADataNotFoundError, match="Failed to fetch hub page.*Network error"):
            find_publication_link("https://www.nisra.gov.uk/hub")


class TestClearCache:
    """Test clear_cache function."""

    @patch("bolster.data_sources.nisra._base._downloader")
    def test_clear_cache_all_files(self, mock_downloader):
        """Test clearing all cached files - covers line 105."""
        mock_downloader.clear.return_value = 5

        result = clear_cache()

        assert result == 5
        mock_downloader.clear.assert_called_once_with(None)

    @patch("bolster.data_sources.nisra._base._downloader")
    def test_clear_cache_with_pattern(self, mock_downloader):
        """Test clearing cache with pattern."""
        mock_downloader.clear.return_value = 3

        result = clear_cache("*.xlsx")

        assert result == 3
        mock_downloader.clear.assert_called_once_with("*.xlsx")


class TestFindHeaderRow:
    """Test find_header_row function."""

    def test_find_header_row_success(self):
        """Test finding header row successfully - covers lines 161-178."""
        # Mock worksheet with header row at row 3
        mock_sheet = Mock()
        mock_rows = [
            (None, None, None),  # Row 1: empty
            ("Data Summary", None, None),  # Row 2: title
            ("Week Ending", "Total Deaths", "Region"),  # Row 3: headers
            ("2023-01-01", "150", "Belfast"),  # Row 4: data
        ]
        mock_sheet.iter_rows.return_value = enumerate(mock_rows, 1)

        result = find_header_row(mock_sheet, ["Week Ending", "Total Deaths"])

        assert result == 3
        mock_sheet.iter_rows.assert_called_once_with(min_row=1, max_row=20, values_only=True)

    def test_find_header_row_partial_match(self):
        """Test header finding with partial matches."""
        mock_sheet = Mock()
        mock_rows = [
            ("Data for Week Ending Date", "Count of Total Deaths by Region", "Area"),  # Partial matches
        ]
        mock_sheet.iter_rows.return_value = enumerate(mock_rows, 1)

        result = find_header_row(mock_sheet, ["Week Ending", "Total Deaths"])

        assert result == 1

    @patch("bolster.data_sources.nisra._base.logger")
    def test_find_header_row_not_found(self, mock_logger):
        """Test when header row is not found - covers line 177."""
        mock_sheet = Mock()
        mock_rows = [
            ("Unrelated", "Column", "Names"),
            ("Data", "Row", "Values"),
        ]
        mock_sheet.iter_rows.return_value = enumerate(mock_rows, 1)

        result = find_header_row(mock_sheet, ["Week Ending", "Total Deaths"])

        assert result is None
        mock_logger.warning.assert_called_once()
        assert "Could not find header row" in mock_logger.warning.call_args[0][0]

    def test_find_header_row_custom_max_rows(self):
        """Test with custom max_rows parameter."""
        mock_sheet = Mock()
        mock_rows = [("Week Ending", "Total Deaths")]
        mock_sheet.iter_rows.return_value = enumerate(mock_rows, 1)

        result = find_header_row(mock_sheet, ["Week Ending", "Total Deaths"], max_rows=5)

        assert result == 1
        mock_sheet.iter_rows.assert_called_once_with(min_row=1, max_row=5, values_only=True)


class TestExtractColumnMapping:
    """Test extract_column_mapping function."""

    def test_extract_column_mapping_success(self):
        """Test successful column mapping extraction - covers lines 197-214."""
        # Mock worksheet row with headers
        mock_cells = [
            Mock(value="Week Ending"),
            Mock(value="Total Deaths"),
            Mock(value="Region"),
            Mock(value="Male Deaths"),
        ]

        mock_sheet = {4: mock_cells}

        result = extract_column_mapping(mock_sheet, 4, ["Week Ending", "Total Deaths", "Region"])

        expected = {
            "Week Ending": 0,
            "Total Deaths": 1,
            "Region": 2,
        }

        assert result == expected

    def test_extract_column_mapping_partial_matches(self):
        """Test column mapping with partial matches."""
        mock_cells = [
            Mock(value="Data for Week Ending Date"),
            Mock(value="Count of Total Deaths"),
            Mock(value="Geographic Region"),
        ]

        mock_sheet = {3: mock_cells}

        result = extract_column_mapping(mock_sheet, 3, ["week ending", "total deaths"])

        expected = {
            "week ending": 0,
            "total deaths": 1,
        }

        assert result == expected

    @patch("bolster.data_sources.nisra._base.logger")
    def test_extract_column_mapping_missing_columns(self, mock_logger):
        """Test when some columns are missing - covers lines 210-213."""
        mock_cells = [
            Mock(value="Week Ending"),
            Mock(value="Region"),
        ]

        mock_sheet = {2: mock_cells}

        result = extract_column_mapping(mock_sheet, 2, ["Week Ending", "Total Deaths", "Missing Column"])

        expected = {
            "Week Ending": 0,
        }

        assert result == expected
        mock_logger.warning.assert_called_once()
        assert "Could not find columns:" in mock_logger.warning.call_args[0][0]
        assert "Total Deaths" in str(mock_logger.warning.call_args[0][0])
        assert "Missing Column" in str(mock_logger.warning.call_args[0][0])


class TestParseAgeBreakdowns:
    """Test parse_age_breakdowns function."""

    def test_parse_age_breakdowns_success(self):
        """Test successful age breakdown parsing - covers lines 322-329."""
        # Mock Excel row with age data
        row = [None] * 25  # Create row with 25 columns
        row[20] = "5"  # 0-7 days deaths
        row[21] = "3"  # 7 days-1 year deaths
        row[22] = "0"  # 1-14 deaths
        row[23] = None  # Missing data

        age_map = {
            "0-7 days": 20,
            "7 days-1 year": 21,
            "1-14": 22,
            "15-64": 23,
        }

        result = parse_age_breakdowns(row, age_map)

        expected = [
            {"age_range": "0-7 days", "deaths": 5},
            {"age_range": "7 days-1 year", "deaths": 3},
            {"age_range": "1-14", "deaths": 0},
        ]

        assert result == expected

    def test_parse_age_breakdowns_empty_data(self):
        """Test with all None/invalid data."""
        row = [None] * 25
        age_map = {"0-7 days": 20, "7 days-1 year": 21}

        result = parse_age_breakdowns(row, age_map)

        assert result == []

    def test_parse_age_breakdowns_mixed_valid_invalid(self):
        """Test with mix of valid and invalid data."""
        row = [None] * 25
        row[20] = "5"  # Valid
        row[21] = "-"  # Invalid placeholder (safe_int returns None)
        row[22] = ""  # Invalid empty (safe_int returns None)

        age_map = {
            "0-7 days": 20,
            "7 days-1 year": 21,
            "1-14": 22,
        }

        result = parse_age_breakdowns(row, age_map)

        expected = [
            {"age_range": "0-7 days", "deaths": 5},
        ]

        assert result == expected
