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

.. code-block:: console

    $ bolster nisra births

Deaths
~~~~~~

Weekly death registrations with demographics, geography (Local Government
Districts), and place-of-death breakdowns.

.. code-block:: python

    from bolster.data_sources.nisra import deaths

    df = deaths.get_latest_deaths(dimension="demographics")

.. code-block:: console

    $ bolster nisra deaths

Marriages
~~~~~~~~~

Monthly marriage registrations.

.. code-block:: python

    from bolster.data_sources.nisra import marriages

    df = marriages.get_latest_marriages()

.. code-block:: console

    $ bolster nisra marriages

Stillbirths
~~~~~~~~~~~

Monthly stillbirth registrations.

.. code-block:: python

    from bolster.data_sources.nisra import stillbirths

    df = stillbirths.get_latest_stillbirths()

.. code-block:: console

    $ bolster nisra stillbirths

Population
~~~~~~~~~~

Annual mid-year population estimates by age, sex, and Local Government District.

.. code-block:: python

    from bolster.data_sources.nisra import population

    df = population.get_latest_population(area="Northern Ireland")

.. code-block:: console

    $ bolster nisra population

Population Projections
~~~~~~~~~~~~~~~~~~~~~~

NI-level and LGD sub-area population projections (2024-based, 2024–2072).

.. code-block:: python

    from bolster.data_sources.nisra import population_projections

    df = population_projections.get_latest_population_projections()

.. code-block:: console

    $ bolster nisra population-projections

Baby Names
~~~~~~~~~~

Annual baby name registrations (1997–present) by sex and rank.

.. code-block:: python

    from bolster.data_sources.nisra import baby_names

    df = baby_names.get_latest_baby_names(sex="female")

.. code-block:: console

    $ bolster nisra baby-names

Migration
~~~~~~~~~

Official and derived migration estimates — demographic components of population
change including natural change, net migration, and cross-border flows.

.. code-block:: python

    from bolster.data_sources.nisra import migration

    df = migration.get_latest_migration()

.. code-block:: console

    $ bolster nisra migration

Labour Market
~~~~~~~~~~~~~

Quarterly Labour Force Survey statistics: employment, economic inactivity, and
unemployment rates for Northern Ireland.

.. code-block:: python

    from bolster.data_sources.nisra import labour_market

    df = labour_market.get_latest_employment()

.. code-block:: console

    $ bolster nisra labour-market

Claimant Count
~~~~~~~~~~~~~~

Monthly UC+JSA claimant count statistics from DfC/ONS.  NI headline back to
April 1997, with LGD and SOA breakdowns.

.. code-block:: python

    from bolster.data_sources.nisra import claimant_count

    df = claimant_count.get_latest_claimant_count("headline")

.. code-block:: console

    $ bolster nisra claimant-count

Annual Survey of Hours and Earnings (ASHE)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Employee earnings statistics for Northern Ireland, covering median weekly and
hourly earnings, real earnings growth, occupation/industry breakdowns, and gender
pay distribution (Figures 1–18).

.. code-block:: python

    from bolster.data_sources.nisra import ashe

    df = ashe.get_latest_ashe_timeseries("weekly")

.. code-block:: console

    $ bolster nisra ashe

Quarterly Employment Survey
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Employee jobs by sector from Q1 1998 to present, seasonally adjusted and
unadjusted.

.. code-block:: python

    from bolster.data_sources.nisra import quarterly_employment_survey

    df = quarterly_employment_survey.get_latest_qes()

.. code-block:: console

    $ bolster nisra quarterly-employment-survey

Composite Economic Index (NICEI)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The headline experimental quarterly economic indicator for Northern Ireland.

.. code-block:: python

    from bolster.data_sources.nisra import composite_index

    df = composite_index.get_latest_nicei()

.. code-block:: console

    $ bolster nisra composite-index

Index of Production / Services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quarterly Index of Production (IOP) and Index of Services (IOS) for NI.

.. code-block:: python

    from bolster.data_sources.nisra import index_of_production, index_of_services

    df_prod = index_of_production.get_latest_iop()
    df_serv = index_of_services.get_latest_ios()

