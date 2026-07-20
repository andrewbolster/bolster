"""Northern Ireland Homelessness Bulletin statistics.

Biannual homelessness statistics from the Department for Communities NI (DfC),
sourced from Northern Ireland Housing Executive (NIHE) casework records.
Covers homeless presentations, acceptances, and temporary accommodation
placements, broken down by Local Government District (LGD).

Data is published approximately every six months (Apr–Sep and Oct–Mar periods),
roughly three months after each period ends.

Note: This data is **not** available in the NISRA PxStat API. It is published
directly by DfC as Excel workbooks.

Publisher:
    Department for Communities NI (DfC) / Northern Ireland Housing Executive (NIHE).
    Publication hub: https://www.communities-ni.gov.uk/articles/northern-ireland-homelessness-bulletin

Coverage:
    Biannual, 2018/19 to present.
    Geography: 11 Local Government Districts (LGDs) + NI total.

Example:
    >>> from bolster.data_sources.nisra import homelessness
    >>> df = homelessness.get_latest_data(section='presentations')
    >>> 'lgd' in df.columns
    True
"""

from __future__ import annotations

import contextlib
import logging
import re

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import NISRAValidationError, download_file

logger = logging.getLogger(__name__)

_HUB_URL = "https://www.communities-ni.gov.uk/articles/northern-ireland-homelessness-bulletin"

_FALLBACK_URL = (
    "https://www.communities-ni.gov.uk/system/files/2026-06/ni-homelessness-bulletin-oct-mar-2026-tables.xlsx"
)

# Sheet names for each section
_SHEET_PRESENTATIONS_LGD = "1_3"
_SHEET_ACCEPTANCES_LGD = "2_3"

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


