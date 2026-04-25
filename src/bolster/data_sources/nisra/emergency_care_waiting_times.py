"""NISRA Emergency Care Waiting Times Module.

Provides access to Northern Ireland's emergency care (A&E) waiting times
statistics, measuring performance against the 4-hour target across HSC Trusts
and hospital departments.

The 4-hour target requires that 95% of emergency care attendances are seen,
treated, admitted or discharged within 4 hours of arrival.

Data Coverage:
    - April 2008 to present (monthly, by hospital department)
    - 5 HSC Trusts: Belfast, Northern, South Eastern, Southern, Western
    - Attendance types: Type 1 (major A&E), Type 2 (single specialty), Type 3 (MIU/UTC)

Data Source:
    Department of Health Northern Ireland publishes emergency care waiting times
    through quarterly HTML interactive data publications at
    https://www.health-ni.gov.uk/articles/emergency-care-waiting-times.

Update Frequency:
    Quarterly, approximately 3 months after the end of each quarter.

Example:
    >>> from bolster.data_sources.nisra import emergency_care_waiting_times as ecwt
    >>> df = ecwt.get_latest_data()
    >>> print(df.tail())

    >>> # Type 1 A&E performance only
    >>> type1 = df[df['attendance_type'] == 'Type 1']
    >>> by_trust = type1.groupby('trust')['pct_within_4hrs'].mean()
    >>> print(by_trust)

Publication Details:
    - Frequency: Quarterly (published ~3 months after quarter end)
    - Published by: Department of Health / NISRA
    - Source: https://www.health-ni.gov.uk/articles/emergency-care-waiting-times
"""

import logging

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.datatables import DataTablesError, datatables_to_dataframe, fetch_datatables_json
from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError

logger = logging.getLogger(__name__)

DOH_LANDING_PAGE = "https://www.health-ni.gov.uk/articles/emergency-care-waiting-times"
DOH_BASE_URL = "https://www.health-ni.gov.uk"

EXPECTED_TRUSTS = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}

# Columns in the raw DT payload (matched to HTML <th> headers)
_RAW_DATE = "Date"
_RAW_MONTH = "Month"
_RAW_YEAR = "Year"
_RAW_TRUST = "Trust"
_RAW_DEPT = "Dept"
_RAW_TYPE = "Type"
_RAW_UNDER_4 = "Under 4 Hours"
_RAW_BTW_4_12 = "Between 4 - 12 Hours"
_RAW_OVER_12 = "Over 12 Hours"
_RAW_TOTAL = "Total"
_RAW_PCT = "Percent Under 4 Hours (%)"


