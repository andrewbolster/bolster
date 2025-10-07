"""
Working with Northern Ireland Water Quality Data

Very basic at the moment. Mostly just to put numbers to how 'hard' people think they are for comedy.

"""

import csv
import logging
from typing import Dict
from urllib.error import HTTPError

import pandas as pd
import requests
from lxml.etree import XMLSyntaxError

from bolster import backoff

POSTCODE_DATASET_URL = "https://admin.opendatani.gov.uk/dataset/38a9a8f1-9346-41a2-8e5f-944d87d9caf2/resource/f2bc12c1-4277-4db5-8bd3-b7bb027cc401/download/postcode-v-zone-lookup-by-year.csv"

T_HARDNESS = pd.CategoricalDtype(["Soft", "Moderately Soft", "Slightly Hard", "Moderately Hard"], ordered=True)

INVALID_ZONE_IDENTIFIER = "No Zone Identified"


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


@backoff(HTTPError)
def get_water_quality_by_postcode(postcode: str, zone_code: str = None, strict=False) -> pd.Series:
    """
    Get the latest Water Quality for a given NI Postcode

    >>> data = get_water_quality_by_postcode('BT14 7EJ')
    >>> data['Water Supply Zone']
    'Dunore Ballygomartin North'
    >>> data.index.tolist()  # doctest: +NORMALIZE_WHITESPACE
    ['Water Supply Zone', 'Raw Water Source', 'Zone water quality report (2024 dataset)',
     'Total Hardness (mg/l)', 'Magnesium (mg/l)', 'Potassium (mg/l)', 'Calcium (mg/l)',
     'Total Hardness (mg CaCO3/l)', 'Clark English Degrees', 'French Degrees',
     'German Degrees', 'NI Hardness Classification', 'Dishwasher Setting']

    >>> get_water_quality_by_postcode('XXXXXX', strict=True)
    Traceback (most recent call last):
    ...
    ValueError: Potentially invalid Postcode XXXXXX
    """
    # Remove spaces from postcode for API call
    postcode_clean = postcode.replace(" ", "")

    try:
        # Check if this postcode has multiple addresses (need zone code)
        response = requests.get(f"https://www.niwater.com/api/water-quality/getitem?p={postcode_clean}")
        response.raise_for_status()

        # If response contains '|', it means multiple addresses
        if '|' in response.text:
            if zone_code:
                # Query with zone code and postcode
                tables = pd.read_html(
                    f"https://www.niwater.com/api/water-quality/getitem?z={zone_code}&p={postcode_clean}",
                    match="Water Supply Zone"
                )
            else:
                # Extract first zone code from the select options
                import re
                zone_match = re.search(r'value="(ZS\d+)"', response.text)
                if zone_match:
                    first_zone = zone_match.group(1)
                    tables = pd.read_html(
                        f"https://www.niwater.com/api/water-quality/getitem?z={first_zone}&p={postcode_clean}",
                        match="Water Supply Zone"
                    )
                else:
                    raise ValueError(f"Could not extract zone code for postcode {postcode}")
        else:
            # Single address, can use just postcode
            tables = pd.read_html(
                f"https://www.niwater.com/api/water-quality/getitem?p={postcode_clean}",
                match="Water Supply Zone"
            )

        if not tables:
            raise ValueError(f"No water quality data found for postcode {postcode}")

        data = tables[0].set_index(0)[1]
        # Filter out the postcode header row (e.g., "BT147EJ")
        data = data[~data.index.str.contains(postcode_clean, case=False, na=False)]
        data.name = postcode
        return data
    except (HTTPError, ValueError, XMLSyntaxError) as err:
        if strict:
            raise ValueError(f"Potentially invalid Postcode {postcode}") from err
        else:
            logging.warning(f"Potentially invalid Postcode {postcode}")
            return pd.Series(name=postcode)


# This may throw 503's on occasion which annoyingly makes it stocastic
@backoff(HTTPError)
def get_water_quality_by_zone(zone_code: str, strict=False) -> pd.Series:
    """
    Get the latest Water Quality for a given Water Supply Zone

    Note: This function now uses a postcode lookup. It finds a postcode associated
    with the zone and returns the water quality data for that postcode.

    >>> data = get_water_quality_by_zone('ZS0101')
    >>> data['Water Supply Zone']
    'Dunore Ballygomartin North'

    >>> get_water_quality_by_zone('XXXXXX', strict=True)
    Traceback (most recent call last):
    ...
    ValueError: Potentially invalid Water Supply Zone XXXXXX
    """
    # Get postcode-to-zone mapping
    zones = get_postcode_to_water_supply_zone()

    # Find a postcode for this zone
    postcode = None
    for pc, z in zones.items():
        if z == zone_code:
            postcode = pc
            break

    if postcode is None:
        if strict:
            raise ValueError(f"Potentially invalid Water Supply Zone {zone_code}")
        else:
            logging.warning(f"No postcode found for Water Supply Zone {zone_code}")
            return pd.Series(name=zone_code)

    # Get water quality data using the postcode and zone code
    data = get_water_quality_by_postcode(postcode, zone_code=zone_code, strict=strict)
    data.name = zone_code
    return data


def get_water_quality() -> pd.DataFrame:
    """
    Get a DataFrame of Water Quality Data from https://www.niwater.com/

    >>> df = get_water_quality()
    >>> df.shape[1]
    11

    Hardness is _technically_ ordered... (The trick here is that `sort=False` disables
    the automatic sorting by count of appearances.
    >>> df['NI Hardness Classification'].value_counts(sort=False) # doctest:+ELLIPSIS
    NI Hardness Classification
    Soft               ...
    Moderately Soft    ...
    Slightly Hard      ...
    Moderately Hard    ...
    Name: count, dtype: int64

    """
    supply_zones = set(get_postcode_to_water_supply_zone().values())

    df = pd.DataFrame(
        [get_water_quality_by_zone(zone_code) for zone_code in supply_zones if zone_code != INVALID_ZONE_IDENTIFIER]
    )
    df = df.astype({"NI Hardness Classification": T_HARDNESS})
    return df
