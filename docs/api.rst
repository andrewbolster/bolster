API Reference
=============

This page contains a comprehensive reference for all public APIs in the Bolster package.

Core Utilities
--------------

The main ``bolster`` module provides core utilities for data processing, concurrency, and general Python development tasks.

.. automodule:: bolster
   :members:
   :undoc-members:
   :show-inheritance:

Data Sources
------------

Bolster provides specialized modules for accessing Northern Ireland and UK data sources.

Northern Ireland Water Quality
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: bolster.data_sources.ni_water
   :members:
   :undoc-members:
   :show-inheritance:

Electoral Office for Northern Ireland (EONI)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: bolster.data_sources.eoni
   :members:
   :undoc-members:
   :show-inheritance:

Companies House
~~~~~~~~~~~~~~~

.. automodule:: bolster.data_sources.companies_house
   :members:
   :undoc-members:
   :show-inheritance:

Met Office Weather Data
~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: bolster.data_sources.metoffice
   :members:
   :undoc-members:
   :show-inheritance:

Northern Ireland House Price Index
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: bolster.data_sources.ni_house_price_index
   :members:
   :undoc-members:
   :show-inheritance:

Wikipedia Data
~~~~~~~~~~~~~~

.. automodule:: bolster.data_sources.wikipedia
   :members:
   :undoc-members:
   :show-inheritance:

Utilities
---------

Web Utilities
~~~~~~~~~~~~~

.. automodule:: bolster.utils.web
   :members:
   :undoc-members:
   :show-inheritance:

Date/Time Utilities
~~~~~~~~~~~~~~~~~~~

.. automodule:: bolster.utils.dt
   :members:
   :undoc-members:
   :show-inheritance:

I/O Utilities
~~~~~~~~~~~~~

.. automodule:: bolster.utils.io
   :members:
   :undoc-members:
   :show-inheritance:

Cloud Services
--------------

AWS Utilities
~~~~~~~~~~~~~

.. automodule:: bolster.utils.aws
   :members:
   :undoc-members:
   :show-inheritance:

Azure Utilities
~~~~~~~~~~~~~~~

.. automodule:: bolster.utils.azure
   :members:
   :undoc-members:
   :show-inheritance:

Statistics
----------

Distribution Utilities
~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: bolster.stats.distributions
   :members:
   :undoc-members:
   :show-inheritance:

Command Line Interface
----------------------

.. automodule:: bolster.cli
   :members:
   :undoc-members:
   :show-inheritance:

.. click:: bolster.cli:cli
   :prog: bolster
   :nested: full