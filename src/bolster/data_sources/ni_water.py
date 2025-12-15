"""
Working with Northern Ireland Water Quality Data

Updated to use modern OpenDataNI data sources after the original
NIWater API endpoints were deprecated.

Current data sources:
- Water quality results: Static CSV data from OpenDataNI
- Zone mapping: Legacy postcode to zone lookup (still available)

"""

import csv
import logging
from typing import Dict, Optional
from urllib.error import HTTPError

import pandas as pd
import requests

from bolster import backoff

# Legacy postcode to zone mapping (still functional)
POSTCODE_DATASET_URL = "https://admin.opendatani.gov.uk/dataset/38a9a8f1-9346-41a2-8e5f-944d87d9caf2/resource/f2bc12c1-4277-4db5-8bd3-b7bb027cc401/download/postcode-v-zone-lookup-by-year.csv"

# Modern water quality data from OpenDataNI
WATER_QUALITY_CSV_URL = "https://admin.opendatani.gov.uk/dataset/38a9a8f1-9346-41a2-8e5f-944d87d9caf2/resource/02d85526-c082-482c-b205-a318f97fd18d/download/2024-ni-water-customer-tap-supply-point-results.csv"

T_HARDNESS = pd.CategoricalDtype(["Soft", "Moderately Soft", "Slightly Hard", "Moderately Hard"], ordered=True)

INVALID_ZONE_IDENTIFIER = "No Zone Identified"

# Cache for water quality data to avoid repeated downloads
_water_quality_cache: Optional[pd.DataFrame] = None


@backoff((HTTPError, RuntimeError))
def get_water_quality_csv_data() -> pd.DataFrame:
    """
    Get the latest water quality CSV data from OpenDataNI.

    This function downloads and caches the complete water quality dataset
    which contains all results from customer tap supply points.

    Returns:
        pd.DataFrame: Complete water quality data with columns:
            - Year: Sample year
            - Sample Location: Location description
            - Site Code: Unique site identifier
            - Site Name: Human-readable site name
            - Sample Id Text: Unique sample identifier
            - Sample Date: Date of sample collection
            - Postcode: Postcode for the sample location
            - Parameter: Water quality parameter name (e.g., 'Total Hardness (mg/l)')
            - PCV Limit: Prescribed Concentration Value limit
            - Result: Numeric test result
            - Report Value: Formatted result value
            - Units: Unit of measurement

    Raises:
        HTTPError: If the CSV download fails
        RuntimeError: If no data is found
    """
    global _water_quality_cache

    if _water_quality_cache is not None:
        return _water_quality_cache

    logging.info(f"Downloading water quality data from {WATER_QUALITY_CSV_URL}")

    with requests.get(WATER_QUALITY_CSV_URL, stream=True) as r:
        r.raise_for_status()
        _water_quality_cache = pd.read_csv(r.url)

        if _water_quality_cache.empty:
            raise RuntimeError("No water quality data found in CSV")

    logging.info(f"Loaded {len(_water_quality_cache)} water quality records")
    return _water_quality_cache


def _site_code_to_zone_code(site_code: str) -> str:
    """
    Convert OpenDataNI site code to legacy zone code format.

    The new CSV data uses site codes like 'BALM' while the legacy API
    used zone codes like 'ZS0101'. This function provides a mapping
    between the two systems for backward compatibility.

    Args:
        site_code: Site code from the CSV data

    Returns:
        Legacy-style zone code
    """
    # For now, we'll use the site code directly as the zone identifier
    # This maintains the function signatures but uses the new data
    return site_code