.. code-block:: console

    $ bolster nisra index-of-production
    $ bolster nisra index-of-services

Construction Output
~~~~~~~~~~~~~~~~~~~

Quarterly construction output statistics — all work, new work, and repair &
maintenance.

.. code-block:: python

    from bolster.data_sources.nisra import construction_output

    df = construction_output.get_latest_construction_output()

.. code-block:: console

    $ bolster nisra construction-output

Business Register (IDBR)
~~~~~~~~~~~~~~~~~~~~~~~~~

NI Business Register (IDBR) — annual VAT/PAYE business counts by industry,
legal status, and Local Government District.

.. code-block:: python

    from bolster.data_sources.nisra import business_register

    df = business_register.get_latest_data()

.. code-block:: console

    $ bolster nisra business-register

Planning Statistics
~~~~~~~~~~~~~~~~~~~

NI Planning Activity Statistics — quarterly applications, approvals, and
refusals by council.

.. code-block:: python

    from bolster.data_sources.nisra import planning_statistics

    df = planning_statistics.get_latest_planning_statistics()

.. code-block:: console

    $ bolster nisra planning-statistics

Deprivation (NIMDM 2017)
~~~~~~~~~~~~~~~~~~~~~~~~~

NI Multiple Deprivation Measure 2017 — SOA-level overall and domain deprivation
ranks for 890 Super Output Areas.

.. code-block:: python

    from bolster.data_sources.nisra import deprivation

    df = deprivation.get_latest_data()
    # Columns: soa_code, soa_name, mdm_rank, income_rank, employment_rank, ...

.. code-block:: console

    $ bolster nisra deprivation

Housing Stock
~~~~~~~~~~~~~

NI Housing Stock Statistics (DoF/LPS) — annual counts of residential properties
by type (detached, semi-detached, terraced, flat) and Local Government District.

.. code-block:: python

    from bolster.data_sources.nisra import housing_stock

    df = housing_stock.get_latest_data()

.. code-block:: console

    $ bolster nisra housing-stock

Housing Bulletin
~~~~~~~~~~~~~~~~

NI Housing Bulletin (DfC) — quarterly housing statistics compiled from NIHE,
LPS and NHBC administrative sources. Nine tables: social housing starts and
completions by tenure, dwelling stock by tenure and district, the social
housing waiting list and allocations, new dwelling sales and average prices,
and the Affordable Warmth Scheme.

Homelessness tables from the same workbook are not parsed here — the richer
LGD-level series lives in :mod:`bolster.data_sources.nisra.homelessness`.

.. code-block:: python

    from bolster.data_sources.nisra import housing_bulletin

    stock = housing_bulletin.get_dwelling_stock_by_tenure()
    starts = housing_bulletin.get_social_housing_starts()
    sales = housing_bulletin.get_new_dwelling_sales()

    # Or fetch any table by name
    housing_bulletin.list_tables()
    df = housing_bulletin.get_latest_data('waiting-list')

.. code-block:: console

    $ bolster nisra housing-bulletin --list-tables
    $ bolster nisra housing-bulletin --table starts
    $ bolster nisra housing-bulletin --table sales --summary

Drug-Related Deaths
~~~~~~~~~~~~~~~~~~~

Annual drug-related and drug misuse deaths by year, age, gender, and substance.

.. code-block:: python

    from bolster.data_sources.nisra import drug_related_deaths

    df = drug_related_deaths.get_latest_drug_related_deaths()

.. code-block:: console

    $ bolster nisra drug-related-deaths

Teacher Workforce
~~~~~~~~~~~~~~~~~

Teachers in grant-aided schools — headcount by age, sex and working pattern,
full-time equivalents by school type, and pupil:teacher ratios, all broken
down by Local Government District.

.. code-block:: python

    from bolster.data_sources.nisra import teacher_workforce

    df = teacher_workforce.get_headcount()

.. code-block:: console

    $ bolster nisra teacher-workforce
    $ bolster nisra teacher-workforce --dimension ptr
    $ bolster nisra teacher-workforce --summary

Wellbeing
~~~~~~~~~

