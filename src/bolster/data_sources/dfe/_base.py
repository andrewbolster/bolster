"""Shared exceptions for Department for the Economy (DfE) data sources.

DfE publishes higher-education statistics at economy-ni.gov.uk. Pages follow
the same hub-article -> year-stamped publication page -> workbook pattern
used elsewhere in bolster, so URL discovery reuses
:func:`bolster.utils.web.find_publication_link` directly rather than
duplicating it here.
"""


class DfEDataError(Exception):
    """Base exception for Department for the Economy data source errors."""


class DfEDataNotFoundError(DfEDataError):
    """Raised when expected data, a publication, or a file link can't be found."""


class DfEValidationError(DfEDataError):
    """Raised when parsed data fails structural validation checks."""