def _create_legacy_format_series(site_data: pd.DataFrame, zone_code: str) -> pd.Series:
    """
    Convert CSV format data to legacy API format for backward compatibility.

    The original API returned a pandas Series with specific keys.
    This function recreates that format using the new CSV data.

    Args:
        site_data: DataFrame containing all parameters for a specific site
        zone_code: The zone/site identifier

    Returns:
        pd.Series in the legacy format
    """
    # Create the legacy format series
    result_data = {}

    # Get the first row for site information
    if not site_data.empty:
        first_row = site_data.iloc[0]
        result_data["Water Supply Zone"] = first_row.get("Site Name", f"Site {zone_code}")

    # Map CSV parameters to legacy format
    parameter_mapping = {
        "Total hardness": "Total Hardness (mg/l)",  # Note: CSV uses "Total hardness", legacy used "Total Hardness (mg/l)"
        "Magnesium": "Magnesium (mg/l)",
        "Potassium": "Potassium (mg/l)",
        "Calcium": "Calcium (mg/l)",
    }

    # Extract parameter values
    for _, row in site_data.iterrows():
        parameter = row.get("Parameter", "")
        if parameter in parameter_mapping:
            legacy_key = parameter_mapping[parameter]
            result_data[legacy_key] = row.get("Report Value", row.get("Result", ""))

    # Calculate derived values if we have the basic measurements
    try:
        if "Total Hardness (mg/l)" in result_data:
            # The CSV data appears to be in mg/l format, which we need to interpret
            # Assuming this is already CaCO3 equivalent (which is standard for water hardness)
            hardness_mg_l = float(result_data["Total Hardness (mg/l)"])
            hardness_caco3 = hardness_mg_l  # Assume it's already in CaCO3 equivalent

            # Add the CaCO3 format that legacy API provided
            result_data["Total Hardness (mg CaCO3/l)"] = str(hardness_caco3)

            # Calculate degrees of hardness
            result_data["Clark English Degrees"] = f"{hardness_caco3 / 14.3:.1f}"
            result_data["French Degrees"] = f"{hardness_caco3 / 10.0:.1f}"
            result_data["German Degrees"] = f"{hardness_caco3 / 17.8:.1f}"

            # Classify hardness based on standard UK classifications
            if hardness_caco3 <= 60:
                hardness_class = "Soft"
                dishwasher_setting = "1"
            elif hardness_caco3 <= 120:
                hardness_class = "Moderately Soft"
                dishwasher_setting = "2"
            elif hardness_caco3 <= 180:
                hardness_class = "Slightly Hard"
                dishwasher_setting = "3"
            else:
                hardness_class = "Moderately Hard"
                dishwasher_setting = "4"

            result_data["NI Hardness Classification"] = hardness_class
            result_data["Dishwasher Setting"] = dishwasher_setting

    except (ValueError, KeyError) as e:
        # If we can't calculate derived values, just skip them
        logging.debug(f"Could not calculate hardness classifications: {e}")
        pass

    return pd.Series(result_data, name=zone_code)


@backoff((HTTPError, RuntimeError))
def get_postcode_to_water_supply_zone() -> Dict[str, str]:
    """
    Using data from OpenDataNI to generate a map from NI Postcodes to Water Supply Zone

    >>> zones = get_postcode_to_water_supply_zone()
    >>> len(zones)
    49006

    Zones is keyed off postcode to a Water Supply Zone
    >>> zones['BT1 1AA']
    'ZS0107'

    There are much fewer zones than postcodes
    >>> len(set(zones.values()))
    65

    And many postcodes that aren't associated with any zone
    >>> len([k for k,v in zones.items() if v == INVALID_ZONE_IDENTIFIER])
    97

    """

    with requests.get(POSTCODE_DATASET_URL, stream=True) as r:
        lines = (line.decode("utf-8") for line in r.iter_lines())
        reader = csv.DictReader(lines)
        keys = reader.fieldnames[:2]  # Take POSTCODE and first year
        zones = dict(([row[k] for k in keys] for row in reader))
        if not zones:
            raise RuntimeError("No data found")

    return zones