def get_latest_publication_url() -> str:
    """Scrape the DfC hub page for the latest homelessness bulletin Excel URL.

    Falls back to the hardcoded 2025/26 Oct–Mar edition URL if scraping fails.

    Returns:
        Absolute URL of the Excel tables file.

    Example:
        >>> url = get_latest_publication_url()
        >>> 'communities-ni.gov.uk' in url
        True
    """
    try:
        response = session.get(_HUB_URL, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        candidates: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if "homelessness-bulletin" in href.lower() and "tables" in href.lower() and ".xlsx" in href.lower():
                if href.startswith("/"):
                    href = f"https://www.communities-ni.gov.uk{href}"
                candidates.append(href)

        if not candidates:
            # Try following the first publication link on the hub page
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "homelessness-bulletin" in href.lower() and "publications" in href.lower():
                    if href.startswith("/"):
                        href = f"https://www.communities-ni.gov.uk{href}"
                    pub_resp = session.get(href, timeout=30)
                    pub_resp.raise_for_status()
                    pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
                    for a2 in pub_soup.find_all("a", href=True):
                        h2 = a2["href"]
                        if ".xlsx" in h2.lower() and "table" in h2.lower():
                            if h2.startswith("/"):
                                h2 = f"https://www.communities-ni.gov.uk{h2}"
                            candidates.append(h2)
                    if candidates:
                        break

        if candidates:
            # Prefer the most recent by embedded date in path (YYYY-MM)
            def _date_key(u: str) -> str:
                m = re.search(r"/(\d{4}-\d{2})/", u)
                return m.group(1) if m else "0000-00"

            candidates.sort(key=_date_key, reverse=True)
            logger.info("Discovered homelessness bulletin URL: %s", candidates[0])
            return candidates[0]

    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not scrape %s for homelessness URL: %s", _HUB_URL, exc)

    logger.info("Using fallback homelessness bulletin URL")
    return _FALLBACK_URL


def _parse_lgd_period_sheet(sheet_df: pd.DataFrame, value_col_name: str) -> pd.DataFrame:
    """Parse a homelessness LGD-by-period sheet into long format.

    These sheets have a composite header where:
    - Row 1: year labels (each spanning two data columns via merged cells → NaNs)
    - Row 2: period labels (same pattern)
    - Row 3: column descriptions (LGD name, count, rate per 1000, count, rate ...)
    - Row 4+: one row per LGD, last row = Northern Ireland total

    Args:
        sheet_df: Raw DataFrame read with ``header=None``.
        value_col_name: Name for the count column (e.g. ``'presentations'``).

    Returns:
        Long-format DataFrame with columns: year, period, lgd, <value_col_name>,
        rate_per_1000. Rows with '*' suppressed values are dropped.
    """
    years_raw = list(sheet_df.iloc[1])
    periods_raw = list(sheet_df.iloc[2])

    # Forward-fill: year/period headers sit on the count column; rate column has NaN
    years_filled: list[str | None] = []
    periods_filled: list[str | None] = []
    current_year: str | None = None
    current_period: str | None = None
    for y, p in zip(years_raw, periods_raw, strict=False):
        if pd.notna(y):
            # Strip footnote digit appended to year ranges: "2023/242" → "2023/24"
            current_year = re.sub(r"^(\d{4}/\d{2})\d+$", r"\1", str(y).strip())
        if pd.notna(p):
            current_period = str(p).strip()
        years_filled.append(current_year)
        periods_filled.append(current_period)

    # Data rows: row index 4 onwards (row 3 = col headers, which we skip)
    records = []
    for row_idx in range(4, len(sheet_df)):
        row = sheet_df.iloc[row_idx]
        lgd = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
        if not lgd or lgd in ("nan", "None", "") or lgd.lower().startswith("source"):
            continue
        # Stop at footnote rows
        if re.match(r"^\d+\.", lgd) or lgd.lower().startswith("note"):
            continue

        # Walk pairs of (count, rate) columns starting at col index 1
        col_idx = 1
        while col_idx < len(row) - 1:
            year_label = years_filled[col_idx]
            period_label = periods_filled[col_idx]
            if year_label is None or period_label is None:
                col_idx += 2
                continue

            raw_count = row.iloc[col_idx]
            raw_rate = row.iloc[col_idx + 1]

            # Skip suppressed ('*') or missing values
            if str(raw_count).strip() in ("*", "nan", "None", ""):
                col_idx += 2
                continue

            try:
                count = int(str(raw_count).replace(",", "").strip())
            except ValueError:
                col_idx += 2
                continue

            rate: float | None = None
            with contextlib.suppress(ValueError, TypeError):
                rate = float(str(raw_rate).replace(",", "").strip())

            records.append(
                {
                    "year": year_label,
                    "period": _normalise_period(period_label),
                    "lgd": lgd,
                    value_col_name: count,
                    "rate_per_1000": rate,
                }
            )
            col_idx += 2

    return pd.DataFrame(records)


def _normalise_period(period: str) -> str:
    """Normalise period label variants to a consistent short form.

    Args:
        period: Raw period string from the spreadsheet header.

    Returns:
        Normalised string, e.g. ``'Apr-Sep'``, ``'Oct-Mar'``.

    Example:
        >>> _normalise_period('April-September')
        'Apr-Sep'
        >>> _normalise_period('October-March')
        'Oct-Mar'
    """
    period = period.strip()
    # Strip footnote markers
    period = re.sub(r"[¹²³⁴1234]\s*$", "", period).strip()

    mapping = {
        "april-september": "Apr-Sep",
        "october-march": "Oct-Mar",
        "july-december": "Jul-Dec",
        "january-june": "Jan-Jun",
    }
    lower = period.lower()
    for key, val in mapping.items():
        if lower.startswith(key[:5]):
            return val

    # Special cases: "Apr-Jun (Financial year Q1)" etc.
    if "apr" in lower and "jun" in lower:
        return "Apr-Jun"
    if "apr" in lower and "sep" in lower:
        return "Apr-Sep"
    if "oct" in lower and "mar" in lower:
        return "Oct-Mar"
    if "jul" in lower and "dec" in lower:
        return "Jul-Dec"
    if "jan" in lower and "jun" in lower:
        return "Jan-Jun"

    return period


def parse_presentations(file_path: str | object) -> pd.DataFrame:
    """Parse the presentations-by-LGD sheet from a homelessness bulletin workbook.

    Args:
        file_path: Path to the downloaded Excel file.

    Returns:
        Long-format DataFrame with columns: year, period, lgd,
        presentations, rate_per_1000.

    Example:
        >>> df = parse_presentations('/tmp/homelessness.xlsx')
        >>> set(df.columns) >= {'year', 'period', 'lgd', 'presentations'}
        True
    """
    xl = pd.ExcelFile(file_path, engine="openpyxl")
    raw = xl.parse(_SHEET_PRESENTATIONS_LGD, header=None)
    return _parse_lgd_period_sheet(raw, "presentations")


def parse_acceptances(file_path: str | object) -> pd.DataFrame:
    """Parse the acceptances-by-LGD sheet from a homelessness bulletin workbook.

    Args:
        file_path: Path to the downloaded Excel file.

    Returns:
        Long-format DataFrame with columns: year, period, lgd,
        acceptances, rate_per_1000.

    Example:
        >>> df = parse_acceptances('/tmp/homelessness.xlsx')
        >>> set(df.columns) >= {'year', 'period', 'lgd', 'acceptances'}
        True
    """
    xl = pd.ExcelFile(file_path, engine="openpyxl")
    raw = xl.parse(_SHEET_ACCEPTANCES_LGD, header=None)
    return _parse_lgd_period_sheet(raw, "acceptances")


def get_latest_data(
    section: str = "presentations",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download and return the latest NI homelessness bulletin data.

    Args:
        section: Which section to return:
            - ``'presentations'`` (default): Households presenting as homeless
              by LGD and period.
            - ``'acceptances'``: Households accepted as homeless by LGD and period.
            - ``'all'``: Both sections combined with a ``'section'`` column.
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        Long-format DataFrame. For ``section='presentations'``, columns are:

        - **year** (str): Reporting year label (e.g. ``'2025/26'``).
        - **period** (str): Six-month period (e.g. ``'Oct-Mar'``, ``'Apr-Sep'``).
        - **lgd** (str): Local Government District name, or ``'Northern Ireland'``
          for the NI-wide total.
        - **presentations** (int): Households presenting as homeless.
        - **rate_per_1000** (float): Presentations per 1,000 population.

        For ``section='acceptances'``, ``'presentations'`` is replaced by
        ``'acceptances'``. For ``section='all'``, both are included with a
        ``'section'`` column (``'presentations'`` or ``'acceptances'``).

    Raises:
        ValueError: If ``section`` is not one of the accepted values.
        NISRADataNotFoundError: If the source file cannot be downloaded.

    Example:
        >>> df = get_latest_data()
        >>> 'lgd' in df.columns
        True
        >>> 'Northern Ireland' in df['lgd'].values
        True
    """
    valid = {"presentations", "acceptances", "all"}
    if section not in valid:
        raise ValueError(f"section must be one of {sorted(valid)!r}, got {section!r}")

    url = get_latest_publication_url()
    file_path = download_file(url, cache_ttl_hours=24 * 7, force_refresh=force_refresh)

    if section == "presentations":
        return parse_presentations(file_path)
    if section == "acceptances":
        return parse_acceptances(file_path)

    # section == 'all'
    pres = parse_presentations(file_path)
    pres["section"] = "presentations"
    pres = pres.rename(columns={"presentations": "count"})

    acc = parse_acceptances(file_path)
    acc["section"] = "acceptances"
    acc = acc.rename(columns={"acceptances": "count"})

    return pd.concat([pres, acc], ignore_index=True)


def validate_data(df: pd.DataFrame, section: str = "presentations") -> bool:
    """Validate a homelessness bulletin DataFrame.

    Args:
        df: DataFrame returned by :func:`get_latest_data`.
        section: ``'presentations'`` or ``'acceptances'``, used to identify
            the count column.

    Returns:
        ``True`` if all checks pass.

    Raises:
        NISRAValidationError: If any check fails.

    Example:
        >>> df = get_latest_data('presentations')
        >>> validate_data(df, 'presentations')
        True
    """
    if df is None or df.empty:
        raise NISRAValidationError("Homelessness DataFrame is empty")

    count_col = "count" if "count" in df.columns else section
    required = {"year", "period", "lgd", count_col}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    # Should cover multiple years (at least 5 periods of data)
    if len(df) < 5:
        raise NISRAValidationError(f"Too few rows ({len(df)}); expected at least 5")

    # NI total should be present
    if "Northern Ireland" not in df["lgd"].values:
        raise NISRAValidationError("'Northern Ireland' total row not found in lgd column")

    # No negative counts
    counts = df[count_col].dropna()
    if (counts < 0).any():
        raise NISRAValidationError(f"Negative values found in '{count_col}' column")

    # Sanity check: NI-wide presentations in a recent period should be > 1000
    ni_rows = df[df["lgd"] == "Northern Ireland"]
    if not ni_rows.empty:
        max_count = ni_rows[count_col].max()
        if max_count < 1000:
            raise NISRAValidationError(f"NI total {section} implausibly low (max={max_count}); expected >1000")

    return True
