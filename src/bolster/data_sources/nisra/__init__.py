"""NISRA (Northern Ireland Statistics and Research Agency) Data Sources.

This package provides access to various statistical datasets published by NISRA,
including births, deaths, labour market, population, migration, economic indicators,
and tourism statistics.

Available modules:
    - ashe: Annual Survey of Hours and Earnings (employee earnings statistics)
    - births: Monthly birth registrations by registration and occurrence date
    - cancer_waiting_times: Cancer treatment waiting times (14-day, 31-day, 62-day targets)
    - emergency_care_waiting_times: Emergency care (A&E) waiting times against the 4-hour target
    - composite_index: Northern Ireland Composite Economic Index (experimental quarterly economic indicator)
    - construction_output: Quarterly construction output statistics (all work, new work, repair & maintenance)
    - deaths: Weekly death registrations with demographic, geographic, and place breakdowns
    - index_of_services: Quarterly Index of Services (IOS) — canonical module
    - index_of_production: Quarterly Index of Production (IOP) — canonical module
    - labour_market: Quarterly Labour Force Survey statistics (employment, economic inactivity)
    - marriages: Monthly marriage registrations
    - migration: Official and derived migration estimates (demographic components)
    - population: Annual mid-year population estimates by age, sex, and geography
    - planning_statistics: NI Planning Activity Statistics - quarterly applications, by council
    - population_projections: Population projections by age, sex, and geography (2022-2072)
    - registrar_general: Registrar General Quarterly Tables (quarterly births, deaths, marriages, LGD breakdowns)
    - baby_names: Annual baby name registrations (1997–present) by sex and rank
    - tourism: Tourism statistics including occupancy surveys, visitor stats (subpackage)
    - wellbeing: Individual wellbeing statistics (life satisfaction, happiness, anxiety, loneliness)
    - work_quality: Work Quality NI — seventeen indicators of job quality for employees

Examples:
    >>> from bolster.data_sources.nisra import ashe
    >>> earnings_df = ashe.get_latest_ashe_timeseries('weekly')
    >>> 'median_weekly_earnings' in earnings_df.columns
    True

    >>> from bolster.data_sources.nisra import emergency_care_waiting_times as ecwt
    >>> df = ecwt.get_latest_data()
    >>> 'pct_within_4hrs' in df.columns
    True

    >>> from bolster.data_sources.nisra import births
    >>> birth_data = births.get_latest_births(event_type='both')
    >>> 'births' in birth_data['registration'].columns
    True

    >>> from bolster.data_sources.nisra import composite_index
    >>> nicei_df = composite_index.get_latest_nicei()
    >>> 'nicei' in nicei_df.columns
    True

    >>> from bolster.data_sources.nisra import construction_output
    >>> construction_df = construction_output.get_latest_construction_output()
    >>> 'all_work_index' in construction_df.columns
    True

    >>> from bolster.data_sources.nisra import deaths
    >>> df = deaths.get_latest_deaths(dimension='demographics')
    >>> 'deaths' in df.columns
    True

    >>> from bolster.data_sources.nisra import index_of_services as ios
    >>> ios_df = ios.get_latest_ios()
    >>> 'ni_index' in ios_df.columns
    True

    >>> from bolster.data_sources.nisra import labour_market
    >>> emp_df = labour_market.get_latest_employment()
    >>> 'percentage' in emp_df.columns
    True

    >>> from bolster.data_sources.nisra import marriages
    >>> marriages_df = marriages.get_latest_marriages()
    >>> 'marriages' in marriages_df.columns
    True

    >>> from bolster.data_sources.nisra.tourism import occupancy
    >>> occ_df = occupancy.get_latest_hotel_occupancy()
    >>> 'room_occupancy' in occ_df.columns
    True

    >>> from bolster.data_sources.nisra import migration
    >>> migration_df = migration.get_latest_migration()
    >>> 'net_migration' in migration_df.columns
    True

    >>> from bolster.data_sources.nisra import registrar_general
    >>> data = registrar_general.get_quarterly_vital_statistics()
    >>> sorted(data.keys())
    ['births', 'deaths', 'lgd']

    >>> from bolster.data_sources.nisra import population
    >>> pop_df = population.get_latest_population(area='Northern Ireland')
    >>> 'population' in pop_df.columns
    True

    >>> from bolster.data_sources.nisra import wellbeing
    >>> df = wellbeing.get_latest_personal_wellbeing()
    >>> 'life_satisfaction' in df.columns
    True

"""

from . import (
    ashe,
    baby_names,
    births,
    cancer_waiting_times,
    composite_index,
    construction_output,
    deaths,
    emergency_care_waiting_times,
    index_of_production,
    index_of_services,
    labour_market,
    marriages,
    migration,
    planning_statistics,
    population,
    population_projections,
    quarterly_employment_survey,
    registrar_general,
    stillbirths,
    tourism,
    wellbeing,
    work_quality,
)

__all__ = [
    "ashe",
    "baby_names",
    "births",
    "cancer_waiting_times",
    "composite_index",
    "construction_output",
    "deaths",
    "emergency_care_waiting_times",
    "index_of_production",
    "index_of_services",
    "labour_market",
    "quarterly_employment_survey",
    "marriages",
    "migration",
    "planning_statistics",
    "population",
    "population_projections",
    "registrar_general",
    "stillbirths",
    "tourism",
    "wellbeing",
    "work_quality",
]