Individual wellbeing statistics from the NI Wellbeing Dashboard — life
satisfaction, happiness, anxiety, and loneliness.

.. code-block:: python

    from bolster.data_sources.nisra import wellbeing

    df = wellbeing.get_latest_personal_wellbeing()

.. code-block:: console

    $ bolster nisra wellbeing

Public Confidence in Official Statistics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Public Awareness of and Trust in Official Statistics (PCOS) — awareness and
trust indicators back to 2009.

.. code-block:: python

    from bolster.data_sources.nisra import public_confidence

    df = public_confidence.get_latest_data()

.. code-block:: console

    $ bolster nisra public-confidence

Registrar General Quarterly Tables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quarterly births, deaths, marriages, and LGD breakdowns.

.. code-block:: python

    from bolster.data_sources.nisra import registrar_general

    data = registrar_general.get_quarterly_vital_statistics()
    # data is a dict with keys: 'births', 'deaths', 'lgd'

.. code-block:: console

    $ bolster nisra registrar-general

School Leavers Survey
~~~~~~~~~~~~~~~~~~~~~~

Qualifications achieved and destinations of school leavers, by geography,
free school meal entitlement, and equality group.

.. code-block:: python

    from bolster.data_sources.nisra import school_leavers

    attainment = school_leavers.get_latest_school_leavers("attainment", "lgd")
    equality = school_leavers.get_attainment_by_equality_group()

.. code-block:: console

    $ bolster nisra school-leavers --dimension destination --geography lgd

Tourism — Occupancy
~~~~~~~~~~~~~~~~~~~~

Monthly hotel and guest accommodation occupancy rates.

.. code-block:: python

    from bolster.data_sources.nisra.tourism import occupancy

    df = occupancy.get_latest_hotel_occupancy()

.. code-block:: console

    $ bolster nisra occupancy

Tourism — Visitor Statistics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quarterly visitor numbers and spend.

.. code-block:: python

    from bolster.data_sources.nisra.tourism import visitor_statistics

    df = visitor_statistics.get_latest_visitor_statistics()

.. code-block:: console

    $ bolster nisra visitors

----

Department of Health NI (health_ni)
-------------------------------------

The `Department of Health <https://www.health-ni.gov.uk/>`_ publishes health
and social care statistics for Northern Ireland.  All health_ni modules live
under :mod:`bolster.data_sources.health_ni`.

Cancer Waiting Times
~~~~~~~~~~~~~~~~~~~~~

14-day, 31-day, and 62-day cancer referral-to-treatment waiting times by tumour
type and HSC Trust.  Data via PxStat.

.. code-block:: python

    from bolster.data_sources.health_ni import cancer_waiting_times

    df = cancer_waiting_times.get_latest_62_day_by_tumour()

.. code-block:: console

    $ bolster nisra cancer-waiting-times

Diagnostic Waiting Times
~~~~~~~~~~~~~~~~~~~~~~~~~

Diagnostic waiting times by test type and HSC Trust.  Data via PxStat DWT matrix.

.. code-block:: python

    from bolster.data_sources.health_ni import diagnostic_waiting_times

    df = diagnostic_waiting_times.get_latest_diagnostic_waiting_times()

.. code-block:: console

    $ bolster nisra diagnostic-waiting-times

Elective Waiting Times
~~~~~~~~~~~~~~~~~~~~~~~

Inpatient/day-case and outpatient referrals waiting by weeks-waited band,
specialty, and HSC Trust.  Covers pre-encompass (legacy PAS) and encompass
(new EPR system from December 2023) data series.

.. code-block:: python

    from bolster.data_sources.health_ni import elective_waiting_times

    df = elective_waiting_times.get_latest_elective_waiting_times()

.. code-block:: console

    $ bolster nisra elective-waiting-times

Emergency Care Waiting Times
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Monthly A&E attendance and 4-hour target performance by HSC Trust and hospital
department.

.. code-block:: python

    from bolster.data_sources.health_ni import emergency_care_waiting_times

    df = emergency_care_waiting_times.get_latest_data()

