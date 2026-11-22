"""Shared readers for the BSO Family Practitioner Services (FPS) statistics.

The Business Services Organisation publishes General Ophthalmic Services and
General Dental Services statistics (and, in a different layout,
:mod:`~bolster.data_sources.health_ni.gms`) through GOV.UK. Each quarterly
release carries one tables workbook with the same shape: a cover sheet, a table
of contents, numbered data sheets, a notes sheet and a user-guidance sheet.
Data sheets hold either one table or several tables stacked under ``Table 2.1a:``
marker rows, with ``Quarter N YYYY/YY`` columns, and the newest workbook carries
the whole history.

The annual series for the same services are in PxStat, in one cube per
geography with the Northern Ireland total as a row of the same cube.

This module holds what the two service modules share:

- :func:`parse_quarterly_workbook` -- every data sheet as one long frame, with
  the quarter columns parsed into ``period``, ``financial_year`` and ``quarter``.
- :func:`quarterly_series` -- pick tables out of that frame by their *title*.
  Table numbers drift between editions (practices were ``12.1`` and ``12.2`` and
  are now ``13.1`` and ``13.2``), so numbers are never used to find a table.
- :func:`read_annual_cube` -- an annual PxStat cube as a tidy frame.
"""

import datetime
import logging
import re
from collections.abc import Sequence

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

from ._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    excel_sheet_rows,
    parse_stacked_tables,
    strip_note_refs,
)

logger = logging.getLogger(__name__)

NORTHERN_IRELAND = "Northern Ireland"

_EXCLUDED_SHEETS = {"cover sheet", "table of contents", "notes", "user guidance"}

_QUARTER_COLUMN_RE = re.compile(r"^Quarter\s+([1-4])\s+(\d{4})/(\d{2})$")
_QUARTER_END = {1: (6, 30, 0), 2: (9, 30, 0), 3: (12, 31, 0), 4: (3, 31, 1)}

# "Table 2.2: Sight Tests by ..." on the first row of every data sheet.
_SHEET_TITLE_RE = re.compile(r"^Table\s*([\d.]+)\s*[:\-–]\s*(.+)$")
_TABLE_PREFIX_RE = re.compile(r"^Table\s*[\d.]+[A-Za-z]?\s*[:\-–]\s*")

# Geography of a table, from its title. Order matters: the first match wins.
_LEVEL_PATTERNS = (
    ("age_sex", re.compile(r"\bby Gender, Age Group\b", re.IGNORECASE)),
    ("trust", re.compile(r"\bby Local Commissioning Group\b", re.IGNORECASE)),
    ("lgd", re.compile(r"\bby Local Government District\b", re.IGNORECASE)),
    ("assembly_area", re.compile(r"\bby Assembly Area\b", re.IGNORECASE)),
)

# PxStat cubes are published once per geography; the cube code ends in one of these.
ANNUAL_GEOGRAPHY_SUFFIX = {"trust": "HSCT", "lgd": "LGD", "assembly_area": "AA", "dea": "DEA"}
_ANNUAL_GEOGRAPHY_COLUMN = {"trust": "HSCT", "lgd": "LGD2014", "assembly_area": "AA", "dea": "DEA2014"}

GEOGRAPHY_LEVELS = ("trust", "lgd", "assembly_area")


def parse_quarter_label(label: str) -> tuple[str, int, datetime.date] | None:
    """Parse a ``"Quarter 2 2026/27"`` column label.

    Args:
        label: A column heading.

    Returns:
        ``(financial_year, quarter, period_end)`` such as
        ``("2026/27", 2, date(2026, 9, 30))``, or ``None`` if the heading
        is not a quarter label.
    """
    match = _QUARTER_COLUMN_RE.match(strip_note_refs(label).strip())
    if not match:
        return None
    quarter, start_year = int(match.group(1)), int(match.group(2))
    month, day, year_offset = _QUARTER_END[quarter]
    financial_year = f"{start_year}/{(start_year + 1) % 100:02d}"
    return financial_year, quarter, datetime.date(start_year + year_offset, month, day)


def core_title(title: str) -> str:
    """Return a table title without its ``Table N.M:`` prefix and ``[note N]`` references.

    Args:
        title: A sheet or table title as published.

    Returns:
        The descriptive part, e.g. ``"Sight Tests by Local Commissioning Group (Health Trust) and Financial Quarter"``.
    """
    return " ".join(_TABLE_PREFIX_RE.sub("", strip_note_refs(title)).split())


def table_level(title: str) -> str | None:
    """Classify a table title by the geography it is broken down by.

    Args:
        title: A sheet title such as ``"Table 2.2: Sight Tests by Local Government District ..."``.

    Returns:
        ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"age_sex"`` (gender and age group), or
        ``None`` for any other layout (national series, monthly payment tables).
    """
    for level, pattern in _LEVEL_PATTERNS:
        if pattern.search(title):
            return level
    return None


def _sheet_title(rows: list[list[str]]) -> str | None:
    for row in rows[:6]:
        if len(row) == 1:
            match = _SHEET_TITLE_RE.match(row[0])
            if match:
                return strip_note_refs(match.group(2)).strip()
    return None


