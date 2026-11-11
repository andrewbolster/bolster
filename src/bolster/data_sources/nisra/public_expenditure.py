"""NISRA Public Expenditure (NI Executive Spending) Data Source.

Published as: NI public expenditure key statistics; Northern Ireland Executive spending.

Public spending in Northern Ireland by department, spending area and expenditure
category, in financial years (April to March) and in pounds sterling (thousands).
The figures come from the Department of Finance's Public Spending Database.

Two sources are read, and they are never mixed without saying so:

- **PxStat matrix** ``PUBEXP`` holds the final outturn series (2016/17 to the latest
  final year). This is what :func:`get_latest_data` returns by default.
- **The NI Executive spending dashboard** embeds a workbook that adds the newest year,
  published as provisional outturn before PxStat catches up. :func:`get_latest_data`
  appends that year only when asked (``include_provisional=True``), and every such row
  has ``provisional=True``. If the dashboard cannot be read, or does not have the
  expected table, an error is raised; nothing else is substituted.

Expenditure categories are those of the source: ``AME Resource``, ``AME Capital``,
``Non Ringfenced Resource DEL``, ``Capital DEL`` and ``FT Capital DEL``. The table
excludes ringfenced resource DEL, resource AME depreciation and impairments, and other
AME capital, so the sum of the categories is *not* total managed expenditure. Values can
be negative (receipts and credits) and are in cash terms, not real terms.

``department`` is the label NISRA publishes. It includes the pseudo-groups ``AME``
(annually managed expenditure not allocated to a department) and ``Other``.

Original data source:
    https://www.nisra.gov.uk/statistics/business-economy-and-trade/ni-executive-spending

Update Frequency: Annual (the provisional year in autumn, final outturn the following spring)
Geographic Coverage: Northern Ireland

Example:
    >>> from bolster.data_sources.nisra import public_expenditure
    >>> df = public_expenditure.get_latest_data()
    >>> {"financial_year", "department", "spending_area", "spend_gbp_thousands"}.issubset(df.columns)
    True
    >>> len(df) > 0
    True
"""

import io
import logging
import re

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset
from bolster.utils.embedded_downloads import extract_embedded_files
from bolster.utils.excel import find_marker_row, parse_sheet
from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError

logger = logging.getLogger(__name__)

PXSTAT_MATRIX = "PUBEXP"
DASHBOARD_URL = "https://explore.nisra.gov.uk/ni-executive-spending/"

EXPENDITURE_CATEGORIES = frozenset(
    {"AME Resource", "AME Capital", "Non Ringfenced Resource DEL", "Capital DEL", "FT Capital DEL"}
)

COLUMNS = [
    "financial_year",
    "year_start",
    "department",
    "spending_area_code",
    "spending_area",
    "expenditure_category",
    "spend_gbp_thousands",
    "provisional",
]

_KEY = ["financial_year", "department", "spending_area", "expenditure_category"]

_PXSTAT_REQUIRED = {"Financial year", "SPNDAREA", "Spending area", "Expenditure category", "VALUE"}

# PxStat labels each area "<name> (<department>)".
_AREA_LABEL_RE = re.compile(r"^(?P<area>.*?)\s*\((?P<department>[^()]+)\)\s*$")

# Spelling differences between the two publications, corrected so an area keeps one name across years.
_LABEL_FIXES = {"accomodation": "accommodation"}

_YEAR_RE = re.compile(r"^(\d{4})[-/](\d{2})$")
_PROVISIONAL_NOTE_RE = re.compile(r"(\d{4})[-/](\d{2})\s+data\s+is\s+based\s+on\s+provisional", re.IGNORECASE)
_DETAIL_SHEET_TITLE = "more detailed data"
_DASHBOARD_COLUMNS = {
    "Department": "department",
    "Spending Area": "spending_area",
    "Expenditure Category": "expenditure_category",
    "Year": "financial_year",
    "Spend (£000s)": "spend_gbp_thousands",
}


def _fix_label(label: str) -> str:
    for wrong, right in _LABEL_FIXES.items():
        label = label.replace(wrong, right)
    return label