.. code-block:: console

    $ bolster nisra emergency-care

Disease Prevalence
~~~~~~~~~~~~~~~~~~

NI disease register statistics at NI, LGD, HSCT, and GP-practice level.
Covers 17 disease categories including hypertension, diabetes, and COPD.

.. code-block:: python

    from bolster.data_sources.health_ni import disease_prevalence

    # NI-level summary
    df = disease_prevalence.get_latest_disease_prevalence(level="ni")

    # GP-practice level (~360 practices, ~17 financial years)
    gp_df = disease_prevalence.get_latest_gp_prevalence()

.. code-block:: console

    $ bolster nisra disease-prevalence
    $ bolster nisra disease-prevalence --level gp

Child Protection
~~~~~~~~~~~~~~~~~

NI child protection registrations, de-registrations, and case conference
statistics from the Department of Health.

.. code-block:: python

    from bolster.data_sources.health_ni import child_protection

    df = child_protection.get_latest_child_protection()

.. code-block:: console

    $ bolster nisra child-protection

HSC Workforce
~~~~~~~~~~~~~

Size, composition and turnover of the Health and Social Care workforce,
from March 2021 to the latest census point.  Figures are whole-time
equivalents (WTE) unless stated otherwise.

.. code-block:: python

    from bolster.data_sources.health_ni import hsc_workforce

    # Headline WTE, headcount and active posts by census point
    df = hsc_workforce.get_workforce_summary()

    # WTE by staff group, or the profession-level cut
    groups = hsc_workforce.get_workforce_by_staff_group()
    professions = hsc_workforce.get_workforce_by_staff_group(sub=True)

    # Joiners, leavers and stability by financial year
    turnover = hsc_workforce.get_turnover(measure="leavers")

.. code-block:: console

    $ bolster nisra hsc-workforce
    $ bolster nisra hsc-workforce --view staff-group --sub
    $ bolster nisra hsc-workforce --view turnover --measure joiners

HSC Active Recruitment
~~~~~~~~~~~~~~~~~~~~~~

Vacancy counts and vacancy rates across the HSC workforce, from March 2017
to the latest census point.  Consultant and SAS doctor vacancies begin in
March 2020.

.. code-block:: python

    from bolster.data_sources.health_ni import hsc_recruitment

    # Vacancies by staff group and census point
    df = hsc_recruitment.get_vacancies_by_staff_group()

    # Vacancy rates as a proportion of funded posts
    rates = hsc_recruitment.get_vacancy_rates()

    # Consultant vacancies by clinical specialty
    doctors = hsc_recruitment.get_doctor_vacancies(grade="consultant")

.. code-block:: console

    $ bolster nisra hsc-recruitment
    $ bolster nisra hsc-recruitment --view rates
    $ bolster nisra hsc-recruitment --view doctors --grade consultant

----

PSNI
----

The `Police Service of Northern Ireland <https://www.psni.police.uk/>`_
publishes open-data releases covering crime, road safety, and police activity.
All PSNI modules live under :mod:`bolster.data_sources.psni`.

Crime Statistics
~~~~~~~~~~~~~~~~

Historical monthly crime statistics broken down by offence type, district
command unit, and outcome.  Note: the most recent 12-month period is not
published in the open-data release; use ``get_historical_crime_statistics()``
for reliable data.

.. code-block:: python

    from bolster.data_sources.psni import crime_statistics

    df = crime_statistics.get_historical_crime_statistics()

.. code-block:: console

    $ bolster psni crime

Road Traffic Collisions
~~~~~~~~~~~~~~~~~~~~~~~

Annual road traffic collision data with casualty severity and road type.

.. code-block:: python

    from bolster.data_sources.psni import road_traffic_collisions

    df = road_traffic_collisions.get_latest_collisions()

.. code-block:: console

    $ bolster psni rtc

Stop and Search
~~~~~~~~~~~~~~~

PSNI stop & search records from OpenDataNI; 199,661 records covering
2017/18–2024/25 with PACE reason flags, legislation, and demographic breakdowns.

.. code-block:: python

    from bolster.data_sources.psni import stop_and_search

    df = stop_and_search.get_latest_stop_and_search()

