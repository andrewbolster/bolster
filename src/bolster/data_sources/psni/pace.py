"""PSNI Police and Criminal Evidence (PACE) Order Statistics.

Provides access to annual PACE statistics for Northern Ireland, covering:
- Stop and search activity (monthly counts by reason: stolen articles, offensive
  weapons/blade or point, going equipped/prohibited articles, fireworks)
- Arrests under PACE by quarter, gender, and whether a solicitor or friend/relative
  was requested during detention

Each annual Excel workbook covers a single financial year (April–March) and is
published by PSNI Statistics Branch each May on the PSNI publications index:

    https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-and-criminal-evidence-pace-order

**URL discovery note**: The PSNI publications index page is protected by Cloudflare
and cannot be scraped programmatically. Direct asset URLs at ``/sites/default/files/``
*can* be fetched with a browser-like ``User-Agent`` + ``Referer`` header, but the
filename portion of the URL is not predictable (includes the year in ``YYYY.YY``
format and may include a revision suffix such as ``a2``).

The :data:`PACE_URLS` dict therefore hard-codes confirmed download URLs. It should
be updated each May when PSNI publishes the new edition. Use
:func:`get_latest_pace_url` to retrieve the most recent known URL.

Data Source:
    PSNI Statistics Branch
    https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-and-criminal-evidence-pace-order

Update Frequency: Annual (published each May)
Geographic Coverage: Northern Ireland (NI-wide aggregate)
Time Coverage: One financial year per workbook; ``PACE_URLS`` spans 2024/25–2025/26

Example:
    >>> from bolster.data_sources.psni import pace
    >>> url = pace.get_latest_pace_url()
    >>> url.startswith("https://")
    True
    >>> df = pace.get_latest_pace(breakdown="stop_search")
    >>> "reason" in df.columns
    True
    >>> pace.validate_pace(df, "stop_search")
    True
"""

import logging
import re
from pathlib import Path

import pandas as pd

from ._base import PSNIValidationError, download_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known download URLs for PACE annual Excel workbooks.
#
# IMPORTANT: Update this dict each May when PSNI publishes the new edition.
# The URL filename is not predictable (year format YYYY.YY, sometimes with a
# revision suffix like ``a2``).  The direct asset URLs can be fetched with the
# browser-like headers defined in _base_http_headers.py.
# ---------------------------------------------------------------------------
PACE_URLS: dict[str, str] = {
    "2024/25": (
        "https://www.psni.police.uk/sites/default/files/2025-05/"
        "PACE%20Statistics%20Report%202024.25%20-%20Accompanying%20Spreadsheet.xlsx"
    ),
    "2025/26": (
        "https://www.psni.police.uk/sites/default/files/2026-05/"
        "PACE%20Statistics%20Report%202025.26%20-%20Accompanying%20Spreadsheeta2.xlsx"
    ),
}

# PSNI publications index — used as the Referer header when downloading assets
_PACE_INDEX_URL = (
    "https://www.psni.police.uk/about-us/our-publications-and-reports/"
    "official-statistics/police-and-criminal-evidence-pace-order"
)

# Cache TTL: annual publication, so refresh roughly annually
_CACHE_TTL_HOURS = 24 * 365

# Month abbreviations in the order they appear across the financial year (Apr–Mar)
_MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]

# Human-readable reason labels as they appear in column 0 of the spreadsheet
# (after forward-filling the merged cells in the source)
_STOP_SEARCH_REASONS = {
    "Stolen Property / Articles": "Stolen Articles",
    "Offensive Weapon / Blade or Point": "Offensive Weapon / Blade or Point",
    "Going Equipped / Prohibited Articles": "Going Equipped / Prohibited Articles",
    "Fireworks": "Fireworks",
    "Total": "Total",
}

# Row indices (0-based from the sheet start) for Table 1 data rows.
# Row 11 in the sheet is the month header row; data starts at row 12.
# Using positional constants avoids fragile header detection.
_T1_HEADER_ROW = 10  # 0-indexed row 10 = sheet row 11 (month names)
_T1_DATA_START = 11  # sheet row 12
_T1_DATA_END = 21  # sheet row 21 (inclusive): last data row before footnotes

