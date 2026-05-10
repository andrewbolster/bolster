Data Sources
============

Bolster provides standardised access to a range of Northern Ireland and UK
government data sources.  Each module follows the same conventions:

- A top-level ``get_latest_*()`` function that downloads and returns a
  :class:`pandas.DataFrame` ready for analysis.
- Caching to ``~/.cache/bolster/<source>/`` to avoid repeated downloads.
- A matching CLI command (``bolster <command> --help``).

.. contents:: Available Sources
   :local:
   :depth: 1

----

NISRA
-----

The `NI Statistics and Research Agency <https://www.nisra.gov.uk/>`_ publishes
a wide range of official statistics for Northern Ireland.  All NISRA modules
live under :mod:`bolster.data_sources.nisra`.

Births
~~~~~~

Monthly birth registrations from 2006 to present, broken down by sex and by
registration vs. occurrence date.

.. code-block:: python

    from bolster.data_sources.nisra import births

    df = births.get_latest_births(event_type="registration")
    print(df.shape)

.. code-block:: console

    $ bolster nisra births

Deaths
~~~~~~

Weekly death registrations with demographics, geography (Local Government
Districts), and place-of-death breakdowns.

.. code-block:: python

    from bolster.data_sources.nisra import deaths

    df = deaths.get_latest_deaths(dimension="demographics")
    print(df.head())

.. code-block:: console

    $ bolster nisra deaths

Marriages
~~~~~~~~~

Monthly marriage registrations.

.. code-block:: python

    from bolster.data_sources.nisra import marriages

    df = marriages.get_latest_marriages()

Stillbirths
~~~~~~~~~~~

Monthly stillbirth registrations.

.. code-block:: python

    from bolster.data_sources.nisra import stillbirths

    df = stillbirths.get_latest_stillbirths()

Population
~~~~~~~~~~

Mid-year population estimates by age, sex, and Local Government District.

.. code-block:: python

    from bolster.data_sources.nisra import population

    df = population.get_latest_population()

Population Projections
~~~~~~~~~~~~~~~~~~~~~~

Long-range population projections by age and sex scenario.

.. code-block:: python

    from bolster.data_sources.nisra import population_projections

    df = population_projections.get_latest_projections()

Migration
~~~~~~~~~

International and internal migration estimates for Northern Ireland.

.. code-block:: python

    from bolster.data_sources.nisra import migration

    df = migration.get_latest_migration()

Labour Market
~~~~~~~~~~~~~

Quarterly labour market statistics (employment, unemployment, economic
inactivity).

.. code-block:: python

    from bolster.data_sources.nisra import labour_market

    df = labour_market.get_latest_labour_market()

.. code-block:: console

    $ bolster nisra labour-market

Annual Survey of Hours and Earnings (ASHE)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Annual workplace earnings data for Northern Ireland.

.. code-block:: python

    from bolster.data_sources.nisra import ashe

    df = ashe.get_latest_ashe()

Quarterly Employment Survey
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources.nisra import quarterly_employment_survey as qes

    df = qes.get_latest_qes()

Wellbeing
~~~~~~~~~

Personal and economic wellbeing indicators from the NI Wellbeing Dashboard.

.. code-block:: python

    from bolster.data_sources.nisra import wellbeing

    df = wellbeing.get_latest_wellbeing()

Cancer Waiting Times
~~~~~~~~~~~~~~~~~~~~

Referral-to-treatment waiting times for cancer services.

.. code-block:: python

    from bolster.data_sources.nisra import cancer_waiting_times

    df = cancer_waiting_times.get_latest_waiting_times()

.. code-block:: console

    $ bolster nisra cancer-waiting-times

Emergency Care Waiting Times
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Emergency department attendance and four-hour target performance.

.. code-block:: python

    from bolster.data_sources.nisra import emergency_care_waiting_times

    df = emergency_care_waiting_times.get_latest_waiting_times()

Construction Output
~~~~~~~~~~~~~~~~~~~

Quarterly construction output index for Northern Ireland.

.. code-block:: python

    from bolster.data_sources.nisra import construction_output

    df = construction_output.get_latest_construction_output()

Economic Indicators
~~~~~~~~~~~~~~~~~~~

Composite economic indicators including GVA and productivity measures.

.. code-block:: python

    from bolster.data_sources.nisra import economic_indicators

    df = economic_indicators.get_latest_economic_indicators()

Index of Production / Services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Monthly production and services indices.

.. code-block:: python

    from bolster.data_sources.nisra import index_of_production, index_of_services

    df_prod = index_of_production.get_latest_index()
    df_serv = index_of_services.get_latest_index()

Composite Economic Index
~~~~~~~~~~~~~~~~~~~~~~~~

The headline NI Composite Economic Index.

.. code-block:: python

    from bolster.data_sources.nisra import composite_index

    df = composite_index.get_latest_composite_index()

Registrar General Annual Report
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Annual summary of births, deaths, marriages, and divorces.