.. code-block:: console

    $ bolster psni stop-and-search

PACE Statistics
~~~~~~~~~~~~~~~

Annual PSNI PACE statistics — monthly stop & search by reason and quarterly
arrests by gender and category, back to 2013/14.

.. code-block:: python

    from bolster.data_sources.psni import pace

    df_searches = pace.get_latest_pace_stop_and_search()
    df_arrests  = pace.get_latest_pace_arrests()

.. code-block:: console

    $ bolster psni pace

Police Ombudsman
~~~~~~~~~~~~~~~~

Annual and quarterly Police Ombudsman complaint statistics — complaints by
district, allegation type, and outcome back to 2000/01.

.. code-block:: python

    from bolster.data_sources.psni import police_ombudsman

    df = police_ombudsman.get_latest_complaints()

.. code-block:: console

    $ bolster psni police-ombudsman

Road Safety Partnership
~~~~~~~~~~~~~~~~~~~~~~~

Record-level safety camera detections from the Northern Ireland Road Safety
Partnership — 719,200 detections from 2011 to 2024 covering fixed, mobile,
average-speed and red light running cameras, with outcome, district, speed
band and offender demographics. Published on OpenDataNI in two batches with
differing column headers; the module normalises both onto a common schema and
attaches LGD and NUTS3 codes.

.. code-block:: python

    from bolster.data_sources.psni import road_safety_partnership as rsp

    df      = rsp.get_detections(year=2024)
    annual  = rsp.get_annual_summary()
    by_lgd  = rsp.get_detections_by_district(year=2024)
    speeds  = rsp.get_speed_distribution(year=2024)

.. code-block:: console

    $ bolster psni road-safety
    $ bolster psni road-safety --dimension district --year 2024

.. note::

   Reference numbers restart at 1 in each published batch and are not globally
   unique. Red light running camera detections record no speed. Speed and
   offender age are published as bands rather than exact values.

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

NI Assembly (AIMS)
-------------------

NI Assembly AIMS data — Members of the Legislative Assembly, oral/written
questions, and assembly votes.

.. code-block:: python

    from bolster.data_sources import niassembly

    members = niassembly.get_members()
    questions = niassembly.get_questions(member_id=123)
    votes = niassembly.get_votes()

.. code-block:: console

    $ bolster niassembly members
    $ bolster niassembly questions
    $ bolster niassembly votes

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

Infrastructure NI (DfI)
-----------------------

Statistics from the Department for Infrastructure.

Travel to and from School (YPBAS)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Young Persons' Behaviour and Attitudes Survey travel module: how pupils
travel to and from school, how they would like to travel, perceived road
safety, and walking/cycling participation. Detail tables carry 95% confidence
intervals and break down by sex and school year group; the trend tables cover
2016, 2019, 2022 and 2025.

.. code-block:: python

    from bolster.data_sources.dfi import school_travel

    # Latest detail tables (686 estimates across 12 questions)
    df = school_travel.get_latest_data()

    # Year-group breakdown only
    by_year = df[df["breakdown_type"] == "year_group"]

    # Multi-year trend
    trend = school_travel.get_trend_data()

    # What questions are available?
    school_travel.list_questions()

.. code-block:: console

    $ bolster dfi school-travel
    $ bolster dfi school-travel --table trend
    $ bolster dfi school-travel --breakdown year_group --summary
    $ bolster dfi school-travel --list-questions

----

Justice
-------

Department of Justice, its sponsored bodies, and the NI Courts and Tribunals
Service (NICTS).

Mortgage Possession Actions
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quarterly mortgage possession proceedings in the Chancery Division of the NI
High Court: cases received, cases disposed, and the final orders made.

.. code-block:: python

    from bolster.data_sources.justice import mortgages

    tables = mortgages.get_latest_data()
    received = tables["received"]

.. code-block:: console

    $ bolster justice mortgages
    $ bolster justice mortgages --table disposed