def is_provisional(workbook: pd.ExcelFile) -> bool:
    """Say whether the workbook's cover sheet marks the quarterly series provisional.

    Args:
        workbook: An open FPS tables workbook.

    Returns:
        ``True`` if the cover sheet contains the word "provisional" (for example
        "Quarterly Series to Q2 2026/27 - Provisional"); ``False`` if there is no such
        marker or no cover sheet.
    """
    for name in workbook.sheet_names:
        if name.strip().lower() == "cover sheet":
            text = " ".join(" ".join(row) for row in excel_sheet_rows(workbook, name))
            return "provisional" in text.lower()
    return False


def parse_quarterly_workbook(workbook: pd.ExcelFile) -> pd.DataFrame:
    """Parse every data sheet of an FPS quarterly tables workbook into one long frame.

    Handles sheets holding one table and sheets holding several tables stacked
    under ``Table 2.1a:`` marker rows. A sheet that holds no table (a cover, contents
    or notes sheet) is skipped.

    Args:
        workbook: An open FPS tables workbook.

    Returns:
        DataFrame with ``sheet``, ``sheet_title``, ``table_id``, ``table_title``, ``row_group``,
        ``row_label``, ``column``, ``value`` and ``provisional`` columns. For columns that are
        quarter labels, ``financial_year`` (``"2026/27"``), ``quarter`` (1-4) and ``period``
        (the quarter's last day) are filled; they are empty for other layouts. ``provisional``
        is the cover sheet's marker for the whole series (see :func:`is_provisional`).

    Raises:
        NISRADataNotFoundError: If no sheet holds a table.
    """
    provisional = is_provisional(workbook)
    frames = []
    for sheet_name in workbook.sheet_names:
        if sheet_name.strip().lower() in _EXCLUDED_SHEETS:
            continue
        rows = excel_sheet_rows(workbook, sheet_name, strip_scroll_hint=True)
        try:
            frame = parse_stacked_tables(rows)
        except NISRADataNotFoundError:
            logger.debug("Sheet %r holds no table", sheet_name)
            continue
        frame["sheet"] = sheet_name
        frame["sheet_title"] = _sheet_title(rows)
        frames.append(frame)

    if not frames:
        raise NISRADataNotFoundError("No data tables found in the FPS quarterly workbook")

    out = pd.concat(frames, ignore_index=True)
    parsed = out["column"].map(parse_quarter_label)
    out["financial_year"] = parsed.map(lambda p: p[0] if p else None)
    out["quarter"] = parsed.map(lambda p: p[1] if p else None).astype("Int64")
    out["period"] = pd.to_datetime(parsed.map(lambda p: p[2] if p else None))
    out["provisional"] = provisional
    return out


def quarterly_series(
    df: pd.DataFrame,
    *,
    title_pattern: str,
    level: str | None,
    area_column: str | None = None,
) -> pd.DataFrame:
    r"""Pick the quarter-by-quarter table whose title matches, as a tidy series.

    Tables are found by title and geography, never by table number.

    Args:
        df: Frame from :func:`parse_quarterly_workbook`.
        title_pattern: Regex matched (case-insensitively, from the start) against the table's
            descriptive title, e.g. ``r"(Number of )?Sight Tests\b"``.
        level: Geography the table is broken down by (see :func:`table_level`), or ``None``
            for a table with no geography.
        area_column: Name for the column holding the row labels (default: the level, or
            ``"label"`` when there is none).

    Returns:
        DataFrame with ``period``, ``financial_year``, ``quarter``, the area column, ``value``,
        ``is_total`` (True for the Northern Ireland total row) and ``provisional``; for the
        gender-and-age tables also ``sex`` and ``age_group``. Sorted by period then area.

    Raises:
        NISRADataNotFoundError: If no table matches, naming the pattern and level.
    """
    pattern = re.compile(title_pattern, re.IGNORECASE)
    mask = df["period"].notna() & df["sheet_title"].map(
        lambda title: bool(title) and bool(pattern.match(core_title(title))) and table_level(title) == level
    )
    picked = df[mask]
    if picked.empty:
        raise NISRADataNotFoundError(
            f"No quarterly table with title matching {title_pattern!r} and level {level!r} found"
        )

    name = area_column or (level if level and level != "age_sex" else "label")
    out = pd.DataFrame(
        {
            "period": picked["period"],
            "financial_year": picked["financial_year"],
            "quarter": picked["quarter"],
            name: picked["row_label"],
            "value": picked["value"],
            "is_total": picked["row_label"].eq(NORTHERN_IRELAND),
            "provisional": picked["provisional"],
        }
    )
    if level == "age_sex":
        out = out.drop(columns=[name, "is_total"])
        out.insert(3, "sex", picked["table_title"].map(_sex_from_table_title))
        out.insert(4, "age_group", picked["row_label"])
        out["is_total"] = picked["row_label"].eq("Total")
    return out.sort_values(["period", out.columns[3]], kind="stable").reset_index(drop=True)


