"""Northern Ireland Housing Bulletin statistics.

Quarterly housing statistics from the Department for Communities NI (DfC),
compiled from Northern Ireland Housing Executive (NIHE), Land & Property
Services (LPS) and NHBC administrative sources. Covers social housing supply,
the dwelling stock, the social housing waiting list and allocations, new
dwelling sales and prices, and the Affordable Warmth Scheme.

Data is published quarterly, roughly two months after each quarter ends.

Note: This data is **not** available in the NISRA PxStat API. It is published
directly by DfC as an OpenDocument Spreadsheet (``.ods``) tables workbook.

Note: The bulletin also contains homelessness tables (2.4–2.7). Those are
deliberately **not** parsed here — the richer, LGD-level homelessness series is
already available via :mod:`bolster.data_sources.nisra.homelessness`.

Publisher:
    Department for Communities NI (DfC).
    Publication hub: https://www.communities-ni.gov.uk/articles/northern-ireland-housing-bulletin

Coverage:
    Quarterly. Social housing supply from 2010/11, new dwelling sales from
    2005/06, waiting list from 2021/22, Affordable Warmth from 2023/24.
    Geography: Northern Ireland and 11 Local Government Districts (LGDs).

Example:
    >>> from bolster.data_sources.nisra import housing_bulletin
    >>> df = housing_bulletin.get_dwelling_stock_by_tenure()
    >>> 'Northern Ireland' in df['lgd'].values
    True
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

_SITE_ROOT = "https://www.communities-ni.gov.uk"
_HUB_URL = f"{_SITE_ROOT}/articles/northern-ireland-housing-bulletin"

_FALLBACK_URL = f"{_SITE_ROOT}/system/files/2026-05/ni-housing-bulletin-jan-mar26-tables_0.ods"

_SHEET_STARTS = "T1_1"
_SHEET_COMPLETIONS = "T1_2"
_SHEET_STOCK = "T1_3"
_SHEET_WAITING_LIST_TREND = "T2_1"
_SHEET_WAITING_LIST_LGD = "T2_2"
_SHEET_ALLOCATIONS_LGD = "T2_3"
_SHEET_SALES_TREND = "T3_1"
_SHEET_SALES_LGD = "T3_2"
_SHEET_AFFORDABLE_WARMTH = "T4_1"

_KNOWN_LGDS = {
    "Antrim and Newtownabbey",
    "Ards and North Down",
    "Armagh City, Banbridge and Craigavon",
    "Belfast",
    "Causeway Coast and Glens",
    "Derry City and Strabane",
    "Fermanagh and Omagh",
    "Lisburn and Castlereagh",
    "Mid and East Antrim",
    "Mid Ulster",
    "Newry, Mourne and Down",
    "Northern Ireland",
}

_FINANCIAL_YEAR_RE = re.compile(r"(\d{4})\s*[/-]\s*(\d{2})")
_QUARTER_ALIASES = {
    "apr": "Apr-Jun",
    "jul": "Jul-Sep",
    "oct": "Oct-Dec",
    "jan": "Jan-Mar",
}


def get_latest_publication_url() -> str:
    """Scrape the DfC hub page for the latest housing bulletin tables URL.

    Falls back to a hardcoded edition URL if scraping fails.

    Returns:
        Absolute URL of the ``.ods`` tables workbook.

    Example:
        >>> url = get_latest_publication_url()
        >>> 'communities-ni.gov.uk' in url
        True
    """
    try:
        response = session.get(_HUB_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            href = str(a_tag["href"])
            if "/publications/northern-ireland-housing-bulletin" not in href.lower():
                continue
            pub_url = f"{_SITE_ROOT}{href}" if href.startswith("/") else href
            pub_resp = session.get(pub_url)
            pub_resp.raise_for_status()
            pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
            for a2 in pub_soup.find_all("a", href=True):
                h2 = str(a2["href"])
                if h2.lower().endswith((".ods", ".xlsx")):
                    file_url = f"{_SITE_ROOT}{h2}" if h2.startswith("/") else h2
                    logger.info("Discovered housing bulletin URL: %s", file_url)
                    return file_url
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not scrape %s for housing bulletin URL: %s", _HUB_URL, exc)

    logger.info("Using fallback housing bulletin URL")
    return _FALLBACK_URL


def _load_sheet(file_path: str | Path, sheet: str) -> pd.DataFrame:
    """Read one sheet of the bulletin workbook with no header inference."""
    engine = "odf" if str(file_path).lower().endswith(".ods") else "openpyxl"
    return pd.ExcelFile(file_path, engine=engine).parse(sheet, header=None)


def _clean_number(value: object) -> float | None:
    """Coerce a spreadsheet cell to a number.

    ``'-'`` marks *not applicable* in the supply tables and becomes ``None``,
    as do blanks and any other non-numeric text.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace(",", "").replace("£", "").strip()
    if text in {"", "-", "..", "*", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalise_financial_year(label: object) -> str | None:
    """Normalise a financial year label to ``YYYY/YY`` form.

    Args:
        label: Raw cell value, e.g. ``'2021-22'``, ``'2010/11'``, ``'Year 2005-06'``.

    Returns:
        Normalised label, or ``None`` if no financial year is present.

    Example:
        >>> normalise_financial_year('2021-22')
        '2021/22'
        >>> normalise_financial_year('Year 2005-06')
        '2005/06'
        >>> normalise_financial_year('Apr - Jun') is None
        True
    """
    if label is None:
        return None
    match = _FINANCIAL_YEAR_RE.search(str(label))
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def normalise_quarter(label: object) -> str | None:
    """Normalise a quarter label to ``Mon-Mon`` form.

    Args:
        label: Raw cell value, e.g. ``'Apr - Jun'``, ``'Jul - Sept'``, ``'Oct-Dec(R)'``.

    Returns:
        One of ``'Apr-Jun'``, ``'Jul-Sep'``, ``'Oct-Dec'``, ``'Jan-Mar'``, or
        ``None`` if the label is not a quarter.

    Example:
        >>> normalise_quarter('Jul - Sept')
        'Jul-Sep'
        >>> normalise_quarter('Oct-Dec(R)')
        'Oct-Dec'
        >>> normalise_quarter('2021-22') is None
        True
    """
    if label is None:
        return None
    text = re.sub(r"\((?:R|P)\)", "", str(label), flags=re.IGNORECASE)
    text = re.sub(r"\d", "", text).strip().lower()
    # The 2021-22 rows of table 2.1 label Q3 as "Sep - Dec" in the source; the
    # surrounding quarters confirm it is Oct-Dec, so the leading month is ignored.
    for month, quarter in _QUARTER_ALIASES.items():
        if text.startswith(month):
            return quarter
    if text.startswith("sep") and "dec" in text:
        return "Oct-Dec"
    return None


def _financial_year_of(label: object, quarter: str | None) -> str | None:
    """Resolve the financial year for a period label.

    Table 3.1 labels its quarterly rows with a calendar year (``'Jan - Mar 2008'``)
    but its annual rows with a financial year (``'Year 2007-08'``).
    """
    year = normalise_financial_year(label)
    if year is not None:
        return year
    if quarter is None:
        return None
    match = re.search(r"(\d{4})", str(label))
    if not match:
        return None
    start = int(match.group(1)) - (1 if quarter == "Jan-Mar" else 0)
    return f"{start}/{(start + 1) % 100:02d}"


def _revision_status(label: object) -> str:
    """Classify a period label's ``(P)``/``(R)`` revision marker."""
    text = str(label).upper()
    if "(P)" in text:
        return "provisional"
    if "(R)" in text:
        return "revised"
    return "final"


def _parse_supply_sheet(raw: pd.DataFrame, value_name: str) -> pd.DataFrame:
    """Parse a social housing supply sheet (tables 1.1 and 1.2) into long format.

    These sheets carry completed financial years across one header row and the
    in-progress year's quarters across a second, with rows grouped into
    ``Shared`` and ``Self-Contained`` tenure blocks each closed by a sub-total.
    """
    year_row, quarter_row = raw.iloc[2], raw.iloc[3]

    annual_cols: dict[int, str] = {}
    quarter_cols: dict[int, str] = {}
    for col in range(2, raw.shape[1]):
        quarter = normalise_quarter(quarter_row.iloc[col])
        year = normalise_financial_year(year_row.iloc[col])
        if quarter is not None:
            quarter_cols[col] = quarter
        elif str(quarter_row.iloc[col]).strip().lower() == "total":
            quarter_cols[col] = "Total"
        elif year is not None:
            annual_cols[col] = year

    current_year = max(
        (y for y in (normalise_financial_year(v) for v in year_row) if y is not None),
        default=None,
    )

    records: list[dict[str, object]] = []
    block: list[int] = []
    block_label: str | None = None

    def _flush(rows: list[int], label: str | None) -> None:
        for row_idx in rows:
            housing_type = str(raw.iat[row_idx, 1]).strip()
            tenure = "All" if housing_type.lower() == "totals" else (label or "Unknown")
            for col, year in annual_cols.items():
                records.append(
                    {
                        "financial_year": year,
                        "period": "Total",
                        "tenure": tenure,
                        "housing_type": housing_type,
                        value_name: _clean_number(raw.iat[row_idx, col]),
                    }
                )
            for col, quarter in quarter_cols.items():
                records.append(
                    {
                        "financial_year": current_year,
                        "period": quarter,
                        "tenure": tenure,
                        "housing_type": housing_type,
                        value_name: _clean_number(raw.iat[row_idx, col]),
                    }
                )

    for row_idx in range(4, raw.shape[0]):
        housing_type = raw.iat[row_idx, 1]
        if housing_type is None or pd.isna(housing_type):
            continue
        label_cell = raw.iat[row_idx, 0]
        if label_cell is not None and not pd.isna(label_cell):
            block_label = str(label_cell).strip()
        block.append(row_idx)
        name = str(housing_type).strip().lower()
        if name == "sub-total":
            _flush(block, block_label)
            block, block_label = [], None
        elif name == "totals":
            _flush(block, None)
            block, block_label = [], None
            break

    return pd.DataFrame(records)


def _parse_lgd_table(raw: pd.DataFrame, header_row: int, columns: dict[int, str]) -> pd.DataFrame:
    """Parse a simple one-row-per-LGD table into a tidy DataFrame."""
    records: list[dict[str, object]] = []
    for row_idx in range(header_row + 1, raw.shape[0]):
        lgd = raw.iat[row_idx, 0]
        if lgd is None or pd.isna(lgd):
            continue
        lgd = normalise_lgd(lgd)
        if lgd not in _KNOWN_LGDS:
            continue
        record: dict[str, object] = {"lgd": lgd}
        for col, name in columns.items():
            record[name] = _clean_number(raw.iat[row_idx, col])
        records.append(record)
    return pd.DataFrame(records)


def normalise_lgd(name: object) -> str:
    """Normalise a Local Government District name to the canonical NISRA form.

    The bulletin mixes ``'&'`` and ``'and'``, and uses ``'Total'`` for the
    Northern Ireland row in some tables.

    Args:
        name: Raw district label from the spreadsheet.

    Returns:
        Canonical district name.

    Example:
        >>> normalise_lgd('Ards & North Down')
        'Ards and North Down'
        >>> normalise_lgd('Total allocations')
        'Northern Ireland'
    """
    text = re.sub(r"\s+", " ", str(name)).strip()
    text = re.sub(r"\d+$", "", text).strip()
    text = text.replace(" & ", " and ")
    if text.lower().startswith("total"):
        return "Northern Ireland"
    return text


def get_social_housing_starts(force_refresh: bool = False) -> pd.DataFrame:
    """Social Housing Development Programme new dwelling starts (table 1.1).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        Long-format DataFrame with columns:

        - **financial_year** (str): e.g. ``'2024/25'``.
        - **period** (str): ``'Total'`` for completed years, otherwise the
          quarter (``'Apr-Jun'``, ``'Jul-Sep'``, ``'Oct-Dec'``, ``'Jan-Mar'``)
          for the in-progress year.
        - **tenure** (str): ``'Shared'``, ``'Self-Contained'`` or ``'All'``.
        - **housing_type** (str): e.g. ``'New Build'``, ``'Sub-total'``, ``'Totals'``.
        - **starts** (float): Dwelling starts, or ``NaN`` where not applicable.

    Example:
        >>> df = get_social_housing_starts()
        >>> set(df['tenure']) >= {'Shared', 'Self-Contained', 'All'}
        True
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_STARTS)
    return _parse_supply_sheet(raw, "starts")


def get_social_housing_completions(force_refresh: bool = False) -> pd.DataFrame:
    """Social Housing Development Programme new dwelling completions (table 1.2).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        Long-format DataFrame shaped as :func:`get_social_housing_starts`, with
        a **completions** column instead of ``starts``.

    Example:
        >>> df = get_social_housing_completions()
        >>> 'completions' in df.columns
        True
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_COMPLETIONS)
    return _parse_supply_sheet(raw, "completions")


