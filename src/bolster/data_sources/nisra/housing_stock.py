"""Northern Ireland Housing Stock Statistics.

Annual housing stock statistics for Northern Ireland, published by Land and
Property Services (LPS), a division of the Department of Finance (DoF) NI.
Provides dwelling counts by property type (converted apartment, purpose built
apartment, detached, semi-detached, terrace) at LGD, Electoral Ward, and
Super Output Area level.

Note: This data is **not** available in the NISRA PxStat API. It is published
directly by DoF/LPS as Excel workbooks.

Publisher:
    Department of Finance NI (DoF) — Land and Property Services (LPS).
    This data is NOT published by NISRA directly; the source is:
    https://www.finance-ni.gov.uk/topics/housing-stock-statistics

Data files (confirmed 2026 edition):
    - LGD-level:
      https://www.finance-ni.gov.uk/sites/default/files/2026-06/Housing%20Stock%20Tables%202008%20-%202026.xlsx
    - Electoral Ward:
      https://www.finance-ni.gov.uk/sites/default/files/2026-06/Housing%20Stock%20LGD%20Ward%20Tables%202008%20-%202026.xlsx
    - Super Output Area (SOA):
      https://www.finance-ni.gov.uk/sites/default/files/2026-06/SOA%20Housing%20Stock%202008%20-%202026.xlsx

Coverage:
    Annual (April/May reference date), 2008–2026.
    Geography: 11 Local Government Districts (LGDs) + NI total.

Example:
    >>> from bolster.data_sources.nisra import housing_stock
    >>> df = housing_stock.get_latest_housing_stock(geo='lgd')
    >>> 'total' in df.columns
    True
"""

from __future__ import annotations

import logging
import re

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import NISRAValidationError, download_file

logger = logging.getLogger(__name__)

# ─── Fallback URLs (2026 edition) ─────────────────────────────────────────────
_SOURCE_PAGE = "https://www.finance-ni.gov.uk/topics/housing-stock-statistics"

_FALLBACK_URLS: dict[str, str] = {
    "lgd": (
        "https://www.finance-ni.gov.uk/sites/default/files/2026-06/Housing%20Stock%20Tables%202008%20-%202026.xlsx"
    ),
    "ward": (
        "https://www.finance-ni.gov.uk/sites/default/files/2026-06/"
        "Housing%20Stock%20LGD%20Ward%20Tables%202008%20-%202026.xlsx"
    ),
    "soa": ("https://www.finance-ni.gov.uk/sites/default/files/2026-06/SOA%20Housing%20Stock%202008%20-%202026.xlsx"),
}

# Sheets to skip (non-data tabs)
_SKIP_SHEETS = {"Cover Sheet", "Notes", "Contents"}

# Column names as they appear (or partial match) in the header row of each data sheet
_LGD_COLUMNS = [
    "LGD 2014 Code",
    "Local Government District",
    "Converted Apartment",
    "Purpose Built Apartment",
    "Detached",
    "Semi-Detached",
    "Terrace",
    "Total Housing Stock",
]

# Output column names (snake_case)
_OUTPUT_COLUMNS = [
    "year",
    "lgd_code",
    "lgd_name",
    "converted_apartment",
    "purpose_built_apartment",
    "detached",
    "semi_detached",
    "terrace",
    "total",
]


