"""Northern Ireland House Price Index Data.

Provides access to quarterly house price index, standardised prices, and sales volumes
for Northern Ireland with breakdowns by:
- Property type (Detached, Semi-Detached, Terrace, Apartment)
- New vs Existing dwellings
- Local Government District (11 LGDs)
- Urban vs Rural areas

Data Source:
    **Publication Page**: https://www.finance-ni.gov.uk/publications/ni-house-price-index-statistical-reports

    The module automatically scrapes this page to find the latest quarterly Excel file,
    which contains multiple worksheets with different data breakdowns.

Update Frequency: Quarterly
Geographic Coverage: Northern Ireland
Reference Period: Q1 2005 - present
Index Base: Q1 2023 = 100

See [here](https://andrewbolster.info/2022/03/NI-House-Price-Index.html) for more details.

Example:
    >>> from bolster.data_sources.ni_house_price_index import get_hpi_trends, get_sales_volumes
    >>> # Get house price index trends over time
    >>> hpi = get_hpi_trends()
    >>> print(hpi[['Period', 'NI House Price Index', 'Annual Change']].tail())

    >>> # Get property sales volumes by type
    >>> sales = get_sales_volumes()
    >>> print(sales[['Period', 'Detached', 'Semi-Detached', 'Total']].tail())
"""

import hashlib
import logging
import re
import warnings
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import bs4
import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Data source URL
DEFAULT_URL = "https://www.finance-ni.gov.uk/publications/ni-house-price-index-statistical-reports"

# Cache directory for downloaded files
CACHE_DIR = Path.home() / ".cache" / "bolster" / "ni_hpi"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Registry of table-specific transformation functions
TABLE_TRANSFORMATION_MAP = {}


class NIHPIDataError(Exception):
    """Base exception for NI HPI data errors."""

    pass


class NIHPIDataNotFoundError(NIHPIDataError):
    """Data file not available."""

    pass


def _hash_url(url: str) -> str:
    """Generate a safe filename from a URL."""
    return hashlib.md5(url.encode()).hexdigest()


def _get_cached_file(url: str, cache_ttl_hours: int = 24) -> Optional[Path]:
    """Return cached file if exists and fresh, else None.

    Args:
        url: URL of the file
        cache_ttl_hours: Cache validity in hours

    Returns:
        Path to cached file if valid, None otherwise
    """
    url_hash = _hash_url(url)
    ext = Path(url).suffix or ".xlsx"
    cache_path = CACHE_DIR / f"{url_hash}{ext}"

    if cache_path.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        if age.total_seconds() < cache_ttl_hours * 3600:
            logger.info(f"Using cached file: {cache_path}")
            return cache_path

    return None


def _download_file(url: str, cache_ttl_hours: int = 24, force_refresh: bool = False) -> Path:
    """Download a file with caching support.

    Args:
        url: URL to download
        cache_ttl_hours: Cache validity in hours (default: 24)
        force_refresh: Force re-download even if cached

    Returns:
        Path to downloaded file

    Raises:
        NIHPIDataNotFoundError: If download fails
    """
    if not force_refresh:
        cached = _get_cached_file(url, cache_ttl_hours)
        if cached:
            return cached

    url_hash = _hash_url(url)
    ext = Path(url).suffix or ".xlsx"
    cache_path = CACHE_DIR / f"{url_hash}{ext}"

    try:
        logger.info(f"Downloading {url}")
        response = session.get(url, timeout=60)
        response.raise_for_status()

        cache_path.write_bytes(response.content)
        logger.info(f"Saved to {cache_path}")
        return cache_path

    except Exception as e:
        raise NIHPIDataNotFoundError(f"Failed to download {url}: {e}") from e


def clear_cache():
    """Clear all cached HPI data files."""
    for file in CACHE_DIR.glob("*"):
        if file.is_file():
            file.unlink()
            logger.info(f"Deleted {file}")