def get_dwelling_stock_by_tenure(force_refresh: bool = False) -> pd.DataFrame:
    """Estimated dwelling stock by tenure and district (table 1.3).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with one row per LGD plus a ``'Northern Ireland'`` total, and
        columns **lgd**, **total_stock**, **occupied_stock**, **owner_occupied**,
        **private_rented**, **social_rented**, **rent_free** (all float dwelling
        counts).

    Example:
        >>> df = get_dwelling_stock_by_tenure()
        >>> len(df)
        12
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_STOCK)
    return _parse_lgd_table(
        raw,
        header_row=2,
        columns={
            1: "total_stock",
            2: "occupied_stock",
            3: "owner_occupied",
            4: "private_rented",
            5: "social_rented",
            6: "rent_free",
        },
    )


def get_waiting_list_trend(force_refresh: bool = False) -> pd.DataFrame:
    """Social housing waiting list and allocations by quarter (table 2.1).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with columns **financial_year**, **quarter**,
        **total_applicants**, **applicants_in_housing_stress**,
        **applicants_with_fda_status**, **allocations_to_applicants**,
        **allocations_to_nihe_transfers**,
        **allocations_to_housing_association_transfers**, **total_allocations**.

        ``applicants_with_fda_status`` is ``NaN`` before 2024/25, when NIHE
        began publishing it.

    Example:
        >>> df = get_waiting_list_trend()
        >>> set(df['quarter']) == {'Apr-Jun', 'Jul-Sep', 'Oct-Dec', 'Jan-Mar'}
        True
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_WAITING_LIST_TREND)
    columns = {
        1: "total_applicants",
        2: "applicants_in_housing_stress",
        3: "applicants_with_fda_status",
        4: "allocations_to_applicants",
        5: "allocations_to_nihe_transfers",
        6: "allocations_to_housing_association_transfers",
        7: "total_allocations",
    }

    records: list[dict[str, object]] = []
    current_year: str | None = None
    for row_idx in range(4, raw.shape[0]):
        label = raw.iat[row_idx, 0]
        if label is None or pd.isna(label):
            continue
        year = normalise_financial_year(label)
        if year is not None:
            current_year = year
            continue
        quarter = normalise_quarter(label)
        if quarter is None or current_year is None:
            continue
        record: dict[str, object] = {"financial_year": current_year, "quarter": quarter}
        for col, name in columns.items():
            record[name] = _clean_number(raw.iat[row_idx, col])
        records.append(record)

    return pd.DataFrame(records)


