Welcome to Bolster's documentation!
======================================

Bolster is a Python library for accessing Northern Ireland and UK government
open data.  It normalises dozens of official statistics sources — population,
health, economy, crime, transport, housing, and more — into clean
:class:`pandas.DataFrame` objects, with a matching CLI for every module.

**Key areas:**

- :doc:`Data sources <data_sources>` — NISRA, Department of Health NI, PSNI,
  DVA, Translink, NI Assembly, ONS, Bank of England, and more
- :doc:`Installation <installation>` — ``pip install bolster``, Python 3.11+
- :doc:`CLI and usage examples <usage>` — ``bolster nisra deaths``,
  ``bolster health-ni disease-prevalence``, ...
- :doc:`API reference <api>` — auto-generated from module docstrings

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   installation
   data_sources
   usage

.. toctree::
   :maxdepth: 3
   :caption: API Reference

   api

.. toctree::
   :maxdepth: 2
   :caption: Development

   contributing
   data_source_development
   development/auto-versioning
   quality-gate-system
   authors
   history

Indices and tables
==================
* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