_SEX_RE = re.compile(r"\b(Females?|Males?|Unknown/Missing Gender|Unknown|All Persons)\b", re.IGNORECASE)
_SEX_NAMES = {
    "male": "Male",
    "males": "Male",
    "female": "Female",
    "females": "Female",
    "unknown/missing gender": "Unknown",
    "unknown": "Unknown",
    "all persons": "All",
}


def _sex_from_table_title(title: str) -> str:
    """Read the sex out of a gender sub-table title.

    The two services word it differently: ``"Male Sight Tests by Age Group ..."`` and
    ``"Fillings for Males by Age Group ..."``. Returns ``"Male"``, ``"Female"``, ``"Unknown"``
    (published as "Unknown/Missing Gender") or ``"All"`` (published as "All Persons"). A title
    with none of these is returned unchanged, so a new category shows up in the data instead
    of being relabelled.
    """
    text = core_title(title)
    match = _SEX_RE.search(text)
    return _SEX_NAMES[match.group(1).lower()] if match else text


def read_annual_cube(code_prefix: str, level: str) -> pd.DataFrame:
    """Read one annual PxStat cube (one cube per geography) as a tidy frame.

    Args:
        code_prefix: The cube code without its geography suffix, e.g. ``"FPSGOSOT"``.
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame with ``financial_year``, ``period`` (31 March ending the year), ``area_code``,
        the geography column named after ``level``, ``measure``, any extra breakdown the cube has
        (for example ``age_group``), ``value`` and ``is_total`` (True for the Northern Ireland row).

    Raises:
        ValueError: If ``level`` is not one of the supported geographies.
        NISRAValidationError: If the cube does not have the expected columns.
    """
    if level not in ANNUAL_GEOGRAPHY_SUFFIX:
        raise ValueError(f"Unknown geography level {level!r}; choose from {sorted(ANNUAL_GEOGRAPHY_SUFFIX)}")
    code = f"{code_prefix}{ANNUAL_GEOGRAPHY_SUFFIX[level]}"
    raw = read_dataset(code)

    code_column = _ANNUAL_GEOGRAPHY_COLUMN[level]
    year_columns = [c for c in raw.columns if c.lower() == "financial year"]
    if code_column not in raw.columns or not year_columns:
        raise NISRAValidationError(f"PxStat cube {code} does not have the expected columns: {list(raw.columns)}")
    label_column = raw.columns[list(raw.columns).index(code_column) + 1]

    out = pd.DataFrame(
        {
            "financial_year": raw[year_columns[0]],
            "area_code": raw[code_column],
            level: raw[label_column],
            "measure": raw["Statistic Label"],
        }
    )
    if "Age Label" in raw.columns:
        out["age_group"] = raw["Age Label"]
    out["value"] = pd.to_numeric(raw["VALUE"], errors="coerce")
    out["period"] = pd.to_datetime((out["financial_year"].str.slice(0, 4).astype(int) + 1).astype(str) + "-03-31")
    out["is_total"] = out[level].eq(NORTHERN_IRELAND)
    first = ["financial_year", "period", "area_code", level, "measure"]
    return out[first + [c for c in out.columns if c not in first]].reset_index(drop=True)


def unallocated(df: pd.DataFrame, *, level: str, by: Sequence[str]) -> pd.DataFrame:
    """Work out what is in the Northern Ireland total but in none of its areas.

    Some activity has no recorded area, so a geography frame's areas add up to less than its
    Northern Ireland row. This returns the gap, per group.

    Args:
        df: A tidy frame with ``is_total`` and ``value`` columns, such as
            :func:`read_annual_cube` or :func:`quarterly_series` return.
        level: Name of the geography column (used only in the error message).
        by: Columns that identify one series, e.g. ``["financial_year", "measure"]``.

    Returns:
        DataFrame with the ``by`` columns, ``total`` (the Northern Ireland row), ``area_sum``
        (every other row added) and ``unallocated`` (``total - area_sum``).

    Raises:
        NISRAValidationError: If the frame has no Northern Ireland total row.
    """
    if not df["is_total"].any():
        raise NISRAValidationError(f"No Northern Ireland total row in the {level} frame")
    total = df[df["is_total"]].groupby(list(by))["value"].sum().rename("total")
    parts = df[~df["is_total"]].groupby(list(by))["value"].sum().rename("area_sum")
    out = pd.concat([total, parts], axis=1).reset_index()
    out["unallocated"] = out["total"] - out["area_sum"]
    return out


def validate_series(df: pd.DataFrame, *, label: str, required: Sequence[str] = ("period", "value")) -> bool:
    """Check that a tidy FPS frame is structurally sound.

    Args:
        df: A frame returned by a quarterly or annual accessor.
        label: Name of the series, for error messages.
        required: Columns that must be present.

    Returns:
        True if every check passes.

    Raises:
        NISRAValidationError: If the frame is empty, a required column is missing, or a count is negative.
    """
    if df.empty:
        raise NISRAValidationError(f"{label} data is empty")
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise NISRAValidationError(f"{label} data is missing columns: {missing}")
    values = pd.to_numeric(df["value"], errors="coerce").dropna()
    if (values < 0).any():
        raise NISRAValidationError(f"{label} data contains negative values")
    return True
