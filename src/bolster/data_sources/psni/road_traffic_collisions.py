"""PSNI Road Traffic Collision Statistics.

Provides access to police-recorded injury road traffic collision (RTC) statistics
for Northern Ireland.

Data includes:
- Collision records with date, location, road conditions, severity
- Casualty records with age, gender, severity, road user class
- Vehicle records with type, manoeuvre, driver details
- Geographic breakdown by 11 policing districts (aligned with LGDs)
- Historical time series from 2013 onwards

Data Source:
    **Primary Source**: OpenDataNI - Police Recorded Injury Road Traffic Collision Statistics

    https://www.opendatani.gov.uk/dataset?q=road+traffic+collision

    PSNI collects RTC statistics in accordance with STATS20 guidance from the
    Department for Transport. Data covers injury collisions only (not damage-only).
    Published under the Open Government Licence v3.0.

    **PSNI Official Statistics**: https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/road-traffic-collision-statistics

Update Frequency: Annual (data available ~6 months after year end)
Geographic Coverage: Northern Ireland (11 policing districts)
Reference Date: Date of collision occurrence
Time Coverage: 2013 to present

Example:
    >>> from bolster.data_sources.psni import road_traffic_collisions
    >>> # Get latest collision data
    >>> df = road_traffic_collisions.get_collisions()
    >>> print(df.head())
    >>>
    >>> # Get casualties with decoded values
    >>> casualties = road_traffic_collisions.get_casualties()
    >>> fatal = casualties[casualties['severity'] == 'Fatal']
    >>> print(f"Fatal casualties: {len(fatal)}")
    >>>
    >>> # Get summary statistics
    >>> summary = road_traffic_collisions.get_annual_summary()
    >>> print(summary)
"""

import logging
from datetime import datetime
from typing import Dict, List, Literal, Optional

import pandas as pd
import requests

from bolster.utils.web import session

from ._base import (
    PSNIDataNotFoundError,
    PSNIValidationError,
    download_file,
    get_lgd_code,
    get_nuts3_code,
)

logger = logging.getLogger(__name__)

# OpenDataNI API endpoint
OPENDATANI_API = "https://admin.opendatani.gov.uk/api/3/action"

# District code mappings (short codes used in RTC data to full names)
DISTRICT_CODES = {
    "ANTN": "Antrim & Newtownabbey",
    "ARND": "Ards & North Down",
    "ARBC": "Armagh City Banbridge & Craigavon",
    "BELC": "Belfast City",
    "CCGL": "Causeway Coast & Glens",
    "DCST": "Derry City & Strabane",
    "FERO": "Fermanagh & Omagh",
    "LISC": "Lisburn & Castlereagh City",
    "MEAN": "Mid & East Antrim",
    "MIDU": "Mid Ulster",
    "NEMD": "Newry Mourne & Down",
}

# Reverse mapping
DISTRICT_NAMES_TO_CODES = {v: k for k, v in DISTRICT_CODES.items()}

# Casualty severity codes
SEVERITY_CODES = {
    1: "Fatal",
    2: "Serious",
    3: "Slight",
}

# Casualty class codes (road user type)
CASUALTY_CLASS_CODES = {
    1: "Driver/Rider",
    2: "Passenger (front)",
    3: "Passenger (rear)",
    4: "Passenger (other)",
    5: "Pedestrian",
    6: "Pillion passenger",
}

# Vehicle type codes
VEHICLE_TYPE_CODES = {
    1: "Pedal cycle",
    2: "Motorcycle 50cc or under",
    3: "Motorcycle over 50cc and up to 125cc",
    4: "Motorcycle over 125cc and up to 500cc",
    5: "Motorcycle over 500cc",
    8: "Car",
    9: "Taxi",
    10: "Minibus (8-16 passengers)",
    11: "Bus/Coach (17+ passengers)",
    15: "Goods vehicle 3.5 tonnes mgw or under",
    16: "Goods vehicle over 3.5 and under 7.5 tonnes mgw",
    17: "Goods vehicle 7.5 tonnes mgw or over",
    18: "Agricultural vehicle",
    19: "Other motor vehicle",
    20: "Other non-motor vehicle",
    21: "Tram/Light rail",
    22: "Mobility scooter",
    23: "Electric scooter",
}

# Day of week codes
DAY_OF_WEEK_CODES = {
    1: "Sunday",
    2: "Monday",
    3: "Tuesday",
    4: "Wednesday",
    5: "Thursday",
    6: "Friday",
    7: "Saturday",
}

