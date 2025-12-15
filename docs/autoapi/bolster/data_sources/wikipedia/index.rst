bolster.data_sources.wikipedia
==============================

.. py:module:: bolster.data_sources.wikipedia


Functions
---------

.. autoapisummary::

   bolster.data_sources.wikipedia.get_ni_executive_basic_table


Module Contents
---------------

.. py:function:: get_ni_executive_basic_table()

   Takes Data from https://en.wikipedia.org/wiki/Northern_Ireland_Executive#Composition_since_devolution
   Table should be called "Historical composition of the Northern Ireland Executive "

   EG
           Established Dissolved       Duration        Interregnum
   Executive
   1st 1998-07-01      2002-10-14      1566 days       1667 days
   2nd 2007-05-08      2011-03-24      1416 days       53 days
   3rd 2011-05-16      2016-05-16      1827 days       10 days
   4th 2016-05-26      2017-01-16      235 days        1090 days
   5th 2020-01-11      2022-02-03      754 days        730 days
   6th 2024-02-03      NaT     127 days        NaT

   >>> get_ni_executive_basic_table().dtypes
   Established     datetime64[ns]
   Dissolved       datetime64[ns]
   Duration       timedelta64[ns]
   Interregnum    timedelta64[ns]
   dtype: object
