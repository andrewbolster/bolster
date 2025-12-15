bolster.data_sources.ni_water
=============================

.. py:module:: bolster.data_sources.ni_water

.. autoapi-nested-parse::

   Working with Northern Ireland Water Quality Data

   Updated to use modern OpenDataNI data sources after the original
   NIWater API endpoints were deprecated.

   Current data sources:
   - Water quality results: Static CSV data from OpenDataNI
   - Zone mapping: Legacy postcode to zone lookup (still available)



Attributes
----------

.. autoapisummary::

   bolster.data_sources.ni_water.POSTCODE_DATASET_URL
   bolster.data_sources.ni_water.WATER_QUALITY_CSV_URL
   bolster.data_sources.ni_water.T_HARDNESS
   bolster.data_sources.ni_water.INVALID_ZONE_IDENTIFIER


Functions
---------

.. autoapisummary::

   bolster.data_sources.ni_water.get_water_quality_csv_data
   bolster.data_sources.ni_water.get_postcode_to_water_supply_zone
   bolster.data_sources.ni_water.get_water_quality_by_zone
   bolster.data_sources.ni_water.get_water_quality


Module Contents
---------------

.. py:data:: POSTCODE_DATASET_URL
   :value: 'https://admin.opendatani.gov.uk/dataset/38a9a8f1-9346-41a2-8e5f-944d87d9caf2/resource/f2bc12c1-4...


.. py:data:: WATER_QUALITY_CSV_URL
   :value: 'https://admin.opendatani.gov.uk/dataset/38a9a8f1-9346-41a2-8e5f-944d87d9caf2/resource/02d85526-c...


.. py:data:: T_HARDNESS

.. py:data:: INVALID_ZONE_IDENTIFIER
   :value: 'No Zone Identified'


.. py:function:: get_water_quality_csv_data()

   Get the latest water quality CSV data from OpenDataNI.

   This function downloads and caches the complete water quality dataset
   which contains all results from customer tap supply points.

   :returns:

             Complete water quality data with columns:
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
   :rtype: pd.DataFrame

   :raises HTTPError: If the CSV download fails
   :raises RuntimeError: If no data is found


.. py:function:: get_postcode_to_water_supply_zone()

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



.. py:function:: get_water_quality_by_zone(zone_code, strict=False)

   Get the latest Water Quality for a given Water Supply Zone.

   Now uses modern OpenDataNI CSV data instead of the deprecated HTML API.
   The zone_code can be either a legacy zone code (like 'ZS0101') or a
   site code from the CSV data (like 'BALM').

   :param zone_code: Water supply zone identifier or site code
   :param strict: If True, raise ValueError for invalid zones

   :returns:

             Water quality data in legacy API format with indices like:
                 - Water Supply Zone: Human-readable zone name
                 - Total Hardness (mg/l): Hardness as mg/l
                 - Total Hardness (mg CaCO3/l): Hardness as mg CaCO3/l
                 - Clark English Degrees: English degrees of hardness
                 - French Degrees: French degrees of hardness
                 - German Degrees: German degrees of hardness
                 - NI Hardness Classification: Categorical hardness level
                 - Dishwasher Setting: Recommended dishwasher setting
   :rtype: pd.Series

   :raises ValueError: If zone_code is invalid and strict=True
   :raises HTTPError: If CSV data cannot be downloaded
   :raises RuntimeError: If CSV data is empty

   Example usage:
       data = get_water_quality_by_zone('BALM')  # Using CSV site code
       print(data['Water Supply Zone'])
       print(data['NI Hardness Classification'])


.. py:function:: get_water_quality()

   Get a DataFrame of Water Quality Data from OpenDataNI.

   This function now uses the modern CSV data source instead of the deprecated
   HTML API. It returns water quality data for all available sites.

   :returns:

             Water quality data with one row per site/zone.
                 Columns include hardness measurements, classifications, and
                 other water quality parameters. The 'NI Hardness Classification'
                 column uses categorical data type with proper ordering.
   :rtype: pd.DataFrame

   :raises HTTPError: If CSV data cannot be downloaded
   :raises RuntimeError: If CSV data is empty

   Example usage:
       df = get_water_quality()
       print(df.shape)  # Number of rows and columns
       print(df['NI Hardness Classification'].value_counts(sort=False))

       # Show available sites
       print(df.index.tolist())  # Site codes

       # Get hardness data
       hardness_summary = df.groupby('NI Hardness Classification').size()
       print(hardness_summary)


