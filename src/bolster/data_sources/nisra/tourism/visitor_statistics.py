"""NISRA Quarterly Tourism Visitor Statistics Data Source.

Provides access to quarterly visitor statistics for Northern Ireland covering
overnight trips, nights spent, and expenditure across geographic markets.

Data includes:
- Overnight trips by visitor origin (GB, Europe, N.America, ROI, NI residents)
- Nights spent (bednights) by market
- Visitor expenditure by market (£ millions)
- Reason for visit breakdowns (holiday, business, visiting friends/relatives)
- Historical trends from 2015 onwards

Data is compiled from multiple sources:
- Northern Ireland Passenger Survey (NIPS)
- Central Statistics Office Inbound Tourism data
- Continuous Household Survey
- Household Travel Survey

Data Source:
    **Mother Page**: https://www.nisra.gov.uk/publications/quarterly-tourism-statistics-publications

    This page lists quarterly tourism statistics publications. The module
    automatically scrapes to find the latest quarterly report Excel file.

Update Frequency: Quarterly (published ~6 weeks after quarter end)
Geographic Coverage: Northern Ireland (by visitor origin market)
Reference Period: Rolling 12-month and year-to-date

Example:
    >>> from bolster.data_sources.nisra.tourism import visitor_statistics
    >>> # Get latest visitor statistics by market
    >>> df = visitor_statistics.get_latest_visitor_statistics()
    >>> print(df.head())

    >>> # Get trips from Great Britain
    >>> gb_trips = df[df['market'] == 'Great Britain']['trips'].values[0]
    >>> print(f"GB trips (12-month): {gb_trips:,.0f}")

    >>> # Get total expenditure
    >>> total_spend = df['expenditure'].sum()
    >>> print(f"Total visitor spend: £{total_spend:.1f}M")
"""

import logging
import re
from typing import Optional, Tuple

import pandas as pd

from bolster.utils.web import session

from .._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

# Base URL for quarterly tourism statistics
TOURISM_PUBLICATIONS_URL = "https://www.nisra.gov.uk/publications/quarterly-tourism-statistics-publications"

# Market names as they appear in the data
MARKET_NAMES = [
    "Great Britain",
    "Other Europe",
    "North America",
    "Other Overseas",
    "Republic of Ireland",
    "NI Residents",
    "Total",
]


