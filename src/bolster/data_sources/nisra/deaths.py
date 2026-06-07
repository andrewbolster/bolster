"""NISRA Weekly Death Registrations Data Source.

Provides access to weekly death registration statistics for Northern Ireland with breakdowns by:
- Totals (observed, expected, excess, COVID-19, flu/pneumonia deaths)
- Demographics (age, sex)
- Geography (Local Government Districts)
- Place of death (hospital, home, care home, etc.)

Data is based on registration date. Most deaths are registered within 5 days in Northern Ireland.

Data Source:
    NISRA PxStat API — https://ws-data.nisra.gov.uk/
    No authentication required; no observed rate limits.

    Matrix codes used:
    - ``WDTHS``: Weekly totals (observed, expected, excess, COVID, flu)
    - ``WDTHSLGD``: Weekly deaths by Local Government District
    - ``WDTHSSXAG``: Weekly deaths by sex and age band
    - ``WDTHSPOD``: Weekly deaths by place of death

Update Frequency: Weekly (published Fridays for week ending previous Friday)
Geographic Coverage: Northern Ireland

Example:
    >>> from bolster.data_sources.nisra import deaths
    >>> df = deaths.get_latest_deaths(dimension='demographics')
    >>> sorted(df.columns.tolist())
    ['age_range', 'deaths', 'sex', 'week_ending']
    >>> len(df) > 0
    True
"""

import logging

import pandas as pd

from ._base import NISRAValidationError
from .pxstat import PxStatError, read_dataset  # noqa: F401 — re-exported for callers

logger = logging.getLogger(__name__)

_STAT_OBSERVED = "DTHSREGPROV"


def _parse_week_ending(raw: pd.Series) -> pd.Series:
    return pd.to_datetime(raw, dayfirst=True, errors="coerce")


def _get_totals() -> pd.DataFrame:
    """Fetch weekly totals dimension.

    Returns DataFrame with columns:
        week_ending, week_number, observed_deaths, expected_deaths_5yr,
        excess_deaths_5yr, flu_pneumonia_deaths, covid_deaths
    """
    df = read_dataset("WDTHS")
    df["week_ending"] = _parse_week_ending(df["Week ending date"])

    pivoted = df.pivot_table(
        index=["week_ending", "TLIST(W1)"],
        columns="STATISTIC",
        values="VALUE",
        aggfunc="first",
    ).reset_index()
    pivoted.columns.name = None

    result = pd.DataFrame()
    result["week_ending"] = pivoted["week_ending"]
    result["week_number"] = pivoted["TLIST(W1)"].str.extract(r"W(\d+)$").astype(int)
    result["observed_deaths"] = pivoted.get("DTHSREGPROV")
    result["expected_deaths_5yr"] = pivoted.get("EXPDTHS")
    result["excess_deaths_5yr"] = pivoted.get("EXCDTHS")
    result["flu_pneumonia_deaths"] = pivoted.get("FPDTHS")
    result["covid_deaths"] = pivoted.get("CVD19DTHS")

    result = result.sort_values("week_ending").reset_index(drop=True)

    if result.empty or result["observed_deaths"].isna().all():
        raise NISRAValidationError("Deaths totals data is empty or missing observed deaths")

    return result


def _get_demographics() -> pd.DataFrame:
    """Fetch demographics (sex × age band) dimension.

    Returns DataFrame with columns:
        week_ending, sex, age_range, deaths

    Includes aggregate rows ("All persons"/"All ages") for cross-validation.
    """
    df = read_dataset("WDTHSSXAG")
    df["week_ending"] = _parse_week_ending(df["Week ending date"])

    return (
        df[df["STATISTIC"] == _STAT_OBSERVED][["week_ending", "Sex Label", "Age band", "VALUE"]]
        .rename(columns={"Sex Label": "sex", "Age band": "age_range", "VALUE": "deaths"})
        .sort_values(["week_ending", "sex", "age_range"])
        .reset_index(drop=True)
    )


def _get_geography() -> pd.DataFrame:
    """Fetch geography (LGD) dimension.

    Returns DataFrame with columns:
        week_ending, lgd_name, deaths

    Excludes the "Northern Ireland" aggregate row — returns 11 district rows per week.
    """
    df = read_dataset("WDTHSLGD")
    df["week_ending"] = _parse_week_ending(df["Week ending date"])

    return (
        df[(df["STATISTIC"] == _STAT_OBSERVED) & (df["Local Government District"] != "Northern Ireland")][
            ["week_ending", "Local Government District", "VALUE"]
        ]
        .rename(columns={"Local Government District": "lgd_name", "VALUE": "deaths"})
        .sort_values(["week_ending", "lgd_name"])
        .reset_index(drop=True)
    )


def _get_place() -> pd.DataFrame:
    """Fetch place of death dimension.

    Returns DataFrame with columns:
        week_ending, place_of_death, deaths

    Excludes the "All places" aggregate row — returns specific place categories only.
    """
    df = read_dataset("WDTHSPOD")
    df["week_ending"] = _parse_week_ending(df["Week ending date"])

    return (
        df[(df["STATISTIC"] == _STAT_OBSERVED) & (df["Place of death"] != "All places")][
            ["week_ending", "Place of death", "VALUE"]
        ]
        .rename(columns={"Place of death": "place_of_death", "VALUE": "deaths"})
        .sort_values(["week_ending", "place_of_death"])
        .reset_index(drop=True)
    )


def get_latest_deaths(
    dimension: str = "all",
    force_refresh: bool = False,
) -> pd.DataFrame | dict:
    """Retrieve weekly deaths data for Northern Ireland.

    Args:
        dimension: Which dimension to retrieve. One of:
            - ``'totals'``: Weekly totals with observed, expected, excess, COVID, flu
            - ``'demographics'``: By sex and age band
            - ``'geography'``: By Local Government District
            - ``'place'``: By place of death
            - ``'all'``: All dimensions (returns dict of DataFrames)
        force_refresh: Ignored — kept for API compatibility. The PxStat API
            always returns current data.

    Returns:
        DataFrame for a single dimension, or ``dict[str, DataFrame]`` for ``'all'``.

    Raises:
        NISRAValidationError: If the API returns empty or invalid data.
        PxStatError: If the API request fails.

    Example:
        >>> df = get_latest_deaths(dimension='demographics')
        >>> sorted(df.columns.tolist())
        ['age_range', 'deaths', 'sex', 'week_ending']
    """
    if force_refresh:
        logger.debug("force_refresh is ignored for PxStat-backed modules")

    if dimension == "totals":
        return _get_totals()
    if dimension == "demographics":
        return _get_demographics()
    if dimension == "geography":
        return _get_geography()
    if dimension == "place":
        return _get_place()
    if dimension == "all":
        return {
            "totals": _get_totals(),
            "demographics": _get_demographics(),
            "geography": _get_geography(),
            "place": _get_place(),
        }
    raise ValueError(f"Invalid dimension: {dimension!r}. Must be one of: totals, demographics, geography, place, all")
