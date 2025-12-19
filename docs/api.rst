API Reference
=============

This page contains a comprehensive reference for all public APIs in the Bolster package.
Functions and classes are organized by module for easy navigation.

Core Utilities
--------------

The main ``bolster`` module provides core utilities for data processing, concurrency,
performance optimization, and general Python development tasks.

Main Module
~~~~~~~~~~~

.. automodule:: bolster
   :members:
   :undoc-members:
   :show-inheritance:

Data Sources
------------

Bolster provides specialized modules for accessing Northern Ireland and UK data sources,
organized by category for easy navigation.

Northern Ireland Data Sources
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These modules provide access to Northern Ireland-specific government and public data.

Northern Ireland Water Quality
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: bolster.data_sources.ni_water
   :members:
   :undoc-members:
   :show-inheritance:

Electoral Office for Northern Ireland (EONI)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: bolster.data_sources.eoni
   :members:
   :undoc-members:
   :show-inheritance:

Northern Ireland House Price Index
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: bolster.data_sources.ni_house_price_index
   :members:
   :undoc-members:
   :show-inheritance:

UK-Wide Data Sources
~~~~~~~~~~~~~~~~~~~~

These modules provide access to UK-wide data and services.

Companies House
^^^^^^^^^^^^^^^

.. automodule:: bolster.data_sources.companies_house
   :members:
   :undoc-members:
   :show-inheritance:

Met Office Weather Data
^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: bolster.data_sources.metoffice
   :members:
   :undoc-members:
   :show-inheritance:

Wikipedia Data
^^^^^^^^^^^^^^

.. automodule:: bolster.data_sources.wikipedia
   :members:
   :undoc-members:
   :show-inheritance:

Entertainment Data Sources
~~~~~~~~~~~~~~~~~~~~~~~~~~

These modules provide access to entertainment and leisure information.

Cineworld Cinema Listings
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: bolster.data_sources.cineworld
   :members:
   :undoc-members:
   :show-inheritance:

Utilities
---------

Bolster provides several utility modules for common development tasks,
from web scraping to cloud service integration.

Core Utilities
~~~~~~~~~~~~~~

These modules provide fundamental utilities for data processing and system operations.

I/O Utilities
^^^^^^^^^^^^^

.. automodule:: bolster.utils.io
   :members:
   :undoc-members:
   :show-inheritance:

Date/Time Utilities
^^^^^^^^^^^^^^^^^^^

.. automodule:: bolster.utils.dt
   :members:
   :undoc-members:
   :show-inheritance:

Web Utilities
^^^^^^^^^^^^^

.. automodule:: bolster.utils.web
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
