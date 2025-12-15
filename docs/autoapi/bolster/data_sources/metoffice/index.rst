bolster.data_sources.metoffice
==============================

.. py:module:: bolster.data_sources.metoffice

.. autoapi-nested-parse::

   This script fetches weather data from the Met Office API, processes it, and generates an image suitable for epaper display, and might be useful for other
   applications as well. It uses the Pillow library for image processing and the requests library for API calls.

   See [here](https://datahub.metoffice.gov.uk/docs/f/category/map-images/type/map-images/api-documentation) for more information on the API.



Attributes
----------

.. autoapisummary::

   bolster.data_sources.metoffice.BASE_URL
   bolster.data_sources.metoffice.session
   bolster.data_sources.metoffice.is_my_date


Functions
---------

.. autoapisummary::

   bolster.data_sources.metoffice.get_order_latest
   bolster.data_sources.metoffice.get_file_meta
   bolster.data_sources.metoffice.get_file
   bolster.data_sources.metoffice.filter_relevant_files
   bolster.data_sources.metoffice.make_borders
   bolster.data_sources.metoffice.make_isolines
   bolster.data_sources.metoffice.make_precipitation
   bolster.data_sources.metoffice.generate_image
   bolster.data_sources.metoffice.get_uk_precipitation


Module Contents
---------------

.. py:data:: BASE_URL
   :value: 'https://data.hub.api.metoffice.gov.uk/map-images/1.0.0'


.. py:data:: session

.. py:function:: get_order_latest(order_name)

.. py:function:: get_file_meta(order_name, file_id)

.. py:function:: get_file(order_name, file_id)

.. py:data:: is_my_date

.. py:function:: filter_relevant_files(order_status)

.. py:function:: make_borders(data)

.. py:function:: make_isolines(data)

.. py:function:: make_precipitation(data)

.. py:function:: generate_image(order_name, block, bounding_box = (100, 250, 500, 550))

.. py:function:: get_uk_precipitation(order_name, bounding_box = None)

   Get the latest UK precipitation forecast from the Met Office API and generate an image suitable for epaper display.