def get_latest_publication_url(geo: str = "lgd") -> str:
    """Scrape the DoF NI housing stock page for the latest Excel download URL.

    Attempts to find the most recent Excel link on the source page.  Falls back
    to the hardcoded 2026 URL if scraping fails or returns no match.

    Args:
        geo: Geography type — 'lgd' (default), 'ward', or 'soa'.

    Returns:
        Absolute URL of the Excel file.

    Example:
        >>> url = get_latest_publication_url('lgd')
        >>> url.endswith('.xlsx')
        True
    """
    if geo not in _FALLBACK_URLS:
        raise ValueError(f"Unknown geo type {geo!r}. Use 'lgd', 'ward', or 'soa'.")

    try:
        response = session.get(_SOURCE_PAGE, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        candidates: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if ".xlsx" not in href.lower():
                continue
            # Make absolute
            if href.startswith("/"):
                href = f"https://www.finance-ni.gov.uk{href}"

            lower = href.lower()
            if (
                geo == "lgd"
                and "soa" not in lower
                and "ward" not in lower
                or geo == "ward"
                and "ward" in lower
                or geo == "soa"
                and "soa" in lower
            ):
                candidates.append(href)

        if candidates:
            # Prefer the most recently dated URL (year is usually in the path)
            candidates.sort(key=lambda u: re.findall(r"\d{4}", u) or ["0000"], reverse=True)
            logger.info("Discovered %s URL from source page: %s", geo, candidates[0])
            return candidates[0]

    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not scrape %s for %s URL: %s", _SOURCE_PAGE, geo, exc)

    logger.info("Using fallback URL for geo=%s", geo)
    return _FALLBACK_URLS[geo]


def _extract_year_from_title(title: str) -> int | None:
    """Extract the reference year from a sheet title string.

    Args:
        title: Sheet title text, e.g.
            "Number of Dwellings by Type ... - April 2009".

    Returns:
        Four-digit year integer, or None if not found.

    Example:
        >>> _extract_year_from_title("... - April 2009")
        2009
        >>> _extract_year_from_title("... - May 2008")
        2008
    """
    match = re.search(r"\b(20\d{2})\b", str(title))
    if match:
        return int(match.group(1))
    return None


def _parse_lgd_sheet(sheet_df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Parse a single annual LGD sheet into a tidy long-format DataFrame.

    Args:
        sheet_df: Raw DataFrame read with ``header=None`` from one Table sheet.
        year: Reference year for the sheet.

    Returns:
        DataFrame with columns matching :data:`_OUTPUT_COLUMNS`.
        Returns an empty DataFrame if the header row cannot be located.
    """
    # Find the header row — it contains "LGD 2014 Code" or similar
    header_row_idx: int | None = None
    for idx, row in sheet_df.iterrows():
        row_str = " ".join(str(v).lower() for v in row if pd.notna(v))
        if "lgd" in row_str and ("code" in row_str or "council" in row_str or "district" in row_str):
            header_row_idx = int(idx)
            break

    if header_row_idx is None:
        logger.warning("Could not find header row in sheet for year %d", year)
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    headers = [str(v).strip() if pd.notna(v) else "" for v in sheet_df.iloc[header_row_idx]]

    # Map semantic names → column positions
    col_map: dict[str, int] = {}

    def _find_col(keyword: str) -> int | None:
        for i, h in enumerate(headers):
            if keyword.lower() in h.lower():
                return i
        return None

    col_map["lgd_code"] = _find_col("LGD")
    col_map["lgd_name"] = _find_col("District") or _find_col("Council") or _find_col("Government")
    col_map["converted_apartment"] = _find_col("Converted")
    col_map["purpose_built_apartment"] = _find_col("Purpose")
    col_map["detached"] = _find_col("Detached")
    col_map["semi_detached"] = _find_col("Semi")
    col_map["terrace"] = _find_col("Terrace")
    col_map["total"] = _find_col("Total")

    missing = [k for k, v in col_map.items() if v is None]
    if missing:
        logger.warning("Year %d: missing columns %s — skipping sheet", year, missing)
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    data_rows = sheet_df.iloc[header_row_idx + 1 :].copy()

    records = []
    for _, row in data_rows.iterrows():
        lgd_code = str(row.iloc[col_map["lgd_code"]]).strip() if pd.notna(row.iloc[col_map["lgd_code"]]) else None
        lgd_name_raw = row.iloc[col_map["lgd_name"]]
        lgd_name = str(lgd_name_raw).strip() if pd.notna(lgd_name_raw) else None

        if not lgd_code or lgd_code in ("nan", "None", ""):
            continue
        # Skip rows that are clearly notes/footers
        if lgd_code.lower().startswith("note") or lgd_code.lower().startswith("source"):
            continue

        # The NI total row has "Northern Ireland" as the code with a NaN name
        if lgd_code == "Northern Ireland" and lgd_name is None:
            lgd_name = "Northern Ireland"

        def _safe_int(val: object) -> int | None:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            try:
                return int(float(str(val)))
            except (ValueError, TypeError):
                return None

        records.append(
            {
                "year": year,
                "lgd_code": lgd_code,
                "lgd_name": lgd_name,
                "converted_apartment": _safe_int(row.iloc[col_map["converted_apartment"]]),
                "purpose_built_apartment": _safe_int(row.iloc[col_map["purpose_built_apartment"]]),
                "detached": _safe_int(row.iloc[col_map["detached"]]),
                "semi_detached": _safe_int(row.iloc[col_map["semi_detached"]]),
                "terrace": _safe_int(row.iloc[col_map["terrace"]]),
                "total": _safe_int(row.iloc[col_map["total"]]),
            }
        )

    if not records:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    return pd.DataFrame(records)[_OUTPUT_COLUMNS]


def parse_lgd_file(file_path: str | object) -> pd.DataFrame:
    """Parse the LGD-level housing stock Excel workbook into a tidy DataFrame.

    Iterates over every data sheet (``Table 1.1`` … ``Table 1.19``), extracts
    the reference year from the sheet title, parses the 11-LGD table plus the
    NI aggregate row, and stacks all years into a single long-format DataFrame.

    Args:
        file_path: Path to the downloaded Excel file.

    Returns:
        Long-format DataFrame with columns: year, lgd_code, lgd_name,
        converted_apartment, purpose_built_apartment, detached,
        semi_detached, terrace, total.

    Example:
        >>> import pathlib
        >>> df = parse_lgd_file("/tmp/housing_stock_lgd.xlsx")
        >>> 'total' in df.columns
        True
    """
    xl = pd.ExcelFile(file_path, engine="openpyxl")
    all_frames: list[pd.DataFrame] = []

    for sheet_name in xl.sheet_names:
        if sheet_name in _SKIP_SHEETS:
            continue
        # Only process individual-year data tables (Table 1.1 … Table 1.19)
        # Table 1.20 is the multi-year summary — skip it
        if not sheet_name.startswith("Table"):
            continue

        raw = xl.parse(sheet_name, header=None)

        # Get the sheet title from the first non-null cell
        title = ""
        for row_idx in range(min(5, len(raw))):
            val = raw.iloc[row_idx, 0]
            if pd.notna(val) and str(val).strip():
                title = str(val).strip()
                break

        year = _extract_year_from_title(title)
        if year is None:
            logger.debug("Could not extract year from sheet '%s' title: %r — skipping", sheet_name, title)
            continue

        sheet_df = _parse_lgd_sheet(raw, year)
        if not sheet_df.empty:
            all_frames.append(sheet_df)

    if not all_frames:
        logger.warning("No data extracted from LGD housing stock file")
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    result = pd.concat(all_frames, ignore_index=True).sort_values(["year", "lgd_code"]).reset_index(drop=True)

    # Ensure numeric types
    int_cols = [
        "year",
        "converted_apartment",
        "purpose_built_apartment",
        "detached",
        "semi_detached",
        "terrace",
        "total",
    ]
    for col in int_cols:
        result[col] = pd.to_numeric(result[col], errors="coerce")

    return result


def get_latest_housing_stock(geo: str = "lgd", force_refresh: bool = False) -> pd.DataFrame:
    """Download and return NI housing stock data in long format.

    Args:
        geo: Geography granularity:
            - ``'lgd'`` (default): 11 Local Government Districts + NI total.
            - ``'ward'``: Electoral Ward level.
            - ``'soa'``: Super Output Area level.
        force_refresh: If ``True``, bypass the local file cache and
            re-download the source file.

    Returns:
        Long-format DataFrame.  For ``geo='lgd'`` the columns are:

        - **year** (int): Reference year (e.g. 2008).
        - **lgd_code** (str): LGD 2014 code (e.g. ``"N09000001"``).
        - **lgd_name** (str): LGD name (e.g. ``"Antrim and Newtownabbey"``),
          or ``"Northern Ireland"`` for the NI-wide total row.
        - **converted_apartment** (int): Converted apartment dwellings.
        - **purpose_built_apartment** (int): Purpose-built apartment dwellings.
        - **detached** (int): Detached dwellings.
        - **semi_detached** (int): Semi-detached dwellings.
        - **terrace** (int): Terrace dwellings.
        - **total** (int): Total housing stock.

        Ward and SOA files share the same column schema but may have
        additional geography columns.

    Raises:
        ValueError: If ``geo`` is not one of ``'lgd'``, ``'ward'``, ``'soa'``.
        NISRADataNotFoundError: If the source file cannot be downloaded.

    Example:
        >>> df = get_latest_housing_stock(geo='lgd')
        >>> set(df.columns) >= {'year', 'lgd_code', 'lgd_name', 'total'}
        True
    """
    if geo not in _FALLBACK_URLS:
        raise ValueError(f"Unknown geo type {geo!r}. Use 'lgd', 'ward', or 'soa'.")

    url = get_latest_publication_url(geo)
    file_path = download_file(url, cache_ttl_hours=24, force_refresh=force_refresh)

    if geo == "lgd":
        return parse_lgd_file(file_path)

    # Ward and SOA files have a different multi-column layout; return raw for now
    # (they are downloaded and cached; a future enhancement can parse them fully)
    logger.warning(
        "Full parsing for geo=%r is not yet implemented; returning raw sheet data from first data tab.",
        geo,
    )
    xl = pd.ExcelFile(file_path, engine="openpyxl")
    for sheet_name in xl.sheet_names:
        if sheet_name in _SKIP_SHEETS or not sheet_name.startswith("Table"):
            continue
        return xl.parse(sheet_name, header=None)

    return pd.DataFrame()


def validate_housing_stock(df: pd.DataFrame) -> bool:
    """Validate an LGD housing stock DataFrame.

    Checks that the DataFrame has the expected structure and plausible values.

    Args:
        df: DataFrame returned by :func:`get_latest_housing_stock`.

    Returns:
        ``True`` if all checks pass.

    Raises:
        NISRAValidationError: If any check fails, with a descriptive message.

    Example:
        >>> df = get_latest_housing_stock()
        >>> validate_housing_stock(df)
        True
    """
    if df is None or df.empty:
        raise NISRAValidationError("Housing stock DataFrame is empty")

    required = {
        "year",
        "lgd_code",
        "lgd_name",
        "converted_apartment",
        "purpose_built_apartment",
        "detached",
        "semi_detached",
        "terrace",
        "total",
    }
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    # At least 10 years of data (2008–2024+)
    years = df["year"].dropna().unique()
    if len(years) < 10:
        raise NISRAValidationError(f"Too few years ({len(years)}); expected at least 10")

    # No negative values in count columns
    count_cols = ["converted_apartment", "purpose_built_apartment", "detached", "semi_detached", "terrace", "total"]
    for col in count_cols:
        vals = df[col].dropna()
        if (vals < 0).any():
            raise NISRAValidationError(f"Negative values found in column '{col}'")

    # Total should be >= sum of known subtypes (it may also include unclassified)
    numeric_cols = ["converted_apartment", "purpose_built_apartment", "detached", "semi_detached", "terrace"]
    sub = df.dropna(subset=numeric_cols + ["total"])
    if not sub.empty:
        computed_sum = sub[numeric_cols].sum(axis=1)
        # Total should be at least as large as sum of subtypes
        mismatch = sub[sub["total"] < computed_sum * 0.95]
        if not mismatch.empty:
            raise NISRAValidationError(f"'total' is implausibly lower than sum of subtypes in {len(mismatch)} rows")

    return True
