"""Shared ODS parsing helpers for Department of Justice NI data sources.

DoJ NI publishes its statistical bulletins as OpenDocument Spreadsheet
workbooks in "accessibility" format: one worksheet per table group, footnote
markers embedded in labels, and suppression markers in place of withheld
values. These helpers cover the parts every DoJ module needs.

pandas' ODF reader is deliberately avoided here — it coerces time-typed cells
through :class:`pandas.Timestamp`, which fails on NICTS sitting-time durations
over 24 hours. Reading the underlying cell text directly sidesteps that.

Example:
    >>> _parse_value("32,339")
    32339.0
    >>> _strip_note_refs("Total [note 3]")
    'Total'
"""

import math
import re

from odf.table import Table, TableCell, TableRow
from odf.text import P

# Suppression markers used in place of a value
_SUPPRESSED = {"", "-", "N/A", "n/a", "[z]", "[c]", "[x]", ":"}

# Durations are published as HH:MM and can exceed 24 hours
_DURATION_RE = re.compile(r"^(\d+):([0-5]\d)$")

# Footnote references embedded in labels, e.g. "Total [note 3]"
_NOTE_REF_RE = re.compile(r"\s*[\[{]note \d+[\]}]", re.IGNORECASE)

# Cell repetition attributes can run to thousands for trailing filler
_MAX_REPEAT = 60


def _strip_note_refs(text: str) -> str:
    """Remove ``[note N]`` footnote markers from a label.

    Example:
        >>> _strip_note_refs("Total [note 3] [note 32]")
        'Total'
    """
    return _NOTE_REF_RE.sub("", text).strip()


def _parse_value(text: str) -> float:
    """Convert a raw cell string into a numeric value.

    Handles the four shapes DoJ publishes: comma-grouped integers, plain
    decimals, ``HH:MM`` durations (converted to fractional hours, and which may
    exceed 24 hours), and suppression markers such as ``[z]`` or ``N/A``.

    Args:
        text: Raw cell text.

    Returns:
        The numeric value, or NaN when suppressed or unparseable.

    Example:
        >>> _parse_value("1,234")
        1234.0
        >>> _parse_value("6485:30")
        6485.5
        >>> import math
        >>> math.isnan(_parse_value("[z]"))
        True
    """
    text = text.strip()
    if text in _SUPPRESSED:
        return float("nan")

    duration = _DURATION_RE.match(text)
    if duration:
        return int(duration.group(1)) + int(duration.group(2)) / 60

    try:
        return float(text.replace(",", ""))
    except ValueError:
        return float("nan")


def _label_column_count(data_rows: list[list[str]]) -> int:
    """Count the leading columns that hold labels rather than values.

    Most tables carry a single label column, but breakdowns such as sentencing
    disposal by gender carry two. A column is a label column when every cell in
    it is non-empty and non-numeric.

    Args:
        data_rows: Body rows of one table block.

    Returns:
        Number of leading label columns, always at least 1.

    Example:
        >>> _label_column_count([["2008/09", "April", "27"], ["2009/10", "May", "30"]])
        2
    """
    width = max(len(row) for row in data_rows)
    count = 0
    for column in range(width):
        cells = [row[column] if column < len(row) else "" for row in data_rows]
        if all(cell.strip() and math.isnan(_parse_value(cell)) for cell in cells):
            count += 1
        else:
            break
    return max(count, 1)


def _sheet_rows(table: Table) -> list[list[str]]:
    """Extract a worksheet as a list of raw text rows.

    Args:
        table: ODF table element.

    Returns:
        List of rows, each a list of cell strings, with trailing blanks removed.
    """
    rows: list[list[str]] = []
    for row in table.getElementsByType(TableRow):
        row_repeat = min(int(row.getAttribute("numberrowsrepeated") or 1), _MAX_REPEAT)
        cells: list[str] = []
        for cell in row.getElementsByType(TableCell):
            col_repeat = min(int(cell.getAttribute("numbercolumnsrepeated") or 1), _MAX_REPEAT)
            text = " ".join(str(p) for p in cell.getElementsByType(P))
            cells.extend([text] * col_repeat)
        while cells and not cells[-1].strip():
            cells.pop()
        if not cells:
            continue
        for _ in range(row_repeat):
            rows.append(list(cells))
    return rows
