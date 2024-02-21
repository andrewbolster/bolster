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

T_HARDNESS = pd.CategoricalDtype(
    ["Soft", "Moderately Soft", "Slightly Hard", "Moderately Hard"], ordered=True
)


def get_postcode_to_water_supply_zone() -> Dict[str, str]:
    """
    Using data from OpenDataNI to generate a map from NI Postcodes to Water Supply Zone

    >>> zones = get_postcode_to_water_supply_zone()
    >>> len(zones)
    48805

    Zones is keyed off postcode to a Water Supply Zone
    >>> zones['BT1 1AA']
    'ZS0107'

    There are much fewer zones than postcodes
    >>> len(set(zones.values()))
    56

    And many postcodes that aren't associated with any zone
    >>> len([k for k,v in zones.items() if v == '#N/A'])
    36

    """

    with requests.get(POSTCODE_DATASET_URL, stream=True) as r:
        lines = (line.decode("utf-8") for line in r.iter_lines())
        reader = csv.DictReader(lines)
        keys = reader.fieldnames[:2]  # Take POSTCODE and first year
        zones = dict(([row[k] for k in keys] for row in reader))

    return zones


# This may throw 503's on occasion which annoyingly makes it stocastic
@backoff(HTTPError)
def get_water_quality_by_zone(zone_code: str, strict=False) -> pd.Series:
    """
    Get the latest Water Quality for a given Water Supply Zone

    >>> data = get_water_quality_by_zone('ZS0101')
    >>> data['Water Supply Zone']
    'Dunore Ballygomartin North'
    >>> data.index
    Index(['Water Supply Zone', 'Total Hardness (mg/l)', 'Magnesium (mg/l)',
           'Potassium (mg/l)', 'Calcium (mg/l)', 'Total Hardness (mg CaCO3/l)',
           'Clark English Degrees', 'French Degrees', 'German Degrees',
           'NI Hardness Classification', 'Dishwasher Setting'],
          dtype='object', name=0)

    >>> get_water_quality_by_zone('XXXXXX', strict=True)
    Traceback (most recent call last):
    ...
    ValueError: Potentially invalid Water Supply Zone XXXXXX
    """
    try:
        d, _, _ = pd.read_html(
            f"https://www.niwater.com/water-quality-lookup.ashx?z={zone_code}"
        )
    except XMLSyntaxError as err:
        if strict:
            raise ValueError(
                f"Potentially invalid Water Supply Zone {zone_code}"
            ) from err
        else:
            logging.warning(f"Potentially invalid Water Supply Zone {zone_code}")
            return pd.Series(name=zone_code)

    data = d.dropna().set_index(0)[1]
    data.drop("Zone water quality report (2023 dataset)", inplace=True)
    data.name = zone_code
    return data


def get_water_quality() -> pd.DataFrame:
    """
    Get a DataFrame of Water Quality Data from https://www.niwater.com/

    >>> df = get_water_quality()
    >>> df.shape
    (55, 11)

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
        [
            get_water_quality_by_zone(zone_code)
            for zone_code in supply_zones
            if zone_code != "#N/A"
        ]
    )
    df = df.astype({"NI Hardness Classification": T_HARDNESS})
    return df