def _split_area_label(label: str) -> tuple[str, str]:
    """Split a PxStat spending area label into ``(area, department)``.

    Args:
        label: A label such as ``"Hospital services (DoH)"``.

    Returns:
        The spending area name (spelling corrected) and its department.

    Raises:
        NISRAValidationError: If the label has no trailing ``(department)``.

    Example:
        >>> _split_area_label("Hospital services (DoH)")
        ('Hospital services', 'DoH')
    """
    match = _AREA_LABEL_RE.match(label)
    if match is None:
        raise NISRAValidationError(f"PUBEXP spending area label has no '(department)' suffix: {label!r}")
    return _fix_label(match.group("area").strip()), match.group("department").strip()


def _normalise_year(value: object) -> tuple[str, int]:
    """Return ``("2025/26", 2025)`` for ``"2025-26"`` or ``"2025/26"``.

    Raises:
        NISRAValidationError: If the value is not a two-year financial year label.
    """
    match = _YEAR_RE.match(str(value).strip())
    if match is None:
        raise NISRAValidationError(f"Unrecognised financial year label: {value!r}")
    start = int(match.group(1))
    if (start + 1) % 100 != int(match.group(2)):
        raise NISRAValidationError(f"Financial year label does not span consecutive years: {value!r}")
    return f"{start}/{match.group(2)}", start


def _read_pxstat() -> pd.DataFrame:
    """Read the final-outturn series from PxStat, dropping cells with no published value."""
    raw = read_dataset(PXSTAT_MATRIX)
    missing = _PXSTAT_REQUIRED - set(raw.columns)
    if missing:
        raise NISRAValidationError(f"PxStat matrix {PXSTAT_MATRIX} is missing columns: {sorted(missing)}")

    published = raw[raw["VALUE"].notna()]
    split = {label: _split_area_label(label) for label in published["Spending area"].unique()}
    years = {value: _normalise_year(value) for value in published["Financial year"].unique()}

    frame = pd.DataFrame(
        {
            "financial_year": [years[v][0] for v in published["Financial year"]],
            "year_start": [years[v][1] for v in published["Financial year"]],
            "department": [split[v][1] for v in published["Spending area"]],
            "spending_area_code": published["SPNDAREA"].astype(str).to_numpy(),
            "spending_area": [split[v][0] for v in published["Spending area"]],
            "expenditure_category": published["Expenditure category"].astype(str).to_numpy(),
            "spend_gbp_thousands": published["VALUE"].astype(float).to_numpy(),
            "provisional": False,
        }
    )
    return frame[COLUMNS]


def _find_detail_sheet(workbook: pd.ExcelFile) -> pd.DataFrame:
    """Return the raw ``Table N: More detailed data`` sheet, found by its title and not its position."""
    for name in workbook.sheet_names:
        raw = parse_sheet(workbook, str(name), header=None)
        if raw.empty:
            continue
        title = str(raw.iat[0, 0]).strip().lower()
        if title.startswith("table") and _DETAIL_SHEET_TITLE in title:
            return raw
    raise NISRADataNotFoundError(
        f"The NI Executive spending workbook at {DASHBOARD_URL} has no table titled "
        f"'{_DETAIL_SHEET_TITLE}' (spending area by expenditure category by year)"
    )


def _provisional_year(raw: pd.DataFrame, header_row: int) -> int | None:
    """Return the start year the workbook's notes call provisional outturn, if it names one."""
    for value in raw.iloc[:header_row, 0].dropna():
        match = _PROVISIONAL_NOTE_RE.search(str(value))
        if match:
            return int(match.group(1))
    return None