def get_latest_url() -> str:
    """Return the URL of the most recent interactive data HTML from datavis.nisra.gov.uk.

    Scrapes the Department of Health landing page to find the most recent quarterly
    publication, then follows to the publication page to extract the data HTML link.

    Returns:
        URL of the HTML page containing the embedded DataTables widget.

    Raises:
        NISRADataNotFoundError: If no publication or data link can be found.
    """
    logger.info("Fetching emergency care waiting times landing page")

    try:
        response = session.get(DOH_LANDING_PAGE, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch emergency care landing page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    pub_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "publications" in href and "emergency-care-waiting-times" in href:
            pub_url = href if href.startswith("http") else f"{DOH_BASE_URL}{href}"
            break

    if not pub_url:
        raise NISRADataNotFoundError("Could not find emergency care waiting times publication link")

    logger.info(f"Fetching publication page: {pub_url}")
    try:
        pub_resp = session.get(pub_url, timeout=30)
        pub_resp.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch publication page {pub_url}: {e}") from e

    pub_soup = BeautifulSoup(pub_resp.content, "html.parser")

    # Prefer the raw data page (contains "-data-") over the interactive publication
    for a in pub_soup.find_all("a", href=True):
        href = a["href"]
        if (
            "datavis.nisra.gov.uk" in href
            and href.endswith(".html")
            and "-data-" in href
            and "interactive" not in href.lower()
        ):
            logger.info(f"Found data URL: {href}")
            return href

    # Fallback: any datavis link that is not the interactive publication
    for a in pub_soup.find_all("a", href=True):
        href = a["href"]
        if "datavis.nisra.gov.uk" in href and href.endswith(".html") and "interactive" not in href.lower():
            logger.info(f"Found datavis URL (fallback): {href}")
            return href

    raise NISRADataNotFoundError(f"Could not find emergency care data HTML link on {pub_url}")


def _parse_numeric_col(series: pd.Series) -> pd.Series:
    """Convert a string column with comma-separated numbers to numeric.

    Args:
        series: pandas Series with values like "1,234" or 567.

    Returns:
        Series with numeric dtype.
    """
    if series.dtype == object:
        series = series.str.replace(",", "", regex=False)
    return pd.to_numeric(series, errors="coerce")


def parse_data(payload: dict) -> pd.DataFrame:
    """Convert a raw DT widget payload into a clean emergency care DataFrame.

    Args:
        payload: The ``x`` sub-dict from the DT widget, as returned by
            :func:`~bolster.utils.datatables.fetch_datatables_json`.

    Returns:
        DataFrame with columns: date, year, month, trust, dept, attendance_type,
        under_4hrs, btw_4_12hrs, over_12hrs, total, pct_within_4hrs.

        ``pct_within_4hrs`` is always in the range [0.0, 1.0].

    Raises:
        NISRAValidationError: If expected columns are missing from the payload.
    """
    df = datatables_to_dataframe(payload)

    expected = {_RAW_DATE, _RAW_TRUST, _RAW_TYPE, _RAW_TOTAL, _RAW_PCT}
    missing = expected - set(df.columns)
    if missing:
        raise NISRAValidationError(
            f"Emergency care data is missing expected columns: {missing}. Found: {list(df.columns)}"
        )

    result = pd.DataFrame()
    result["date"] = pd.to_datetime(df[_RAW_DATE], errors="coerce")
    result["year"] = result["date"].dt.year.where(result["date"].notna()).astype("Int64")
    result["month"] = result["date"].dt.strftime("%B").where(result["date"].notna())
    result["trust"] = df[_RAW_TRUST].astype(str)
    result["dept"] = df[_RAW_DEPT].astype(str) if _RAW_DEPT in df.columns else pd.NA
    result["attendance_type"] = df[_RAW_TYPE].astype(str)
    result["under_4hrs"] = _parse_numeric_col(df[_RAW_UNDER_4]).astype("Int64") if _RAW_UNDER_4 in df.columns else pd.NA
    result["btw_4_12hrs"] = (
        _parse_numeric_col(df[_RAW_BTW_4_12]).astype("Int64") if _RAW_BTW_4_12 in df.columns else pd.NA
    )
    result["over_12hrs"] = _parse_numeric_col(df[_RAW_OVER_12]).astype("Int64") if _RAW_OVER_12 in df.columns else pd.NA
    result["total"] = _parse_numeric_col(df[_RAW_TOTAL]).astype("Int64")
    result["pct_within_4hrs"] = pd.to_numeric(df[_RAW_PCT], errors="coerce")

    # Normalise: values > 1.0 are percentages (0–100), convert to proportion (0–1)
    mask = result["pct_within_4hrs"] > 1.0
    result.loc[mask, "pct_within_4hrs"] = result.loc[mask, "pct_within_4hrs"] / 100.0

    return result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch and return the latest emergency care waiting times data.

    Downloads the most recent quarterly interactive data HTML, extracts the
    embedded DataTables widget, and returns a clean DataFrame.

    Args:
        force_refresh: Ignored (HTML pages are always re-fetched; use for API
            consistency with other NISRA modules).

    Returns:
        DataFrame with columns:
            - date (datetime): First of the month for the reporting period
            - year (int): Calendar year
            - month (str): Month name, e.g. "April"
            - trust (str): HSC Trust name
            - dept (str): Hospital department / site name
            - attendance_type (str): Type 1, Type 2, or Type 3
            - under_4hrs (int): Attendances seen within 4 hours
            - btw_4_12hrs (int): Attendances between 4 and 12 hours
            - over_12hrs (int): Attendances waiting over 12 hours
            - total (int): Total attendances
            - pct_within_4hrs (float): Proportion seen within 4 hours (0.0–1.0)

    Raises:
        NISRADataNotFoundError: If the data page cannot be located or fetched.
        NISRAValidationError: If the downloaded data fails schema validation.
    """
    data_url = get_latest_url()
    logger.info(f"Fetching emergency care data from {data_url}")

    try:
        payload = fetch_datatables_json(data_url)
    except DataTablesError as e:
        raise NISRADataNotFoundError(f"Failed to extract DataTables payload: {e}") from e

    return parse_data(payload)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate that the emergency care DataFrame is internally consistent.

    Args:
        df: DataFrame as returned by :func:`get_latest_data`.

    Returns:
        True if validation passes.

    Raises:
        NISRAValidationError: If validation fails.
    """
    required_cols = {"date", "year", "month", "trust", "attendance_type", "total", "pct_within_4hrs"}
    missing = required_cols - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if len(df) == 0:
        raise NISRAValidationError("DataFrame is empty")

    pct = df["pct_within_4hrs"].dropna()
    if len(pct) > 0 and not ((pct >= 0.0) & (pct <= 1.0)).all():
        bad = pct[(pct < 0.0) | (pct > 1.0)]
        raise NISRAValidationError(f"pct_within_4hrs has {len(bad)} values outside [0, 1]: {bad.head().tolist()}")

    return True