# Table 2 starts at sheet row 31 (0-indexed 30)
_T2_DATA_START = 30  # sheet rows 31–35 (Q1–Q4 + Total)
_T2_DATA_END = 35  # exclusive


def get_latest_pace_url() -> str:
    """Return the download URL for the most recent known PACE annual workbook.

    The URL is drawn from :data:`PACE_URLS`. Update that dict each May when
    PSNI publishes a new edition.

    Returns:
        Direct download URL for the latest PACE Excel workbook.

    Example:
        >>> from bolster.data_sources.psni.pace import get_latest_pace_url
        >>> url = get_latest_pace_url()
        >>> url.startswith("https://www.psni.police.uk/")
        True
    """
    latest_year = sorted(PACE_URLS.keys())[-1]
    return PACE_URLS[latest_year]


def _extract_financial_year(file_path: Path) -> str:
    """Extract the financial year string from the spreadsheet header row.

    Reads the cell at (row 4, col A) which contains text like
    ``"Accompanying spreadsheet for statistics covering the period 2025/26 …"``
    and extracts the ``YYYY/YY`` portion.

    Falls back to ``"unknown"`` if the pattern is not found.

    Args:
        file_path: Local path to the downloaded Excel workbook.

    Returns:
        Financial year string, e.g. ``"2025/26"``.
    """
    df_raw = pd.read_excel(file_path, sheet_name="Statistical_Tables", header=None, nrows=5)
    header_text = str(df_raw.iloc[3, 0])  # Row 4 (0-indexed 3)
    match = re.search(r"(\d{4}/\d{2})", header_text)
    return match.group(1) if match else "unknown"


def parse_stop_search(file_path: Path | str) -> pd.DataFrame:
    """Parse Table 1 (monthly stop & search counts) from a PACE Excel workbook.

    The table covers stop and search activity for a single financial year,
    broken down by month (Apr–Mar) and search reason.

    Args:
        file_path: Local path to the downloaded PACE Excel workbook.

    Returns:
        DataFrame with columns:
        - ``financial_year``: e.g. ``"2025/26"``
        - ``year``: int, start year of financial year (e.g. ``2025``)
        - ``month``: month abbreviation, e.g. ``"Apr"``
        - ``reason``: search reason category
        - ``metric``: ``"Searches"`` or ``"Arrests"``
        - ``count``: integer count

    Raises:
        PSNIValidationError: If the expected table structure is not found.

    Example:
        >>> import tempfile, pathlib
        >>> df = parse_stop_search("/tmp/pace_2025_26.xlsx")  # doctest: +SKIP
        >>> list(df.columns)  # doctest: +SKIP
        ['financial_year', 'year', 'month', 'reason', 'metric', 'count']
    """
    file_path = Path(file_path)
    financial_year = _extract_financial_year(file_path)
    year = int(financial_year.split("/")[0]) if "/" in financial_year else 0

    df_raw = pd.read_excel(file_path, sheet_name="Statistical_Tables", header=None)

    # Find the row containing the month abbreviation "Apr" to locate table start
    t1_header_idx = None
    for idx, row in df_raw.iterrows():
        if row[2] == "Apr":
            t1_header_idx = idx
            break

    if t1_header_idx is None:
        raise PSNIValidationError("Could not locate stop & search table header row (expected 'Apr' in column C)")

    # Data rows immediately follow the header
    data_rows = df_raw.iloc[t1_header_idx + 1 : t1_header_idx + 11]

    records = []
    current_reason = None

    for _, row in data_rows.iterrows():
        # Column A (idx 0): reason label (may be None for continuation rows)
        reason_raw = row[0]
        metric_raw = str(row[1]) if row[1] is not None else ""

        if reason_raw is not None and str(reason_raw).strip():
            current_reason = _STOP_SEARCH_REASONS.get(str(reason_raw).strip(), str(reason_raw).strip())

        if current_reason is None:
            continue

        # Normalise metric label: strip footnote markers like (1), (2), (1,2)
        metric = re.sub(r"\s*\(\d[,\d]*\)", "", metric_raw).strip()
        if metric not in ("Searches", "Arrests"):
            continue

        # Columns C–N (indices 2–13) hold Apr–Mar monthly counts
        for col_idx, month in enumerate(_MONTHS, start=2):
            val = row[col_idx]
            count = int(val) if pd.notna(val) else 0
            records.append(
                {
                    "financial_year": financial_year,
                    "year": year,
                    "month": month,
                    "reason": current_reason,
                    "metric": metric,
                    "count": count,
                }
            )

    df = pd.DataFrame(records)
    if df.empty:
        raise PSNIValidationError("No stop & search data rows were parsed from the workbook")

    df["count"] = df["count"].astype(int)
    df["year"] = df["year"].astype(int)
    df["financial_year"] = df["financial_year"].astype("category")
    df["month"] = pd.Categorical(df["month"], categories=_MONTHS, ordered=True)
    df["reason"] = df["reason"].astype("category")
    df["metric"] = df["metric"].astype("category")

    logger.info(f"Parsed {len(df)} stop & search records for {financial_year}")
    return df