Quarterly Court Business Figures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Provisional case receipts, disposals, and outstanding workload across all ten
NICTS court datasets — Court of Appeal (criminal and civil), the three High
Court divisions, Crown, County, Magistrates', Children Order proceedings, and
judicial sitting days. Annual totals from 2017 plus quarterly figures for the
most recent years, returned as a single tidy long frame.

.. code-block:: python

    from bolster.data_sources.justice import nicts_quarterly

    # Every court, every period
    df = nicts_quarterly.get_latest_data()

    # A single court
    crown = nicts_quarterly.get_crown_court()

    # What court keys are available?
    nicts_quarterly.list_courts()

.. code-block:: console

    $ bolster justice nicts-quarterly --list-courts
    $ bolster justice nicts-quarterly --court crown_court
    $ bolster justice nicts-quarterly --annual --format json

Prosecutions, Convictions and Out of Court Disposals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Annual figures on how criminal cases are resolved: convictions and conviction
rates by court tier, the mix of out of court disposals (cautions, informed
warnings, penalty notices, youth conference plans), and diversionary disposals
by gender and age band. Publications run from 2008 to the present.

.. code-block:: python

    from bolster.data_sources.justice import prosecutions_convictions as pcd

    # Conviction rates by court tier
    df = pcd.get_prosecutions_convictions()

    # Court versus out of court resolution
    cases = pcd.get_cases_dealt_with()

    # Out of court disposals by type
    disposals = pcd.get_out_of_court_disposals()

    # Diversionary disposals by age band
    by_age = pcd.get_diversionary_disposals(by="age")

.. code-block:: console

    $ bolster justice prosecutions-convictions --summary
    $ bolster justice prosecutions-convictions --dataset out-of-court
    $ bolster justice prosecutions-convictions --dataset diversionary --by age
First Time Entrants
~~~~~~~~~~~~~~~~~~~

People receiving their first conviction or diversionary disposal in Northern
Ireland, broken down by age band, gender, offence classification and disposal
type, alongside the headline percentage of all offenders who are first time
entrants. Financial years from 2011-12, with thirteen editions available.

Tables are keyed by their title text rather than sheet name or worksheet
number, since both drift between editions.

.. code-block:: python

    from bolster.data_sources.justice import first_time_entrants as fte

    # Every table, every breakdown
    df = fte.get_latest_data()

    # A single breakdown
    by_age = fte.get_by_age()
    by_offence = fte.get_by_offence()

    # Headline first time offender percentage over time
    headline = fte.get_headline_series()

    # Older editions
    older = fte.parse_data(fte.download_file(fte.find_data_file(fte.list_publications()[5]["url"])))

.. code-block:: console

    $ bolster justice first-time-entrants --headline
    $ bolster justice first-time-entrants --breakdown age_band
    $ bolster justice first-time-entrants --table 3e --format json

PBNI Caseload
~~~~~~~~~~~~~

Probation Board for Northern Ireland caseload statistics — annual (31 March
snapshot, five years of history) and quarterly bulletins covering the people
under probation supervision, their orders, demographics, risk assessments, and
registered victims.

.. code-block:: python

    from bolster.data_sources.justice import pbni_caseload

    df = pbni_caseload.get_annual_caseload()

    # Any published breakdown
    orders = pbni_caseload.get_latest_data("order_type", frequency="quarterly")
    pbni_caseload.list_dimensions("quarterly")

.. code-block:: console

    $ bolster justice pbni-caseload --summary
    $ bolster justice pbni-caseload --frequency quarterly --dimension order_type

----

Communities — Child Maintenance Service
---------------------------------------

Quarterly Child Maintenance Service statistics for Northern Ireland, published
by the Department for Communities: applications and their clearance, the
composition of arrangements, children covered, paying parent numbers and
demographics, maintenance due and paid, and enforcement collections. All eight
workbook tables are flattened into one tidy long frame with a ``table``
discriminator column.

A single release does not carry the full back series — most tables show only the
last few years, and paying parent characteristics only a single quarter — so
``get_historical_data()`` stitches successive releases together.

