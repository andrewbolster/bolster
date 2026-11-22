"""PPS Thematic Bulletins: cases involving sexual offences and hate crime.

Alongside its annual statistical bulletin (see :mod:`.pps_statistical_bulletin`),
the Public Prosecution Service for Northern Ireland (PPS) publishes two
thematic series, each following the same cases from file receipt through
prosecutorial decision to court outcome for one kind of offending:

- ``sexual_offences``: ``Statistical Bulletin: Cases Involving Sexual Offences``,
  with a ``Tables`` workbook for each of 2018/19 to the latest year, a revised
  workbook for 2015/16 and 2016/17, and (from 2024/25) an ``Overall Trends``
  workbook that gives the whole series from 2015/16.
- ``hate_crime``: ``Statistical Bulletin: Cases Involving Hate Crime``, with a
  ``Tables`` workbook for each of 2018/19 to the latest year (earlier years are
  PDF-only).

Published as: Statistical Bulletin: Cases Involving Sexual Offences. Statistical Bulletin: Cases Involving Hate Crime.

Every table reduces to the same tidy shape: one row per (series, table,
financial year, category, breakdown) observation. Table keys are namespaced by
series (``"sexual_offences:4a"``) because the two series, and the main PPS
bulletin, all number their tables from 1 and mean different things by them.

Data Source:
    **Hubs**: https://www.ppsni.gov.uk/thematic-bulletins-sexual-offences and
    https://www.ppsni.gov.uk/node/516

    Each hub lists one page per year; the module scrapes the hub for those
    pages, then picks the ``Tables`` (or ``Overall Trends``) workbook on each
    page by its link text. Year-page URLs follow no single pattern and are never
    constructed from the year.

Update Frequency: Annual (financial year, published the following autumn)
Geographic Coverage: Northern Ireland
Reference Period: 2015/16 - present (sexual offences), 2018/19 - present (hate crime)

.. note::
    ``value`` is not a single unit: ``unit`` says whether a row is a ``count``
    (files, suspects, persons, summonses), ``days`` (timeliness) or a
    ``proportion`` between 0 and 1 (a published 61% is ``0.61``). Filter on
    ``unit`` before aggregating.

.. note::
    Some tables nest rows: after a row labelled ``Of which:`` the indented
    rows are parts of the row above, so summing every row of a table double
    counts. ``parent`` names the row a nested row belongs to (``None`` for
    top-level rows); exclude rows with a ``parent`` before summing, and rows
    whose ``category`` starts ``All`` (totals).

.. note::
    PPS suppresses small counts: ``-`` (fewer than 3), ``#`` (3 or more but
    withheld to protect another figure) and ``*`` (category not available) all
    arrive as ``value`` of NaN with the published symbol in ``marker``, and
    ``N/A`` (rate not defined) likewise.

.. note::
    Hate crime changed its motivation categories between bulletins (``Faith /
    Religion`` versus older wording) and PPS reorganised its regions between
    2024/25 and 2025/26. ``category`` and ``breakdown`` are the labels as
    published and are not comparable across those boundaries; ``All PPS`` totals
    are.

Example:
    >>> from bolster.data_sources.justice import pps_thematic_bulletins as pps
    >>> df = pps.get_latest_data("hate_crime", table="3a")
    >>> set(df["series"]) == {"hate_crime"}
    True
    >>> set(df["table"]) == {"hate_crime:3a"}
    True
"""

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast
from urllib.parse import unquote, urljoin

import pandas as pd
from bs4 import Tag  # noqa: TC002 (used inside `cast(...)`, evaluated at runtime)

from bolster.utils.cache import CachedDownloader, bind_download_file, stitch_publications
from bolster.utils.web import fetch_soup, scrape_file_links

from .pps_statistical_bulletin import (
    PPSDataError,
    PPSDataNotFoundError,
    PPSValidationError,
    _clean_label,
    _parse_value,
    _sheet_rows,
)

logger = logging.getLogger(__name__)

Series = Literal["sexual_offences", "hate_crime"]
SERIES: tuple[str, ...] = ("sexual_offences", "hate_crime")

# Hub pages listing one page per year for each thematic series
_HUBS: dict[str, str] = {
    "sexual_offences": "https://www.ppsni.gov.uk/thematic-bulletins-sexual-offences",
    "hate_crime": "https://www.ppsni.gov.uk/node/516",
}

# Link text of a year page: "Statistical Bulletin: Cases Involving Hate Crime 2025/26"
_TITLE_RE: dict[str, re.Pattern[str]] = {
    "sexual_offences": re.compile(r"cases involving sexual offences", re.IGNORECASE),
    "hate_crime": re.compile(r"cases involving hate crime", re.IGNORECASE),
}

_FY_RE = re.compile(r"(\d{4})\s*[/-]\s*(\d{2})")

# A period label on its own, with an optional "Q1-4" prefix and trailing footnote digits
_PERIOD_CELL_RE = re.compile(r"^(?:q\s*1\s*-\s*4\s*)?(\d{4})\s*/\s*(\d{2})[\d,\s]*$", re.IGNORECASE)

# Sheet names look like "Table 3A"; the key is normalised to "3a"
_TABLE_SHEET_RE = re.compile(r"table\s*([0-9]+[a-z]?)\s*$", re.IGNORECASE)

# Worksheets carrying front matter rather than statistical tables
_NON_DATA_SHEET_RE = re.compile(r"explanatory|metadata|contents|bulletin", re.IGNORECASE)

# Row labels that head the period column of a table
_PERIOD_HEADERS = {"financial year", "year", "quarters", "quarter"}

# Header cells that name a unit rather than a breakdown
_UNIT_LABELS = {"number", "%", "n", "rate", "calendar days", "days"}

