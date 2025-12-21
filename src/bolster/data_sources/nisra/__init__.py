"""
NISRA (Northern Ireland Statistics and Research Agency) Data Sources.

This package provides access to various statistical datasets published by NISRA,
including deaths, labour market, crime, economic indices, and more.

Available modules:
    - deaths: Weekly death registrations with demographic, geographic, and place breakdowns
    - labour_market: Monthly employment, unemployment, and economic activity statistics (coming soon)
    - crime: Monthly police-recorded crime statistics (coming soon)

Example:
    >>> from bolster.data_sources.nisra import deaths
    >>> df = deaths.get_latest_deaths(dimension='demographics')
    >>> print(df.head())
"""

from . import deaths

__all__ = ["deaths"]
