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
    - economic_indicators: Quarterly Index of Services and Index of Production
    - labour_market: Quarterly Labour Force Survey statistics (employment, economic inactivity)
    - marriages: Monthly marriage registrations
    - migration: Official and derived migration estimates (demographic components)
    - population: Annual mid-year population estimates by age, sex, and geography
    - population_projections: Population projections by age, sex, and geography (2022-2072)
    - registrar_general: Registrar General Quarterly Tables (quarterly births, deaths, marriages, LGD breakdowns)
    - tourism: Tourism statistics including occupancy surveys, visitor stats (subpackage)
    - wellbeing: Individual wellbeing statistics (life satisfaction, happiness, anxiety, loneliness)

Examples:
    >>> from bolster.data_sources.nisra import ashe
    >>> earnings_df = ashe.get_latest_ashe_timeseries('weekly')
    >>> latest = earnings_df[earnings_df['year'] == earnings_df['year'].max()]

    >>> from bolster.data_sources.nisra import emergency_care_waiting_times as ecwt
    >>> df = ecwt.get_latest_data()
    >>> type1 = df[df['attendance_type'] == 'Type 1']

    >>> from bolster.data_sources.nisra import births
    >>> birth_data = births.get_latest_births(event_type='both')

    >>> from bolster.data_sources.nisra import composite_index
    >>> nicei_df = composite_index.get_latest_nicei()
    >>> latest = nicei_df.iloc[-1]

    >>> from bolster.data_sources.nisra import construction_output
    >>> construction_df = construction_output.get_latest_construction_output()

    >>> from bolster.data_sources.nisra import deaths
    >>> df = deaths.get_latest_deaths(dimension='demographics')

    >>> from bolster.data_sources.nisra import economic_indicators
    >>> ios_df = economic_indicators.get_latest_index_of_services()
    >>> iop_df = economic_indicators.get_latest_index_of_production()

    >>> from bolster.data_sources.nisra import labour_market
    >>> emp_df = labour_market.get_latest_employment()
    >>> inact_df = labour_market.get_latest_economic_inactivity()

    >>> from bolster.data_sources.nisra import marriages
    >>> marriages_df = marriages.get_latest_marriages()
    >>> df_2024 = marriages.get_marriages_by_year(marriages_df, 2024)

    >>> from bolster.data_sources.nisra.tourism import occupancy
    >>> occ_df = occupancy.get_latest_hotel_occupancy()
    >>> avg_2024 = occ_df[occ_df['year'] == 2024]['room_occupancy'].mean()

    >>> # SSA (B&B/guest house) occupancy
    >>> ssa_df = occupancy.get_latest_ssa_occupancy()

    >>> # Compare hotel vs SSA
    >>> combined = occupancy.get_combined_occupancy()

    >>> from bolster.data_sources.nisra import migration
    >>> migration_df = migration.get_latest_migration()
    >>> df_2024 = migration.get_migration_by_year(migration_df, 2024)

    >>> from bolster.data_sources.nisra import registrar_general
    >>> data = registrar_general.get_quarterly_vital_statistics()
    >>> births = data['births']

    >>> from bolster.data_sources.nisra import population
    >>> pop_df = population.get_latest_population(area='Northern Ireland')

    >>> from bolster.data_sources.nisra import wellbeing
    >>> df = wellbeing.get_latest_personal_wellbeing()
    >>> latest = df.iloc[-1]
"""

from . import (
    ashe,
    births,
    cancer_waiting_times,
    composite_index,
    construction_output,
    deaths,
    economic_indicators,
    emergency_care_waiting_times,
    index_of_production,
    index_of_services,
    labour_market,
    marriages,
    migration,
    population,
    population_projections,
    quarterly_employment_survey,
    registrar_general,
    stillbirths,
    tourism,
    wellbeing,
)

__all__ = [
    "ashe",
    "births",
    "cancer_waiting_times",
    "composite_index",
    "construction_output",
    "deaths",
    "economic_indicators",
    "emergency_care_waiting_times",
    "index_of_production",
    "index_of_services",
    "labour_market",
    "quarterly_employment_survey",
    "marriages",
    "migration",
    "population",
    "population_projections",
    "registrar_general",
    "stillbirths",
    "tourism",
    "wellbeing",
]
