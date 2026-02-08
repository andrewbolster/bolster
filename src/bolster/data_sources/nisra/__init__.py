"""
NISRA (Northern Ireland Statistics and Research Agency) Data Sources.

This package provides access to various statistical datasets published by NISRA,
including births, deaths, labour market, population, migration, economic indicators,
and tourism statistics.

Available modules:
    - ashe: Annual Survey of Hours and Earnings (employee earnings statistics)
    - births: Monthly birth registrations by registration and occurrence date
    - cancer_waiting_times: Cancer treatment waiting times (14-day, 31-day, 62-day targets)
    - composite_index: Northern Ireland Composite Economic Index (experimental quarterly economic indicator)
    - construction_output: Quarterly construction output statistics (all work, new work, repair & maintenance)
    - deaths: Weekly death registrations with demographic, geographic, and place breakdowns
    - economic_indicators: Quarterly Index of Services and Index of Production
    - labour_market: Quarterly Labour Force Survey statistics (employment, economic inactivity)
    - marriages: Monthly marriage registrations
    - migration: Derived migration estimates from demographic components
    - population: Annual mid-year population estimates by age, sex, and geography
    - registrar_general: Registrar General Quarterly Tables (quarterly births, deaths, marriages, LGD breakdowns)
    - tourism: Tourism statistics including occupancy surveys, visitor stats (subpackage)
    - validation: Cross-validation utilities using demographic accounting equation
    - wellbeing: Individual wellbeing statistics (life satisfaction, happiness, anxiety, loneliness)

Examples:
    >>> from bolster.data_sources.nisra import ashe
    >>> earnings_df = ashe.get_latest_ashe_timeseries('weekly')
    >>> latest = earnings_df[earnings_df['year'] == earnings_df['year'].max()]
    >>> print(f"Latest NI median weekly earnings: £{latest[latest['work_pattern']=='All']['median_weekly_earnings'].values[0]:.2f}")

    >>> from bolster.data_sources.nisra import births
    >>> birth_data = births.get_latest_births(event_type='both')
    >>> print(birth_data['registration'].head())

    >>> from bolster.data_sources.nisra import composite_index
    >>> nicei_df = composite_index.get_latest_nicei()
    >>> latest = nicei_df.iloc[-1]
    >>> print(f"Latest NICEI (Q{latest['quarter']} {latest['year']}): {latest['nicei']:.2f}")

    >>> from bolster.data_sources.nisra import construction_output
    >>> construction_df = construction_output.get_latest_construction_output()
    >>> print(f"Latest All Work Index: {construction_df.iloc[-1]['all_work_index']:.1f}")

    >>> from bolster.data_sources.nisra import deaths
    >>> df = deaths.get_latest_deaths(dimension='demographics')
    >>> print(df.head())

    >>> from bolster.data_sources.nisra import economic_indicators
    >>> ios_df = economic_indicators.get_latest_index_of_services()
    >>> iop_df = economic_indicators.get_latest_index_of_production()
    >>> print(f"Latest NI services index: {ios_df.iloc[-1]['ni_index']}")

    >>> from bolster.data_sources.nisra import labour_market
    >>> emp_df = labour_market.get_latest_employment()
    >>> inact_df = labour_market.get_latest_economic_inactivity()

    >>> from bolster.data_sources.nisra import marriages
    >>> marriages_df = marriages.get_latest_marriages()
    >>> df_2024 = marriages.get_marriages_by_year(marriages_df, 2024)
    >>> print(f"Total marriages in 2024: {df_2024['marriages'].sum():,}")

    >>> from bolster.data_sources.nisra.tourism import occupancy
    >>> occ_df = occupancy.get_latest_hotel_occupancy()
    >>> avg_2024 = occ_df[occ_df['year'] == 2024]['room_occupancy'].mean()
    >>> print(f"2024 average room occupancy: {avg_2024:.1%}")

    >>> # SSA (B&B/guest house) occupancy
    >>> ssa_df = occupancy.get_latest_ssa_occupancy()
    >>> print(f"SSA room occupancy: {ssa_df['room_occupancy'].mean():.1%}")

    >>> # Compare hotel vs SSA
    >>> combined = occupancy.get_combined_occupancy()
    >>> print(combined.groupby('accommodation_type')['room_occupancy'].mean())

    >>> from bolster.data_sources.nisra import migration
    >>> migration_df = migration.get_latest_migration()
    >>> df_2024 = migration.get_migration_by_year(migration_df, 2024)
    >>> print(f"Net migration in 2024: {df_2024['net_migration'].values[0]:+,}")

    >>> from bolster.data_sources.nisra import registrar_general
    >>> data = registrar_general.get_quarterly_vital_statistics()
    >>> births = data['births']
    >>> print(f"Quarterly births from {births['year'].min()} to {births['year'].max()}")

    >>> from bolster.data_sources.nisra import population
    >>> pop_df = population.get_latest_population(area='Northern Ireland')
    >>> print(f"NI population 2024: {pop_df[pop_df['year'] == 2024]['population'].sum():,}")

    >>> from bolster.data_sources.nisra import wellbeing
    >>> df = wellbeing.get_latest_personal_wellbeing()
    >>> latest = df.iloc[-1]
    >>> print(f"Life satisfaction {latest['year']}: {latest['life_satisfaction']}")
"""

from . import (
    ashe,
    births,
    cancer_waiting_times,
    composite_index,
    construction_output,
    deaths,
    economic_indicators,
    labour_market,
    marriages,
    migration,
    population,
    registrar_general,
    tourism,
    validation,
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
    "labour_market",
    "marriages",
    "migration",
    "population",
    "registrar_general",
    "tourism",
    "validation",
    "wellbeing",
]
