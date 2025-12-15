bolster.utils.azure
===================

.. py:module:: bolster.utils.azure

.. autoapi-nested-parse::

   Azure Utils



Functions
---------

.. autoapisummary::

   bolster.utils.azure.az_file_url_to_query_components


Package Contents
----------------

.. py:function:: az_file_url_to_query_components(url)

   Helper function to parse an Azure file URL into its components to then be used by `pandas`/`dask`/`fsspec` etc.

   >>> az_file_url_to_query_components("https://storageaccount.blob.core.windows.net/container/file_path.parquet")
   {'storage_account': 'storageaccount', 'container': 'container', 'file_path': 'file_path.parquet'}