def parse_arrests(file_path: Path | str) -> pd.DataFrame:
    """Parse Table 2 (quarterly PACE arrests) from a PACE Excel workbook.

    The table covers arrests under PACE for a single financial year, broken
    down by quarter and category (total, male, female, unknown/other, and
    whether a solicitor or friend/relative was requested during detention).

    Args:
        file_path: Local path to the downloaded PACE Excel workbook.

    Returns:
        DataFrame with columns:
        - ``financial_year``: e.g. ``"2025/26"``
        - ``year``: int, start year of financial year (e.g. ``2025``)
        - ``quarter``: quarter label, e.g. ``"Q1 (Apr–Jun)"``
        - ``category``: demographic/request category
        - ``count``: integer count

    Raises:
        PSNIValidationError: If the expected table structure is not found.

    Example:
        >>> df = parse_arrests("/tmp/pace_2025_26.xlsx")  # doctest: +SKIP
        >>> list(df.columns)  # doctest: +SKIP
        ['financial_year', 'year', 'quarter', 'category', 'count']
    """
    file_path = Path(file_path)
    financial_year = _extract_financial_year(file_path)
    year = int(financial_year.split("/")[0]) if "/" in financial_year else 0

    df_raw = pd.read_excel(file_path, sheet_name="Statistical_Tables", header=None)

    # Find the row containing a quarter label like "April 25 – June 25"
    # which is the first data row of Table 2.
    t2_data_start = None
    for idx, row in df_raw.iterrows():
        cell = str(row[0]) if row[0] is not None else ""
        # Quarter data rows start with a month name + year span, e.g. "April 25 – June 25"
        if re.match(r"(April|July|October|January)\s+\d{2}", cell):
            t2_data_start = idx
            break

    if t2_data_start is None:
        raise PSNIValidationError("Could not locate arrests table data rows (expected quarter label in column A)")

    # Collect up to 5 rows: Q1, Q2, Q3, Q4, Total
    data_rows = df_raw.iloc[t2_data_start : t2_data_start + 5]

    # Categories correspond to column indices 1, 2, 3, 4, 6, 7
    # Col 1: Total, Col 2: Male, Col 3: Female, Col 4: Unknown/Other
    # Col 6: Friend/relative, Col 7: Solicitor
    category_cols = {
        1: "Total",
        2: "Male",
        3: "Female",
        4: "Unknown / Other",
        6: "Requested friend / relative",
        7: "Requested solicitor",
    }

    # Quarter labels: map from source row labels to standardised short labels
    quarter_labels = ["Q1 (Apr–Jun)", "Q2 (Jul–Sep)", "Q3 (Oct–Dec)", "Q4 (Jan–Mar)", "Annual Total"]

    records = []
    for row_pos, (_, row) in enumerate(data_rows.iterrows()):
        if row_pos >= len(quarter_labels):
            break
        quarter = quarter_labels[row_pos]
        for col_idx, category in category_cols.items():
            val = row[col_idx]
            count = int(val) if pd.notna(val) and val != "" else 0
            records.append(
                {
                    "financial_year": financial_year,
                    "year": year,
                    "quarter": quarter,
                    "category": category,
                    "count": count,
                }
            )

    df = pd.DataFrame(records)
    if df.empty:
        raise PSNIValidationError("No arrests data rows were parsed from the workbook")

    df["count"] = df["count"].astype(int)
    df["year"] = df["year"].astype(int)
    df["financial_year"] = df["financial_year"].astype("category")
    _quarter_order = ["Q1 (Apr–Jun)", "Q2 (Jul–Sep)", "Q3 (Oct–Dec)", "Q4 (Jan–Mar)", "Annual Total"]
    df["quarter"] = pd.Categorical(df["quarter"], categories=_quarter_order, ordered=True)
    df["category"] = df["category"].astype("category")

    logger.info(f"Parsed {len(df)} arrests records for {financial_year}")
    return df


