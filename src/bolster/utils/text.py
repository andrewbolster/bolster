"""Shared text-normalisation helpers for data source modules.

Several data source modules parse spreadsheet column headers into
snake_case for use as DataFrame column names, each having independently
reimplemented the same core normalisation (see issue #2176). This module
centralises it.

It also holds the month-name helpers for parsing publication slugs and
filenames, which publishers spell as full names (``november``), three-letter
abbreviations (``nov``) or ``sept``, in any letter case.
"""

import re

_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]+")

# A month as it appears in a publication slug or filename: the full name, the
# three-letter abbreviation or ``sept``. A regex fragment with no capture group,
# for embedding in a larger pattern: compile it with ``re.IGNORECASE`` and put
# ``(?<![a-z])`` / ``(?![a-z])`` around it so a month inside another word
# (``mayhem``) cannot match.
MONTH_TOKEN_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

_MONTH_NUMBERS = {
    **{name: number for number, name in enumerate(_MONTH_NAMES, start=1)},
    **{name[:3]: number for number, name in enumerate(_MONTH_NAMES, start=1)},
    "sept": 9,
}


def month_number(token: str) -> int:
    """Return the month number (1-12) for a month name as publishers spell it.

    Accepts the full name (``"November"``), the three-letter abbreviation
    (``"Nov"``) and ``"Sept"``, in any letter case, ignoring surrounding
    whitespace.

    Args:
        token: A single month token such as one captured by
            :data:`MONTH_TOKEN_PATTERN`.

    Returns:
        The month number, 1 for January to 12 for December.

    Raises:
        ValueError: If the token is not a month name, including prefixes such
            as ``"marc"`` and names with extra text such as ``"mayhem"``.

    Example:
        >>> month_number("Nov"), month_number("september"), month_number("SEPT")
        (11, 9, 9)
    """
    try:
        return _MONTH_NUMBERS[token.strip().lower()]
    except KeyError:
        raise ValueError(f"Not a month name: {token!r}") from None


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
