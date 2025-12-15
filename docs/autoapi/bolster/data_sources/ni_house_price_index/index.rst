bolster.data_sources.ni_house_price_index
=========================================

.. py:module:: bolster.data_sources.ni_house_price_index

.. autoapi-nested-parse::

   Working with the Norther Ireland House Price index data

   Original Source: https://www.nisra.gov.uk/statistics/housing-community-and-regeneration/northern-ireland-house-price-index

   See [here](https://andrewbolster.info/2022/03/NI-House-Price-Index.html) for more details

   Generic problems fixed;

   * Tables offset from header with notes and annotations
   * Inconsistent offset
   * Inconsistent treatment of quarterly periods (Q1 2020/Quarter 1 2020/ (2020,Q1) etc)
   * Inconsistent header alignment (i.e. leaving sub-category annotations on what is actually the period index header)



Attributes
----------

.. autoapisummary::

   bolster.data_sources.ni_house_price_index.DEFAULT_URL
   bolster.data_sources.ni_house_price_index.TABLE_TRANSFORMATION_MAP


Functions
---------

.. autoapisummary::

   bolster.data_sources.ni_house_price_index.get_source_url
   bolster.data_sources.ni_house_price_index.pull_sources
   bolster.data_sources.ni_house_price_index.basic_cleanup
   bolster.data_sources.ni_house_price_index.cleanup_contents
   bolster.data_sources.ni_house_price_index.cleanup_price_by_property_type_agg
   bolster.data_sources.ni_house_price_index.cleanup_price_by_property_type
   bolster.data_sources.ni_house_price_index.cleanup_with_munged_quarters_and_total_rows
   bolster.data_sources.ni_house_price_index.cleanup_with_LGDs
   bolster.data_sources.ni_house_price_index.cleanup_merged_year_quarters_and_totals
   bolster.data_sources.ni_house_price_index.cleanup_missing_year_quarter
   bolster.data_sources.ni_house_price_index.transform_sources
   bolster.data_sources.ni_house_price_index.build


Module Contents
---------------

.. py:data:: DEFAULT_URL
   :value: 'https://www.finance-ni.gov.uk/publications/ni-house-price-index-statistical-reports'


.. py:data:: TABLE_TRANSFORMATION_MAP

.. py:function:: get_source_url(base_url=DEFAULT_URL)

.. py:function:: pull_sources(base_url=DEFAULT_URL)

   Pull raw NI House Price Index Excel from finance-ni.gov.uk listing

   :param base_url:


.. py:function:: basic_cleanup(df, offset=1)

   Generic cleanup operations for NI HPI data;
   * Re-header from Offset row and translate table to eliminate incorrect headers
   * remove any columns with 'Nan' or 'None' in the given offset-row
   * If 'NI' appears and all the values are 100, remove it.
   * Remove any rows below and including the first 'all nan' row (gets most tail-notes)
   * If 'Sale Year','Sale Quarter' appear in the columns, replace with 'Year','Quarter' respectively
   * For Year; forward fill any none/nan values
   * If Year/Quarter appear, add  a new composite 'Period' column with a PeriodIndex columns representing the
       year/quarter (i.e. 2022-Q1)
   * Reset and drop the index
   * Attempt to infer the new/current column object types

   :param df:
   :param offset:


.. py:function:: cleanup_contents(df)

   Fix Contents table of NI HPI Stats
   * Shift/rebuild headers
   * Strip Figures because they're gonna be broken anyway

   :param df:


.. py:function:: cleanup_price_by_property_type_agg(df)

   NI HPI & Standardised Price Statistics by Property Type (Aggregate Table)

   Standard cleanup with a split to remove trailing index date data

   :param df:


.. py:function:: cleanup_price_by_property_type(df)

   NI HPI & Standardised Price Statistics by Property Type (Per Class)

   Standard cleanup, removing the property class from the table columns

   :param df:


.. py:function:: cleanup_with_munged_quarters_and_total_rows(df, offset=3)

   Number of Verified Residential Property Sales

   * Regex 'Quarter X' to 'QX' in future 'Sales Quarter' column
   * Drop Year Total rows
   * Clear any Newlines from the future 'Sales Year' column
   * call `basic_cleanup` with offset=3

   :param df:


.. py:function:: cleanup_with_LGDs(df)

   Standardised House Price & Index for each Local Government District Northern Ireland
   * Build multi-index of LGD / Metric [Index,Price]



.. py:function:: cleanup_merged_year_quarters_and_totals(df)

   Table 5a: Number of Verified Residential Property Sales by Local Government District
   * Remove 'Total' rows (i.e. Yearly totals)
   * Replace 'Quarter N' with 'QN' in the Sale Quarter column


.. py:function:: cleanup_missing_year_quarter(df)

   Table 7: Standardised House Price & Index for Rural Areas of Northern Ireland by drive times
   * Insert Year/Quarter future-headers
   * Clean normally
   # TODO THIS MIGHT BE VALID FOR MULTIINDEXING ON DRIVETIME/[Index/Price]


.. py:function:: transform_sources(source_df)

   Cleanup all the tables from the NI Housing Price Index, conforming to the best attempt at a 'standard'

   :param source_df:


.. py:function:: build()

   Pulls and Cleans up the latest Northern Ireland House Price Index Data