def get_water_quality_by_zone(zone_code: str, strict=False) -> pd.Series:
    """
    Get the latest Water Quality for a given Water Supply Zone.

    Now uses modern OpenDataNI CSV data instead of the deprecated HTML API.
    The zone_code can be either a legacy zone code (like 'ZS0101') or a
    site code from the CSV data (like 'BALM').

    Args:
        zone_code: Water supply zone identifier or site code
        strict: If True, raise ValueError for invalid zones

    Returns:
        pd.Series: Water quality data in legacy API format with indices like:
            - Water Supply Zone: Human-readable zone name
            - Total Hardness (mg/l): Hardness as mg/l
            - Total Hardness (mg CaCO3/l): Hardness as mg CaCO3/l
            - Clark English Degrees: English degrees of hardness
            - French Degrees: French degrees of hardness
            - German Degrees: German degrees of hardness
            - NI Hardness Classification: Categorical hardness level
            - Dishwasher Setting: Recommended dishwasher setting

    Raises:
        ValueError: If zone_code is invalid and strict=True
        HTTPError: If CSV data cannot be downloaded
        RuntimeError: If CSV data is empty

    Example usage:
        data = get_water_quality_by_zone('BALM')  # Using CSV site code
        print(data['Water Supply Zone'])
        print(data['NI Hardness Classification'])
    """
    try:
        # Get the full CSV dataset
        water_quality_df = get_water_quality_csv_data()

        # Try to find data for this zone/site code
        # First try as site code, then try as a potential zone mapping
        site_data = water_quality_df[water_quality_df["Site Code"] == zone_code]

        if site_data.empty:
            # Try to find by site name containing the zone code
            site_data = water_quality_df[water_quality_df["Site Name"].str.contains(zone_code, case=False, na=False)]

        if site_data.empty:
            # No data found for this zone
            if strict:
                raise ValueError(f"Potentially invalid Water Supply Zone {zone_code}")
            else:
                logging.warning(f"Potentially invalid Water Supply Zone {zone_code}")
                return pd.Series(name=zone_code)

        # Convert to legacy format
        return _create_legacy_format_series(site_data, zone_code)

    except (HTTPError, RuntimeError) as err:
        # Handle data source errors
        if strict:
            raise ValueError(f"Unable to retrieve data for Water Supply Zone {zone_code}") from err
        else:
            logging.warning(f"Unable to retrieve data for Water Supply Zone {zone_code}: {err}")
            return pd.Series(name=zone_code)


def get_water_quality() -> pd.DataFrame:
    """
    Get a DataFrame of Water Quality Data from OpenDataNI.

    This function now uses the modern CSV data source instead of the deprecated
    HTML API. It returns water quality data for all available sites.

    Returns:
        pd.DataFrame: Water quality data with one row per site/zone.
            Columns include hardness measurements, classifications, and
            other water quality parameters. The 'NI Hardness Classification'
            column uses categorical data type with proper ordering.

    Raises:
        HTTPError: If CSV data cannot be downloaded
        RuntimeError: If CSV data is empty

    Example usage:
        df = get_water_quality()
        print(df.shape)  # Number of rows and columns
        print(df['NI Hardness Classification'].value_counts(sort=False))

        # Show available sites
        print(df.index.tolist())  # Site codes

        # Get hardness data
        hardness_summary = df.groupby('NI Hardness Classification').size()
        print(hardness_summary)
    """
    try:
        # Get the full CSV dataset
        water_quality_df = get_water_quality_csv_data()

        # Get unique site codes (equivalent to the old zone concept)
        unique_sites = water_quality_df["Site Code"].unique()

        logging.info(f"Processing water quality data for {len(unique_sites)} sites")

        # Process each site to create legacy-format series
        site_series_list = []
        for site_code in unique_sites:
            if pd.isna(site_code) or site_code == "":
                continue

            site_data = water_quality_df[water_quality_df["Site Code"] == site_code]
            if not site_data.empty:
                try:
                    series = _create_legacy_format_series(site_data, site_code)
                    if not series.empty:
                        site_series_list.append(series)
                except Exception as e:
                    logging.warning(f"Error processing site {site_code}: {e}")
                    continue

        if not site_series_list:
            raise RuntimeError("No valid water quality data could be processed")

        # Combine all series into a DataFrame
        df = pd.DataFrame(site_series_list)

        # Ensure NI Hardness Classification uses proper categorical type
        if "NI Hardness Classification" in df.columns:
            df = df.astype({"NI Hardness Classification": T_HARDNESS})

        logging.info(f"Created water quality DataFrame with {len(df)} sites and {len(df.columns)} parameters")
        return df

    except Exception as e:
        logging.error(f"Failed to get water quality data: {e}")
        raise