# Rows that close the data region: derived change rows and the contents link
_FOOTER_RE = re.compile(r"^(%\s*change|change\b|percentage\s+change|contents\b)", re.IGNORECASE)

# "Source:" lines close a block but not the sheet: the trends workbook stacks blocks beneath them
_SOURCE_RE = re.compile(r"^source\b", re.IGNORECASE)

# Footnote lines: a lone digit then text, or a quoted/bulleted legend line
_FOOTNOTE_RE = re.compile(r"^(\d\s|[\"“”'‘’*#])")

# "N/A" (optionally followed by a footnote digit) is published where a rate is undefined
_NA_RE = re.compile(r"^n/?a\s*\d*$", re.IGNORECASE)

# A nested row group opens with "Of which:" and its rows read "Convicted of at least one ..."
_OF_WHICH_RE = re.compile(r"^of which", re.IGNORECASE)
_NESTED_ROW_RE = re.compile(r"^convicted of at least one", re.IGNORECASE)

# Rates and percentages are published as fractions
_PROPORTION_LABEL_RE = re.compile(r"(%|\brate\b)", re.IGNORECASE)

# Header cells that say the values are days
_DAYS_LABELS = {"calendar days", "days"}

# Year, then decision type, then the row itself: the deepest label nesting in any bulletin
_MAX_LABEL_COLUMNS = 3

# A period-column table may hold this many values in a column with no header before it is an error
_MAX_STRAY_CELLS = 2

# Bulletins are annual, so a cached workbook stays valid for a long time
_CACHE_TTL_HOURS = 24 * 90

_downloader = CachedDownloader("pps_thematic_bulletins", timeout=60)

# download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=False) -> Path,
# raising PPSDataNotFoundError in place of DownloadError.
download_file = bind_download_file(_downloader, PPSDataNotFoundError, _CACHE_TTL_HOURS)


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------


def _value(text: str) -> tuple[float, str | None]:
    """Convert a raw cell into a numeric value and a suppression marker.

    Extends the main bulletin's parser with ``N/A`` (an undefined rate), which
    PPS writes with a trailing footnote digit such as ``N/A3``.

    Example:
        >>> _value("1,234")
        (1234.0, None)
        >>> _value("N/A3")[1]
        'N/A'
        >>> _value("#")[1]
        '#'
        >>> _value("Rape")[1] is None
        True
    """
    cleaned = str(text).strip()
    if _NA_RE.match(cleaned):
        return float("nan"), "N/A"
    return _parse_value(cleaned)


def _is_value(text: str) -> bool:
    """Check whether a cell holds a number or a suppression marker."""
    value, marker = _value(text)
    return not math.isnan(value) or marker is not None


