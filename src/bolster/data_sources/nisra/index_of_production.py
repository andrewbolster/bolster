"""NISRA Index of Production (IOP) for Northern Ireland.

Provides quarterly index of manufacturing and production output, comparing
Northern Ireland against the UK average. Base year 2020=100.

Sectors covered (with approximate weights):
- Manufacturing (78.8%): food, drink, tobacco, textiles, chemicals, machinery, etc.
- Electricity, gas, steam (11.0%)
- Water supply and waste management (8.4%)
- Mining and quarrying (1.8%)

Data Source:
    **Statistics page**: https://www.nisra.gov.uk/statistics/economic-output/index-production
    The module scrapes this page to find the latest quarterly publication,
    then downloads the Excel tables file.

Update Frequency: Quarterly (published ~3 months after reference quarter)
Geographic Coverage: Northern Ireland and UK comparison
Base Year: 2020=100

Example:
    >>> from bolster.data_sources.nisra import index_of_production as iop
    >>> df = iop.get_latest_iop()
    >>> print(df.tail())

    >>> # NI vs UK production gap in latest quarter
    >>> latest = df.iloc[-1]
    >>> print(f"Q{latest['quarter']} {latest['year']}: NI={latest['ni_index']:.1f}, UK={latest['uk_index']:.1f}")
"""

import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

IOP_STATS_URL = "https://www.nisra.gov.uk/statistics/economic-output/index-production"
IOP_BASE_URL = "https://www.nisra.gov.uk"