def get_waiting_list_by_district(force_refresh: bool = False) -> pd.DataFrame:
    """Social housing waiting list by district (table 2.2).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with columns **lgd**, **total_applicants**,
        **applicants_in_housing_stress**, **applicants_with_fda_status**.
        Figures are a snapshot at the end of the reporting quarter.

    Example:
        >>> df = get_waiting_list_by_district()
        >>> df.set_index('lgd').loc['Belfast', 'total_applicants'] > 0
        True
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_WAITING_LIST_LGD)
    return _parse_lgd_table(
        raw,
        header_row=2,
        columns={
            1: "total_applicants",
            2: "applicants_in_housing_stress",
            3: "applicants_with_fda_status",
        },
    )


def get_allocations_by_district(force_refresh: bool = False) -> pd.DataFrame:
    """Social housing allocations by district (table 2.3).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with columns **lgd**, **allocations_to_applicants**,
        **allocations_to_nihe_transfers**,
        **allocations_to_housing_association_transfers**, **total_allocations**.

    Example:
        >>> df = get_allocations_by_district()
        >>> 'total_allocations' in df.columns
        True
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_ALLOCATIONS_LGD)
    return _parse_lgd_table(
        raw,
        header_row=2,
        columns={
            1: "allocations_to_applicants",
            2: "allocations_to_nihe_transfers",
            3: "allocations_to_housing_association_transfers",
            4: "total_allocations",
        },
    )


