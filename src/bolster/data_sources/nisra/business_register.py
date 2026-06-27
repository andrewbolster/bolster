"""NISRA NI Business Register (IDBR) Module.

Provides access to the annual count of VAT and/or PAYE registered businesses
operating in Northern Ireland, sourced from the Inter-Departmental Business
Register (IDBR). This is the only structured time-series of NI business stock.

Data Coverage:
    - By broad industry group: 2010-present
    - By legal status: 2010-present
    - By Local Government District (LGD): 2013-present

Data Source:
    Publication page (year-specific):
        https://www.nisra.gov.uk/publications/northern-ireland-business-activity-size-location-and-ownership-{year}
    Direct file (year-specific):
        https://www.nisra.gov.uk/system/files/statistics/{year}-06/IDBR-Publication-{year}.xlsx

Update Frequency:
    Annual, published in June.

Example:
    >>> from bolster.data_sources.nisra import business_register
    >>> df = business_register.get_latest_data()
    >>> 'businesses' in df.columns
    True
"""

import logging
from datetime import datetime

import pandas as pd

from bolster.utils.web import session

from ._base import NISRADataError, NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

NISRA_BASE_URL = "https://www.nisra.gov.uk"
PUBLICATION_PAGE_TEMPLATE = (
    "https://www.nisra.gov.uk/publications/northern-ireland-business-activity-size-location-and-ownership-{year}"
)
FILE_URL_TEMPLATE = "https://www.nisra.gov.uk/system/files/statistics/{year}-06/IDBR-Publication-{year}.xlsx"

_SHEET_INDUSTRY = "1.1"
_SHEET_LEGAL_STATUS = "2.1"
_SHEET_LGD = "3.1"


def get_idbr_publication_url(year: int | None = None) -> tuple[str, int]:
    """Find the IDBR publication Excel URL for a given (or latest) year.

    Tries the direct, stable URL pattern first (year is incremented each
    publication). Falls back to scraping the year-specific publication page
    if the direct URL is not reachable.

    Args:
        year: Publication year to look for. Defaults to trying the current
            year, then the previous year.

    Returns:
        Tuple of (excel_url, year).

    Raises:
        NISRADataNotFoundError: If no publication could be found.

    Example:
        >>> url, year = get_idbr_publication_url()
        >>> url.startswith('https://')
        True
    """
    candidate_years = [year] if year is not None else [datetime.now().year, datetime.now().year - 1]

    for candidate_year in candidate_years:
        direct_url = FILE_URL_TEMPLATE.format(year=candidate_year)
        try:
            response = session.head(direct_url, timeout=15, allow_redirects=True)
            if response.status_code == 200:
                return direct_url, candidate_year
        except Exception as e:
            logger.debug(f"HEAD request failed for {direct_url}: {e}")

        pub_url = PUBLICATION_PAGE_TEMPLATE.format(year=candidate_year)
        try:
            response = session.get(pub_url, timeout=30)
            response.raise_for_status()
        except Exception as e:
            logger.debug(f"Failed to fetch IDBR publication page {pub_url}: {e}")
            continue

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.content, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "idbr" in href.lower() and href.lower().endswith(".xlsx"):
                excel_url = href if href.startswith("http") else f"{NISRA_BASE_URL}{href}"
                return excel_url, candidate_year

    raise NISRADataNotFoundError(
        f"Could not find IDBR publication for years {candidate_years}. "
        f"Check: {PUBLICATION_PAGE_TEMPLATE.format(year=candidate_years[0])}"
    )


def _wide_to_long(df: pd.DataFrame, id_col: str, id_label: str, value_label: str) -> pd.DataFrame:
    """Pivot a wide year-columned table to tidy long format."""
    year_cols = [c for c in df.columns if c != id_col]
    long = df.melt(id_vars=[id_col], value_vars=year_cols, var_name="year", value_name=value_label)
    long = long.rename(columns={id_col: id_label})
    long["year"] = pd.to_numeric(long["year"], errors="coerce").astype("Int64")
    long[value_label] = pd.to_numeric(long[value_label], errors="coerce")
    return long.dropna(subset=["year"]).reset_index(drop=True)


def get_businesses_by_industry(force_refresh: bool = False) -> pd.DataFrame:
    """Get annual business counts by broad industry group (Table 1.1).

    Args:
        force_refresh: Force re-download even if cached.

    Returns:
        DataFrame with columns: year, industry_group, businesses.
    """
    url, _ = get_idbr_publication_url()
    path = download_file(url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)

    try:
        raw = pd.read_excel(path, sheet_name=_SHEET_INDUSTRY, engine="openpyxl", header=None)
    except Exception as e:
        raise NISRADataError(f"Failed to parse IDBR industry sheet: {e}") from e

    header_row = raw.index[raw[0] == "Broad Industry Group"][0]
    table = raw.iloc[header_row + 1 :].copy()
    table.columns = raw.iloc[header_row]
    table = table.rename(columns={"Broad Industry Group": "industry_group"})
    table = table.dropna(subset=["industry_group"]).reset_index(drop=True)

    return _wide_to_long(table, "industry_group", "industry_group", "businesses")