def get_latest_visitor_statistics_publication_url() -> Tuple[str, str]:
    """Scrape NISRA tourism publications page to find the latest quarterly file.

    The publications page directly lists Excel files for each quarter in the format:
    "NI Tourism Q3 2025" linking to .xlsx files.

    Returns:
        Tuple of (excel_file_url, publication_period) e.g. ("https://...", "Q3 2025")

    Raises:
        NISRADataNotFoundError: If publication or file not found
    """
    import requests
    from bs4 import BeautifulSoup

    try:
        # Use shared session with retry logic for resilient requests
        response = session.get(TOURISM_PUBLICATIONS_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise NISRADataNotFoundError(f"Failed to fetch tourism publications page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find latest quarterly tourism Excel file
    # Pattern: "NI Tourism Q3 2025" with href ending in .xlsx
    excel_files = []

    for link in soup.find_all("a", href=True):
        link_text = link.get_text(strip=True)
        href = link["href"]

        # Match Excel files with tourism in text
        if "tourism" in link_text.lower() and (href.endswith(".xls") or href.endswith(".xlsx")):
            if href.startswith("/"):
                href = f"https://www.nisra.gov.uk{href}"

            # Extract quarter/year from link text
            # Pattern: "NI Tourism Q3 2025" or "NI Tourism 2025 Quarter 3"
            q_match = re.search(r"Q(\d)\s+(\d{4})", link_text, re.IGNORECASE)
            if q_match:
                quarter = int(q_match.group(1))
                year = int(q_match.group(2))
                pub_period = f"Q{quarter} {year}"
            else:
                q_match = re.search(r"(\d{4})\s+Quarter\s+(\d)", link_text, re.IGNORECASE)
                if q_match:
                    year = int(q_match.group(1))
                    quarter = int(q_match.group(2))
                    pub_period = f"Q{quarter} {year}"
                else:
                    continue  # Skip if we can't extract period

            excel_files.append((href, year, quarter, pub_period))
            logger.info(f"Found tourism file: {link_text} -> {pub_period}")

    if not excel_files:
        raise NISRADataNotFoundError("Could not find quarterly tourism Excel files on publications page")

    # Sort by year and quarter descending, take the latest
    excel_files.sort(key=lambda x: (x[1], x[2]), reverse=True)
    latest_url, _, _, latest_period = excel_files[0]

    logger.info(f"Selected latest: {latest_period} from {latest_url}")
    return latest_url, latest_period


def _parse_visitor_statistics_file(
    file_path: str,
) -> pd.DataFrame:
    """Parse visitor statistics Excel file (Table 10 - comprehensive market data).

    Table 10 contains trips, nights, and expenditure by market for rolling 12-month
    periods. Structure:
    - Rows 0-14: Metadata and notes
    - Row 15: Headers with column descriptions
    - Rows 16-22: Data by market (GB, Other Europe, North America, etc.)

    The latest year's data is in columns 2, 4, 6 (trips, nights, spend).
    Previous year's data is in columns 1, 3, 5.

    Args:
        file_path: Path to downloaded Excel file

    Returns:
        DataFrame with columns: market, trips, nights, expenditure, period, year, quarter

    Raises:
        NISRAValidationError: If parsing fails or data is invalid
    """
    try:
        # Read entire sheet to find header row
        df_raw = pd.read_excel(
            file_path,
            sheet_name="Table 10",
            header=None,
        )
    except Exception as e:
        raise NISRAValidationError(f"Failed to read Table 10 from Excel file: {e}")

    # Find header row (contains "Variable" or "Overnight Trips")
    header_row_idx = None
    for idx in range(len(df_raw)):
        row_text = " ".join(str(v) for v in df_raw.iloc[idx].values if pd.notna(v))
        if "Variable" in row_text or "Overnight Trips" in row_text:
            header_row_idx = idx
            break

    if header_row_idx is None:
        raise NISRAValidationError("Could not identify header row in Table 10")

    # Parse the header to understand column structure
    # Typical format: col 1/2 = trips (prev/curr), col 3/4 = nights, col 5/6 = spend
    # We want the latest year's data (higher column indices)
    header_row = df_raw.iloc[header_row_idx]
    headers = [str(v).strip() if pd.notna(v) else "" for v in header_row.values]

    # Find column indices for latest year data by finding highest year in headers
    trips_col = None
    nights_col = None
    spend_col = None
    year = None

    # First pass: find all years mentioned in headers
    all_years = set()
    for h in headers:
        # Match both 4-digit (2025) and 2-digit (25) years
        for match in re.findall(r"\b(20\d{2})\b", h):
            all_years.add(int(match))
        for match in re.findall(r"\b(\d{2})\b", h):
            if 20 <= int(match) <= 30:  # Reasonable range for 2-digit years
                all_years.add(2000 + int(match))

    latest_year = max(all_years) if all_years else None
    year = latest_year

    # Find columns for latest year (match either full year or 2-digit suffix)
    latest_year_patterns = []
    if latest_year:
        latest_year_patterns = [str(latest_year), str(latest_year)[-2:]]

    for i, h in enumerate(headers):
        h_lower = h.lower()
        is_latest = any(p in h for p in latest_year_patterns)

        if "overnight trips" in h_lower and is_latest:
            trips_col = i
        elif "overnights" in h_lower and is_latest:
            nights_col = i
        elif "spend" in h_lower and is_latest:
            spend_col = i

    # Fallback: use fixed columns if header parsing fails
    # Column 2 = trips latest, 4 = nights latest, 6 = spend latest
    if trips_col is None:
        trips_col = 2
    if nights_col is None:
        nights_col = 4
    if spend_col is None:
        spend_col = 6 if len(headers) > 6 else 5

    # Market name mappings (handling variations in source data)
    market_mappings = {
        "great britain": "Great Britain",
        "gb": "Great Britain",
        "other europe": "Other Europe",
        "north america": "North America",
        "other overseas": "Other Overseas",
        "roi": "Republic of Ireland",
        "republic of ireland": "Republic of Ireland",
        "ni": "NI Residents",
        "ni residents": "NI Residents",
        "total": "Total",
    }

    records = []

    # Parse data rows (after header)
    for idx in range(header_row_idx + 1, len(df_raw)):
        row = df_raw.iloc[idx]
        first_cell = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""

        # Skip empty rows
        if not first_cell:
            continue

        # Match market name
        market_key = first_cell.lower().strip()
        market = market_mappings.get(market_key)

        if market is None:
            # Try partial matching
            for key, value in market_mappings.items():
                if key in market_key:
                    market = value
                    break

        if market is None:
            continue

        # Extract values from identified columns
        try:
            trips = float(row.iloc[trips_col]) if pd.notna(row.iloc[trips_col]) else 0
            nights = float(row.iloc[nights_col]) if pd.notna(row.iloc[nights_col]) else 0
            spend = float(row.iloc[spend_col]) if pd.notna(row.iloc[spend_col]) else 0
        except (ValueError, TypeError, IndexError):
            continue

        records.append(
            {
                "market": market,
                "trips": trips * 1000,  # Convert from thousands
                "nights": nights * 1000,  # Convert from thousands
                "expenditure": spend,  # Already in £ millions
                "period": "12-month rolling",
                "year": year,
                "quarter": None,
            }
        )

    if not records:
        raise NISRAValidationError("No visitor statistics data found in Table 10")

    df = pd.DataFrame(records)
    return df


def get_latest_visitor_statistics(
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the latest quarterly visitor statistics by market.

    Retrieves comprehensive visitor statistics including trips, nights spent,
    and expenditure broken down by visitor origin market.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - market: Visitor origin (Great Britain, Other Europe, etc.)
            - trips: Number of overnight trips
            - nights: Number of nights spent
            - expenditure: Visitor spending (£ millions)
            - period: Measurement period (12-month rolling, year-to-date)
            - year: Reference year
            - quarter: Reference quarter

    Raises:
        NISRADataNotFoundError: If publication not found
        NISRAValidationError: If data parsing fails

    Example:
        >>> df = get_latest_visitor_statistics()
        >>> gb = df[df['market'] == 'Great Britain'].iloc[0]
        >>> print(f"GB: {gb['trips']:,.0f} trips, £{gb['expenditure']:.1f}M spent")
    """
    excel_url, pub_period = get_latest_visitor_statistics_publication_url()

    logger.info(f"Downloading visitor statistics for {pub_period}: {excel_url}")

    cache_ttl = 0 if force_refresh else 24
    file_path = download_file(excel_url, cache_ttl_hours=cache_ttl)

    df = _parse_visitor_statistics_file(file_path)

    # Validate data
    if not validate_visitor_statistics(df):
        raise NISRAValidationError("Visitor statistics validation failed")

    return df


def validate_visitor_statistics(df: pd.DataFrame) -> bool:
    """Validate visitor statistics data integrity.

    Args:
        df: DataFrame to validate

    Returns:
        True if valid, False otherwise
    """
    if df.empty:
        logger.warning("Visitor statistics DataFrame is empty")
        return False

    required_cols = {"market", "trips", "nights", "expenditure"}
    if not required_cols.issubset(df.columns):
        logger.warning(f"Missing required columns: {required_cols - set(df.columns)}")
        return False

    # Check for reasonable value ranges
    if (df["trips"] < 0).any():
        logger.warning("Negative trip values found")
        return False

    if (df["expenditure"] < 0).any():
        logger.warning("Negative expenditure values found")
        return False

    # Check we have multiple markets
    if df["market"].nunique() < 3:
        logger.warning(f"Too few markets: {df['market'].nunique()}")
        return False

    return True


def get_visitor_statistics_by_market(df: pd.DataFrame, market: str) -> Optional[pd.Series]:
    """Get visitor statistics for a specific market.

    Args:
        df: Visitor statistics DataFrame
        market: Market name (e.g., "Great Britain", "Republic of Ireland")

    Returns:
        Series with statistics for the market, or None if not found

    Example:
        >>> df = get_latest_visitor_statistics()
        >>> gb = get_visitor_statistics_by_market(df, "Great Britain")
        >>> if gb is not None:
        ...     print(f"GB trips: {gb['trips']:,.0f}")
    """
    matches = df[df["market"].str.lower() == market.lower()]
    if matches.empty:
        return None
    return matches.iloc[0]


def get_total_visitor_statistics(df: pd.DataFrame) -> Optional[pd.Series]:
    """Get total visitor statistics across all markets.

    Args:
        df: Visitor statistics DataFrame

    Returns:
        Series with total statistics, or None if not found
    """
    return get_visitor_statistics_by_market(df, "Total")


def get_domestic_vs_external(df: pd.DataFrame) -> pd.DataFrame:
    """Compare domestic (NI residents) vs external visitor statistics.

    Args:
        df: Visitor statistics DataFrame

    Returns:
        DataFrame with domestic and external totals and percentages

    Example:
        >>> df = get_latest_visitor_statistics()
        >>> comparison = get_domestic_vs_external(df)
        >>> print(comparison)
    """
    domestic = df[df["market"] == "NI Residents"]
    external = df[~df["market"].isin(["NI Residents", "Total"])]

    if domestic.empty:
        return pd.DataFrame()

    domestic_stats = domestic.iloc[0]
    external_total = external.agg({"trips": "sum", "nights": "sum", "expenditure": "sum"})

    total_trips = domestic_stats["trips"] + external_total["trips"]
    total_expenditure = domestic_stats["expenditure"] + external_total["expenditure"]

    result = pd.DataFrame(
        [
            {
                "category": "Domestic (NI)",
                "trips": domestic_stats["trips"],
                "nights": domestic_stats["nights"],
                "expenditure": domestic_stats["expenditure"],
                "trips_pct": domestic_stats["trips"] / total_trips * 100 if total_trips > 0 else 0,
                "expenditure_pct": domestic_stats["expenditure"] / total_expenditure * 100
                if total_expenditure > 0
                else 0,
            },
            {
                "category": "External",
                "trips": external_total["trips"],
                "nights": external_total["nights"],
                "expenditure": external_total["expenditure"],
                "trips_pct": external_total["trips"] / total_trips * 100 if total_trips > 0 else 0,
                "expenditure_pct": external_total["expenditure"] / total_expenditure * 100
                if total_expenditure > 0
                else 0,
            },
        ]
    )

    return result


def get_expenditure_per_trip(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate average expenditure per trip by market.

    Args:
        df: Visitor statistics DataFrame

    Returns:
        DataFrame with market and expenditure_per_trip columns

    Example:
        >>> df = get_latest_visitor_statistics()
        >>> spend = get_expenditure_per_trip(df)
        >>> print(spend.sort_values('expenditure_per_trip', ascending=False))
    """
    result = df[df["market"] != "Total"].copy()
    # Expenditure is in millions, trips are individual
    result["expenditure_per_trip"] = (result["expenditure"] * 1_000_000 / result["trips"]).round(2)
    return result[["market", "trips", "expenditure", "expenditure_per_trip"]]


def get_nights_per_trip(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate average nights per trip by market.

    Args:
        df: Visitor statistics DataFrame

    Returns:
        DataFrame with market and nights_per_trip columns

    Example:
        >>> df = get_latest_visitor_statistics()
        >>> duration = get_nights_per_trip(df)
        >>> print(duration.sort_values('nights_per_trip', ascending=False))
    """
    result = df[df["market"] != "Total"].copy()
    result["nights_per_trip"] = (result["nights"] / result["trips"]).round(2)
    return result[["market", "trips", "nights", "nights_per_trip"]]


def get_market_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Get summary of all markets with derived metrics.

    Args:
        df: Visitor statistics DataFrame

    Returns:
        DataFrame with market summary including percentages and per-trip metrics

    Example:
        >>> df = get_latest_visitor_statistics()
        >>> summary = get_market_summary(df)
        >>> print(summary)
    """
    total = get_total_visitor_statistics(df)
    if total is None:
        return df

    result = df[df["market"] != "Total"].copy()

    # Add percentage columns
    result["trips_pct"] = (result["trips"] / total["trips"] * 100).round(1)
    result["nights_pct"] = (result["nights"] / total["nights"] * 100).round(1)
    result["expenditure_pct"] = (result["expenditure"] / total["expenditure"] * 100).round(1)

    # Add per-trip metrics
    result["nights_per_trip"] = (result["nights"] / result["trips"]).round(2)
    result["expenditure_per_trip"] = (result["expenditure"] * 1_000_000 / result["trips"]).round(2)

    return result
