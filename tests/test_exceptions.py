"""Tests for Bolster exception hierarchy.

These tests validate that all domain-specific exceptions work correctly,
including instantiation, string representation, and inheritance.
"""

import pytest

from bolster import exceptions


class TestDataSourceError:
    """Tests for base DataSourceError exception."""

    def test_basic_instantiation(self):
        """Test basic exception creation with message."""
        error = exceptions.DataSourceError("Something went wrong")
        assert str(error) == "Something went wrong"

    def test_inheritance(self):
        """Test that DataSourceError inherits from Exception."""
        error = exceptions.DataSourceError("test")
        assert isinstance(error, Exception)
        assert isinstance(error, exceptions.DataSourceError)

    def test_can_be_raised(self):
        """Test that exception can be raised and caught."""
        with pytest.raises(exceptions.DataSourceError) as exc_info:
            raise exceptions.DataSourceError("test error")
        assert "test error" in str(exc_info.value)


class TestDataNotFoundError:
    """Tests for DataNotFoundError exception."""

    def test_message_only(self):
        """Test with message only."""
        error = exceptions.DataNotFoundError("Data not found")
        assert str(error) == "Data not found"
        assert error.url is None
        assert error.source is None

    def test_with_url(self):
        """Test with message and URL."""
        error = exceptions.DataNotFoundError("Data not found", url="https://example.com/data.xlsx")
        assert "Data not found" in str(error)
        assert "https://example.com/data.xlsx" in str(error)
        assert error.url == "https://example.com/data.xlsx"

    def test_with_source(self):
        """Test with message and source."""
        error = exceptions.DataNotFoundError("Data not found", source="NISRA")
        assert "Data not found" in str(error)
        assert "NISRA" in str(error)
        assert error.source == "NISRA"

    def test_with_all_parameters(self):
        """Test with all parameters."""
        error = exceptions.DataNotFoundError("Publication not found", url="https://example.com", source="NISRA")
        error_str = str(error)
        assert "Publication not found" in error_str
        assert "https://example.com" in error_str
        assert "NISRA" in error_str

    def test_inheritance(self):
        """Test inheritance chain."""
        error = exceptions.DataNotFoundError("test")
        assert isinstance(error, exceptions.DataSourceError)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test exception can be raised and caught."""
        with pytest.raises(exceptions.DataNotFoundError):
            raise exceptions.DataNotFoundError("Not found")

    def test_can_be_caught_as_base_exception(self):
        """Test can be caught as DataSourceError."""
        with pytest.raises(exceptions.DataSourceError):
            raise exceptions.DataNotFoundError("Not found")


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_message_only(self):
        """Test with message only."""
        error = exceptions.ValidationError("Validation failed")
        assert str(error) == "Validation failed"
        assert error.data_info is None
        assert error.validation_type is None

    def test_with_data_info(self):
        """Test with message and data_info."""
        error = exceptions.ValidationError("Invalid data", data_info="DataFrame(100 rows)")
        assert "Invalid data" in str(error)
        assert "DataFrame(100 rows)" in str(error)
        assert error.data_info == "DataFrame(100 rows)"

    def test_with_validation_type(self):
        """Test with message and validation_type."""
        error = exceptions.ValidationError("Check failed", validation_type="column_check")
        assert "Check failed" in str(error)
        assert "column_check" in str(error)
        assert error.validation_type == "column_check"

    def test_with_all_parameters(self):
        """Test with all parameters."""
        error = exceptions.ValidationError(
            "Data validation failed", data_info="occupancy data", validation_type="range_check"
        )
        error_str = str(error)
        assert "Data validation failed" in error_str
        assert "occupancy data" in error_str
        assert "range_check" in error_str

    def test_inheritance(self):
        """Test inheritance chain."""
        error = exceptions.ValidationError("test")
        assert isinstance(error, exceptions.DataSourceError)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test exception can be raised and caught."""
        with pytest.raises(exceptions.ValidationError):
            raise exceptions.ValidationError("Validation failed")