def get_latest_iop_publication_url() -> tuple[str, int, int]:
    """Scrape the IOP statistics page to find the latest quarterly Excel file.

    Returns:
        Tuple of (excel_url, year, quarter)

    Raises:
        NISRADataNotFoundError: If publication cannot be found
    """
    try:
        response = session.get(IOP_STATS_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch IOP statistics page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    # Find latest publication link — pattern: "Index of Production ... Q# YYYY"
    # Pub list uses slugs like: /publications/index-production-iop-...-quarter-4-2025
    quarter_word = {"1": 1, "2": 2, "3": 3, "4": 4, "one": 1, "two": 2, "three": 3, "four": 4}
    quarter_slug_pat = re.compile(r"quarter[- _](\d+)[- _](\d{4})", re.IGNORECASE)

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "index-production-iop" not in href or "publications" not in href:
            continue

        match = quarter_slug_pat.search(href)
        if not match:
            continue

        q_str = match.group(1)
        quarter = quarter_word.get(q_str.lower(), int(q_str))
        year = int(match.group(2))
        pub_url = href if href.startswith("http") else f"{IOP_BASE_URL}{href}"

        try:
            pub_resp = session.get(pub_url, timeout=30)
            pub_resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to fetch publication page {pub_url}: {e}")
            continue

        pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
        for file_link in pub_soup.find_all("a", href=True):
            file_href = file_link["href"]
            file_text = file_link.get_text(strip=True).lower()
            if "iop" in file_text and "tables" in file_text and file_href.endswith(".xlsx"):
                excel_url = file_href if file_href.startswith("http") else f"{IOP_BASE_URL}{file_href}"
                logger.info(f"Found IOP Q{quarter} {year}: {excel_url}")
                return excel_url, year, quarter

    raise NISRADataNotFoundError("Could not find latest IOP publication")


def parse_iop_file(file_path: str | Path) -> pd.DataFrame:
    """Parse IOP Excel tables file into long-format DataFrame.

    Reads Table_1 which contains the headline NI and UK index series.

    Args:
        file_path: Path to downloaded IOP tables Excel file

    Returns:
        DataFrame with columns:
            - date: Timestamp (first day of quarter)
            - year: int
            - quarter: int (1-4)
            - quarter_label: str (e.g. "Q1 2025")
            - ni_index: float (NI Index of Production, 2020=100)
            - uk_index: float (UK Index of Production, 2020=100)

    Raises:
        NISRAValidationError: If file structure is unexpected
    """
    file_path = Path(file_path)

    try:
        df = pd.read_excel(file_path, sheet_name="Table_1", skiprows=2, header=0)
    except Exception as e:
        raise NISRAValidationError(f"Failed to read IOP file: {e}") from e

    # First column is quarter label, remaining are NI and UK
    col0 = df.columns[0]
    df = df.rename(columns={col0: "quarter_label"})

    # Strip trailing whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={"NI": "ni_index", "UK": "uk_index"})

    # Drop rows without a valid quarter label
    df = df[df["quarter_label"].notna()].copy()
    df["quarter_label"] = df["quarter_label"].astype(str).str.strip()

    # Keep only rows matching "Q# YYYY" pattern
    quarter_pattern = re.compile(r"^Q([1-4])\s+(\d{4})$")
    mask = df["quarter_label"].str.match(quarter_pattern)
    df = df[mask].copy()

    if df.empty:
        raise NISRAValidationError("No valid quarter rows found in IOP Table_1")

    # Parse year and quarter
    parsed = df["quarter_label"].str.extract(quarter_pattern)
    df["quarter"] = parsed[0].astype(int)
    df["year"] = parsed[1].astype(int)

    # Quarter start dates: Q1=Jan, Q2=Apr, Q3=Jul, Q4=Oct
    quarter_month = {1: 1, 2: 4, 3: 7, 4: 10}
    df["date"] = pd.to_datetime(df["year"].astype(str) + "-" + df["quarter"].map(quarter_month).astype(str) + "-01")

    df["ni_index"] = pd.to_numeric(df["ni_index"], errors="coerce")
    df["uk_index"] = pd.to_numeric(df["uk_index"], errors="coerce")

    df = df[["date", "year", "quarter", "quarter_label", "ni_index", "uk_index"]]
    df = df.sort_values("date").reset_index(drop=True)

    logger.info(
        f"Parsed IOP: {len(df)} quarters, {df['year'].min()} Q{df['quarter'].iloc[0]}-{df['year'].max()} Q{df['quarter'].iloc[-1]}"
    )
    return df


def get_latest_iop(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest NI Index of Production quarterly series.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns: date, year, quarter, quarter_label,
        ni_index, uk_index (base year 2020=100)

    Raises:
        NISRADataNotFoundError: If latest publication cannot be found
        NISRAValidationError: If file structure is unexpected

    Example:
        >>> df = get_latest_iop()
        >>> print(df.tail(4))
        >>> # NI outperforming UK?
        >>> latest = df.iloc[-1]
        >>> gap = latest['ni_index'] - latest['uk_index']
        >>> print(f"NI vs UK gap: {gap:+.1f} points")
    """
    excel_url, year, quarter = get_latest_iop_publication_url()
    logger.info(f"Downloading IOP Q{quarter} {year} from: {excel_url}")
    file_path = download_file(excel_url, cache_ttl_hours=24 * 90, force_refresh=force_refresh)
    return parse_iop_file(file_path)


def validate_iop_data(df: pd.DataFrame) -> bool:
    """Validate IOP DataFrame for basic integrity.

    Args:
        df: DataFrame from get_latest_iop()

    Returns:
        True if validation passes

    Raises:
        NISRAValidationError: If validation fails
    """
    required = {"date", "year", "quarter", "ni_index", "uk_index"}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if df["year"].min() > 2010:
        raise NISRAValidationError(f"Expected data from before 2010, got {df['year'].min()}")

    if (df["ni_index"] <= 0).any():
        raise NISRAValidationError("Non-positive NI index values found")

    return True


def get_iop_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter IOP data to a specific year.

    Args:
        df: DataFrame from get_latest_iop()
        year: Year to filter

    Returns:
        Filtered DataFrame (up to 4 quarters)

    Example:
        >>> df = get_latest_iop()
        >>> df_2024 = get_iop_by_year(df, 2024)
        >>> print(df_2024[['quarter_label', 'ni_index', 'uk_index']])
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_iop_growth(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate quarter-on-quarter and year-on-year growth rates.

    Args:
        df: DataFrame from get_latest_iop()

    Returns:
        DataFrame with additional columns:
            - ni_qoq: NI quarter-on-quarter % change
            - ni_yoy: NI year-on-year % change
            - uk_qoq: UK quarter-on-quarter % change
            - uk_yoy: UK year-on-year % change

    Example:
        >>> df = get_latest_iop()
        >>> growth = get_iop_growth(df)
        >>> print(growth[['quarter_label', 'ni_yoy', 'uk_yoy']].tail(8))
    """
    result = df.copy()
    result["ni_qoq"] = result["ni_index"].pct_change(1).mul(100).round(2)
    result["ni_yoy"] = result["ni_index"].pct_change(4).mul(100).round(2)
    result["uk_qoq"] = result["uk_index"].pct_change(1).mul(100).round(2)
    result["uk_yoy"] = result["uk_index"].pct_change(4).mul(100).round(2)
    return result
