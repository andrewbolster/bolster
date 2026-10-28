"""Shared pandas/Excel parsing helpers for data source modules.

Several data source modules locate a header/title row by scanning the first
few rows of a sheet's leading column for a marker value, each having
independently reimplemented the same bounded linear scan (see issue #2176).
This module centralises that scan; each module keeps its own predicate and
its own "not found" error, since those are module-specific. ``parse_sheet``
reads one named sheet with a DataFrame return type.
"""

from collections.abc import Callable
from typing import Any, cast

import pandas as pd


def parse_sheet(workbook: pd.ExcelFile, sheet_name: str, **kwargs: Any) -> pd.DataFrame:
    """Parse one named sheet of ``workbook`` as a DataFrame.

    ``pandas.ExcelFile.parse`` is annotated as returning a DataFrame or a dict of
    DataFrames, because ``sheet_name`` may also be a list or ``None``. A single
    sheet name always yields a DataFrame, which this wrapper states in its type.

    Args:
        workbook: An open workbook.
        sheet_name: The name of the sheet to parse.
        **kwargs: Passed to ``ExcelFile.parse`` (``header``, ``skiprows``, ``nrows``...).

    Returns:
        The parsed sheet.
    """
    return cast("pd.DataFrame", workbook.parse(sheet_name, **kwargs))


def find_marker_row(sheet: pd.DataFrame, predicate: Callable[[object], bool], max_rows: int = 10) -> int | None:
    """Return the index of the first row whose leading-column value matches ``predicate``.

    Scans only the first ``max_rows`` rows of ``sheet``'s first column
    (``sheet.iat[index, 0]``) and returns as soon as ``predicate`` matches.
    Does not raise if nothing matches -- callers know their own "not found"
    error and message.

    Args:
        sheet: A sheet read with ``pandas.read_excel(..., header=None)``.
        predicate: Called with each raw cell value in turn (which may be a
            non-string, e.g. ``NaN`` or an ``int``); return ``True`` to
            select that row.
        max_rows: Number of leading rows to scan.

    Returns:
        The 0-indexed row number of the first match, or ``None`` if no row
        in the scanned range matches.

    Example:
        >>> import pandas as pd
        >>> sheet = pd.DataFrame([["Title"], ["Mode and Year"], ["Full-time"]])
        >>> find_marker_row(sheet, lambda v: str(v).strip() == "Mode and Year")
        1
        >>> find_marker_row(sheet, lambda v: str(v).strip() == "Nope") is None
        True
    """
    for index in range(min(max_rows, len(sheet))):
        if predicate(sheet.iat[index, 0]):
            return index
    return None
