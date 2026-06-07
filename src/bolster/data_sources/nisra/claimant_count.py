"""NISRA Claimant Count Statistics Module.

Provides monthly Claimant Count statistics for Northern Ireland via the NISRA
PxStat API.  The Claimant Count is an experimental statistic measuring the
number of people claiming benefits principally for the reason of being
unemployed.  Data is published monthly and covers Northern Ireland with two
geographic breakdowns: Local Government Districts and Assembly Areas.

Original data source:
    https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare/claimant-count

PxStat matrices used:
    - CCMLGD  — monthly count and rate by LGD (11 districts + NI total)
    - CCMAA   — monthly count and rate by Assembly Area (18 areas + NI total)
    - CCMSOA  — monthly count by Super Output Area (~92 k rows, large)

Update Frequency: Monthly, approximately 2–3 weeks after the reference month.

Usage:
    >>> from bolster.data_sources.nisra import claimant_count
    >>> df = claimant_count.get_latest_claimant_count("lgd")
    >>> "claimants_total" in df.columns
    True

Example:
    >>> from bolster.data_sources.nisra import claimant_count
    >>> df = claimant_count.get_latest_claimant_count("lgd")
    >>> df[df["geography"] == "Northern Ireland"]["claimants_total"].iloc[0] > 0
    True
"""

import logging

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_LGD = "CCMLGD"
_MATRIX_AA = "CCMAA"
_MATRIX_SOA = "CCMSOA"


def _parse_month(month_str: str) -> pd.Timestamp:
    """Convert a PxStat month code (e.g. ``'2024M03'``) to a Timestamp.

    Args:
        month_str: Month code in the form ``'{YYYY}M{MM}'``.

    Returns:
        pandas Timestamp for the first day of the month.

    Example:
        >>> _parse_month("2024M03")
        Timestamp('2024-03-01 00:00:00')
    """
    year, month = month_str.split("M")
    return pd.Timestamp(int(year), int(month), 1)


def _pivot_geo(df_raw: pd.DataFrame, geo_col: str, geo_name_col: str) -> pd.DataFrame:
    """Pivot a raw PxStat geography DataFrame into the standard output shape.

    The API returns CCN (count) and CCP (rate) as separate rows identified by
    the ``STATISTIC`` column.  This function pivots them into columns named
    ``claimants_total`` and ``claimant_rate_total_pct``.

    Args:
        df_raw: Raw DataFrame from :func:`~bolster.data_sources.nisra.pxstat.read_dataset`.
        geo_col: Column name for the geography code (e.g. ``'LGD2014'``).
        geo_name_col: Column name for the geography label (e.g. ``'Local Government District'``).

    Returns:
        DataFrame with columns:
            - ``date``: pandas Timestamp (monthly, day=1)
            - ``geography_code``: geography identifier code
            - ``geography``: geography name label
            - ``claimants_total``: claimant count (float)
            - ``claimant_rate_total_pct``: claimant rate as percentage (float)
    """
    df_raw = df_raw.copy()
    df_raw["date"] = df_raw["Month"].apply(_parse_month)

    count_df = df_raw[df_raw["STATISTIC"] == "CCN"][["date", geo_col, geo_name_col, "VALUE"]].rename(
        columns={geo_col: "geography_code", geo_name_col: "geography", "VALUE": "claimants_total"}
    )
    rate_df = df_raw[df_raw["STATISTIC"] == "CCP"][["date", geo_col, "VALUE"]].rename(
        columns={geo_col: "geography_code", "VALUE": "claimant_rate_total_pct"}
    )

    return (
        count_df.merge(rate_df, on=["date", "geography_code"], how="left")
        .sort_values(["date", "geography"])
        .reset_index(drop=True)
    )