.. code-block:: python

    from bolster.data_sources.dfc import child_maintenance

    # Every table from the most recent release
    df = child_maintenance.get_latest_data()

    # Stitch releases together for the full published run
    history = child_maintenance.get_historical_data(max_publications=8)

    # A single table
    enforcement = child_maintenance.get_enforcement()

    # What tables are available?
    child_maintenance.list_tables()

.. code-block:: console

    $ bolster dfc child-maintenance --list-tables
    $ bolster dfc child-maintenance --table enforcement
    $ bolster dfc child-maintenance --historical --summary

----

Justice — PPS Statistical Bulletin
----------------------------------

Public Prosecution Service casework statistics: files and defendants received
from police, prosecution and diversion decisions by offence group, the number
of days taken to issue a decision, and the outcomes of contested Crown and
Magistrates' court cases. Each annual bulletin restates the prior financial
year alongside the current one, so a single download covers two years.

Suppressed cells (small-count disclosure control) come back as ``NaN`` in
``value`` with the original symbol preserved in ``marker``.

.. code-block:: python

    from bolster.data_sources.justice import pps_statistical_bulletin as pps

    # Every table in the latest bulletin
    df = pps.get_latest_data()

    # Typed accessors for the headline tables
    received = pps.get_files_received()
    decisions = pps.get_decisions()
    timeliness = pps.get_timeliness()
    outcomes = pps.get_court_outcomes()

    # Several bulletins stitched into one series
    history = pps.get_historical_data(max_publications=5)

    # What table keys are available?
    pps.list_tables()

.. code-block:: console

    $ bolster justice pps-statistical-bulletin --list-tables
    $ bolster justice pps-statistical-bulletin --table 1a
    $ bolster justice pps-statistical-bulletin --table 3a --year 2024/25
    $ bolster justice pps-statistical-bulletin --historical --format json

----

Translink
---------

Live and scheduled bus and rail departures, and vehicle positions, for the
Translink NI public transport network.

.. code-block:: python

    from bolster.data_sources import translink

    # Next departures from a stop (by name)
    df = translink.get_departures_by_name("Europa Buscentre")

    # Live vehicle positions
    vehicles = translink.get_live_vehicles()

.. code-block:: console

    $ bolster translink departures "Europa Buscentre"
    $ bolster translink vehicles

----

ONS — Office for National Statistics
--------------------------------------

ONS UK-wide statistical releases relevant to Northern Ireland.

CPI / CPIH / RPI Inflation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Annual rates and price indices for CPI, CPIH, and RPI from ONS.

.. code-block:: python

    from bolster.data_sources import ons_cpi

    df = ons_cpi.get_latest_cpi()

.. code-block:: console

    $ bolster ons-cpi

----

Bank of England
---------------

Bank of England official Bank Rate (base rate) from 1694 to present.

.. code-block:: python

    from bolster.data_sources import boe_base_rate

    df = boe_base_rate.get_latest_base_rate()

.. code-block:: console

    $ bolster boe-base-rate

----

Companies House
---------------

UK Companies House public data — basic company details and registered
companies connected to a given address.

.. code-block:: python

    from bolster.data_sources.companies_house import query_basic_company_data

    details = query_basic_company_data("12345678")

.. code-block:: console

    $ bolster companies-house --query "Farset Labs"

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

DAERA
-----

Greenhouse Gas Inventory
~~~~~~~~~~~~~~~~~~~~~~~~

Northern Ireland greenhouse gas emissions from 1990 onwards, broken down by
sector, by gas, and under the National Communication and Territorial Emissions
Statistics classifications, with UK totals for comparison.

Full time series are reported in ktCO2e; summary and change tables are in
MtCO2e.  LULUCF values can legitimately be negative where removals exceed
emissions.

.. code-block:: python

    from bolster.data_sources.daera_greenhouse_gas import (
        get_annual_totals,
        get_emissions_by_sector,
        get_gas_changes,
    )

    totals = get_annual_totals()
    by_sector = get_emissions_by_sector()
    by_gas = get_gas_changes()

.. code-block:: console

    $ bolster daera greenhouse-gas --summary
    $ bolster daera greenhouse-gas --dataset totals
    $ bolster daera greenhouse-gas --sector Agriculture --year 2024

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