def get_businesses_by_legal_status(force_refresh: bool = False) -> pd.DataFrame:
    """Get annual business counts by legal status (Table 2.1).

    Args:
        force_refresh: Force re-download even if cached.

    Returns:
        DataFrame with columns: year, legal_status, sector, businesses.
    """
    url, _ = get_idbr_publication_url()
    path = download_file(url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)

    try:
        raw = pd.read_excel(path, sheet_name=_SHEET_LEGAL_STATUS, engine="openpyxl", header=None)
    except Exception as e:
        raise NISRADataError(f"Failed to parse IDBR legal status sheet: {e}") from e

    header_row = raw.index[raw[0] == "Legal Status"][0]
    table = raw.iloc[header_row + 1 :].copy()
    table.columns = raw.iloc[header_row]
    table = table.rename(columns={"Legal Status": "legal_status", "Public/Private Sector": "sector"})
    table = table.dropna(subset=["legal_status"]).reset_index(drop=True)

    year_cols = [c for c in table.columns if c not in ("legal_status", "sector")]
    long = table.melt(
        id_vars=["legal_status", "sector"], value_vars=year_cols, var_name="year", value_name="businesses"
    )
    long["year"] = pd.to_numeric(long["year"], errors="coerce").astype("Int64")
    long["businesses"] = pd.to_numeric(long["businesses"], errors="coerce")
    return long.dropna(subset=["year"]).reset_index(drop=True)


def get_businesses_by_lgd(force_refresh: bool = False) -> pd.DataFrame:
    """Get annual business counts by Local Government District (Table 3.1).

    Args:
        force_refresh: Force re-download even if cached.

    Returns:
        DataFrame with columns: year, lgd, businesses.
    """
    url, _ = get_idbr_publication_url()
    path = download_file(url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)

    try:
        raw = pd.read_excel(path, sheet_name=_SHEET_LGD, engine="openpyxl", header=None)
    except Exception as e:
        raise NISRADataError(f"Failed to parse IDBR LGD sheet: {e}") from e

    header_row = raw.index[raw[0] == "Local Government District"][0]
    table = raw.iloc[header_row + 1 :].copy()
    table.columns = raw.iloc[header_row]
    table = table.rename(columns={"Local Government District": "lgd"})
    table = table.dropna(subset=["lgd"]).reset_index(drop=True)

    return _wide_to_long(table, "lgd", "lgd", "businesses")


def get_latest_data(force_refresh: bool = False, level: str = "industry") -> pd.DataFrame:
    """Get the latest NI Business Register (IDBR) data.

    Args:
        force_refresh: Force re-download even if cached.
        level: Breakdown level - 'industry' (default), 'legal_status', or 'lgd'.

    Returns:
        DataFrame for the requested breakdown level. See
        :func:`get_businesses_by_industry`, :func:`get_businesses_by_legal_status`,
        and :func:`get_businesses_by_lgd` for column details.

    Raises:
        ValueError: If level is not one of 'industry', 'legal_status', or 'lgd'.

    Example:
        >>> df = get_latest_data()
        >>> 'businesses' in df.columns
        True
    """
    if level == "industry":
        return get_businesses_by_industry(force_refresh=force_refresh)
    if level == "legal_status":
        return get_businesses_by_legal_status(force_refresh=force_refresh)
    if level == "lgd":
        return get_businesses_by_lgd(force_refresh=force_refresh)
    raise ValueError(f"level must be 'industry', 'legal_status', or 'lgd', got {level!r}")


def validate_data(df: pd.DataFrame, level: str = "industry") -> bool:
    """Validate the IDBR DataFrame for internal consistency.

    Args:
        df: DataFrame as returned by :func:`get_latest_data`.
        level: Validation mode matching the breakdown level - 'industry'
            (default), 'legal_status', or 'lgd'.

    Returns:
        True if all checks pass.

    Raises:
        NISRAValidationError: Describing the first failing check.
        ValueError: If level is not a recognised value.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     "year": [2020, 2021], "industry_group": ["Retail", "Retail"],
        ...     "businesses": [5890.0, 6040.0],
        ... })
        >>> validate_data(df)
        True
    """
    if level not in ("industry", "legal_status", "lgd"):
        raise ValueError(f"level must be 'industry', 'legal_status', or 'lgd', got {level!r}")

    id_col = {"industry": "industry_group", "legal_status": "legal_status", "lgd": "lgd"}[level]
    required = {"year", id_col, "businesses"}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    min_year_expected = 2013 if level == "lgd" else 2010
    min_year = df["year"].min()
    if min_year > min_year_expected + 2:
        raise NISRAValidationError(f"Expected coverage from ~{min_year_expected}, earliest year is {min_year}")

    businesses = df["businesses"].dropna()
    if (businesses < 0).any():
        bad = businesses[businesses < 0]
        raise NISRAValidationError(f"businesses has {len(bad)} negative values: {bad.head().tolist()}")

    if df[id_col].nunique() < 3:
        raise NISRAValidationError(f"Too few distinct {id_col} categories: {df[id_col].nunique()}")

    return True