def get_new_dwelling_sales(force_refresh: bool = False) -> pd.DataFrame:
    """New dwelling sales and average prices over time (table 3.1).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with columns:

        - **financial_year** (str): e.g. ``'2025/26'``.
        - **period** (str): quarter, or ``'Total'`` for the financial year row.
        - **sales** (float): Number of new dwelling sales.
        - **average_price** (float): Average price in £.
        - **status** (str): ``'final'``, ``'provisional'`` or ``'revised'``,
          from the source's ``(P)``/``(R)`` markers.

    Example:
        >>> df = get_new_dwelling_sales()
        >>> df['financial_year'].min()
        '2005/06'
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_SALES_TREND)

    records: list[dict[str, object]] = []
    for row_idx in range(4, raw.shape[0]):
        label = raw.iat[row_idx, 0]
        if label is None or pd.isna(label):
            continue
        quarter = normalise_quarter(label)
        year = _financial_year_of(label, quarter)
        if year is None:
            continue
        sales = _clean_number(raw.iat[row_idx, 1])
        if sales is None:
            continue
        records.append(
            {
                "financial_year": year,
                "period": quarter or "Total",
                "sales": sales,
                "average_price": _clean_number(raw.iat[row_idx, 2]),
                "status": _revision_status(label),
            }
        )

    return pd.DataFrame(records)


def get_new_dwelling_sales_by_district(force_refresh: bool = False) -> pd.DataFrame:
    """New dwelling sales and average prices by district and sector (table 3.2).

    Covers the most recent quarter only; the reporting quarter is returned in
    the **quarter** column.

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        Long-format DataFrame with columns **lgd**, **sector** (``'Private'``,
        ``'Public'`` or ``'All'``), **quarter**, **sales**, and
        **average_price** (in £; the source publishes £'000).

    Example:
        >>> df = get_new_dwelling_sales_by_district()
        >>> set(df['sector']) == {'Private', 'Public', 'All'}
        True
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_SALES_LGD)
    quarter = normalise_quarter(raw.iat[4, 1])
    sectors = {1: "Private", 3: "Public", 5: "All"}

    records: list[dict[str, object]] = []
    for row_idx in range(7, raw.shape[0]):
        lgd = raw.iat[row_idx, 0]
        if lgd is None or pd.isna(lgd):
            continue
        lgd = normalise_lgd(lgd)
        if lgd not in _KNOWN_LGDS:
            continue
        for col, sector in sectors.items():
            price = _clean_number(raw.iat[row_idx, col + 1])
            records.append(
                {
                    "lgd": lgd,
                    "sector": sector,
                    "quarter": quarter,
                    "sales": _clean_number(raw.iat[row_idx, col]),
                    "average_price": None if price is None else price * 1000,
                }
            )

    return pd.DataFrame(records)


