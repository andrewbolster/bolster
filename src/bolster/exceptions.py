"""Bolster domain-specific exception hierarchy.

This module provides the constitutional exception hierarchy for all data source modules.
All data sources MUST use these domain-specific exceptions instead of generic Exception.
"""


class DataSourceError(Exception):
    """Base class for all data source errors.

    This is the root exception for all domain-specific errors in Bolster.
    All other exceptions should inherit from this base class.
    """

    pass


class DataNotFoundError(DataSourceError):
    """Raised when expected data publications or URLs are not found.

    Examples:
        - Publication page returns 404
        - Expected Excel file link missing from page
        - RSS feed returns no entries
        - API endpoint returns empty response

    Args:
        message: Description of what data was not found
        url: Optional URL that was being accessed
        source: Optional data source identifier
    """

    def __init__(self, message: str, url: str = None, source: str = None):
        super().__init__(message)
        self.url = url
        self.source = source

    def __str__(self):
        base_message = super().__str__()
        if self.url:
            base_message += f" (URL: {self.url})"
        if self.source:
            base_message += f" (Source: {self.source})"
        return base_message


class ValidationError(DataSourceError):
    """Raised when data fails integrity validation checks.

    Examples:
        - Required columns missing from DataFrame
        - Data values outside expected ranges
        - Inconsistent data relationships
        - Empty datasets when data expected

    Args:
        message: Description of validation failure
        data_info: Optional info about the problematic data
        validation_type: Optional type of validation that failed
    """

    def __init__(self, message: str, data_info: str = None, validation_type: str = None):
        super().__init__(message)
        self.data_info = data_info
        self.validation_type = validation_type

    def __str__(self):
        base_message = super().__str__()
        if self.validation_type:
            base_message += f" (Validation: {self.validation_type})"
        if self.data_info:
            base_message += f" (Data: {self.data_info})"
        return base_message


class ParseError(DataSourceError):
    """Raised when file or data parsing fails.

    Examples:
        - Malformed Excel file structure
        - Unexpected CSV format
        - HTML parsing issues
        - JSON decode errors

    Args:
        message: Description of parsing failure
        file_path: Optional path to file that failed to parse
        parser_type: Optional type of parser (excel, csv, html, json)
    """

    def __init__(self, message: str, file_path: str = None, parser_type: str = None):
        super().__init__(message)
        self.file_path = file_path
        self.parser_type = parser_type

    def __str__(self):
        base_message = super().__str__()
        if self.parser_type:
            base_message += f" (Parser: {self.parser_type})"
        if self.file_path:
            base_message += f" (File: {self.file_path})"
        return base_message


class NetworkError(DataSourceError):
    """Raised when network operations fail beyond retry limits.

    Examples:
        - Timeout errors after retries
        - Connection refused
        - DNS resolution failures
        - Server returning persistent errors (500, 503)

    Args:
        message: Description of network failure
        url: Optional URL that failed
        status_code: Optional HTTP status code
        retry_count: Optional number of retries attempted
    """

    def __init__(self, message: str, url: str = None, status_code: int = None, retry_count: int = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.retry_count = retry_count

    def __str__(self):
        base_message = super().__str__()
        if self.status_code:
            base_message += f" (Status: {self.status_code})"
        if self.url:
            base_message += f" (URL: {self.url})"
        if self.retry_count:
            base_message += f" (Retries: {self.retry_count})"
        return base_message


# Legacy aliases for existing code compatibility
# These will be deprecated in future versions
NISRADataNotFoundError = DataNotFoundError
NISRAValidationError = ValidationError
PSNIDataNotFoundError = DataNotFoundError
PSNIValidationError = ValidationError
