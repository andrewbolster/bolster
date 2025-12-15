bolster.utils.web
=================

.. py:module:: bolster.utils.web


Attributes
----------

.. autoapisummary::

   bolster.utils.web.ua
   bolster.utils.web.session


Functions
---------

.. autoapisummary::

   bolster.utils.web.get_last_valid
   bolster.utils.web.resilient_get
   bolster.utils.web.get_excel_dataframe
   bolster.utils.web.download_extract_zip


Module Contents
---------------

.. py:data:: ua

.. py:data:: session

.. py:function:: get_last_valid(url)

.. py:function:: resilient_get(url, **kwargs)

   Attempt a get, but if it fails, try using the wayback machine to get the last valid version and get that.
   If all else fails, raise a HTTPError from the inner "NoCDXRecordFound" exception


.. py:function:: get_excel_dataframe(file_url, requests_kwargs = None, read_kwargs = None)

.. py:function:: download_extract_zip(url)

   Download a ZIP file and extract its contents in memory
   yields (filename, file-like object) pairs
