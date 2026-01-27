"""NISRA Cancer Waiting Times Module.

This module provides access to Northern Ireland's cancer waiting times statistics,
measuring performance against key cancer treatment targets.

Cancer Waiting Time Targets:
    - 14-day: Urgent breast cancer referrals seen within 14 days
    - 31-day: Treatment started within 31 days of decision to treat
    - 62-day: Treatment started within 62 days of urgent GP referral

Data Coverage:
    - 31-day and 62-day by HSC Trust: April 2008 - Present (monthly)
    - 31-day and 62-day by Tumour Site: December 2008 - Present (monthly)
    - 14-day Breast (Historic by Trust): April 2008 - April 2025
    - 14-day Breast (Regional): May 2025 - Present (new regional service)
    - Breast Cancer Referrals: April 2016 - Present (monthly)

HSC Trusts:
    - Belfast, Northern, South Eastern, Southern, Western

Tumour Sites:
    - Brain/Central Nervous System, Breast Cancer, Gynaecological Cancers,
    - Haematological Cancers, Head/Neck Cancer, Lower Gastrointestinal Cancer,
    - Lung Cancer, Other, Skin Cancers, Upper Gastrointestinal Cancer,
    - Urological Cancer

Examples:
    >>> from bolster.data_sources.nisra import cancer_waiting_times as cwt
    >>> # Get latest 31-day waiting times by HSC Trust
    >>> df = cwt.get_latest_31_day_by_trust()
    >>> print(df.tail())

    >>> # Get 62-day waiting times by tumour site
    >>> df_tumour = cwt.get_latest_62_day_by_tumour()
    >>> print(df_tumour[df_tumour['tumour_site'] == 'Lung Cancer'].tail())

    >>> # Calculate performance rates
    >>> summary = cwt.get_performance_summary()
    >>> print(summary)

Publication Details:
    - Frequency: Quarterly (published ~3 months after quarter end)
    - Published by: Department of Health / NISRA
    - Source: https://www.health-ni.gov.uk/articles/cancer-waiting-times
"""

import logging
import re
from pathlib import Path
from typing import Tuple, Union

import pandas as pd
from bs4 import BeautifulSoup

from ._base import NISRADataNotFoundError, download_file
from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Base URLs
DOH_CANCER_PAGE = "https://www.health-ni.gov.uk/articles/cancer-waiting-times"
DOH_BASE_URL = "https://www.health-ni.gov.uk"

# Sheet configurations
SHEET_31_DAY_TRUST = "31 Day Wait by HSC Trust"
SHEET_31_DAY_TUMOUR = "31 Day Wait by Tumour Site"
SHEET_62_DAY_TRUST = "62 Day Wait by HSC Trust"
SHEET_62_DAY_TUMOUR = "62 Day Wait by Tumour Site"
SHEET_14_DAY_REGIONAL = "14 d Wait - Breast Regional"
SHEET_14_DAY_HISTORIC = "14 d Wait - Breast Historic"
SHEET_BREAST_REFERRALS = "Breast Cancer Referrals"


def get_latest_publication_url() -> Tuple[str, str]:
    """Find the latest cancer waiting times publication URL.

    Scrapes the Department of Health cancer waiting times page to find the
    most recent quarterly publication.

    Returns:
        Tuple of (excel_file_url, quarter_string)

    Raises:
        NISRADataNotFoundError: If publication cannot be found
    """
    logger.info(f"Fetching latest publication from {DOH_CANCER_PAGE}")

    try:
        response = session.get(DOH_CANCER_PAGE, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch cancer waiting times page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find links to publications - look for "cancer waiting times" in link text
    publication_links = []
    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True).lower()
        href = link["href"]
        if "cancer waiting times" in text and "publications" in href:
            publication_links.append((link.get_text(strip=True), href))

    if not publication_links:
        raise NISRADataNotFoundError("Could not find any cancer waiting times publications")

    # Get the first (most recent) publication
    pub_text, pub_url = publication_links[0]
    logger.info(f"Found publication: {pub_text}")

    # Make absolute URL
    if pub_url.startswith("/"):
        pub_url = f"{DOH_BASE_URL}{pub_url}"

    # Extract quarter from publication text
    quarter_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"[^0-9]*(\d{4})",
        pub_text,
        re.IGNORECASE,
    )
    quarter_str = quarter_match.group(0) if quarter_match else "Unknown"

    # Now fetch the publication page to get the Excel file
    try:
        pub_response = session.get(pub_url, timeout=30)
        pub_response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch publication page: {e}")

    pub_soup = BeautifulSoup(pub_response.content, "html.parser")

    # Find Excel download link (main data file, not ICD codes)
    excel_url = None
    for link in pub_soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True).lower()
        if ".xlsx" in href.lower() and "icd" not in href.lower() and "icd" not in text:
            excel_url = href
            break

    if not excel_url:
        raise NISRADataNotFoundError("Could not find Excel file in publication page")

    # Make absolute URL
    if excel_url.startswith("/"):
        excel_url = f"{DOH_BASE_URL}{excel_url}"

    logger.info(f"Found Excel file: {excel_url}")
    return excel_url, quarter_str


