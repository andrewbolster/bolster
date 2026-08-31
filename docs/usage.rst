=====
Usage
=====

.. contents::
   :local:
   :depth: 1

----

Quick start
-----------

Install and run your first query:

.. code-block:: bash

    pip install bolster

.. code-block:: python

    from bolster.data_sources.nisra import claimant_count

    df = claimant_count.get_latest_claimant_count("lgd")
    print(df[df["date"] == df["date"].max()]
          .sort_values("claimant_rate_total_pct", ascending=False)
          [["geography", "claimants_total", "claimant_rate_total_pct"]])

Or from the command line:

.. code-block:: bash

    bolster nisra claimant-count --breakdown lgd
    bolster nisra deaths
    bolster health-ni disease-prevalence --level gp
    bolster translink departures "Europa Buscentre"

See :doc:`data_sources` for the full list of available modules and
:doc:`api` for the complete API reference.

----

Common patterns
---------------

All data source modules follow the same conventions.

Getting a DataFrame
~~~~~~~~~~~~~~~~~~~

Every module exposes a ``get_latest_*()`` function that returns a tidy
:class:`pandas.DataFrame`:

.. code-block:: python

    from bolster.data_sources.nisra import population, births, deaths
    from bolster.data_sources.health_ni import disease_prevalence, emergency_care_waiting_times
    from bolster.data_sources.psni import road_traffic_collisions

    pop = population.get_latest_population(area="Northern Ireland")
    b   = births.get_latest_births(event_type="registration")
    d   = deaths.get_latest_deaths(dimension="demographics")

    dp  = disease_prevalence.get_latest_disease_prevalence(level="ni")
    gp  = disease_prevalence.get_latest_gp_prevalence()   # ~360 practices

    ec  = emergency_care_waiting_times.get_latest_data()
    rtc = road_traffic_collisions.get_latest_collisions()

Caching
~~~~~~~

Downloads are cached to ``~/.cache/bolster/`` by default.  Pass
``force_refresh=True`` to bypass the cache:

.. code-block:: python

    from bolster.data_sources.nisra import labour_market

    df = labour_market.get_latest_employment(force_refresh=True)

HTTP requests use a shared session with automatic retry and jitter backoff.
Do not use ``requests.get()`` directly in data source modules — use
:func:`bolster.utils.web.session` instead.

----

Example analyses
----------------

Claimant count trends by district
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import matplotlib.pyplot as plt
    from bolster.data_sources.nisra import claimant_count

    df = claimant_count.get_latest_claimant_count("lgd")

    # Exclude the NI-wide summary row
    lgd = df[df["geography"] != "Northern Ireland"]

    pivot = lgd.pivot(index="date", columns="geography",
                      values="claimant_rate_total_pct")
    pivot.plot(title="UC+JSA claimant rate by LGD (%)", figsize=(12, 5))
    plt.tight_layout()
    plt.show()

Disease prevalence at GP-practice level
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources.health_ni import disease_prevalence

    gp = disease_prevalence.get_latest_gp_prevalence()

    # Practices with highest hypertension prevalence in 2024/25
    latest = gp[gp["financial_year"] == gp["financial_year"].max()]
    hyp = latest[latest["disease"] == "Hypertension"]
    print(hyp.sort_values("prevalence_per_1000", ascending=False)
             .head(10)[["practice_name", "lcg", "registered_patients",
                         "prevalence_per_1000"]])

Economy: NICEI sector breakdown
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources.nisra import composite_index

    df = composite_index.get_latest_nicei()

    # Year-on-year change in headline index
    df["yoy"] = df["nicei"].pct_change(4) * 100
    print(df.tail(8)[["year", "quarter", "nicei", "yoy"]])

Earnings by sex (ASHE gender pay analysis)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources.nisra import ashe

    hourly = ashe.get_latest_ashe_timeseries("hourly")
    weekly = ashe.get_latest_ashe_timeseries("weekly")

    # Gender pay gap trend (full-time)
    ft = weekly[weekly["work_pattern"] == "Full-time"]
    print(ft.tail(10)[["year", "median_weekly_earnings"]])

A&E performance by Trust
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import pandas as pd
    from bolster.data_sources.health_ni import emergency_care_waiting_times

    df = emergency_care_waiting_times.get_latest_data()

    # Monthly 4-hour performance by Trust
    monthly = (df.groupby(["date", "trust"])["pct_within_4hrs"]
                 .mean()
                 .reset_index()
                 .sort_values("date"))
    print(monthly[monthly["date"] == monthly["date"].max()])

Live bus departures
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources import translink

    # Next departures from a named stop
    df = translink.get_departures_by_name("Europa Buscentre", limit=10)
    print(df[["service", "destination", "aimed_departure", "status"]])

----

Utilities
---------

These helpers are used internally and available for general use.

Parallel processing
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import bolster

    results = bolster.poolmap(
        lambda x: x ** 2,
        range(1000),
        max_workers=4,
        progress=True,   # tqdm progress bar
    )

Retry with exponential backoff
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import requests
    import bolster

    @bolster.backoff((requests.RequestException, ConnectionError),
                    tries=5, delay=1, backoff=2)
    def fetch(url):
        return requests.get(url, timeout=10).json()

Instance method caching
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import bolster

    class Processor:
        @bolster.memoize
        def expensive(self, key):
            ...   # computed once per unique key

Nested dict utilities
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import bolster

    data = {"a": {"b": [{"x": 1}, {"x": 2}]}}

    bolster.get_recursively(data, "x")   # [1, 2]
    bolster.flatten_dict(data)           # {"a:b:0:x": 1, "a:b:1:x": 2}
    bolster.depth(data)                  # 4
