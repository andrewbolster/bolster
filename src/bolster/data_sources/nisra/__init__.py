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
    >>> from bolster.data_sources.nisra import ashe  # doctest: +SKIP
    >>> earnings_df = ashe.get_latest_ashe_timeseries('weekly')  # doctest: +SKIP
    >>> latest = earnings_df[earnings_df['year'] == earnings_df['year'].max()]  # doctest: +SKIP
    >>> print(f"Latest NI median weekly earnings: £{latest[latest['work_pattern']=='All']['median_weekly_earnings'].values[0]:.2f}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import emergency_care_waiting_times as ecwt  # doctest: +SKIP
    >>> df = ecwt.get_latest_data()  # doctest: +SKIP
    >>> type1 = df[df['attendance_type'] == 'Type 1']  # doctest: +SKIP
    >>> print(type1.groupby('trust')['pct_within_4hrs'].mean().sort_values())  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import births  # doctest: +SKIP
    >>> birth_data = births.get_latest_births(event_type='both')  # doctest: +SKIP
    >>> print(birth_data['registration'].head())  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import composite_index  # doctest: +SKIP
    >>> nicei_df = composite_index.get_latest_nicei()  # doctest: +SKIP
    >>> latest = nicei_df.iloc[-1]  # doctest: +SKIP
    >>> print(f"Latest NICEI (Q{latest['quarter']} {latest['year']}): {latest['nicei']:.2f}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import construction_output  # doctest: +SKIP
    >>> construction_df = construction_output.get_latest_construction_output()  # doctest: +SKIP
    >>> print(f"Latest All Work Index: {construction_df.iloc[-1]['all_work_index']:.1f}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import deaths  # doctest: +SKIP
    >>> df = deaths.get_latest_deaths(dimension='demographics')  # doctest: +SKIP
    >>> print(df.head())  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import economic_indicators  # doctest: +SKIP
    >>> ios_df = economic_indicators.get_latest_index_of_services()  # doctest: +SKIP
    >>> iop_df = economic_indicators.get_latest_index_of_production()  # doctest: +SKIP
    >>> print(f"Latest NI services index: {ios_df.iloc[-1]['ni_index']}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import labour_market  # doctest: +SKIP
    >>> emp_df = labour_market.get_latest_employment()  # doctest: +SKIP
    >>> inact_df = labour_market.get_latest_economic_inactivity()  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import marriages  # doctest: +SKIP
    >>> marriages_df = marriages.get_latest_marriages()  # doctest: +SKIP
    >>> df_2024 = marriages.get_marriages_by_year(marriages_df, 2024)  # doctest: +SKIP
    >>> print(f"Total marriages in 2024: {df_2024['marriages'].sum():,}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra.tourism import occupancy  # doctest: +SKIP
    >>> occ_df = occupancy.get_latest_hotel_occupancy()  # doctest: +SKIP
    >>> avg_2024 = occ_df[occ_df['year'] == 2024]['room_occupancy'].mean()  # doctest: +SKIP
    >>> print(f"2024 average room occupancy: {avg_2024:.1%}")  # doctest: +SKIP

    >>> # SSA (B&B/guest house) occupancy
    >>> ssa_df = occupancy.get_latest_ssa_occupancy()  # doctest: +SKIP
    >>> print(f"SSA room occupancy: {ssa_df['room_occupancy'].mean():.1%}")  # doctest: +SKIP

    >>> # Compare hotel vs SSA
    >>> combined = occupancy.get_combined_occupancy()  # doctest: +SKIP
    >>> print(combined.groupby('accommodation_type')['room_occupancy'].mean())  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import migration  # doctest: +SKIP
    >>> migration_df = migration.get_latest_migration()  # doctest: +SKIP
    >>> df_2024 = migration.get_migration_by_year(migration_df, 2024)  # doctest: +SKIP
    >>> print(f"Net migration in 2024: {df_2024['net_migration'].values[0]:+,}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import registrar_general  # doctest: +SKIP
    >>> data = registrar_general.get_quarterly_vital_statistics()  # doctest: +SKIP
    >>> births = data['births']  # doctest: +SKIP
    >>> print(f"Quarterly births from {births['year'].min()} to {births['year'].max()}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import population  # doctest: +SKIP
    >>> pop_df = population.get_latest_population(area='Northern Ireland')  # doctest: +SKIP
    >>> print(f"NI population 2024: {pop_df[pop_df['year'] == 2024]['population'].sum():,}")  # doctest: +SKIP

    >>> from bolster.data_sources.nisra import wellbeing  # doctest: +SKIP
    >>> df = wellbeing.get_latest_personal_wellbeing()  # doctest: +SKIP
    >>> latest = df.iloc[-1]  # doctest: +SKIP
    >>> print(f"Life satisfaction {latest['year']}: {latest['life_satisfaction']}")  # doctest: +SKIP
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