def _parse_month(month_str: str) -> pd.Timestamp:
    """Parse month string like 'April 2008' to datetime."""
    try:
        return pd.to_datetime(month_str, format="%B %Y")
    except ValueError:
        return pd.NaT


def parse_31_day_by_trust(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse 31-day waiting times by HSC Trust.

    Args:
        file_path: Path to the Excel file

    Returns:
        DataFrame with columns: date, year, month, trust, within_target,
        over_target, total, performance_rate
    """
    df = pd.read_excel(file_path, sheet_name=SHEET_31_DAY_TRUST)

    df.columns = ["treatment_month", "trust", "within_target", "over_target", "total"]
    df["date"] = df["treatment_month"].apply(_parse_month)
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.strftime("%B")
    df["performance_rate"] = df["within_target"] / df["total"]

    return df[["date", "year", "month", "trust", "within_target", "over_target", "total", "performance_rate"]]


def parse_31_day_by_tumour(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse 31-day waiting times by Tumour Site.

    Args:
        file_path: Path to the Excel file

    Returns:
        DataFrame with columns: date, year, month, tumour_site, within_target,
        over_target, total, performance_rate
    """
    df = pd.read_excel(file_path, sheet_name=SHEET_31_DAY_TUMOUR)

    df.columns = ["treatment_month", "tumour_site", "within_target", "over_target", "total"]
    df["date"] = df["treatment_month"].apply(_parse_month)
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.strftime("%B")
    df["performance_rate"] = df["within_target"] / df["total"]

    return df[["date", "year", "month", "tumour_site", "within_target", "over_target", "total", "performance_rate"]]


def parse_62_day_by_trust(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse 62-day waiting times by HSC Trust.

    Args:
        file_path: Path to the Excel file

    Returns:
        DataFrame with columns: date, year, month, trust, within_target,
        over_target, total, performance_rate

    Note:
        62-day data may contain fractional patient counts due to shared care
        arrangements between trusts.
    """
    df = pd.read_excel(file_path, sheet_name=SHEET_62_DAY_TRUST)

    df.columns = ["treatment_month", "trust", "within_target", "over_target", "total"]
    df["date"] = df["treatment_month"].apply(_parse_month)
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.strftime("%B")
    df["performance_rate"] = df["within_target"] / df["total"]

    return df[["date", "year", "month", "trust", "within_target", "over_target", "total", "performance_rate"]]


def parse_62_day_by_tumour(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse 62-day waiting times by Tumour Site.

    Args:
        file_path: Path to the Excel file

    Returns:
        DataFrame with columns: date, year, month, tumour_site, within_target,
        over_target, total, performance_rate
    """
    df = pd.read_excel(file_path, sheet_name=SHEET_62_DAY_TUMOUR)

    df.columns = ["treatment_month", "tumour_site", "within_target", "over_target", "total"]
    df["date"] = df["treatment_month"].apply(_parse_month)
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.strftime("%B")
    df["performance_rate"] = df["within_target"] / df["total"]

    return df[["date", "year", "month", "tumour_site", "within_target", "over_target", "total", "performance_rate"]]


def parse_14_day_breast(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse 14-day breast cancer waiting times (combined historic and regional).

    Args:
        file_path: Path to the Excel file

    Returns:
        DataFrame with columns: date, year, month, trust, within_target,
        over_target, total, performance_rate

    Note:
        From May 2025, breast cancer services became regional. Historic data
        (pre-May 2025) is by individual Trust. Regional data shows NI-wide figures.
    """
    # Parse historic data (by Trust, up to April 2025)
    df_historic = pd.read_excel(file_path, sheet_name=SHEET_14_DAY_HISTORIC)
    df_historic.columns = ["month_seen", "trust", "within_target", "over_target", "total"]
    df_historic["date"] = df_historic["month_seen"].apply(_parse_month)
    df_historic = df_historic.dropna(subset=["date"])

    # Parse regional data (May 2025 onwards)
    df_regional = pd.read_excel(file_path, sheet_name=SHEET_14_DAY_REGIONAL)
    df_regional.columns = ["month_seen", "trust", "within_target", "over_target", "total"]
    df_regional["date"] = df_regional["month_seen"].apply(_parse_month)
    df_regional = df_regional.dropna(subset=["date"])

    # Combine
    df = pd.concat([df_historic, df_regional], ignore_index=True)
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.strftime("%B")
    df["performance_rate"] = df["within_target"] / df["total"]

    return df[["date", "year", "month", "trust", "within_target", "over_target", "total", "performance_rate"]]


def parse_breast_referrals(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse breast cancer referrals data.

    Args:
        file_path: Path to the Excel file

    Returns:
        DataFrame with columns: date, year, month, trust, total_referrals,
        urgent_referrals, urgent_rate
    """
    df = pd.read_excel(file_path, sheet_name=SHEET_BREAST_REFERRALS)

    df.columns = ["referral_month", "trust", "total_referrals", "urgent_referrals"]
    df["date"] = df["referral_month"].apply(_parse_month)
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].dt.year.astype(int)
    df["month"] = df["date"].dt.strftime("%B")
    df["urgent_rate"] = df["urgent_referrals"] / df["total_referrals"]

    return df[["date", "year", "month", "trust", "total_referrals", "urgent_referrals", "urgent_rate"]]


# High-level functions with automatic download


def get_latest_31_day_by_trust(force_refresh: bool = False) -> pd.DataFrame:
    """Get latest 31-day waiting times by HSC Trust.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with 31-day performance by Trust
    """
    excel_url, _ = get_latest_publication_url()
    file_path = download_file(excel_url, force_refresh=force_refresh)
    return parse_31_day_by_trust(file_path)


def get_latest_31_day_by_tumour(force_refresh: bool = False) -> pd.DataFrame:
    """Get latest 31-day waiting times by Tumour Site.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with 31-day performance by tumour site
    """
    excel_url, _ = get_latest_publication_url()
    file_path = download_file(excel_url, force_refresh=force_refresh)
    return parse_31_day_by_tumour(file_path)


def get_latest_62_day_by_trust(force_refresh: bool = False) -> pd.DataFrame:
    """Get latest 62-day waiting times by HSC Trust.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with 62-day performance by Trust
    """
    excel_url, _ = get_latest_publication_url()
    file_path = download_file(excel_url, force_refresh=force_refresh)
    return parse_62_day_by_trust(file_path)


def get_latest_62_day_by_tumour(force_refresh: bool = False) -> pd.DataFrame:
    """Get latest 62-day waiting times by Tumour Site.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with 62-day performance by tumour site
    """
    excel_url, _ = get_latest_publication_url()
    file_path = download_file(excel_url, force_refresh=force_refresh)
    return parse_62_day_by_tumour(file_path)


def get_latest_14_day_breast(force_refresh: bool = False) -> pd.DataFrame:
    """Get latest 14-day breast cancer waiting times.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with 14-day breast cancer performance
    """
    excel_url, _ = get_latest_publication_url()
    file_path = download_file(excel_url, force_refresh=force_refresh)
    return parse_14_day_breast(file_path)


def get_latest_breast_referrals(force_refresh: bool = False) -> pd.DataFrame:
    """Get latest breast cancer referrals data.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with breast cancer referrals
    """
    excel_url, _ = get_latest_publication_url()
    file_path = download_file(excel_url, force_refresh=force_refresh)
    return parse_breast_referrals(file_path)


# Helper/analysis functions


def get_data_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter data for a specific year.

    Args:
        df: DataFrame with 'year' column
        year: Year to filter for

    Returns:
        Filtered DataFrame
    """
    return df[df["year"] == year].copy()


def get_performance_summary_by_year(
    df: pd.DataFrame, group_col: str = "trust"
) -> pd.DataFrame:
    """Calculate annual performance summary.

    Args:
        df: DataFrame with performance data
        group_col: Column to group by ('trust' or 'tumour_site')

    Returns:
        DataFrame with annual summary statistics
    """
    summary = (
        df.groupby(["year", group_col])
        .agg(
            total_patients=("total", "sum"),
            within_target=("within_target", "sum"),
            over_target=("over_target", "sum"),
            months_reported=("total", "count"),
        )
        .reset_index()
    )
    summary["performance_rate"] = summary["within_target"] / summary["total_patients"]
    return summary


def get_ni_wide_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate NI-wide performance (aggregated across all trusts/sites).

    Args:
        df: DataFrame with performance data

    Returns:
        DataFrame with NI-wide monthly performance
    """
    ni_wide = (
        df.groupby(["date", "year", "month"])
        .agg(
            within_target=("within_target", "sum"),
            over_target=("over_target", "sum"),
            total=("total", "sum"),
        )
        .reset_index()
    )
    ni_wide["performance_rate"] = ni_wide["within_target"] / ni_wide["total"]
    return ni_wide


def get_performance_trend(df: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    """Calculate rolling performance trend.

    Args:
        df: DataFrame with NI-wide performance data
        window: Rolling window size in months (default: 12)

    Returns:
        DataFrame with rolling average performance
    """
    df = df.sort_values("date").copy()
    df["rolling_performance"] = df["performance_rate"].rolling(window=window, min_periods=1).mean()
    return df


def get_tumour_site_ranking(df: pd.DataFrame, year: int = None) -> pd.DataFrame:
    """Rank tumour sites by performance.

    Args:
        df: DataFrame with tumour site data
        year: Optional year to filter (default: all years)

    Returns:
        DataFrame ranked by performance (worst to best)
    """
    if year:
        df = df[df["year"] == year]

    ranking = (
        df.groupby("tumour_site")
        .agg(
            total_patients=("total", "sum"),
            within_target=("within_target", "sum"),
        )
        .reset_index()
    )
    ranking["performance_rate"] = ranking["within_target"] / ranking["total_patients"]
    ranking = ranking.sort_values("performance_rate", ascending=True)
    ranking["rank"] = range(1, len(ranking) + 1)
    return ranking


def validate_performance_data(df: pd.DataFrame) -> bool:
    """Validate that performance data is internally consistent.

    Args:
        df: DataFrame with performance columns

    Returns:
        True if validation passes

    Raises:
        ValueError: If validation fails

    Note:
        Rows with NaN values (e.g., due to encompass system rollout) or
        zero totals are excluded from validation checks.
    """
    # Filter to non-null rows with non-zero totals
    valid_df = df.dropna(subset=["within_target", "over_target", "total"])
    valid_df = valid_df[valid_df["total"] > 0]

    if len(valid_df) == 0:
        return True

    # Check within + over = total (with tolerance for fractional patients)
    total_check = abs(valid_df["within_target"] + valid_df["over_target"] - valid_df["total"]) < 1.0
    if not total_check.all():
        raise ValueError("within_target + over_target != total for some rows")

    # Check performance rate calculation
    expected_rate = valid_df["within_target"] / valid_df["total"]
    rate_check = abs(valid_df["performance_rate"] - expected_rate) < 0.001
    if not rate_check.all():
        raise ValueError("Performance rate calculation is incorrect")

    # Check performance rate is between 0 and 1 (filter out inf/nan from division)
    valid_rates = valid_df["performance_rate"].replace([float("inf"), float("-inf")], float("nan")).dropna()
    if len(valid_rates) > 0 and not ((valid_rates >= 0) & (valid_rates <= 1)).all():
        raise ValueError("Performance rate outside 0-1 range")

    return True