# Light conditions codes
LIGHT_CONDITIONS_CODES = {
    1: "Daylight",
    2: "Darkness: street lights present and lit",
    3: "Darkness: street lights present but unlit",
    4: "Darkness: no street lighting",
    5: "Darkness: street lighting unknown",
}

# Weather codes
WEATHER_CODES = {
    1: "Fine without high winds",
    2: "Raining without high winds",
    3: "Snowing without high winds",
    4: "Fine with high winds",
    5: "Raining with high winds",
    6: "Snowing with high winds",
    7: "Fog or mist",
    8: "Other",
    9: "Unknown",
}

# Road surface codes
ROAD_SURFACE_CODES = {
    1: "Dry",
    2: "Wet/Damp",
    3: "Snow",
    4: "Frost/Ice",
    5: "Flood (surface water over 3cm deep)",
}


def _get_available_datasets() -> List[Dict]:
    """Get list of available RTC datasets from OpenDataNI.

    Returns:
        List of dataset metadata dictionaries with keys:
            - year: int
            - id: str (package ID)
            - title: str
            - resources: List of resource dicts

    Raises:
        PSNIDataNotFoundError: If API request fails
    """
    try:
        resp = session.get(
            f"{OPENDATANI_API}/package_search",
            params={"q": "police recorded injury road traffic collision northern ireland", "rows": 50},
            headers={"User-Agent": "bolster/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise PSNIDataNotFoundError("OpenDataNI API returned unsuccessful response")

        datasets = []
        for pkg in data["result"]["results"]:
            # Extract year from title or name
            title = pkg.get("title", "")
            name = pkg.get("name", "")

            # Try to extract year (e.g., "...2024" or "...2013")
            year = None
            for part in title.split() + name.split("-"):
                if part.isdigit() and 2010 <= int(part) <= 2030:
                    year = int(part)
                    break

            if year:
                datasets.append(
                    {
                        "year": year,
                        "id": pkg["id"],
                        "name": pkg["name"],
                        "title": title,
                        "resources": pkg.get("resources", []),
                    }
                )

        # Sort by year descending
        datasets.sort(key=lambda x: x["year"], reverse=True)
        return datasets

    except requests.RequestException as e:
        raise PSNIDataNotFoundError(f"Failed to fetch dataset list: {e}") from e


def get_available_years() -> List[int]:
    """Get list of years with available RTC data.

    Returns:
        List of years (integers) in descending order

    Example:
        >>> years = get_available_years()
        >>> print(years)  # e.g., [2024, 2023, 2022, ...]
    """
    datasets = _get_available_datasets()
    return [d["year"] for d in datasets]


def _get_resource_url(year: int, resource_type: Literal["collision", "casualty", "vehicle"]) -> str:
    """Get download URL for a specific resource type and year.

    Args:
        year: Data year
        resource_type: One of 'collision', 'casualty', 'vehicle'

    Returns:
        Download URL for the CSV file

    Raises:
        PSNIDataNotFoundError: If resource not found
    """
    datasets = _get_available_datasets()

    # Find dataset for year
    dataset = next((d for d in datasets if d["year"] == year), None)
    if not dataset:
        available = [d["year"] for d in datasets]
        raise PSNIDataNotFoundError(f"No data available for year {year}. Available years: {available}")

    # Find matching resource
    search_terms = {
        "collision": ["collision"],
        "casualty": ["casualt"],  # matches "casualty" and "casualties"
        "vehicle": ["vehicle"],
    }

    for resource in dataset["resources"]:
        name = resource.get("name", "").lower()
        url = resource.get("url", "")

        if resource.get("format", "").upper() == "CSV":
            for term in search_terms[resource_type]:
                if term in name or term in url.lower():
                    return url

    raise PSNIDataNotFoundError(f"No {resource_type} CSV found for year {year}")


def get_collisions(
    year: Optional[int] = None,
    force_refresh: bool = False,
    decode_values: bool = True,
) -> pd.DataFrame:
    """Get collision records for a specific year.

    Each row represents a single road traffic collision with details about
    date, time, location, road conditions, and severity.

    Args:
        year: Year to fetch (default: latest available)
        force_refresh: If True, bypass cache and re-download
        decode_values: If True, decode coded values to human-readable strings

    Returns:
        DataFrame with columns including:
            - year: int
            - ref: int (collision reference number)
            - district: str (policing district name if decoded)
            - district_code: str (original code)
            - month: int
            - day: int
            - weekday: str (day name if decoded)
            - hour: int
            - vehicles: int (number of vehicles)
            - casualties: int (number of casualties)
            - light_conditions: str (if decoded)
            - weather: str (if decoded)
            - road_surface: str (if decoded)
            - lgd_code: str (ONS LGD code)
            - nuts3_code: str (NUTS3 region code)

    Example:
        >>> df = get_collisions(2024)
        >>> print(f"Total collisions: {len(df)}")
        >>> print(df.groupby('district')['casualties'].sum())
    """
    if year is None:
        years = get_available_years()
        if not years:
            raise PSNIDataNotFoundError("No RTC datasets available")
        year = years[0]
        logger.info(f"Using latest available year: {year}")

    url = _get_resource_url(year, "collision")
    file_path = download_file(url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)

    df = pd.read_csv(file_path)

    # Standardize column names
    column_mapping = {
        "a_year": "year",
        "a_ref": "ref",
        "a_District": "district_code",
        "a_type": "collision_type",
        "a_veh": "vehicles",
        "a_cas": "casualties",
        "a_wkday": "weekday_code",
        "a_day": "day",
        "a_month": "month",
        "a_hour": "hour",
        "a_min": "minute",
        "a_speed": "speed_limit",
        "a_light": "light_code",
        "a_weat": "weather_code",
        "a_roadsc": "road_surface_code",
    }
    df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

    # Add decoded values
    if decode_values:
        if "district_code" in df.columns:
            df["district"] = df["district_code"].map(DISTRICT_CODES)
            df["lgd_code"] = df["district"].apply(get_lgd_code)
            df["nuts3_code"] = df["district"].apply(get_nuts3_code)

        if "weekday_code" in df.columns:
            df["weekday"] = df["weekday_code"].map(DAY_OF_WEEK_CODES)

        if "light_code" in df.columns:
            df["light_conditions"] = pd.to_numeric(df["light_code"], errors="coerce").map(LIGHT_CONDITIONS_CODES)

        if "weather_code" in df.columns:
            df["weather"] = pd.to_numeric(df["weather_code"], errors="coerce").map(WEATHER_CODES)

        if "road_surface_code" in df.columns:
            df["road_surface"] = pd.to_numeric(df["road_surface_code"], errors="coerce").map(ROAD_SURFACE_CODES)

    # Create date column
    if all(col in df.columns for col in ["year", "month", "day"]):
        df["date"] = pd.to_datetime(
            {"year": df["year"], "month": df["month"], "day": df["day"]},
            errors="coerce",
        )

    logger.info(f"Loaded {len(df):,} collisions for {year}")
    return df


def get_casualties(
    year: Optional[int] = None,
    force_refresh: bool = False,
    decode_values: bool = True,
) -> pd.DataFrame:
    """Get casualty records for a specific year.

    Each row represents a single casualty involved in a road traffic collision.
    Casualties are linked to collisions via the 'ref' column.

    Args:
        year: Year to fetch (default: latest available)
        force_refresh: If True, bypass cache and re-download
        decode_values: If True, decode coded values to human-readable strings

    Returns:
        DataFrame with columns including:
            - year: int
            - ref: int (collision reference number for linking)
            - vehicle_id: int
            - casualty_id: int
            - casualty_class: str (road user type if decoded)
            - sex_code: int
            - age_group: int
            - severity: str ('Fatal', 'Serious', 'Slight' if decoded)
            - severity_code: int (1=fatal, 2=serious, 3=slight)

    Example:
        >>> df = get_casualties(2024)
        >>> print(df['severity'].value_counts())
        >>> fatal = df[df['severity'] == 'Fatal']
        >>> print(f"Fatal casualties: {len(fatal)}")
    """
    if year is None:
        years = get_available_years()
        if not years:
            raise PSNIDataNotFoundError("No RTC datasets available")
        year = years[0]
        logger.info(f"Using latest available year: {year}")

    url = _get_resource_url(year, "casualty")
    file_path = download_file(url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)

    df = pd.read_csv(file_path)

    # Standardize column names
    column_mapping = {
        "a_year": "year",
        "a_ref": "ref",
        "v_id": "vehicle_id",
        "c_id": "casualty_id",
        "c_class": "casualty_class_code",
        "c_sex": "sex_code",
        "c_agegroup": "age_group",
        "c_sever": "severity_code",
        "c_vtype": "vehicle_type_code",
    }
    df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

    # Add decoded values
    if decode_values:
        if "severity_code" in df.columns:
            df["severity"] = df["severity_code"].map(SEVERITY_CODES)

        if "casualty_class_code" in df.columns:
            df["casualty_class"] = df["casualty_class_code"].map(CASUALTY_CLASS_CODES)

        if "vehicle_type_code" in df.columns:
            df["vehicle_type"] = pd.to_numeric(df["vehicle_type_code"], errors="coerce").map(VEHICLE_TYPE_CODES)

    logger.info(f"Loaded {len(df):,} casualties for {year}")
    return df


def get_vehicles(
    year: Optional[int] = None,
    force_refresh: bool = False,
    decode_values: bool = True,
) -> pd.DataFrame:
    """Get vehicle records for a specific year.

    Each row represents a single vehicle involved in a road traffic collision.
    Vehicles are linked to collisions via the 'ref' column.

    Args:
        year: Year to fetch (default: latest available)
        force_refresh: If True, bypass cache and re-download
        decode_values: If True, decode coded values to human-readable strings

    Returns:
        DataFrame with columns including:
            - year: int
            - ref: int (collision reference number for linking)
            - vehicle_id: int
            - vehicle_type: str (if decoded)
            - vehicle_type_code: int
            - driver_sex_code: int
            - driver_age_group: int

    Example:
        >>> df = get_vehicles(2024)
        >>> print(df['vehicle_type'].value_counts())
    """
    if year is None:
        years = get_available_years()
        if not years:
            raise PSNIDataNotFoundError("No RTC datasets available")
        year = years[0]
        logger.info(f"Using latest available year: {year}")

    url = _get_resource_url(year, "vehicle")
    file_path = download_file(url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)

    df = pd.read_csv(file_path)

    # Standardize column names
    column_mapping = {
        "a_year": "year",
        "a_ref": "ref",
        "v_id": "vehicle_id",
        "v_type": "vehicle_type_code",
        "v_sex": "driver_sex_code",
        "v_agegroup": "driver_age_group",
    }
    df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

    # Add decoded values
    if decode_values:
        if "vehicle_type_code" in df.columns:
            df["vehicle_type"] = df["vehicle_type_code"].map(VEHICLE_TYPE_CODES)

    logger.info(f"Loaded {len(df):,} vehicles for {year}")
    return df


def get_casualties_with_collision_details(
    year: Optional[int] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get casualty records merged with collision details.

    Combines casualty data with collision information including date,
    location, and road conditions.

    Args:
        year: Year to fetch (default: latest available)
        force_refresh: If True, bypass cache and re-download

    Returns:
        DataFrame with casualty records enriched with collision details

    Example:
        >>> df = get_casualties_with_collision_details(2024)
        >>> # Fatal casualties by district
        >>> fatal_by_district = df[df['severity'] == 'Fatal'].groupby('district').size()
        >>> print(fatal_by_district.sort_values(ascending=False))
    """
    casualties = get_casualties(year, force_refresh=force_refresh)
    collisions = get_collisions(year, force_refresh=force_refresh)

    # Select key collision columns for merge
    collision_cols = [
        "ref",
        "district",
        "district_code",
        "date",
        "month",
        "day",
        "weekday",
        "hour",
        "light_conditions",
        "weather",
        "road_surface",
        "lgd_code",
        "nuts3_code",
    ]
    collision_cols = [c for c in collision_cols if c in collisions.columns]

    merged = casualties.merge(collisions[collision_cols], on="ref", how="left", suffixes=("", "_collision"))

    logger.info(f"Merged {len(merged):,} casualty records with collision details")
    return merged


def get_annual_summary(
    years: Optional[List[int]] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get annual summary statistics across multiple years.

    Provides aggregated collision and casualty counts by year, useful for
    trend analysis.

    Args:
        years: List of years to include (default: all available)
        force_refresh: If True, bypass cache and re-download

    Returns:
        DataFrame with columns:
            - year: int
            - collisions: int (total collisions)
            - casualties: int (total casualties)
            - fatal: int (fatal casualties)
            - serious: int (serious injuries)
            - slight: int (slight injuries)
            - fatalities_per_100_collisions: float

    Example:
        >>> summary = get_annual_summary()
        >>> print(summary)
        >>> # Plot fatality trend
        >>> summary.plot(x='year', y='fatal', kind='line')
    """
    if years is None:
        years = get_available_years()

    summaries = []
    for year in years:
        try:
            collisions = get_collisions(year, force_refresh=force_refresh)
            casualties = get_casualties(year, force_refresh=force_refresh)

            fatal = len(casualties[casualties["severity_code"] == 1])
            serious = len(casualties[casualties["severity_code"] == 2])
            slight = len(casualties[casualties["severity_code"] == 3])

            summaries.append(
                {
                    "year": year,
                    "collisions": len(collisions),
                    "casualties": len(casualties),
                    "fatal": fatal,
                    "serious": serious,
                    "slight": slight,
                    "fatalities_per_100_collisions": round(fatal / len(collisions) * 100, 2)
                    if len(collisions) > 0
                    else 0,
                }
            )
        except PSNIDataNotFoundError as e:
            logger.warning(f"Could not fetch data for {year}: {e}")
            continue

    df = pd.DataFrame(summaries)
    df = df.sort_values("year").reset_index(drop=True)

    logger.info(f"Generated annual summary for {len(df)} years")
    return df


def get_casualties_by_district(
    year: Optional[int] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get casualty counts by policing district.

    Args:
        year: Year to fetch (default: latest available)
        force_refresh: If True, bypass cache and re-download

    Returns:
        DataFrame with columns:
            - district: str (policing district name)
            - lgd_code: str (ONS LGD code)
            - collisions: int
            - casualties: int
            - fatal: int
            - serious: int
            - slight: int

    Example:
        >>> by_district = get_casualties_by_district(2024)
        >>> print(by_district.sort_values('fatal', ascending=False))
    """
    df = get_casualties_with_collision_details(year, force_refresh=force_refresh)

    # Aggregate by district
    result = (
        df.groupby(["district", "lgd_code"])
        .agg(
            casualties=("casualty_id", "count"),
            fatal=("severity_code", lambda x: (x == 1).sum()),
            serious=("severity_code", lambda x: (x == 2).sum()),
            slight=("severity_code", lambda x: (x == 3).sum()),
        )
        .reset_index()
    )

    # Add collision count
    collisions = get_collisions(year, force_refresh=force_refresh)
    collision_counts = collisions.groupby("district").size().reset_index(name="collisions")
    result = result.merge(collision_counts, on="district", how="left")

    # Reorder columns
    result = result[["district", "lgd_code", "collisions", "casualties", "fatal", "serious", "slight"]]

    return result.sort_values("casualties", ascending=False).reset_index(drop=True)


def get_casualties_by_road_user(
    year: Optional[int] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get casualty counts by road user type.

    Args:
        year: Year to fetch (default: latest available)
        force_refresh: If True, bypass cache and re-download

    Returns:
        DataFrame with columns:
            - casualty_class: str (road user type)
            - casualties: int
            - fatal: int
            - serious: int
            - slight: int
            - fatality_rate: float (fatal / total %)

    Example:
        >>> by_user = get_casualties_by_road_user(2024)
        >>> print(by_user)
    """
    df = get_casualties(year, force_refresh=force_refresh)

    result = (
        df.groupby("casualty_class")
        .agg(
            casualties=("casualty_id", "count"),
            fatal=("severity_code", lambda x: (x == 1).sum()),
            serious=("severity_code", lambda x: (x == 2).sum()),
            slight=("severity_code", lambda x: (x == 3).sum()),
        )
        .reset_index()
    )

    result["fatality_rate"] = (result["fatal"] / result["casualties"] * 100).round(2)

    return result.sort_values("casualties", ascending=False).reset_index(drop=True)


def validate_data(df: pd.DataFrame, data_type: Literal["collision", "casualty", "vehicle"]) -> bool:
    """Validate RTC data integrity.

    Args:
        df: DataFrame to validate
        data_type: Type of data ('collision', 'casualty', or 'vehicle')

    Returns:
        True if validation passes

    Raises:
        PSNIValidationError: If validation fails
    """
    if df.empty:
        raise PSNIValidationError(f"Empty {data_type} DataFrame")

    # Check for required columns based on type
    required_cols = {
        "collision": ["year", "ref"],
        "casualty": ["year", "ref", "casualty_id"],
        "vehicle": ["year", "ref", "vehicle_id"],
    }

    missing = set(required_cols[data_type]) - set(df.columns)
    if missing:
        raise PSNIValidationError(f"Missing required columns: {missing}")

    # Check year range
    years = df["year"].unique()
    for year in years:
        if not (2010 <= year <= datetime.now().year + 1):
            raise PSNIValidationError(f"Invalid year value: {year}")

    # Check for duplicates in key columns
    if data_type == "collision":
        if df.duplicated(subset=["year", "ref"]).any():
            raise PSNIValidationError("Duplicate collision records found")

    elif data_type == "casualty":
        if df.duplicated(subset=["year", "ref", "casualty_id"]).any():
            raise PSNIValidationError("Duplicate casualty records found")

    logger.info(f"Validation passed for {len(df):,} {data_type} records")
    return True