def get_source_url(base_url=DEFAULT_URL) -> str:
    """Find the URL of the latest HPI Excel file from the publication page.

    Args:
        base_url: URL of the publication listing page

    Returns:
        URL of the Excel file

    Raises:
        NIHPIDataNotFoundError: If no Excel file found
    """
    try:
        response = session.get(base_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NIHPIDataNotFoundError(f"Failed to fetch publication page: {e}") from e

    base_soup = bs4.BeautifulSoup(response.content, features="html.parser")

    for a in base_soup.find_all("a"):
        if a.attrs.get("href", "").lower().endswith("xlsx"):
            source_url = a.attrs["href"]
            if source_url.startswith("/"):  # Relative URL
                source_url = urlparse(base_url)._replace(path=source_url).geturl()
            logger.info(f"Found HPI Excel file: {source_url}")
            return source_url

    raise NIHPIDataNotFoundError(f"Could not find Excel source file on {base_url}")


def pull_sources(
    base_url: str = DEFAULT_URL,
    force_refresh: bool = False,
    cache_ttl_hours: int = 24 * 7,  # Weekly cache (quarterly data)
) -> dict[str, pd.DataFrame]:
    """Pull raw NI House Price Index Excel from finance-ni.gov.uk.

    Downloads the latest HPI Excel file and returns all worksheets as a dictionary
    of DataFrames. Files are cached locally to avoid repeated downloads.

    Args:
        base_url: URL of the publication listing page
        force_refresh: If True, bypass cache and download fresh data
        cache_ttl_hours: Cache validity in hours (default: 7 days)

    Returns:
        Dictionary mapping sheet names to raw DataFrames

    Raises:
        NIHPIDataNotFoundError: If source file not found or download fails
    """
    source_url = get_source_url(base_url)

    # Download with caching
    file_path = _download_file(source_url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    # Load all worksheets
    ni_house_price_index = pd.read_excel(file_path, sheet_name=None)
    logger.info(f"Loaded {len(ni_house_price_index)} sheets from HPI Excel file")

    return ni_house_price_index


def basic_cleanup(df: pd.DataFrame, offset=1) -> pd.DataFrame:
    """Generic cleanup operations for NI HPI data.

    Operations performed:

    - Re-header from Offset row and translate table to eliminate incorrect headers
    - Remove any columns with 'Nan' or 'None' in the given offset-row
    - If 'NI' appears and all the values are 100, remove it
    - Remove any rows below and including the first 'all nan' row (gets most tail-notes)
    - If 'Sale Year','Sale Quarter' appear in the columns, replace with 'Year','Quarter' respectively
    - For Year; forward fill any none/nan values
    - If Year/Quarter appear, add a new composite 'Period' column with a PeriodIndex columns representing the year/quarter (i.e. 2022-Q1)
    - Reset and drop the index
    - Attempt to infer the new/current column object types

    Args:
        df: DataFrame to clean
        offset: Row offset to find headers

    Returns:
        Cleaned DataFrame
    """
    df = df.copy()
    # Re-header from row 1 (which was row 3 in excel)
    new_header = df.iloc[offset]
    df = df.iloc[offset + 1 :]
    df.columns = new_header

    # remove 'NaN' trailing columns
    df = df[df.columns[pd.notna(df.columns)]]

    # 'NI' is a usually hidden column that appears to be a checksum;
    # if it's all there and all 100, remove it, otherwise, complain.
    # (Note, need to change this 'if' logic to just 'if there's a
    # column with all 100's, but cross that bridge later)
    if "NI" in df:
        assert df["NI"].all() and df["NI"].mean() == 100, "Not all values in df['NI'] == 100"
        df = df.drop("NI", axis=1)

    # Strip rows below the first all-nan row, if there is one
    # (Otherwise this truncates the tables as there is no
    # idxmax in the table of all 'false's)
    if any(df.isna().all(axis=1)):
        idx_first_bad_row = df.isna().all(axis=1).idxmax()
        df = df.loc[: idx_first_bad_row - 1]

    # By Inspection, other tables use 'Sale Year' and 'Sale Quarter'
    if set(df.keys()).issuperset({"Sale Year", "Sale Quarter"}):
        df = df.rename(columns={"Sale Year": "Year", "Sale Quarter": "Quarter"})

    # For 'Year','Quarter' indexed pages, there is an implied Year
    # in Q2/4, so fill it downwards
    if set(df.keys()).issuperset({"Year", "Quarter"}):
        df["Year"] = df["Year"].astype(float).ffill().astype(int)
        df = df.dropna(how="any", subset=["Year", "Quarter"])

        # In Pandas we can represent Y/Q combinations as proper datetimes
        # https://stackoverflow.com/questions/53898482/clean-way-to-convert-quarterly-periods-to-datetime-in-pandas
        df.insert(
            loc=0,
            column="Period",
            value=pd.PeriodIndex(df.apply(lambda r: f"{r.Year}-{r.Quarter}", axis=1), freq="Q"),
        )

    # reset index, try to fix dtypes, etc, (this should be the last
    # operation before returning!
    return df.reset_index(drop=True).infer_objects()


def cleanup_contents(df: pd.DataFrame) -> pd.DataFrame:
    """Fix Contents table of NI HPI Stats.

    - Shift/rebuild headers
    - Strip Figures because they're gonna be broken anyway

    Args:
        df: Raw DataFrame from Excel

    Returns:
        Cleaned DataFrame
    """
    new_header = df.iloc[0]
    df = df[1:].copy()
    df.columns = [*new_header[:-1], "Title"]
    # df['Worksheet Name'] = df['Worksheet Name'].str.replace('Figure', 'Fig')
    return df[df["Worksheet Name"].str.startswith("Table")]


TABLE_TRANSFORMATION_MAP["Contents"] = cleanup_contents

# Table 1: NI HPI Trends (offset=2 due to "Back to contents" row)
TABLE_TRANSFORMATION_MAP["Table 1"] = partial(basic_cleanup, offset=2)


def cleanup_price_by_property_type_agg(df: pd.DataFrame, offset: int = 2) -> pd.DataFrame:
    """NI HPI & Standardised Price Statistics by Property Type (Aggregate Table).

    Standard cleanup with a split to remove trailing index date data.

    Args:
        df: Raw DataFrame from Excel
        offset: Row offset to find headers (default: 2)

    Returns:
        Cleaned DataFrame
    """
    df = basic_cleanup(df, offset=offset)
    df.columns = [c.split("\n")[0] for c in df.columns]
    return df


# Table 2: NI HPI & Standardised Price Statistics by Property Type (offset=2)
TABLE_TRANSFORMATION_MAP["Table 2"] = partial(cleanup_price_by_property_type_agg, offset=2)


def cleanup_price_by_property_type(df: pd.DataFrame, offset: int = 2) -> pd.DataFrame:
    """NI HPI & Standardised Price Statistics by Property Type (Per Class).

    Standard cleanup, removing the property class from the table columns.

    Args:
        df: Raw DataFrame from Excel
        offset: Row offset to find headers (default: 2)

    Returns:
        Cleaned DataFrame with simplified column names
    """
    df = basic_cleanup(df, offset=offset)
    new_columns = []
    for c in df.columns:
        if c.endswith("Price Index"):
            new_columns.append("Index")
        elif c.endswith("Standardised Price"):
            new_columns.append("Price")
        else:
            new_columns.append(c)

    df.columns = new_columns

    return df


# Table 2a-2d: NI {property type} Property Price Index (offset=2)
TABLE_TRANSFORMATION_MAP[re.compile("Table 2[a-z]")] = partial(cleanup_price_by_property_type, offset=2)

# Table 3: NI HPI & Standardised Price Statistics by New/Existing Resold Dwelling Type (offset=2)
TABLE_TRANSFORMATION_MAP["Table 3"] = partial(cleanup_price_by_property_type_agg, offset=2)
TABLE_TRANSFORMATION_MAP[re.compile("Table 3[a-z]")] = partial(
    cleanup_price_by_property_type_agg, offset=2
)  # Table 3c Overridden below


def cleanup_with_munged_quarters_and_total_rows(df: pd.DataFrame, offset=3) -> pd.DataFrame:
    """Number of Verified Residential Property Sales.

    - Regex 'Quarter X' to 'QX' in future 'Sales Quarter' column
    - Drop Year Total rows
    - Clear any Newlines from the future 'Sales Year' column
    - Call ``basic_cleanup`` with offset=3

    Args:
        df: Raw DataFrame from Excel
        offset: Number of header rows to skip during cleanup

    Returns:
        Cleaned DataFrame
    """
    df = df.copy()
    df.iloc[:, 1] = df.iloc[:, 1].str.replace("Quarter ([1-4])", r"Q\1", regex=True)
    df = df[~df.iloc[:, 1].str.contains("Total", na=False)]
    # Lose the year new-lines (needs astype because non str lines are
    # correctly inferred to be ints, so .str methods nan-out
    with pd.option_context("mode.chained_assignment", None):
        df.iloc[:, 0] = df.iloc[:, 0].astype(str).str.replace("\n", "")

    return basic_cleanup(df, offset=offset)


TABLE_TRANSFORMATION_MAP["Table 3c"] = partial(cleanup_with_munged_quarters_and_total_rows, offset=4)

# Table 4: Number of Verified Residential Property Sales
TABLE_TRANSFORMATION_MAP["Table 4"] = cleanup_with_munged_quarters_and_total_rows


def cleanup_with_LGDs(df: pd.DataFrame, offset: int = 2) -> pd.DataFrame:
    """Standardised House Price & Index for each Local Government District.

    Builds multi-index of LGD / Metric [Index,Price] for the 11 NI LGDs.

    Args:
        df: Raw DataFrame from Excel
        offset: Row offset to find headers (default: 2)

    Returns:
        Cleaned DataFrame with LGD multi-index columns
    """
    # Basic Cleanup first
    df = basic_cleanup(df, offset=offset)
    # Build multi-index of LGD / Metric [Index,Price]
    # Two inner-columns per LGD
    lgds = (
        df.columns[3:]
        .str.replace(" Standardised HPI", " HPI")
        .str.replace(" HPI", "")
        .str.replace(" Standardised Price", "")
        .unique()
    )
    df.columns = [
        *df.columns[:3],
        *pd.MultiIndex.from_product([lgds, ["Index", "Price"]], names=["LGD", "Metric"]),
    ]
    return df


# Table 5: Standardised House Price & Index for each Local Government District (offset=2)
TABLE_TRANSFORMATION_MAP["Table 5"] = partial(cleanup_with_LGDs, offset=2)


def cleanup_combined_year_quarter(df: pd.DataFrame, offset: int = 2) -> pd.DataFrame:
    """Cleanup tables with combined 'Q1 2005' year/quarter format.

    Parses the combined format into Period, Year, and Quarter columns
    for consistency with other tables.

    Args:
        df: Raw DataFrame from Excel
        offset: Row offset to find headers (default: 2)

    Returns:
        Cleaned DataFrame with Period, Year, Quarter columns
    """
    df = df.copy()

    # Re-header from offset row
    new_header = df.iloc[offset]
    df = df.iloc[offset + 1 :]
    df.columns = new_header

    # Find the year/quarter column (first column, may be named NaN or various things)
    yq_col = df.columns[0]

    # If first column header is NaN, rename it to "Period_Raw"
    if pd.isna(yq_col):
        df = df.rename(columns={yq_col: "Period_Raw"})
        yq_col = "Period_Raw"

    # Remove NaN trailing columns (but keep the year/quarter column)
    valid_cols = [c for c in df.columns if pd.notna(c) or c == yq_col]
    df = df[valid_cols]

    # Remove any 'Total' rows
    df = df[~df[yq_col].astype(str).str.contains("Total", na=False)]

    # Remove rows where the quarter column is NaN or empty
    df = df[df[yq_col].notna() & (df[yq_col] != "")]

    # Filter to only rows matching "Q1 2005" pattern (removes footer notes)
    df = df[df[yq_col].astype(str).str.match(r"^Q\d\s+\d{4}$")]

    # Parse "Q1 2005" format into Period
    # Convert "Q1 2005" -> "2005Q1" for pandas Period parsing
    period_str = df[yq_col].astype(str).str.replace(r"(Q\d)\s+(\d+)", r"\2\1", regex=True)
    df.insert(0, "Period", pd.PeriodIndex(period_str, freq="Q"))

    # Extract Year and Quarter from Period for consistency
    df.insert(1, "Year", df["Period"].dt.year)
    df.insert(2, "Quarter", "Q" + df["Period"].dt.quarter.astype(str))

    # Drop the original combined column
    df = df.drop(columns=[yq_col])

    # Reset index and infer types
    return df.reset_index(drop=True).infer_objects()


# Table 5a: Number of Verified Residential Property Sales by Local Government District (offset=2)
# Uses combined "Q1 2005" format
TABLE_TRANSFORMATION_MAP["Table 5a"] = partial(cleanup_combined_year_quarter, offset=2)

# Table 6: Standardised House Price & Index for all Urban and Rural areas in NI (offset=2)
TABLE_TRANSFORMATION_MAP["Table 6"] = partial(basic_cleanup, offset=2)


def cleanup_missing_year_quarter(df: pd.DataFrame, offset: int = 1) -> pd.DataFrame:
    """Standardised House Price & Index for Rural Areas by drive times.

    Inserts Year/Quarter headers and cleans normally.

    Args:
        df: Raw DataFrame from Excel
        offset: Row offset to find headers (default: 1)

    Returns:
        Cleaned DataFrame
    """
    df = df.copy()
    df.iloc[offset, 0] = "Year"
    df.iloc[offset, 1] = "Quarter"
    return basic_cleanup(df, offset=offset)


# Table 7: Standardised House Price & Index for Rural Areas by drive times (offset=1)
TABLE_TRANSFORMATION_MAP["Table 7"] = partial(cleanup_missing_year_quarter, offset=1)

# Table 8: Number of Verified Residential Property Sales in urban/rural areas (offset=2)
# Uses combined "Q1 2015" format (data starts 2015)
TABLE_TRANSFORMATION_MAP["Table 8"] = partial(cleanup_combined_year_quarter, offset=2)

# Table 9: NI Average Sales Prices (offset=1 - different structure with "Back to contents" in row 0)
TABLE_TRANSFORMATION_MAP["Table 9"] = partial(basic_cleanup, offset=1)
TABLE_TRANSFORMATION_MAP[re.compile("Table 9[a-z]")] = partial(cleanup_missing_year_quarter, offset=1)

# Table 10a-k: Number of Verified Residential Property Sales by Type in each LGD (offset=2)
# Uses combined "Q1 2005" format
TABLE_TRANSFORMATION_MAP[re.compile("Table 10[a-z]")] = partial(cleanup_combined_year_quarter, offset=2)


def transform_sources(source_df: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Transform all raw tables using registered transformation functions.

    Args:
        source_df: Dictionary of raw DataFrames from Excel file

    Returns:
        Dictionary of cleaned/transformed DataFrames

    Raises:
        RuntimeError: If transformation fails for any table
    """
    dest_df = {}
    for table_key, table_transformer in TABLE_TRANSFORMATION_MAP.items():
        try:
            table = None  # Catch looping variables in debug
            if isinstance(table_key, re.Pattern):
                for table in source_df:
                    if table_key.match(table):
                        dest_df[table] = table_transformer(source_df[table])
            else:
                dest_df[table_key] = table_transformer(source_df[table_key])
            logger.debug(f"Transformed {table_key}")
        except Exception as e:
            raise RuntimeError(f"Error transforming {table_key} / {table_transformer}") from e

    return dest_df


# =============================================================================
# Public API - Entry Points
# =============================================================================


def get_all_tables(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Get all HPI tables as a dictionary of DataFrames.

    This is the main entry point for accessing NI House Price Index data.
    Returns all available tables in a dictionary keyed by table name.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        Dictionary mapping table names to cleaned DataFrames.
        Available tables include:
            - Table 1: NI HPI Trends
            - Table 2: HPI by Property Type (summary)
            - Table 2a-d: HPI by Property Type (detailed)
            - Table 3: HPI by New/Existing Dwelling
            - Table 3a-c: New/Existing Dwelling details
            - Table 4: Sales Volumes by Property Type
            - Table 5: HPI by Local Government District
            - Table 5a: Sales Volumes by LGD
            - Table 6: HPI by Urban/Rural
            - Table 7: HPI by Rural Drive Times
            - Table 8: Sales Volumes by Urban/Rural/Drive Times
            - Table 9: Average Sale Prices
            - Table 9a-d: Average Prices by Property Type
            - Table 10a-k: Sales Volumes by Property Type per LGD

    Example:
        >>> tables = get_all_tables()
        >>> print(tables.keys())
        >>> # Access specific table
        >>> hpi_trends = tables['Table 1']
    """
    source_dfs = pull_sources(force_refresh=force_refresh)
    return transform_sources(source_dfs)


def get_hpi_trends(force_refresh: bool = False) -> pd.DataFrame:
    """Get NI House Price Index trends over time (Table 1).

    Returns quarterly HPI values, standardised prices, and percentage changes
    from Q1 2005 to present.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - Period: Quarterly period (e.g., 2005Q1)
            - Year: Year
            - Quarter: Quarter (Q1-Q4)
            - NI House Price Index: Index value (Q1 2023 = 100)
            - NI House Standardised Price: Price in GBP
            - Quarterly Change: Percentage change from previous quarter
            - Annual Change: Percentage change from same quarter previous year

    Example:
        >>> hpi = get_hpi_trends()
        >>> # Get latest quarter
        >>> print(hpi.tail(1))
        >>> # Plot index over time
        >>> hpi.plot(x='Period', y='NI House Price Index')
    """
    tables = get_all_tables(force_refresh=force_refresh)
    return tables.get("Table 1")


def get_sales_volumes(force_refresh: bool = False) -> pd.DataFrame:
    """Get property sales volumes by type (Table 4).

    Returns quarterly counts of verified residential property sales
    broken down by property type.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - Period: Quarterly period
            - Year: Year
            - Quarter: Quarter
            - Detached: Detached house sales
            - Semi-Detached: Semi-detached sales
            - Terrace: Terraced house sales
            - Apartment: Apartment sales
            - Total: Total sales

    Example:
        >>> sales = get_sales_volumes()
        >>> # Total sales per year
        >>> annual = sales.groupby('Year')['Total'].sum()
    """
    tables = get_all_tables(force_refresh=force_refresh)
    return tables.get("Table 4")


def get_average_prices(force_refresh: bool = False) -> pd.DataFrame:
    """Get NI average sale prices over time (Table 9).

    Returns simple mean, median, and standardised (HPI) prices
    for all property sales.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - Period: Quarterly period
            - Year: Year
            - Quarter: Quarter
            - Simple Mean: Average sale price
            - Simple Median: Median sale price
            - Standardised Price (HPI): Quality-adjusted price

    Example:
        >>> prices = get_average_prices()
        >>> # Current median price
        >>> latest = prices.iloc[-1]['Simple Median']
    """
    tables = get_all_tables(force_refresh=force_refresh)
    return tables.get("Table 9")


def get_hpi_by_lgd(force_refresh: bool = False) -> pd.DataFrame:
    """Get HPI and prices for each Local Government District (Table 5).

    Returns standardised house prices and HPI for all 11 NI LGDs.

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with multi-index columns:
            - Period, Year, Quarter: Time dimensions
            - {LGD_Name}: For each of the 11 LGDs
                - Index: HPI value
                - Price: Standardised price

        LGDs include: Antrim and Newtownabbey, Ards and North Down,
        Armagh City Banbridge and Craigavon, Belfast, Causeway Coast and Glens,
        Derry City and Strabane, Fermanagh and Omagh, Lisburn and Castlereagh,
        Mid and East Antrim, Mid Ulster, Newry Mourne and Down

    Example:
        >>> lgd = get_hpi_by_lgd()
        >>> # Belfast prices
        >>> belfast = lgd[['Period', 'Belfast']]
    """
    tables = get_all_tables(force_refresh=force_refresh)
    return tables.get("Table 5")


def get_hpi_by_property_type(force_refresh: bool = False) -> pd.DataFrame:
    """Get HPI summary by property type (Table 2).

    Returns latest quarter's HPI and price statistics broken down
    by property type (Detached, Semi-Detached, Terrace, Apartment).

    Args:
        force_refresh: If True, bypass cache and download fresh data

    Returns:
        DataFrame with columns:
            - Property Type: Type of property
            - Index: HPI value
            - Percentage Change on Previous Quarter
            - Percentage Change over 12 months
            - Standardised Price

    Example:
        >>> by_type = get_hpi_by_property_type()
        >>> print(by_type)
    """
    tables = get_all_tables(force_refresh=force_refresh)
    return tables.get("Table 2")


# =============================================================================
# Backwards Compatibility
# =============================================================================


def build() -> dict[str, pd.DataFrame]:
    """Pulls and cleans up the latest NI House Price Index Data.

    .. deprecated::
        Use :func:`get_all_tables` instead for a more descriptive API.

    Returns:
        Dictionary of cleaned DataFrames keyed by table name.
    """
    warnings.warn(
        "build() is deprecated, use get_all_tables() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_all_tables()
