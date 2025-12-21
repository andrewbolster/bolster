"""
NISRA (Northern Ireland Statistics and Research Agency) Data Sources.

This package provides access to various statistical datasets published by NISRA,
including deaths, labour market, crime, economic indices, and more.

Available modules:
    - deaths: Weekly death registrations with demographic, geographic, and place breakdowns
    - labour_market: Quarterly Labour Force Survey statistics (employment, economic inactivity)
    - crime: Monthly police-recorded crime statistics (coming soon)

Examples:
    >>> from bolster.data_sources.nisra import deaths
    >>> df = deaths.get_latest_deaths(dimension='demographics')
    >>> print(df.head())

    >>> from bolster.data_sources.nisra import labour_market
    >>> emp_df = labour_market.get_latest_employment()
    >>> inact_df = labour_market.get_latest_economic_inactivity()
"""

from . import deaths, labour_market

__all__ = ["deaths", "labour_market"]