def _read_dashboard_workbook(force_refresh: bool = False) -> pd.DataFrame:
    """Read every year from the dashboard's embedded workbook (detail table).

    Returns:
        A frame with the published columns (no area code), ``provisional`` set for the year the
        workbook's notes call provisional.

    Raises:
        NISRADataNotFoundError: If the page has no embedded workbook, the detail table, or a column.
        NISRAValidationError: If a year label or a value cannot be read.
    """
    response = session.get(DASHBOARD_URL, timeout=90, force_refresh=force_refresh)
    response.raise_for_status()
    workbooks = [f for f in extract_embedded_files(response.text) if f.kind == "xlsx"]
    if not workbooks:
        raise NISRADataNotFoundError(f"No embedded workbook found on {DASHBOARD_URL}")

    raw = _find_detail_sheet(pd.ExcelFile(io.BytesIO(workbooks[0].content)))
    header_row = find_marker_row(raw, lambda v: str(v).strip() == "Department", max_rows=20)
    if header_row is None:
        raise NISRADataNotFoundError(
            "The detail table of the NI Executive spending workbook has no 'Department' header"
        )

    headers = [str(v).strip() for v in raw.iloc[header_row]]
    missing = [name for name in _DASHBOARD_COLUMNS if name not in headers]
    if missing:
        raise NISRADataNotFoundError(f"The detail table of the NI Executive spending workbook lacks columns: {missing}")

    body = raw.iloc[header_row + 1 :].copy()
    body.columns = pd.Index(headers)
    body = body[list(_DASHBOARD_COLUMNS)].rename(columns=_DASHBOARD_COLUMNS).dropna(subset=["financial_year"])

    years = {value: _normalise_year(value) for value in body["financial_year"].unique()}
    values = pd.to_numeric(body["spend_gbp_thousands"], errors="coerce")
    if values.isna().any():
        raise NISRAValidationError(f"{int(values.isna().sum())} spend values in the workbook are not numeric")

    provisional_start = _provisional_year(raw, header_row)
    frame = pd.DataFrame(
        {
            "financial_year": [years[v][0] for v in body["financial_year"]],
            "year_start": [years[v][1] for v in body["financial_year"]],
            "department": body["department"].astype(str).str.strip().to_numpy(),
            "spending_area": [_fix_label(str(v).strip()) for v in body["spending_area"]],
            "expenditure_category": body["expenditure_category"].astype(str).str.strip().to_numpy(),
            "spend_gbp_thousands": values.astype(float).to_numpy(),
            "provisional": [years[v][1] == provisional_start for v in body["financial_year"]],
        }
    )
    return frame.reset_index(drop=True)


def _provisional_rows(final: pd.DataFrame, force_refresh: bool = False) -> pd.DataFrame:
    """Provisional rows from the dashboard for a year PxStat does not yet hold, with area codes where known."""
    dashboard = _read_dashboard_workbook(force_refresh=force_refresh)
    new = dashboard[dashboard["provisional"] & ~dashboard["financial_year"].isin(final["financial_year"])]
    if new.empty:
        logger.info("The dashboard has no provisional year that PxStat does not already hold")
        return pd.DataFrame(columns=COLUMNS)

    codes = final.drop_duplicates(["department", "spending_area"])[
        ["department", "spending_area", "spending_area_code"]
    ]
    merged = new.merge(codes, on=["department", "spending_area"], how="left")
    unmatched = merged[merged["spending_area_code"].isna()][["department", "spending_area"]].drop_duplicates()
    if not unmatched.empty:
        logger.info(
            "%d provisional spending areas have no PxStat code (new this year): %s",
            len(unmatched),
            ", ".join(f"{d}/{a}" for d, a in zip(unmatched["department"], unmatched["spending_area"], strict=True)),
        )
    return merged[COLUMNS]


def get_latest_data(include_provisional: bool = False, force_refresh: bool = False) -> pd.DataFrame:
    """Get public expenditure by department, spending area and expenditure category.

    Args:
        include_provisional: Also append the newest year, published as provisional outturn on
            the NI Executive spending dashboard before PxStat holds it. Its rows have
            ``provisional=True`` and ``spending_area_code`` null for areas PxStat has never
            carried. When the dashboard has no such year (PxStat already holds it) nothing is added.
        force_refresh: Bypass the page cache for the dashboard. PxStat is always current.

    Returns:
        DataFrame with columns ``financial_year`` (``"2024/25"``), ``year_start`` (``2024``),
        ``department``, ``spending_area_code``, ``spending_area``, ``expenditure_category``,
        ``spend_gbp_thousands`` (cash terms, can be negative) and ``provisional``.

    Raises:
        NISRADataNotFoundError: If ``include_provisional`` is set and the dashboard workbook
            or its detail table cannot be found.
        NISRAValidationError: If the data fails validation.

    Example:
        >>> from bolster.data_sources.nisra import public_expenditure
        >>> df = public_expenditure.get_latest_data()
        >>> bool((~df["provisional"]).all())
        True
    """
    frame = _read_pxstat()
    if include_provisional:
        extra = _provisional_rows(frame, force_refresh=force_refresh)
        if not extra.empty:
            frame = pd.concat([frame, extra], ignore_index=True)
    frame = frame.sort_values(["year_start", "department", "spending_area", "expenditure_category"])
    frame = frame.reset_index(drop=True)
    validate_data(frame)
    return frame


