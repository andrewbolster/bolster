"""PSNI Police Recorded Crime Statistics.

Provides access to police recorded crime statistics for Northern Ireland.

Data includes:
- Monthly crime counts by crime type and policing district
- Geographic breakdown by 11 policing districts (aligned with LGDs)
- Outcome data (charges, cautions, etc.) by district
- Historical time series from April 2001 onwards
- Integration with NISRA datasets via LGD and NUTS3 codes

Data Source:
    **Primary Source**: OpenDataNI - Police Recorded Crime in Northern Ireland

    https://www.opendatani.gov.uk/dataset/police-recorded-crime-in-northern-ireland

    The PSNI website uses Cloudflare protection, so this module uses the
    OpenDataNI mirror which provides direct CSV downloads. Data is published
    quarterly by PSNI and made available through OpenDataNI under the Open
    Government Licence v3.0.

    **PSNI Official Statistics**: https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics

    **DATA LIMITATION**: The OpenDataNI dataset was last updated January 2022
    and only contains data through December 2021. For 2022-2025 data, consult
    PSNI's quarterly PDF bulletins at the official statistics website above, or
    contact PSNI Statistics Branch (statistics@psni.police.uk).

Update Frequency: Quarterly (end of Jan, May, Jul, Oct) - **STALE SINCE 2022**
Geographic Coverage: Northern Ireland (11 policing districts + NI total)
Reference Date: Month of crime occurrence
Time Coverage: April 2001 to December 2021 (OpenDataNI dataset)

Example:
    >>> from bolster.data_sources.psni import crime_statistics
    >>> # Get latest crime data
    >>> df = crime_statistics.get_latest_crime_statistics()
    >>> print(df.head())
    >>>
    >>> # Filter to Belfast
    >>> belfast = df[df['policing_district'] == 'Belfast City']
    >>>
    >>> # Get LGD code for cross-referencing with NISRA data
    >>> belfast_lgd = crime_statistics.get_lgd_code('Belfast City')
    >>> print(f"Belfast LGD code: {belfast_lgd}")  # N09000003
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

import pandas as pd

from ._base import (
    PSNIValidationError,
    download_file,
    get_lgd_code,
    get_nuts3_code,
    get_nuts_region_name,
)

logger = logging.getLogger(__name__)

# OpenDataNI CSV URL (direct download, no Cloudflare protection)
CRIME_STATISTICS_URL = "https://admin.opendatani.gov.uk/dataset/80dc9542-7b2a-48f5-bbf4-ccc7040d36af/resource/6fd51851-df78-4469-98c5-4f06953621a0/download/police-recorded-crime-monthly-data.csv"

# Data guide for reference
DATA_GUIDE_URL = "https://admin.opendatani.gov.uk/dataset/80dc9542-7b2a-48f5-bbf4-ccc7040d36af/resource/51cd6a9e-646b-42bf-9daa-8d2cb618764e/download/police-recorded-crime-data-guide.pdf"

# PSNI Official Statistics (for current data not available on OpenDataNI)
PSNI_OFFICIAL_STATS_URL = "https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/police-recorded-crime-statistics"
PSNI_STATISTICS_EMAIL = "statistics@psni.police.uk"


def get_data_source_info() -> dict:
    """Get information about crime statistics data sources.

    Returns a dictionary with URLs and contact information for accessing
    PSNI crime statistics. Use this when you need data beyond December 2021.

    Returns:
        Dictionary with keys:
            - opendatani_url: OpenDataNI dataset URL (data through Dec 2021)
            - data_guide_url: PDF data guide URL
            - psni_official_url: PSNI official statistics page (current data)
            - contact_email: PSNI Statistics Branch email
            - data_limitation: Description of OpenDataNI data limitations
            - last_update: Last known update date for OpenDataNI

    Example:
        >>> info = get_data_source_info()
        >>> print(f"For current data, visit: {info['psni_official_url']}")
        >>> print(f"Or contact: {info['contact_email']}")
    """
    return {
        "opendatani_url": "https://www.opendatani.gov.uk/dataset/police-recorded-crime-in-northern-ireland",
        "data_guide_url": DATA_GUIDE_URL,
        "psni_official_url": PSNI_OFFICIAL_STATS_URL,
        "contact_email": PSNI_STATISTICS_EMAIL,
        "data_limitation": (
            "OpenDataNI dataset was last updated January 2022 and only contains "
            "data through December 2021. For 2022-2025 data, consult PSNI's quarterly "
            "bulletins at the official statistics URL or contact PSNI Statistics Branch."
        ),
        "last_update": "2022-01-27",
    }


def parse_crime_statistics_file(
    file_path: Union[str, Path],
    add_geographic_codes: bool = True,
) -> pd.DataFrame:
    """Parse PSNI crime statistics CSV file.

    The file is in long format with columns for year, month, district,
    crime type, data measure, and count. This function reads the CSV,
    cleans column names, adds date parsing, and optionally adds LGD and
    NUTS3 geographic codes for cross-dataset integration.

    Args:
        file_path: Path to the crime statistics CSV file
        add_geographic_codes: If True, add LGD and NUTS3 code columns

    Returns:
        DataFrame with columns:
            - calendar_year: int (year of crime)
            - month: str (month name: Apr, May, ..., Dec)
            - policing_district: str (district name or "Northern Ireland")
            - crime_type: str (Home Office crime classification)
            - data_measure: str (type of measure - crime count, outcome number, outcome rate)
            - count: float (value - can be count or percentage)
            - date: datetime (first day of month)
            - lgd_code: str (ONS LGD code, if add_geographic_codes=True)
            - nuts3_code: str (NUTS3 region code, if add_geographic_codes=True)
            - nuts3_name: str (NUTS3 region name, if add_geographic_codes=True)

    Raises:
        PSNIValidationError: If file structure is unexpected

    Example:
        >>> from pathlib import Path
        >>> df = parse_crime_statistics_file(Path("crime_data.csv"))
        >>> print(df.columns.tolist())
        >>> print(f"Date range: {df['date'].min()} to {df['date'].max()}")
        >>> print(f"Districts: {df['policing_district'].nunique()}")
    """
    file_path = Path(file_path)

    try:
        # Read CSV - it's already clean and well-structured
        df = pd.read_csv(file_path)
    except Exception as e:
        raise PSNIValidationError(f"Failed to read crime statistics file: {e}")

    # Validate expected columns
    expected_cols = {"Calendar_Year", "Month", "Policing_District", "Crime_Type", "Data_Measure", "Count"}
    if not expected_cols.issubset(df.columns):
        missing = expected_cols - set(df.columns)
        raise PSNIValidationError(f"Missing expected columns: {missing}")

    # Clean column names (lowercase with underscores)
    df = df.rename(
        columns={
            "Calendar_Year": "calendar_year",
            "Month": "month",
            "Policing_District": "policing_district",
            "Crime_Type": "crime_type",
            "Data_Measure": "data_measure",
            "Count": "count",
        }
    )

    # Strip whitespace from string columns (source data has trailing spaces)
    for col in ["policing_district", "crime_type", "data_measure", "month"]:
        df[col] = df[col].str.strip()

    # Create datetime column (first day of month)
    # Month names are 3-letter abbreviations: Apr, May, Jun, etc.
    month_map = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }

    df["month_num"] = df["month"].map(month_map)

    if df["month_num"].isna().any():
        unrecognized = df[df["month_num"].isna()]["month"].unique()
        raise PSNIValidationError(f"Unrecognized month values: {unrecognized}")

    df["date"] = pd.to_datetime({"year": df["calendar_year"], "month": df["month_num"], "day": 1}, errors="coerce")

    # Drop temporary month_num column
    df = df.drop(columns=["month_num"])

    # Handle special values in count column
    # "/0" means outcome rate could not be calculated (distinct from 0)
    df["count"] = df["count"].replace("/0", pd.NA)
    df["count"] = pd.to_numeric(df["count"], errors="coerce")

    # Add geographic codes for cross-dataset integration
    if add_geographic_codes:
        df["lgd_code"] = df["policing_district"].apply(get_lgd_code)
        df["nuts3_code"] = df["policing_district"].apply(get_nuts3_code)
        df["nuts3_name"] = df["nuts3_code"].apply(get_nuts_region_name)

    # Sort by date and district for consistent output
    df = df.sort_values(["date", "policing_district", "crime_type"]).reset_index(drop=True)

    # Log summary
    total_records = len(df)
    date_range = f"{df['date'].min().strftime('%Y-%m')} to {df['date'].max().strftime('%Y-%m')}"
    districts = df["policing_district"].nunique()
    crime_types = df["crime_type"].nunique()

    logger.info(f"Parsed {total_records:,} crime records ({date_range})")
    logger.info(f"  {districts} policing districts, {crime_types} crime types")

    return df


def get_latest_crime_statistics(
    force_refresh: bool = False,
    add_geographic_codes: bool = True,
) -> pd.DataFrame:
    """Get the latest police recorded crime statistics.

    Downloads the crime statistics CSV from OpenDataNI, caches it,
    and parses it into a pandas DataFrame with optional geographic
    codes for cross-dataset integration.

    **WARNING**: This dataset was last updated in January 2022 and only
    contains data through December 2021. The function will log a warning
    if the data is more than 1 year old.

    Args:
        force_refresh: If True, bypass cache and download fresh data
        add_geographic_codes: If True, add LGD and NUTS3 code columns

    Returns:
        DataFrame with crime statistics (see parse_crime_statistics_file for columns)

    Raises:
        PSNIDataNotFoundError: If download fails
        PSNIValidationError: If file structure is unexpected

    Example:
        >>> # Get all crime data (NOTE: only through Dec 2021)
        >>> df = get_latest_crime_statistics()
        >>>
        >>> # Filter to recent data
        >>> recent = df[df['date'] >= '2020-01-01']
        >>>
        >>> # Get total crimes by district for 2021
        >>> crimes_2021 = df[
        ...     (df['calendar_year'] == 2021) &
        ...     (df['data_measure'] == 'Police Recorded Crime') &
        ...     (df['crime_type'] == 'Total police recorded crime')
        ... ].groupby('policing_district')['count'].sum()
        >>> print(crimes_2021.sort_values(ascending=False))
    """
    logger.info("Fetching PSNI crime statistics from OpenDataNI")

    # Cache for 90 days (quarterly updates, but allow for delays)
    cache_ttl_hours = 90 * 24
    file_path = download_file(CRIME_STATISTICS_URL, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)

    # Parse the file
    df = parse_crime_statistics_file(file_path, add_geographic_codes=add_geographic_codes)

    # Check data staleness and warn users
    latest_date = df["date"].max()
    age_days = (datetime.now() - latest_date).days
    age_years = age_days / 365.25

    if age_days > 365:
        logger.warning(
            f"⚠️  Data is {age_years:.1f} years old (latest: {latest_date.strftime('%B %Y')}). "
            f"OpenDataNI dataset has not been updated since January 2022. "
            f"For 2022-2025 data, consult PSNI quarterly bulletins or contact statistics@psni.police.uk"
        )

    return df


def validate_crime_statistics(df: pd.DataFrame) -> bool:  # pragma: no cover
    """Validate crime statistics data integrity.

    Performs sanity checks on the crime statistics data:
    - Non-negative crime counts
    - Reasonable date ranges
    - Expected policing districts present
    - No unexpected missing data

    Args:
        df: DataFrame from parse_crime_statistics_file or get_latest_crime_statistics

    Returns:
        True if validation passes

    Raises:
        PSNIValidationError: If validation fails

    Example:
        >>> df = get_latest_crime_statistics()
        >>> validate_crime_statistics(df)
        True
    """
    # Check for negative crime counts (excluding NA which represents "/0")
    crime_counts = df[df["data_measure"] == "Police Recorded Crime"]["count"]
    if (crime_counts < 0).any():
        negative_count = (crime_counts < 0).sum()
        raise PSNIValidationError(f"Found {negative_count} negative crime counts")

    # Check date range is reasonable
    min_date = df["date"].min()
    max_date = df["date"].max()

    if min_date < pd.Timestamp("2001-01-01"):
        raise PSNIValidationError(f"Data includes dates before 2001: {min_date}")

    if max_date > pd.Timestamp.now():
        raise PSNIValidationError(f"Data includes future dates: {max_date}")

    # Check that we have the expected policing districts
    expected_districts = {
        "Northern Ireland",
        "Belfast City",
        "Lisburn & Castlereagh City",
        "Ards & North Down",
        "Newry Mourne & Down",
        "Armagh City Banbridge & Craigavon",
        "Mid Ulster",
        "Fermanagh & Omagh",
        "Derry City & Strabane",
        "Causeway Coast & Glens",
        "Mid & East Antrim",
        "Antrim & Newtownabbey",
    }

    actual_districts = set(df["policing_district"].unique())
    missing_districts = expected_districts - actual_districts

    if missing_districts:
        logger.warning(f"Missing expected policing districts: {missing_districts}")

    # Check for reasonable data coverage per district
    records_per_district = df.groupby("policing_district").size()
    if records_per_district.min() < 100:
        sparse_districts = records_per_district[records_per_district < 100]
        logger.warning(f"Some districts have very few records: {sparse_districts.to_dict()}")

    logger.info(f"Validation passed: {len(df):,} records checked")
    logger.info(f"  Date range: {min_date.strftime('%Y-%m')} to {max_date.strftime('%Y-%m')}")
    logger.info(f"  {len(actual_districts)} policing districts")

    return True


def filter_by_district(
    df: pd.DataFrame,
    district: Union[str, List[str]],
) -> pd.DataFrame:
    """Filter crime statistics to specific policing district(s).

    Args:
        df: DataFrame from get_latest_crime_statistics
        district: District name(s) to filter (e.g., "Belfast City" or ["Belfast City", "Derry City & Strabane"])

    Returns:
        Filtered DataFrame

    Example:
        >>> df = get_latest_crime_statistics()
        >>> belfast = filter_by_district(df, "Belfast City")
        >>> print(f"Belfast records: {len(belfast):,}")
        >>>
        >>> # Multiple districts
        >>> cities = filter_by_district(df, ["Belfast City", "Derry City & Strabane"])
    """
    if isinstance(district, str):
        district = [district]

    return df[df["policing_district"].isin(district)].reset_index(drop=True)


def filter_by_crime_type(
    df: pd.DataFrame,
    crime_type: Union[str, List[str]],
) -> pd.DataFrame:
    """Filter crime statistics to specific crime type(s).

    Args:
        df: DataFrame from get_latest_crime_statistics
        crime_type: Crime type(s) to filter (e.g., "Burglary" or ["Violence with injury", "Robbery"])

    Returns:
        Filtered DataFrame

    Example:
        >>> df = get_latest_crime_statistics()
        >>> violence = filter_by_crime_type(df, "Violence with injury (including homicide & death/serious injury by unlawful driving)")
        >>> print(f"Violence crimes: {len(violence):,}")
    """
    if isinstance(crime_type, str):
        crime_type = [crime_type]

    return df[df["crime_type"].isin(crime_type)].reset_index(drop=True)


def filter_by_date_range(
    df: pd.DataFrame,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
) -> pd.DataFrame:
    """Filter crime statistics to a date range.

    Args:
        df: DataFrame from get_latest_crime_statistics
        start_date: Start date (inclusive), e.g., "2020-01-01" or datetime
        end_date: End date (inclusive), e.g., "2021-12-31" or datetime

    Returns:
        Filtered DataFrame

    Example:
        >>> df = get_latest_crime_statistics()
        >>> # Get 2020 data
        >>> df_2020 = filter_by_date_range(df, "2020-01-01", "2020-12-31")
        >>>
        >>> # Get data from 2018 onwards
        >>> recent = filter_by_date_range(df, start_date="2018-01-01")
    """
    filtered = df.copy()

    if start_date:
        if isinstance(start_date, str):
            start_date = pd.to_datetime(start_date)
        filtered = filtered[filtered["date"] >= start_date]

    if end_date:
        if isinstance(end_date, str):
            end_date = pd.to_datetime(end_date)
        filtered = filtered[filtered["date"] <= end_date]

    return filtered.reset_index(drop=True)


def get_total_crimes_by_district(
    df: pd.DataFrame,
    year: Optional[int] = None,
) -> pd.DataFrame:
    """Calculate total recorded crimes by policing district.

    Args:
        df: DataFrame from get_latest_crime_statistics
        year: Optional year to filter (uses all years if None)

    Returns:
        DataFrame with columns: policing_district, lgd_code, nuts3_code, total_crimes

    Example:
        >>> df = get_latest_crime_statistics()
        >>> totals_2021 = get_total_crimes_by_district(df, year=2021)
        >>> print(totals_2021.sort_values('total_crimes', ascending=False))
    """
    # Filter to total crimes measure
    crime_df = df[
        (df["data_measure"] == "Police Recorded Crime") & (df["crime_type"] == "Total police recorded crime")
    ].copy()

    # Filter to specific year if provided
    if year:
        crime_df = crime_df[crime_df["calendar_year"] == year]

    # Group by district and sum
    result = (
        crime_df.groupby(["policing_district", "lgd_code", "nuts3_code"])["count"]
        .sum()
        .reset_index()
        .rename(columns={"count": "total_crimes"})
    )

    return result.sort_values("total_crimes", ascending=False).reset_index(drop=True)


def get_crime_trends(
    df: pd.DataFrame,
    crime_type: str = "Total police recorded crime",
    district: str = "Northern Ireland",
    measure: str = "Police Recorded Crime",
) -> pd.DataFrame:
    """Get monthly crime trends for a specific crime type and district.

    Args:
        df: DataFrame from get_latest_crime_statistics
        crime_type: Crime type to analyze (default: total crimes)
        district: Policing district (default: Northern Ireland total)
        measure: Data measure to use (default: Police Recorded Crime)

    Returns:
        DataFrame with columns: date, calendar_year, month, count

    Example:
        >>> df = get_latest_crime_statistics()
        >>> # Belfast violence trends
        >>> trends = get_crime_trends(
        ...     df,
        ...     crime_type="Violence with injury (including homicide & death/serious injury by unlawful driving)",
        ...     district="Belfast City"
        ... )
        >>> print(trends.tail())
        >>>
        >>> # Plot with pandas
        >>> import matplotlib.pyplot as plt
        >>> trends.set_index('date')['count'].plot()
        >>> plt.title('Crime Trends')
        >>> plt.show()
    """
    filtered = df[
        (df["crime_type"] == crime_type) & (df["policing_district"] == district) & (df["data_measure"] == measure)
    ].copy()

    result = filtered[["date", "calendar_year", "month", "count"]].sort_values("date").reset_index(drop=True)

    return result


def get_outcome_rates_by_district(
    df: pd.DataFrame,
    year: Optional[int] = None,
    crime_type: str = "Total police recorded crime",
) -> pd.DataFrame:
    """Calculate crime outcome rates by policing district.

    Outcome rate represents the percentage of crimes with an outcome
    (charge, caution, community resolution, etc.)

    Args:
        df: DataFrame from get_latest_crime_statistics
        year: Optional year to filter (uses all years if None)
        crime_type: Crime type to analyze (default: total crimes)

    Returns:
        DataFrame with columns: policing_district, lgd_code, average_outcome_rate

    Example:
        >>> df = get_latest_crime_statistics()
        >>> outcomes = get_outcome_rates_by_district(df, year=2021)
        >>> print(outcomes.sort_values('average_outcome_rate', ascending=False))
    """
    # Filter to outcome rate measure
    outcome_df = df[
        (df["data_measure"] == "Police Recorded Crime Outcomes (rate %)") & (df["crime_type"] == crime_type)
    ].copy()

    # Filter to specific year if provided
    if year:
        outcome_df = outcome_df[outcome_df["calendar_year"] == year]

    # Group by district and calculate average outcome rate
    result = (
        outcome_df.groupby(["policing_district", "lgd_code"])["count"]
        .mean()
        .reset_index()
        .rename(columns={"count": "average_outcome_rate"})
    )

    # Round to 1 decimal place
    result["average_outcome_rate"] = result["average_outcome_rate"].round(1)

    return result.sort_values("average_outcome_rate", ascending=False).reset_index(drop=True)


def get_available_crime_types(df: pd.DataFrame) -> List[str]:
    """Get list of all crime types in the dataset.

    Args:
        df: DataFrame from get_latest_crime_statistics

    Returns:
        Sorted list of crime type names

    Example:
        >>> df = get_latest_crime_statistics()
        >>> crime_types = get_available_crime_types(df)
        >>> for crime_type in crime_types:
        ...     print(crime_type)
    """
    return sorted(df["crime_type"].unique().tolist())


def get_available_districts(df: pd.DataFrame) -> List[str]:
    """Get list of all policing districts in the dataset.

    Args:
        df: DataFrame from get_latest_crime_statistics

    Returns:
        Sorted list of district names

    Example:
        >>> df = get_latest_crime_statistics()
        >>> districts = get_available_districts(df)
        >>> for district in districts:
        ...     lgd = get_lgd_code(district)
        ...     print(f"{district}: {lgd}")
    """
    return sorted(df["policing_district"].unique().tolist())