def get_affordable_warmth(force_refresh: bool = False) -> pd.DataFrame:
    """Affordable Warmth Scheme activity by quarter (table 4.1).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with columns **financial_year**, **quarter**, **approvals**,
        **approvals_value** (£), **homes_improved**, **measures_installed**,
        **annual_spend_to_date** (£).

    Example:
        >>> df = get_affordable_warmth()
        >>> df['approvals'].sum() > 0
        True
    """
    raw = _load_sheet(_download(force_refresh), _SHEET_AFFORDABLE_WARMTH)
    columns = {
        1: "approvals",
        2: "approvals_value",
        3: "homes_improved",
        4: "measures_installed",
        5: "annual_spend_to_date",
    }

    records: list[dict[str, object]] = []
    current_year: str | None = None
    for row_idx in range(4, raw.shape[0]):
        label = raw.iat[row_idx, 0]
        if label is None or pd.isna(label):
            continue
        year = normalise_financial_year(label)
        if year is not None:
            current_year = year
            continue
        quarter = normalise_quarter(label)
        if quarter is None or current_year is None:
            continue
        record: dict[str, object] = {"financial_year": current_year, "quarter": quarter}
        for col, name in columns.items():
            record[name] = _clean_number(raw.iat[row_idx, col])
        records.append(record)

    return pd.DataFrame(records)