def get_latest_pace(breakdown: str = "stop_search", force_refresh: bool = False) -> pd.DataFrame:
    """Download and return the latest PACE statistics.

    Downloads the most recent PACE Excel workbook (from :data:`PACE_URLS`),
    caches it locally for one year, and returns either the stop & search or
    the arrests breakdown.

    Args:
        breakdown: Which table to return — ``"stop_search"`` (Table 1, monthly
            stop & search counts) or ``"arrests"`` (Table 2, quarterly arrest
            demographics). Default: ``"stop_search"``.
        force_refresh: If ``True``, bypass the cache and re-download. Default:
            ``False``.

    Returns:
        DataFrame — see :func:`parse_stop_search` or :func:`parse_arrests` for
        column descriptions.

    Raises:
        ValueError: If ``breakdown`` is not ``"stop_search"`` or ``"arrests"``.
        PSNIDataNotFoundError: If the download fails.
        PSNIValidationError: If the workbook structure is not as expected.

    Example:
        >>> df = get_latest_pace(breakdown="stop_search")  # doctest: +SKIP
        >>> "reason" in df.columns
        True
        >>> df = get_latest_pace(breakdown="arrests")  # doctest: +SKIP
        >>> "category" in df.columns
        True
    """
    if breakdown not in ("stop_search", "arrests"):
        raise ValueError(f"breakdown must be 'stop_search' or 'arrests', got {breakdown!r}")

    url = get_latest_pace_url()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": _PACE_INDEX_URL,
    }

    file_path = download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh, headers=headers)

    if breakdown == "stop_search":
        return parse_stop_search(file_path)
    return parse_arrests(file_path)


def validate_pace(df: pd.DataFrame, breakdown: str) -> bool:
    """Validate a PACE DataFrame for structural integrity.

    Checks that the DataFrame has the required columns and contains at least
    some data.

    Args:
        df: DataFrame returned by :func:`parse_stop_search` or
            :func:`parse_arrests`.
        breakdown: ``"stop_search"`` or ``"arrests"`` — selects the expected
            column set.

    Returns:
        ``True`` if the DataFrame passes all checks.

    Raises:
        PSNIValidationError: If any check fails (empty DataFrame, missing
            columns, non-positive counts).

    Example:
        >>> import pandas as pd
        >>> from bolster.data_sources.psni.pace import validate_pace, PSNIValidationError
        >>> validate_pace(pd.DataFrame(), "stop_search")
        Traceback (most recent call last):
            ...
        bolster.data_sources.psni._base.PSNIValidationError: PACE DataFrame is empty
    """
    if df.empty:
        raise PSNIValidationError("PACE DataFrame is empty")

    required_columns: dict[str, list[str]] = {
        "stop_search": ["financial_year", "year", "month", "reason", "metric", "count"],
        "arrests": ["financial_year", "year", "quarter", "category", "count"],
    }

    if breakdown not in required_columns:
        raise PSNIValidationError(f"Unknown breakdown {breakdown!r}; expected 'stop_search' or 'arrests'")

    missing = [c for c in required_columns[breakdown] if c not in df.columns]
    if missing:
        raise PSNIValidationError(f"PACE DataFrame missing required columns: {missing}")

    if (df["count"] < 0).any():
        raise PSNIValidationError("PACE DataFrame contains negative counts")

    return True