.. code-block:: python

    from bolster.data_sources.nisra import registrar_general

    df = registrar_general.get_latest_registrar_general()

Tourism — Occupancy
~~~~~~~~~~~~~~~~~~~

Monthly occupancy rates for hotels and guest accommodation.

.. code-block:: python

    from bolster.data_sources.nisra.tourism import occupancy

    df = occupancy.get_latest_occupancy()

Tourism — Visitor Statistics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quarterly visitor numbers and spend.

.. code-block:: python

    from bolster.data_sources.nisra.tourism import visitor_statistics

    df = visitor_statistics.get_latest_visitor_statistics()

----

PSNI
----

The `Police Service of Northern Ireland <https://www.psni.police.uk/>`_
publishes open-data releases covering crime and road safety.  All PSNI modules
live under :mod:`bolster.data_sources.psni`.

Crime Statistics
~~~~~~~~~~~~~~~~

Monthly crime statistics broken down by offence type, district command unit,
and outcome.

.. code-block:: python

    from bolster.data_sources.psni import crime_statistics

    df = crime_statistics.get_latest_crime_statistics()

.. code-block:: console

    $ bolster nisra crime-statistics   # proxied via nisra group

Road Traffic Collisions
~~~~~~~~~~~~~~~~~~~~~~~

Annual road traffic collision data with casualty severity and road type.

.. code-block:: python

    from bolster.data_sources.psni import road_traffic_collisions

    df = road_traffic_collisions.get_latest_collisions()

----

DVA — Driver and Vehicle Agency
--------------------------------

Monthly test statistics from the NI Driver and Vehicle Agency.

.. code-block:: python

    from bolster.data_sources import dva

    vehicles = dva.get_vehicle_test_statistics()
    drivers  = dva.get_driver_test_statistics()
    theory   = dva.get_theory_test_statistics()

.. code-block:: console

    $ bolster dva vehicle-tests
    $ bolster dva driver-tests
    $ bolster dva theory-tests

----

NI Water
--------

Drinking water quality data for all NI supply zones.

.. code-block:: python

    from bolster.data_sources.ni_water import get_water_quality, get_water_quality_by_zone

    df = get_water_quality()
    zone = get_water_quality_by_zone("BALM")  # Belfast Malone

.. code-block:: console

    $ bolster water-quality --postcode "BT1 1AA"

----

EONI — Electoral Office for Northern Ireland
--------------------------------------------

NI Assembly election results (2016 and 2022).

.. code-block:: python

    from bolster.data_sources.eoni import get_results

    df_2022 = get_results(2022)
    df_2016 = get_results(2016)

.. code-block:: console

    $ bolster ni-elections 2022

----

NI House Price Index
--------------------

Standardised house price index for Northern Ireland.

.. code-block:: python

    from bolster.data_sources.ni_house_price_index import build

    df = build()

.. code-block:: console

    $ bolster ni-house-prices

----

Companies House
---------------

UK Companies House public data — basic company details and registered
companies connected to a given address (useful for research on specific
organisations).

.. code-block:: python

    from bolster.data_sources.companies_house import (
        query_basic_company_data,
        get_companies_house_records_that_might_be_in_farset,
    )

    details = query_basic_company_data("12345678")

.. code-block:: console

    $ bolster companies-house --query "Farset Labs"

----

Met Office
----------

UK precipitation maps from the Met Office DataPoint API.

Requires the environment variable ``MET_OFFICE_API_KEY``.

.. code-block:: python

    from bolster.data_sources.metoffice import get_uk_precipitation

    img = get_uk_precipitation(order_name="my-order")

.. code-block:: console

    $ bolster get-precipitation --order-name "my-order"

----

Gender Pay Gap
--------------

UK Gender Pay Gap reporting data from 2017 to present (all employers with
250+ employees).

.. code-block:: python

    from bolster.data_sources import gender_pay_gap

    df = gender_pay_gap.get_gender_pay_gap_data()

.. code-block:: console

    $ bolster gender-pay-gap

----

Wikipedia
---------

Structured data from NI-related Wikipedia tables (e.g. the NI Executive
composition table).

.. code-block:: python

    from bolster.data_sources.wikipedia import get_ni_executive_basic_table

    df = get_ni_executive_basic_table()

.. code-block:: console

    $ bolster ni-executive

----

Discovering New Publications
-----------------------------

NISRA publishes new datasets regularly.  Use the RSS feed integration to
discover publications before they are implemented as modules:

.. code-block:: console

    $ bolster nisra feed --limit 20

Or programmatically:

.. code-block:: python

    from bolster.utils.rss import get_nisra_statistics_feed

    feed = get_nisra_statistics_feed(limit=20)
    for entry in feed.entries:
        print(entry.published.date(), entry.title)

----

See Also
--------

- :doc:`data_source_development` — how to add a new data source module
- :doc:`api` — full API reference for all modules