def get_latest_claimant_count(
    breakdown: str = "lgd",
    adjusted: bool = True,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download and return the latest NISRA claimant count data.

    Fetches data from the NISRA PxStat API for the chosen geographic breakdown.
    Returns the full time series available from the API (from January 2005).

    Note:
        ``adjusted`` is accepted for API compatibility but is ignored — the
        PxStat API does not distinguish seasonally adjusted from unadjusted
        counts at geographic level.

        ``force_refresh`` is accepted for API compatibility but is ignored —
        the PxStat API is called directly with no local cache layer.

    Args:
        breakdown: Geographic breakdown to return.  One of:

            - ``"lgd"`` — 11 Local Government Districts + NI total (default)
            - ``"aa"``  — 18 Assembly Areas + NI total
            - ``"soa"`` — Super Output Areas (~92 k rows, large)

        adjusted: Ignored.  Retained for API compatibility.
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        For ``"lgd"`` and ``"aa"``: DataFrame with columns:

            - ``date``: pandas Timestamp (monthly, day=1)
            - ``geography_code``: geography identifier code
            - ``geography``: geography name label
            - ``claimants_total``: claimant count (float)
            - ``claimant_rate_total_pct``: claimant rate as percentage (float)

        For ``"soa"``: DataFrame with columns:

            - ``date``: pandas Timestamp (monthly, day=1)
            - ``soa_code``: Super Output Area code
            - ``soa_name``: Super Output Area name
            - ``claimants``: claimant count (float)

    Raises:
        ValueError: If ``breakdown`` is not a supported value.

    Example:
        >>> df = get_latest_claimant_count("lgd")
        >>> "claimants_total" in df.columns
        True
        >>> df_aa = get_latest_claimant_count("aa")
        >>> "claimants_total" in df_aa.columns
        True
    """
    valid = ("lgd", "aa", "soa")
    if breakdown not in valid:
        raise ValueError(f"breakdown must be one of {valid}, got {breakdown!r}")

    if breakdown == "lgd":
        raw = read_dataset(_MATRIX_LGD)
        return _pivot_geo(raw, "LGD2014", "Local Government District")

    if breakdown == "aa":
        raw = read_dataset(_MATRIX_AA)
        return _pivot_geo(raw, "AA", "Assembly Area")

    # breakdown == "soa"
    raw = read_dataset(_MATRIX_SOA)
    raw = raw.copy()
    raw["date"] = raw["Month"].apply(_parse_month)
    # SOA matrix columns: STATISTIC, Statistic Label, TLIST(M1), Month, SOA, <SOA name col>, UNIT, VALUE
    soa_code_col = (
        "SOA2001" if "SOA2001" in raw.columns else [c for c in raw.columns if "SOA" in c and c != "STATISTIC"][0]
    )
    soa_name_col = [
        c
        for c in raw.columns
        if c not in {"STATISTIC", "Statistic Label", "TLIST(M1)", "Month", soa_code_col, "UNIT", "VALUE", "date"}
    ][0]
    result = raw[["date", soa_code_col, soa_name_col, "VALUE"]].rename(
        columns={soa_code_col: "soa_code", soa_name_col: "soa_name", "VALUE": "claimants"}
    )
    return result.sort_values(["date", "soa_code"]).reset_index(drop=True)


def validate_claimant_count(df: pd.DataFrame, breakdown: str) -> bool:
    """Validate the integrity of a claimant count DataFrame.

    Checks that required columns are present, values are in plausible ranges,
    and the DataFrame is non-empty.

    Args:
        df: DataFrame returned by :func:`get_latest_claimant_count`.
        breakdown: The breakdown type that produced the DataFrame.
            One of ``"lgd"``, ``"aa"``, or ``"soa"``.

    Returns:
        ``True`` if validation passes, ``False`` otherwise.

    Example:
        >>> import pandas as pd
        >>> validate_claimant_count(pd.DataFrame(), "lgd")
        False
    """
    if df is None or df.empty:
        logger.warning("Claimant count DataFrame is empty (breakdown=%s)", breakdown)
        return False

    required_columns: dict[str, list[str]] = {
        "lgd": ["date", "geography_code", "geography", "claimants_total", "claimant_rate_total_pct"],
        "aa": ["date", "geography_code", "geography", "claimants_total", "claimant_rate_total_pct"],
        "soa": ["date", "soa_code", "claimants"],
    }

    if breakdown not in required_columns:
        logger.warning("Unknown breakdown type: %s", breakdown)
        return False

    missing = [c for c in required_columns[breakdown] if c not in df.columns]
    if missing:
        logger.warning("Missing columns for %s breakdown: %s", breakdown, missing)
        return False

    if breakdown in ("lgd", "aa"):
        if (df["claimants_total"] < 0).any():
            logger.warning("Negative claimant counts in %s data", breakdown)
            return False
        rates = df["claimant_rate_total_pct"].dropna()
        if len(rates) > 0 and ((rates < 0).any() or (rates > 100).any()):
            logger.warning("Claimant rates out of range [0, 100] in %s data", breakdown)
            return False

    if breakdown == "soa" and (df["claimants"] < 0).any():
        logger.warning("Negative claimant counts in SOA data")
        return False

    return True