def _period_label(text: str) -> str | None:
    """Return the financial year a cell consists of, or ``None``.

    Example:
        >>> _period_label("2025/26")
        '2025/26'
        >>> _period_label("2025/262")
        '2025/26'
        >>> _period_label("Q1-4 2017/18")
        '2017/18'
        >>> _period_label("2024/25 and 2025/261") is None
        True
    """
    match = _PERIOD_CELL_RE.match(str(text).strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _all_periods(text: str) -> list[str]:
    """Return every financial year mentioned in ``text``, in order of appearance.

    Example:
        >>> _all_periods("2024/25 and 2025/261")
        ['2024/25', '2025/26']
    """
    return [f"{a}/{b}" for a, b in re.findall(r"(\d{4})\s*/\s*(\d{2})", str(text))]


def _is_footnote_or_footer(row: list[str]) -> bool:
    """Check whether a row closes the data region of a sheet."""
    first = row[0].strip() if row else ""
    others = any(cell.strip() for cell in row[1:])
    if first and _FOOTER_RE.match(first):
        return True
    if first and not others and _FOOTNOTE_RE.match(first):
        return True
    # Derived "Percentage Change" rows carry the label in the second column
    return bool(not first and len(row) > 1 and _FOOTER_RE.match(row[1].strip()))


# ---------------------------------------------------------------------------
# Sheet parsing
# ---------------------------------------------------------------------------


@dataclass
class _Event:
    """One classified row inside a block: a data row, a group label or a nesting marker."""

    kind: Literal["data", "group", "of_which"]
    row: int = -1
    label: str = ""


@dataclass
class _Block:
    """A header (one or more rows) followed by the rows it describes."""

    header_rows: list[int] = field(default_factory=list)
    events: list[_Event] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return any(event.kind == "data" for event in self.events)


@dataclass
class _Column:
    """A value column of a block: its published name, period and unit."""

    name: str | None
    period: str | None
    proportion: bool
    days: bool = False


def _label_columns(rows: list[list[str]], end: int) -> int:
    """Count the leading label columns (1 to 3) of a sheet.

    A column after the first is a label column when, among data rows, it holds
    more labels than values. Blank cells (a merged cell's continuation) count
    for neither.

    Raises:
        PPSDataError: If the sheet has no data rows.
    """
    data = [row for row in rows[1:end] if any(_is_value(cell) for cell in row[1:])]
    if not data:
        raise PPSDataError("sheet has no data rows")
    n_label = 1
    while n_label < _MAX_LABEL_COLUMNS:
        cells = [row[n_label] for row in data if len(row) > n_label and row[n_label]]
        values = sum(1 for cell in cells if _is_value(cell))
        if len(cells) - values <= values:
            break
        n_label += 1
    return n_label


def _data_end(rows: list[list[str]]) -> int:
    """Index of the first footer or footnote row (``len(rows)`` if there is none)."""
    return next((idx for idx, row in enumerate(rows) if idx > 0 and _is_footnote_or_footer(row)), len(rows))


def _split_blocks(rows: list[list[str]], end: int, n_label: int) -> tuple[list[_Block], list[str]]:
    """Group the rows of a sheet into header blocks, and collect the preamble.

    Returns:
        Tuple of the blocks and the preamble texts (subtitle and unit lines that
        appear above the first header).
    """
    blocks: list[_Block] = []
    preamble: list[str] = []
    current: _Block | None = None

    for idx in range(1, end):
        row = rows[idx]
        if not any(cell for cell in row) or _SOURCE_RE.match(row[0].strip()):
            continue

        has_value = any(_is_value(cell) for cell in row[n_label:])
        has_header_cells = any(cell for cell in row[n_label:])
        period_word = _clean_label(row[0]).lower() in _PERIOD_HEADERS if row[0] else False

        if has_value:
            if current is None:
                current = _Block()
                blocks.append(current)
            current.events.append(_Event("data", row=idx))
        elif has_header_cells or period_word:
            if current is None or current.has_data:
                current = _Block()
                blocks.append(current)
            current.header_rows.append(idx)
        else:
            label = _clean_label(next(cell for cell in row if cell))
            if current is None:
                preamble.append(label)
            elif _OF_WHICH_RE.match(label):
                current.events.append(_Event("of_which"))
            else:
                current.events.append(_Event("group", label=label))

    return blocks, preamble


def _resolve_columns(rows: list[list[str]], block: _Block, n_label: int) -> dict[int, _Column]:
    """Resolve the name, period and unit of every value column of a block.

    Names are read from the header rows bottom-up, skipping unit cells
    (``Number``, ``%``) so a stacked header resolves to the row of real names
    above the unit row.
    """
    value_cols = sorted(
        {
            col
            for event in block.events
            if event.kind == "data"
            for col in range(n_label, len(rows[event.row]))
            if _is_value(rows[event.row][col])
        }
    )
    columns: dict[int, _Column] = {}
    stacked: dict[int, list[str]] = {}
    for col in value_cols:
        name: str | None = None
        proportion = False
        days = False
        for header_idx in reversed(block.header_rows):
            cell = _clean_label(rows[header_idx][col]) if col < len(rows[header_idx]) else ""
            if cell == "%":
                proportion = True
            if cell.lower() in _DAYS_LABELS:
                days = True
            if cell and cell.lower() not in _UNIT_LABELS and name is None:
                name = cell
        # Every distinct name cell from the top down, to tell apart columns whose bottom names repeat
        stacked[col] = _dedup(
            [
                _clean_label(rows[idx][col])
                for idx in block.header_rows
                if col < len(rows[idx]) and rows[idx][col] and _clean_label(rows[idx][col]).lower() not in _UNIT_LABELS
            ]
        )
        columns[col] = _Column(
            name=name, period=_period_label(name) if name else None, proportion=proportion, days=days
        )

    # "Median" under "Rape" and "Median" under "Other Sexual Offences" are two columns, not one:
    # where bottom names collide, the stacked header is the name
    names = [column.name for column in columns.values() if column.name]
    for col, column in columns.items():
        if column.name and names.count(column.name) > 1 and len(stacked[col]) > 1:
            column.name = " - ".join(stacked[col])
            column.period = _period_label(column.name)
    return columns


def _dedup(items: list[str]) -> list[str]:
    """Drop repeats, keeping order."""
    return list(dict.fromkeys(items))


def _row_unit(category: str, column: _Column, sheet_unit: str) -> str:
    """Classify a value as a ``count``, ``days`` or ``proportion``."""
    if column.proportion or _PROPORTION_LABEL_RE.search(category):
        return "proportion"
    if column.days or "days" in sheet_unit:
        return "days"
    return "count"


def _parse_grid(table: str, title: str, rows: list[list[str]]) -> list[dict]:
    """Parse one worksheet into observation dicts.

    Three layouts occur and all are handled by the same pass:

    - **Period rows**: the first column states the financial year (carried down
      a merged cell), an optional second column labels the row, and each
      remaining column is a named breakdown.
    - **Period columns**: the header row names a financial year for each value
      column; an optional merged first column groups the rows.
    - **Matrix**: the period is stated once in the subtitle, rows are labelled in
      the first column, and columns are named breakdowns.

    Raises:
        PPSDataError: If the layout cannot be interpreted. Nothing is guessed.
    """
    end = _data_end(rows)
    n_label = _label_columns(rows, end)
    blocks, preamble = _split_blocks(rows, end, n_label)
    sheet_unit = " ".join(preamble).lower()
    first_header = blocks[0].header_rows[0] if blocks and blocks[0].header_rows else min(end, 4)
    subtitle_periods = sorted({fy for row in rows[1:first_header] for cell in row for fy in _all_periods(cell)})
    measure = title.split(":", 1)[-1].strip() if ":" in title else title

    records: list[dict] = []
    for block_no, block in enumerate(blocks):
        columns = _resolve_columns(rows, block, n_label)
        period_cols = [col for col, column in columns.items() if column.period]
        if period_cols:
            named_others = [column.name for col, column in columns.items() if col not in period_cols and column.name]
            if named_others:
                raise PPSDataError(f"Table {table}: columns mix periods and other headers ({named_others})")
            # A value in a column with no header at all is a stray cell, not a series: tolerate a couple, say so
            strays = [col for col in columns if col not in period_cols]
            if strays:
                cells = [
                    f"row {event.row + 1}"
                    for event in block.events
                    if event.kind == "data"
                    for col in strays
                    if col < len(rows[event.row]) and _is_value(rows[event.row][col])
                ]
                if len(cells) > _MAX_STRAY_CELLS:
                    raise PPSDataError(f"Table {table}: {len(cells)} values sit in columns with no period header")
                logger.warning(
                    f"Table {table}: ignoring {len(cells)} stray value(s) in an unlabelled column ({', '.join(cells)})"
                )
                for col in strays:
                    del columns[col]
        layout = "columns" if period_cols else "rows"

        if layout == "columns" and n_label == _MAX_LABEL_COLUMNS:
            raise PPSDataError(f"Table {table}: {n_label} label columns with period columns is not a known layout")

        header = rows[block.header_rows[-1]] if block.header_rows else []
        if n_label == _MAX_LABEL_COLUMNS:
            # The dimension is named in the second label column, on whichever header row states it
            named = [rows[idx][1] for idx in reversed(block.header_rows) if len(rows[idx]) > 1 and rows[idx][1]]
            dim_cell = _clean_label(named[0]) if named else ""
        else:
            dim_cell = _clean_label(header[n_label - 1]) if len(header) >= n_label else ""
        dimension = None if (not dim_cell or dim_cell.lower() in _PERIOD_HEADERS) else dim_cell

        group: str | None = None
        carry_fy: str | None = None
        carry_type: str | None = None
        last_category: str | None = None
        nest_parent: str | None = None

        for event in block.events:
            if event.kind == "of_which":
                nest_parent = last_category
                continue
            if event.kind == "group":
                group = event.label
                nest_parent = None
                continue

            row = rows[event.row]
            first = _clean_label(row[0]) if row[0] else ""
            second = _clean_label(row[1]) if n_label >= 2 and len(row) > 1 and row[1] else ""
            third = _clean_label(row[2]) if n_label == _MAX_LABEL_COLUMNS and len(row) > 2 and row[2] else ""

            row_fy: str | None = None
            if layout == "columns":
                if n_label == 2 and second:
                    group = first or group
                    category = second
                elif n_label == 2:
                    # A label in the first column alone is a row of its own ("All Decisions Issued"), not a group
                    category, group = first, None
                else:
                    category = first
            elif n_label >= 2:
                if first:
                    parsed = _period_label(first)
                    if not parsed:
                        raise PPSDataError(f"Table {table}: row label {first!r} is not a financial year")
                    carry_fy = parsed
                row_fy = carry_fy
                if n_label == _MAX_LABEL_COLUMNS:
                    # The decision type is stated once, above its rows ("Prosecution"), and the row
                    # itself may be left blank when the decision type is the row ("Diversion")
                    carry_type = second or carry_type
                    category = third or carry_type or ""
                else:
                    category = second
            else:
                parsed = _period_label(first)
                if parsed:
                    row_fy, category = parsed, measure
                else:
                    if len(subtitle_periods) != 1:
                        raise PPSDataError(
                            f"Table {table}: expected one period in the subtitle, found {subtitle_periods or 'none'}"
                        )
                    row_fy, category = subtitle_periods[0], first

            if not category or (layout == "rows" and not row_fy):
                raise PPSDataError(f"Table {table}: could not read the row at sheet row {event.row + 1}")

            parent = nest_parent if (nest_parent and _NESTED_ROW_RE.match(category)) else None
            if not parent:
                nest_parent = None
            last_category = category if not parent else last_category

            # A group in the first column is only labelled on its first row and closes with a
            # subtotal that names it ("... - For Other Offences"); rows after that subtotal
            # (No Prosecution, All Decisions Issued, shares) belong to the whole table.
            closes_group = bool(
                layout == "columns" and n_label == 2 and group and category.lower().endswith(group.lower())
            )

            for col, column in columns.items():
                if col >= len(row) or not _is_value(row[col]):
                    continue
                value, marker = _value(row[col])
                if layout == "columns":
                    fy, breakdown = cast("str", column.period), group
                else:
                    fy = cast("str", row_fy)
                    breakdown = column.name or (_clean_label(preamble[-1]) if preamble else "Value")
                records.append(
                    {
                        "table": table,
                        "title": title,
                        "financial_year": fy,
                        "dimension": dimension,
                        "category": category,
                        "breakdown": breakdown,
                        "parent": parent,
                        "unit": _row_unit(category, column, sheet_unit),
                        "value": value,
                        "marker": marker,
                        "_layout": layout,
                        "_n_label": n_label,
                        "_block": block_no,
                    }
                )

            if closes_group:
                group = None

    return records


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _is_total(label: object) -> bool:
    """Check whether a label names a total (``All files``, ``All PPS``, ...)."""
    return isinstance(label, str) and label.strip().lower().startswith("all ")


def _sum_matches(parts: pd.Series, total: float) -> bool | None:
    """Compare a sum with a stated total; ``None`` when a suppressed cell blocks the check."""
    if parts.empty or parts.isna().any() or math.isnan(total):
        return None
    return math.isclose(float(parts.sum()), total, abs_tol=1e-6)


@dataclass(frozen=True)
class _Problem:
    """One failed identity: which table, year and row or column, and what was found."""

    table: str
    financial_year: str
    label: str
    message: str


# Errors in PPS's own published figures. Each is checked against the workbook, not assumed: the
# reconciliation fails on exactly these cells and the explanation says what the table itself shows.
# Keyed by (series, table, financial year, row or column label).
_KNOWN_DISCREPANCIES: dict[tuple[str, str, str, str], str] = {
    ("hate_crime", "5", "2021/22", "Multiple Motivations"): (
        "PPS publishes 'All defendants' as 0 for Multiple Motivations although its outcomes sum to 1; "
        "the table's own total row (13) counts that defendant"
    ),
    ("hate_crime", "5", "2021/22", "All defendants"): (
        "PPS publishes 'All defendants' as 0 for Multiple Motivations although its outcomes sum to 1; "
        "the table's own total row (13) counts that defendant"
    ),
}


def _check_totals(df: pd.DataFrame) -> list[_Problem]:
    """Check that the components of a parsed table add up to its stated totals.

    Counts only: days and proportions are not additive. A check that touches a
    suppressed cell (``-``, ``#``, ``*``) cannot be made and is skipped, so only
    verifiable identities can fail:

    - **Column totals**: in a table with an ``All ...`` column, the other count
      columns of a row sum to it.
    - **Row totals**: in a table with a single ``All ...`` row per block, the
      other (non-nested) rows sum to it.
    - **Grand total**: in a table that groups rows under a first-column label,
      the last ``All ...`` row equals the sum of every leaf row.

    Args:
        df: One table's parsed observations, including the internal ``_layout``,
            ``_n_label`` and ``_block`` columns.

    Returns:
        Every identity that fails.
    """
    problems: list[_Problem] = []
    counts = df[df["unit"] == "count"]
    table = str(df["table"].iloc[0])
    rows_layout = counts[counts["_layout"] == "rows"]

    # Column totals: one row's components against its "All ..." column
    for (_, fy, category), group in rows_layout.groupby(["_block", "financial_year", "category"], dropna=False):
        totals = group[group["breakdown"].map(_is_total)]
        if len(totals) != 1:
            continue
        total = float(totals["value"].iloc[0])
        parts = group.drop(totals.index)
        if _sum_matches(parts["value"], total) is False:
            problems.append(
                _Problem(
                    table,
                    fy,
                    str(category),
                    f"Table {table}, {fy}, {category}: columns sum to {parts['value'].sum():g}, stated total {total:g}",
                )
            )

    # Row totals: one column's non-nested rows against its "All ..." row
    for (_, fy, breakdown), group in rows_layout.groupby(["_block", "financial_year", "breakdown"], dropna=False):
        totals = group[group["category"].map(_is_total)]
        if len(totals) != 1:
            continue
        parts = group.drop(totals.index)
        parts = parts[parts["parent"].isna()]
        total = float(totals["value"].iloc[0])
        if _sum_matches(parts["value"], total) is False:
            problems.append(
                _Problem(
                    table,
                    fy,
                    str(breakdown),
                    f"Table {table}, {fy}, {breakdown}: rows sum to {parts['value'].sum():g}, stated total {total:g}",
                )
            )

    # Period-column layouts
    columns_layout = counts[counts["_layout"] == "columns"]
    for (_, fy), group in columns_layout.groupby(["_block", "financial_year"], dropna=False):
        if int(group["_n_label"].iloc[0]) == 2:
            # Grouped in the first column: the last "All ..." row is the grand total of every leaf row
            totals = group[group["category"].map(_is_total)]
            if totals.empty:
                continue
            grand = totals.iloc[-1]
            leaves = group[
                ~group["category"].map(_is_total) & ~group["category"].str.lower().str.startswith("total prosecution")
            ]
            if _sum_matches(leaves["value"], float(grand["value"])) is False:
                problems.append(
                    _Problem(
                        table,
                        fy,
                        str(grand["category"]),
                        f"Table {table}, {fy}: rows sum to {leaves['value'].sum():g}, stated total {float(grand['value']):g}",
                    )
                )
        else:
            # Grouped by label rows: each group's "All ..." row is its own total
            for breakdown, sub in group.groupby("breakdown", dropna=False):
                totals = sub[sub["category"].map(_is_total)]
                if len(totals) != 1:
                    continue
                parts = sub.drop(totals.index)
                parts = parts[parts["parent"].isna()]
                if _sum_matches(parts["value"], float(totals["value"].iloc[0])) is False:
                    problems.append(
                        _Problem(
                            table,
                            fy,
                            str(breakdown),
                            f"Table {table}, {fy}, {breakdown}: rows sum to {parts['value'].sum():g}, "
                            f"stated total {float(totals['value'].iloc[0]):g}",
                        )
                    )

    return problems


# ---------------------------------------------------------------------------
# Workbook parsing
# ---------------------------------------------------------------------------

_COLUMNS = [
    "series",
    "table",
    "title",
    "financial_year",
    "year",
    "dimension",
    "category",
    "breakdown",
    "parent",
    "unit",
    "value",
    "marker",
]


def _sheet_title(rows: list[list[str]]) -> str:
    """Read a sheet's title: the first cell, plus a continuation line when it has one."""
    title = _clean_label(rows[0][0]) if rows and rows[0] else ""
    if len(rows) > 2 and rows[1] and rows[1][0] and not any(rows[1][1:]) and _all_periods(rows[2][0]):
        continuation = _clean_label(rows[1][0])
        if not _all_periods(continuation):
            title = f"{title} - {continuation}"
    return title


def _sheet_frame(series: str, table: str, sheet_name: str, rows: list[list[str]], strict: bool) -> pd.DataFrame | None:
    """Parse and verify one worksheet, or return ``None`` when a non-strict parse skips it.

    Raises:
        PPSDataError: In strict mode, if the sheet cannot be parsed or yields no records.
        PPSValidationError: In strict mode, if the rows do not add up to the stated totals.
    """
    title = _sheet_title(rows)
    try:
        records = _parse_grid(table, title, rows)
        if not records:
            raise PPSDataError("no observations were found")
    except PPSDataError as e:
        if strict:
            raise PPSDataError(f"Sheet {sheet_name!r}: {e}") from e
        logger.warning(f"Sheet {sheet_name!r}: {e}; skipping")
        return None

    frame = pd.DataFrame.from_records(records)
    unexplained = []
    for problem in _check_totals(frame):
        known = _KNOWN_DISCREPANCIES.get((series, problem.table, problem.financial_year, problem.label))
        if known:
            logger.warning(f"{problem.message} (known PPS publication error: {known})")
        else:
            unexplained.append(problem.message)
    if unexplained:
        message = f"Sheet {sheet_name!r} does not reconcile: " + "; ".join(unexplained[:5])
        if strict:
            raise PPSValidationError(message)
        logger.warning(message)

    frame.insert(0, "series", series)
    frame["table"] = f"{series}:{table}"
    frame.insert(4, "year", frame["financial_year"].str[:4].astype(int))
    return frame[_COLUMNS].reset_index(drop=True)


def _read_workbook(file_path: Path) -> dict[str, list[list[str]]]:
    """Read every sheet of a workbook as rows of stripped strings."""
    try:
        book = pd.read_excel(Path(file_path), sheet_name=None, header=None)
    except (OSError, ValueError) as e:
        raise PPSDataNotFoundError(f"Failed to read workbook {file_path}: {e}") from e
    return {str(name): _sheet_rows(frame) for name, frame in book.items()}


def parse_tables_workbook(file_path: Path, series: str, strict: bool = True) -> pd.DataFrame:
    """Parse every statistical table from a thematic ``Tables`` workbook.

    Args:
        file_path: Path to the ``.xlsx`` workbook.
        series: ``"sexual_offences"`` or ``"hate_crime"``; recorded in ``series``
            and used to namespace ``table`` (``"hate_crime:3a"``).
        strict: If True (default), a sheet that yields no observations, a layout
            that cannot be interpreted, or rows that do not add up to the stated
            total raise instead of being skipped. If False each is logged and
            the sheet skipped.

    Returns:
        DataFrame with columns series, table, title, financial_year, year,
        dimension, category, breakdown, parent, unit, value, marker.

    Raises:
        PPSDataNotFoundError: If the workbook cannot be read.
        PPSDataError: If a sheet cannot be parsed (strict), or none can.
        PPSValidationError: If a table does not reconcile (strict).
    """
    _check_series(series)
    frames: list[pd.DataFrame] = []
    for position, (sheet_name, rows) in enumerate(_read_workbook(file_path).items()):
        match = _TABLE_SHEET_RE.match(sheet_name.strip())
        if not match:
            holds_data = sum(1 for row in rows for cell in row[1:] if _is_value(cell)) >= 3
            if position > 0 and holds_data and not _NON_DATA_SHEET_RE.search(sheet_name):
                message = f"Sheet {sheet_name!r} holds data but is not a 'Table N' sheet"
                if strict:
                    raise PPSDataError(message)
                logger.warning(f"{message}; skipping")
            continue
        frame = _sheet_frame(series, match.group(1).lower(), sheet_name, rows, strict)
        if frame is not None:
            frames.append(frame)

    if not frames:
        raise PPSDataError(f"No parseable tables found in {file_path}")
    return pd.concat(frames, ignore_index=True)


def parse_trends_workbook(file_path: Path, strict: bool = True) -> pd.DataFrame:
    """Parse the sexual offences ``Overall Trends`` workbook.

    Each sheet (``Files Received``, ``Decisions Issued``, ``Timeliness``,
    ``Outcomes Crown``, ``Outcomes Magistrates``) is a series from 2015/16 to the
    latest year, with the years across the columns. ``table`` is
    ``"sexual_offences:trends/<sheet>"``.

    Args:
        file_path: Path to the ``.xlsx`` workbook.
        strict: As in :func:`parse_tables_workbook`.

    Returns:
        DataFrame in the same shape as :func:`parse_tables_workbook`.

    Raises:
        PPSDataNotFoundError: If the workbook cannot be read.
        PPSDataError: If no sheet can be parsed.
    """
    frames: list[pd.DataFrame] = []
    for position, (sheet_name, rows) in enumerate(_read_workbook(file_path).items()):
        has_data = any(_is_value(cell) for row in rows for cell in row[1:])
        if position == 0 and not has_data:
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", sheet_name.lower()).strip("_")
        frame = _sheet_frame("sexual_offences", f"trends/{slug}", sheet_name, rows, strict)
        if frame is not None:
            frames.append(frame)

    if not frames:
        raise PPSDataError(f"No parseable sheets found in {file_path}")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _check_series(series: str) -> None:
    """Raise if ``series`` is not one of the thematic series."""
    if series not in SERIES:
        raise PPSDataNotFoundError(f"Unknown series {series!r}. Available: {', '.join(SERIES)}")


def list_publications(series: str, force_refresh: bool = False) -> list[dict]:
    """List every bulletin on a thematic series' hub page.

    Args:
        series: ``"sexual_offences"`` or ``"hate_crime"``.
        force_refresh: If True, bypass the page cache.

    Returns:
        List of dicts with ``series``, ``title``, ``url``, ``financial_year`` (the
        newest year covered), ``financial_years`` (every year in the title),
        ``year`` and ``kind`` (``"bulletin"``, or ``"revised"`` for the revised
        2015/16 and 2016/17 statistics), newest first.

    Raises:
        PPSDataNotFoundError: If the series is unknown, the hub cannot be fetched or lists no bulletins.

    Example:
        >>> pubs = list_publications("sexual_offences")
        >>> pubs[0]["year"] >= pubs[-1]["year"]
        True
        >>> pubs[0]["url"].startswith("https://www.ppsni.gov.uk")
        True
    """
    _check_series(series)
    hub = _HUBS[series]
    try:
        soup = fetch_soup(hub, force_refresh=force_refresh)
    except Exception as e:
        raise PPSDataNotFoundError(f"Failed to fetch hub page {hub}: {e}") from e

    publications: dict[str, dict] = {}
    for anchor in cast("list[Tag]", soup.find_all("a", href=True)):
        title = " ".join(anchor.get_text().split())
        if not _TITLE_RE[series].search(title) or title.lower().startswith("archived"):
            continue
        years = [f"{a}/{b}" for a, b in _FY_RE.findall(title)]
        if not years:
            continue
        url = urljoin(hub, cast("str", anchor["href"]))
        newest = max(years)
        publications[url] = {
            "series": series,
            "title": title,
            "url": url,
            "financial_year": newest,
            "financial_years": years,
            "year": int(newest[:4]),
            "kind": "revised" if title.lower().startswith("revised") else "bulletin",
        }

    if not publications:
        raise PPSDataNotFoundError(f"No bulletins found on {hub}")

    return sorted(publications.values(), key=lambda p: (p["year"], p["kind"] == "bulletin"), reverse=True)


def find_workbooks(publication_url: str, force_refresh: bool = False) -> list[dict]:
    """List the workbooks on a bulletin page, classified by link text.

    A workbook is a ``tables`` workbook when its link text or file name says
    ``Tables``, and a ``trends`` workbook when it says ``Trends``; anything else
    is ``other``. Position on the page plays no part.

    Args:
        publication_url: URL of a bulletin page from :func:`list_publications`.
        force_refresh: If True, bypass the page cache.

    Returns:
        List of dicts with ``kind``, ``url`` and ``text``, in page order.

    Raises:
        PPSDataNotFoundError: If the page cannot be fetched.

    Example:
        >>> pubs = list_publications("hate_crime")
        >>> [w["kind"] for w in find_workbooks(pubs[0]["url"])]
        ['tables']
    """
    try:
        links = scrape_file_links(publication_url, ".xlsx", force_refresh=force_refresh)
    except Exception as e:
        raise PPSDataNotFoundError(f"Failed to fetch bulletin page {publication_url}: {e}") from e

    seen: set[str] = set()
    workbooks: list[dict] = []
    for link in links:
        if link["url"] in seen:
            continue
        seen.add(link["url"])
        haystack = f"{link['text']} {unquote(link['url'].rsplit('/', 1)[-1])}".lower()
        kind = "trends" if "trend" in haystack else "tables" if "table" in haystack else "other"
        workbooks.append({"kind": kind, "url": link["url"], "text": link["text"]})
    return workbooks


def _single_workbook(publication_url: str, kind: str, force_refresh: bool) -> str:
    """Return the URL of the one workbook of ``kind`` on a page, or raise."""
    found = [w for w in find_workbooks(publication_url, force_refresh=force_refresh) if w["kind"] == kind]
    if len(found) == 1:
        return found[0]["url"]
    if not found:
        raise PPSDataNotFoundError(f"No {kind!r} workbook found on {publication_url}")
    names = ", ".join(w["text"] or w["url"] for w in found)
    raise PPSDataNotFoundError(
        f"{len(found)} {kind!r} workbooks found on {publication_url} ({names}); not choosing one"
    )


def find_tables_workbook(publication_url: str, force_refresh: bool = False) -> str:
    """Find the ``Tables`` workbook on a bulletin page.

    Args:
        publication_url: URL of a bulletin page from :func:`list_publications`.
        force_refresh: If True, bypass the page cache.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        PPSDataNotFoundError: If the page has none or more than one.
    """
    return _single_workbook(publication_url, "tables", force_refresh)


def find_trends_workbook(publication_url: str, force_refresh: bool = False) -> str:
    """Find the ``Overall Trends`` workbook on a bulletin page.

    Only the sexual offences bulletins for 2024/25 onwards carry one.

    Args:
        publication_url: URL of a bulletin page from :func:`list_publications`.
        force_refresh: If True, bypass the page cache.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        PPSDataNotFoundError: If the page has none or more than one.
    """
    return _single_workbook(publication_url, "trends", force_refresh)


def _latest_bulletin(series: str, force_refresh: bool) -> dict:
    """Return the newest regular bulletin of a series."""
    latest = next((p for p in list_publications(series, force_refresh=force_refresh) if p["kind"] == "bulletin"), None)
    if latest is None:
        raise PPSDataNotFoundError(f"No bulletin found for series {series!r}")
    return latest


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _table_key(series: str, table: str) -> str:
    """Normalise ``"4A"``, ``"4a"`` or ``"sexual_offences:4a"`` to ``"sexual_offences:4a"``."""
    return f"{series}:{table.lower().split(':')[-1]}"


def get_latest_data(series: str, table: str = "all", force_refresh: bool = False, strict: bool = True) -> pd.DataFrame:
    """Download and parse the most recent bulletin of a thematic series.

    Each bulletin restates the prior financial year alongside the current one,
    so a single download covers two years.

    Args:
        series: ``"sexual_offences"`` or ``"hate_crime"``.
        table: Table key (``"4a"``; see :func:`list_tables`), or ``"all"``.
        force_refresh: If True, bypass the cache and download fresh data.
        strict: If False, a sheet that cannot be parsed is skipped with a warning instead of raising.

    Returns:
        Tidy DataFrame of observations.

    Raises:
        PPSDataNotFoundError: If the bulletin or ``table`` cannot be found.

    Example:
        >>> df = get_latest_data("sexual_offences", "4a")
        >>> set(df["table"]) == {"sexual_offences:4a"}
        True
    """
    _check_series(series)
    latest = _latest_bulletin(series, force_refresh)
    url = find_tables_workbook(latest["url"], force_refresh=force_refresh)
    df = parse_tables_workbook(download_file(url, force_refresh=force_refresh), series, strict=strict)

    if table == "all":
        return df

    key = _table_key(series, table)
    available = sorted(df["table"].unique())
    if key not in available:
        raise PPSDataNotFoundError(
            f"Unknown table '{table}'. Available: {', '.join(t.split(':')[-1] for t in available)}"
        )
    return df[df["table"] == key].reset_index(drop=True)


def get_overall_trends(force_refresh: bool = False, strict: bool = True) -> pd.DataFrame:
    """Get the sexual offences series from 2015/16 to the latest year.

    Reads the ``Overall Trends`` workbook of the newest sexual offences bulletin.
    It never reads an older bulletin's workbook in its place: if the newest
    bulletin has none, it raises.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.
        strict: If False, a sheet that cannot be parsed is skipped with a warning instead of raising.

    Returns:
        Tidy DataFrame of files received, decisions, timeliness and court outcomes.

    Raises:
        PPSDataNotFoundError: If the newest bulletin has no ``Overall Trends`` workbook.

    Example:
        >>> df = get_overall_trends()
        >>> df["financial_year"].min()
        '2015/16'
    """
    latest = _latest_bulletin("sexual_offences", force_refresh)
    url = find_trends_workbook(latest["url"], force_refresh=force_refresh)
    return parse_trends_workbook(download_file(url, force_refresh=force_refresh), strict=strict)


def get_historical_data(
    series: str, max_publications: int = 10, force_refresh: bool = False, strict: bool = True
) -> pd.DataFrame:
    """Stitch several bulletins of a series into one long series.

    Bulletins are read newest-first and overlapping years are resolved in
    favour of the more recent publication. A bulletin that cannot be read
    raises: a missing year is never skipped silently.

    Args:
        series: ``"sexual_offences"`` or ``"hate_crime"``.
        max_publications: Maximum number of bulletins to download.
        force_refresh: If True, bypass the cache and download fresh data.
        strict: As in :func:`parse_tables_workbook`.

    Returns:
        Tidy DataFrame spanning every year covered by those bulletins.

    Raises:
        PPSDataNotFoundError: If no bulletin could be parsed.
        PPSDataError: If any bulletin's workbook fails to parse.

    Example:
        >>> df = get_historical_data("hate_crime", max_publications=2)
        >>> df["financial_year"].nunique() >= 2
        True
    """
    _check_series(series)
    publications = [p for p in list_publications(series, force_refresh=force_refresh) if p["kind"] == "bulletin"]

    def fetch_one(publication: dict) -> pd.DataFrame:
        url = find_tables_workbook(publication["url"], force_refresh=force_refresh)
        return parse_tables_workbook(download_file(url, force_refresh=force_refresh), series, strict=strict)

    try:
        return stitch_publications(
            publications[:max_publications],
            fetch_one,
            dedup_keys=["table", "financial_year", "dimension", "category", "breakdown", "parent"],
            sort_keys=["year", "table", "category", "breakdown"],
            errors=(),
            sort_kind="stable",
        )
    except ValueError as e:
        raise PPSDataNotFoundError("No bulletins could be parsed") from e


def list_tables(series: str, force_refresh: bool = False) -> list[str]:
    """List the table keys available in the latest bulletin of a series.

    Args:
        series: ``"sexual_offences"`` or ``"hate_crime"``.
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Sorted list of table keys, e.g. ``["hate_crime:1a", "hate_crime:1b", ...]``.

    Example:
        >>> "hate_crime:3a" in list_tables("hate_crime")
        True
    """
    return sorted(get_latest_data(series, force_refresh=force_refresh)["table"].unique())


def validate_data(df: pd.DataFrame, min_records: int = 50) -> bool:
    """Validate a parsed thematic bulletin DataFrame.

    Checks structure and sanity:

    - Required columns are present and the frame is not empty.
    - There are at least ``min_records`` rows.
    - ``series`` and ``unit`` take only the published values.
    - Years are well formed and plausible (2010 onwards).
    - Counts and days are non-negative; proportions lie between 0 and 1.

    Args:
        df: DataFrame to validate.
        min_records: Minimum acceptable number of rows.

    Returns:
        True if the data passes all checks.

    Raises:
        PPSValidationError: If any validation check fails.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        Traceback (most recent call last):
        ...
        bolster.data_sources.justice.pps_statistical_bulletin.PPSValidationError: DataFrame is empty
    """
    if df is None or df.empty:
        raise PPSValidationError("DataFrame is empty")

    missing = set(_COLUMNS) - set(df.columns)
    if missing:
        raise PPSValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise PPSValidationError(f"Too few records: {len(df)} < {min_records}")

    unknown_series = set(df["series"]) - set(SERIES)
    if unknown_series:
        raise PPSValidationError(f"Unknown series: {sorted(unknown_series)}")

    unknown_units = set(df["unit"]) - {"count", "days", "proportion"}
    if unknown_units:
        raise PPSValidationError(f"Unknown units: {sorted(unknown_units)}")

    malformed = df.loc[~df["financial_year"].str.match(r"^\d{4}/\d{2}$"), "financial_year"].unique()
    if len(malformed):
        raise PPSValidationError(f"Malformed financial years: {sorted(malformed)}")

    if df["year"].min() < 2010 or df["year"].max() > 2100:
        raise PPSValidationError(f"Year range out of bounds: {df['year'].min()}-{df['year'].max()}")

    values = df["value"].dropna()
    if (values < 0).any():
        raise PPSValidationError("Negative values found in column 'value'")

    proportions = df.loc[df["unit"] == "proportion", "value"].dropna()
    if ((proportions < 0) | (proportions > 1)).any():
        raise PPSValidationError("Proportions outside 0-1 found in column 'value'")

    return True


def clear_cache() -> int:
    """Clear all cached thematic bulletin workbooks.

    Returns:
        Number of files deleted.
    """
    return _downloader.clear()
