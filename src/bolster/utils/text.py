"""Shared text-normalisation helpers for data source modules.

Several data source modules parse spreadsheet column headers into
snake_case for use as DataFrame column names, each having independently
reimplemented the same core normalisation (see issue #2176). This module
centralises it.
"""

import re

_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]+")


def clean_column_name(name: object) -> str:
    """Normalise a spreadsheet column header into snake_case.

    Modules with extra header quirks (footnote markers, ``[note N]``
    references, ``(%)``/``(Number)`` suffixes) should strip those first,
    then pass the result through this function for the final
    lowercase-and-underscore step, rather than duplicating this regex.

    Args:
        name: Raw column header value (often not already a string, e.g.
            an ``int`` or ``float`` cell read from Excel).

    Returns:
        The header as snake_case, with leading/trailing underscores
        stripped.

    Example:
        >>> clean_column_name("First degree NI")
        'first_degree_ni'
        >>> clean_column_name("OU(1)")
        'ou_1'
        >>> clean_column_name("Postgraduate  Total")
        'postgraduate_total'
    """
    text = _NON_ALNUM_RE.sub("_", str(name).strip().lower())
    return text.strip("_")
