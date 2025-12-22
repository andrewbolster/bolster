"""
NISRA (Northern Ireland Statistics and Research Agency) Data Sources.

This package provides access to various statistical datasets published by NISRA,
including births, deaths, labour market, population, migration, and economic indicators.

Available modules:
    - births: Monthly birth registrations by registration and occurrence date
    - deaths: Weekly death registrations with demographic, geographic, and place breakdowns
    - labour_market: Quarterly Labour Force Survey statistics (employment, economic inactivity)
    - marriages: Monthly marriage registrations
    - migration: Derived migration estimates from demographic components
    - population: Annual mid-year population estimates by age, sex, and geography

Examples:
    >>> from bolster.data_sources.nisra import births
    >>> birth_data = births.get_latest_births(event_type='both')
    >>> print(birth_data['registration'].head())

    >>> from bolster.data_sources.nisra import deaths
    >>> df = deaths.get_latest_deaths(dimension='demographics')
    >>> print(df.head())

    >>> from bolster.data_sources.nisra import labour_market
    >>> emp_df = labour_market.get_latest_employment()
    >>> inact_df = labour_market.get_latest_economic_inactivity()

    >>> from bolster.data_sources.nisra import marriages
    >>> marriages_df = marriages.get_latest_marriages()
    >>> df_2024 = marriages.get_marriages_by_year(marriages_df, 2024)
    >>> print(f"Total marriages in 2024: {df_2024['marriages'].sum():,}")

    >>> from bolster.data_sources.nisra import migration
    >>> migration_df = migration.get_latest_migration()
    >>> df_2024 = migration.get_migration_by_year(migration_df, 2024)
    >>> print(f"Net migration in 2024: {df_2024['net_migration'].values[0]:+,}")

    >>> from bolster.data_sources.nisra import population
    >>> pop_df = population.get_latest_population(area='Northern Ireland')
    >>> print(f"NI population 2024: {pop_df[pop_df['year'] == 2024]['population'].sum():,}")
"""

from . import births, deaths, labour_market, marriages, migration, population

__all__ = ["births", "deaths", "labour_market", "marriages", "migration", "population"]