_TABLES: dict[str, Callable[..., pd.DataFrame]] = {
    "starts": get_social_housing_starts,
    "completions": get_social_housing_completions,
    "stock": get_dwelling_stock_by_tenure,
    "waiting-list": get_waiting_list_trend,
    "waiting-list-district": get_waiting_list_by_district,
    "allocations-district": get_allocations_by_district,
    "sales": get_new_dwelling_sales,
    "sales-district": get_new_dwelling_sales_by_district,
    "affordable-warmth": get_affordable_warmth,
}


def list_tables() -> list[str]:
    """List the table names accepted by :func:`get_latest_data`.

    Returns:
        Sorted table names.

    Example:
        >>> 'stock' in list_tables()
        True
    """
    return sorted(_TABLES)


def get_latest_data(table: str = "stock", force_refresh: bool = False) -> pd.DataFrame:
    """Fetch one table from the latest bulletin by name.

    Args:
        table: One of the names returned by :func:`list_tables`.
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        The requested DataFrame.

    Raises:
        NISRADataNotFoundError: If ``table`` is not a known table name.

    Example:
        >>> df = get_latest_data('stock')
        >>> 'lgd' in df.columns
        True
    """
    accessor = _TABLES.get(table)
    if accessor is None:
        raise NISRADataNotFoundError(f"Unknown table {table!r}. Available: {', '.join(list_tables())}")
    return accessor(force_refresh=force_refresh)


def _download(force_refresh: bool = False) -> str | Path:
    """Download the latest bulletin workbook, caching for a week."""
    return download_file(get_latest_publication_url(), cache_ttl_hours=24 * 7, force_refresh=force_refresh)


def validate_data(df: pd.DataFrame, required_columns: set[str] | None = None) -> bool:
    """Validate a housing bulletin DataFrame.

    Args:
        df: DataFrame returned by any of the accessor functions.
        required_columns: Columns that must be present. Defaults to no
            column requirement beyond the frame being non-empty.

    Returns:
        ``True`` if all checks pass.

    Raises:
        NISRAValidationError: If any check fails.

    Example:
        >>> df = get_dwelling_stock_by_tenure()
        >>> validate_data(df, {'lgd', 'total_stock'})
        True
    """
    if df is None or df.empty:
        raise NISRAValidationError("Housing bulletin DataFrame is empty")

    if required_columns:
        missing = required_columns - set(df.columns)
        if missing:
            raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    numeric = df.select_dtypes(include="number")
    for column in numeric.columns:
        if (numeric[column].dropna() < 0).any():
            raise NISRAValidationError(f"Column {column!r} contains negative values")

    if "lgd" in df.columns:
        unknown = set(df["lgd"].dropna().unique()) - _KNOWN_LGDS
        if unknown:
            raise NISRAValidationError(f"Unknown Local Government Districts: {sorted(unknown)}")

    return True