class TestParseError:
    """Tests for ParseError exception."""

    def test_message_only(self):
        """Test with message only."""
        error = exceptions.ParseError("Parse failed")
        assert str(error) == "Parse failed"
        assert error.file_path is None
        assert error.parser_type is None

    def test_with_file_path(self):
        """Test with message and file_path."""
        error = exceptions.ParseError("Cannot parse file", file_path="/path/to/data.xlsx")
        assert "Cannot parse file" in str(error)
        assert "/path/to/data.xlsx" in str(error)
        assert error.file_path == "/path/to/data.xlsx"

    def test_with_parser_type(self):
        """Test with message and parser_type."""
        error = exceptions.ParseError("Parse error", parser_type="excel")
        assert "Parse error" in str(error)
        assert "excel" in str(error)
        assert error.parser_type == "excel"

    def test_with_all_parameters(self):
        """Test with all parameters."""
        error = exceptions.ParseError("Failed to parse Excel file", file_path="/tmp/data.xlsx", parser_type="openpyxl")
        error_str = str(error)
        assert "Failed to parse Excel file" in error_str
        assert "/tmp/data.xlsx" in error_str
        assert "openpyxl" in error_str

    def test_inheritance(self):
        """Test inheritance chain."""
        error = exceptions.ParseError("test")
        assert isinstance(error, exceptions.DataSourceError)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test exception can be raised and caught."""
        with pytest.raises(exceptions.ParseError):
            raise exceptions.ParseError("Parse failed")


class TestNetworkError:
    """Tests for NetworkError exception."""

    def test_message_only(self):
        """Test with message only."""
        error = exceptions.NetworkError("Connection failed")
        assert str(error) == "Connection failed"
        assert error.url is None
        assert error.status_code is None
        assert error.retry_count is None

    def test_with_url(self):
        """Test with message and URL."""
        error = exceptions.NetworkError("Timeout", url="https://example.com")
        assert "Timeout" in str(error)
        assert "https://example.com" in str(error)
        assert error.url == "https://example.com"

    def test_with_status_code(self):
        """Test with message and status_code."""
        error = exceptions.NetworkError("Server error", status_code=503)
        assert "Server error" in str(error)
        assert "503" in str(error)
        assert error.status_code == 503

    def test_with_retry_count(self):
        """Test with message and retry_count."""
        error = exceptions.NetworkError("Failed after retries", retry_count=3)
        assert "Failed after retries" in str(error)
        assert "3" in str(error)
        assert error.retry_count == 3

    def test_with_all_parameters(self):
        """Test with all parameters."""
        error = exceptions.NetworkError("Request failed", url="https://example.com/api", status_code=500, retry_count=5)
        error_str = str(error)
        assert "Request failed" in error_str
        assert "https://example.com/api" in error_str
        assert "500" in error_str
        assert "5" in error_str

    def test_inheritance(self):
        """Test inheritance chain."""
        error = exceptions.NetworkError("test")
        assert isinstance(error, exceptions.DataSourceError)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test exception can be raised and caught."""
        with pytest.raises(exceptions.NetworkError):
            raise exceptions.NetworkError("Network error")


class TestLegacyAliases:
    """Tests for legacy exception aliases."""

    def test_nisra_data_not_found_alias(self):
        """Test NISRADataNotFoundError is alias for DataNotFoundError."""
        assert exceptions.NISRADataNotFoundError is exceptions.DataNotFoundError
        error = exceptions.NISRADataNotFoundError("test")
        assert isinstance(error, exceptions.DataNotFoundError)

    def test_nisra_validation_alias(self):
        """Test NISRAValidationError is alias for ValidationError."""
        assert exceptions.NISRAValidationError is exceptions.ValidationError
        error = exceptions.NISRAValidationError("test")
        assert isinstance(error, exceptions.ValidationError)

    def test_psni_data_not_found_alias(self):
        """Test PSNIDataNotFoundError is alias for DataNotFoundError."""
        assert exceptions.PSNIDataNotFoundError is exceptions.DataNotFoundError
        error = exceptions.PSNIDataNotFoundError("test")
        assert isinstance(error, exceptions.DataNotFoundError)

    def test_psni_validation_alias(self):
        """Test PSNIValidationError is alias for ValidationError."""
        assert exceptions.PSNIValidationError is exceptions.ValidationError
        error = exceptions.PSNIValidationError("test")
        assert isinstance(error, exceptions.ValidationError)

    def test_legacy_aliases_can_be_raised(self):
        """Test that legacy aliases can be raised and caught."""
        with pytest.raises(exceptions.DataNotFoundError):
            raise exceptions.NISRADataNotFoundError("Not found")

        with pytest.raises(exceptions.ValidationError):
            raise exceptions.PSNIValidationError("Invalid")
