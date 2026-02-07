API Reference
=============

This page provides a comprehensive reference for all public APIs in the Bolster package.
Documentation is automatically generated from source code docstrings.

.. toctree::
   :maxdepth: 3
   :caption: Package Documentation

   autoapi/bolster/index

Quick Links
-----------

**Core Module**
   The main ``bolster`` module provides utilities for data processing, concurrency,
   and tree/dictionary navigation. See :doc:`autoapi/bolster/index`.

**Data Sources**
   Access Northern Ireland and UK government data:

   - NISRA (births, deaths, population, labour market, etc.)
   - PSNI (crime statistics, road traffic collisions)
   - NI Water, EONI, Companies House, Met Office

   See :doc:`autoapi/bolster/data_sources/index`.

**Utilities**
   Helper modules for AWS, Azure, web scraping, caching, and more.
   See :doc:`autoapi/bolster/utils/index`.

**Command Line Interface**
   CLI commands for data retrieval and processing.
   See :doc:`autoapi/bolster/cli/index`.

.. click:: bolster.cli:cli
   :prog: bolster
   :nested: full