def get_dashboard_data(force_refresh: bool = False) -> pd.DataFrame:
    """Get every year in the NI Executive spending dashboard's workbook, as published there.

    Unlike :func:`get_latest_data` this has no area codes and no PxStat involvement. It exists
    so the two publications can be reconciled (see the integrity tests).

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with columns ``financial_year``, ``year_start``, ``department``,
        ``spending_area``, ``expenditure_category``, ``spend_gbp_thousands`` and ``provisional``.

    Raises:
        NISRADataNotFoundError: If the workbook or its detail table cannot be found.
    """
    return _read_dashboard_workbook(force_refresh=force_refresh)


def get_department_totals(include_provisional: bool = False, force_refresh: bool = False) -> pd.DataFrame:
    """Total spend by department and financial year (all expenditure categories summed).

    The categories exclude some items (see the module docstring), so this is the published
    table's total, not total managed expenditure.

    Args:
        include_provisional: As for :func:`get_latest_data`.
        force_refresh: As for :func:`get_latest_data`.

    Returns:
        DataFrame with columns ``financial_year``, ``year_start``, ``department``,
        ``provisional`` and ``spend_gbp_thousands``.
    """
    data = get_latest_data(include_provisional=include_provisional, force_refresh=force_refresh)
    grouped = data.groupby(["financial_year", "year_start", "department", "provisional"], as_index=False)[
        "spend_gbp_thousands"
    ].sum()
    return grouped.sort_values(["year_start", "department"]).reset_index(drop=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a public expenditure frame.

    Checks the columns, that spend values are finite, the financial years are well formed,
    that the expenditure categories are known, that no row is duplicated, that provisional
    rows are confined to the latest year, and that only provisional rows lack an area code.
    Negative values are allowed.

    Args:
        df: A frame as returned by :func:`get_latest_data`.

    Returns:
        True if validation passes.

    Raises:
        NISRAValidationError: If any check fails.

    Example:
        >>> import pandas as pd
        >>> good = pd.DataFrame({
        ...     "financial_year": ["2024/25"], "year_start": [2024], "department": ["DoH"],
        ...     "spending_area_code": ["DoH01"], "spending_area": ["Hospital services"],
        ...     "expenditure_category": ["Capital DEL"], "spend_gbp_thousands": [1.0],
        ...     "provisional": [False],
        ... })
        >>> validate_data(good)
        True
    """
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing columns: {sorted(missing)}")
    if df.empty:
        raise NISRAValidationError("No public expenditure rows")

    spend = pd.to_numeric(df["spend_gbp_thousands"], errors="coerce")
    if not spend.notna().all() or not spend.abs().lt(float("inf")).all():
        raise NISRAValidationError("spend_gbp_thousands has missing or non-finite values")

    for label, start in zip(df["financial_year"], df["year_start"], strict=True):
        if _normalise_year(label)[1] != start:
            raise NISRAValidationError(f"year_start {start} does not match financial_year {label!r}")

    unknown = set(df["expenditure_category"]) - EXPENDITURE_CATEGORIES
    if unknown:
        raise NISRAValidationError(f"Unexpected expenditure categories: {sorted(unknown)}")

    if df.duplicated(_KEY).any():
        raise NISRAValidationError("Duplicate rows for a financial year, department, spending area and category")

    latest = df["year_start"].max()
    stray = df[df["provisional"] & (df["year_start"] != latest)]
    if not stray.empty:
        raise NISRAValidationError("Provisional rows must all be in the latest financial year")

    uncoded = df[df["spending_area_code"].isna() & ~df["provisional"]]
    if not uncoded.empty:
        raise NISRAValidationError(f"{len(uncoded)} final-outturn rows have no spending area code")
    return True
