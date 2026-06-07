"""NISRA Stillbirths and Infant Deaths Data Source.

Provides access to annual stillbirth and infant death statistics for Northern
Ireland via the NISRA PxStat API, with geographic breakdowns by HSC Trust and
Local Government District.

A stillbirth is defined as a baby born after 24 weeks of pregnancy that did not
show any signs of life.  Infant deaths are deaths of children under one year old.

Original data source:
    https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/stillbirths

PxStat matrices used:
    - SBAIDHSCT — annual stillbirths and infant deaths by HSC Trust (5 trusts + NI total)
    - SBAIDLGD  — annual stillbirths and infant deaths by LGD (11 districts + NI total)

Update Frequency: Annual
Geographic Coverage: Northern Ireland

Example:
    >>> from bolster.data_sources.nisra import stillbirths
    >>> df = stillbirths.get_latest_stillbirths()
    >>> sorted(df.columns.tolist())
    ['geography', 'geography_code', 'infant_deaths', 'stillbirths', 'year']

    >>> # NI total stillbirths in 2024
    >>> ni_2024 = df[(df["geography"] == "Northern Ireland") & (df["year"] == 2024)]
    >>> bool(ni_2024["stillbirths"].iloc[0] > 0)
    True
"""

import logging

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_HSCT = "SBAIDHSCT"
_MATRIX_LGD = "SBAIDLGD"


class NISRAValidationError(Exception):
    """Raised when stillbirths data fails validation."""


def _process_matrix(matrix: str, geo_col: str, geo_name_col: str) -> pd.DataFrame:
    """Fetch and pivot a stillbirths/infant deaths PxStat matrix into wide format.

    The API returns SBCOUNT (stillbirths) and IDCOUNT (infant deaths) as
    separate rows.  This function pivots them into columns.

    Args:
        matrix: PxStat matrix code.
        geo_col: Column name for the geography code.
        geo_name_col: Column name for the geography label.

    Returns:
        DataFrame with columns:
            - ``year``: Registration year (int)
            - ``geography_code``: geography identifier code
            - ``geography``: geography name label
            - ``stillbirths``: Annual stillbirth count (int)
            - ``infant_deaths``: Annual infant death count (int)
    """
    df = read_dataset(matrix)
    df = df.rename(columns={geo_col: "geography_code", geo_name_col: "geography", "Year": "year", "VALUE": "value"})

    sb = df[df["STATISTIC"] == "SBCOUNT"][["year", "geography_code", "geography", "value"]].rename(
        columns={"value": "stillbirths"}
    )
    id_ = df[df["STATISTIC"] == "IDCOUNT"][["year", "geography_code", "geography", "value"]].rename(
        columns={"value": "infant_deaths"}
    )
    result = sb.merge(id_, on=["year", "geography_code", "geography"], how="outer")
    return result.sort_values(["year", "geography"]).reset_index(drop=True)


def get_latest_stillbirths(
    dimension: str = "hsct",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the latest annual stillbirth and infant death data for Northern Ireland.

    Fetches annual data from the NISRA PxStat API for the chosen geographic
    breakdown.  Returns the full time series available (HSCT from 1974, LGD
    from 2008).

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored —
        the PxStat API is called directly with no local cache layer.

    Args:
        dimension: Geographic breakdown to return.  One of:

            - ``"hsct"`` — 5 HSC Trusts + NI total (default, data from 1974)
            - ``"lgd"``  — 11 Local Government Districts + NI total (data from 2008)

        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns:
            - ``year``: Registration year (int)
            - ``geography_code``: geography identifier code
            - ``geography``: geography name label
            - ``stillbirths``: Annual stillbirth count (int)
            - ``infant_deaths``: Annual infant death count (int)

    Raises:
        ValueError: If ``dimension`` is not a supported value.

    Example:
        >>> df = get_latest_stillbirths()
        >>> sorted(df.columns.tolist())
        ['geography', 'geography_code', 'infant_deaths', 'stillbirths', 'year']
        >>> annual = df[df["geography"] == "Northern Ireland"].groupby("year")["stillbirths"].sum()
        >>> len(annual) > 0
        True
    """
    valid = ("hsct", "lgd")
    if dimension not in valid:
        raise ValueError(f"dimension must be one of {valid}, got {dimension!r}")

    if dimension == "hsct":
        return _process_matrix(_MATRIX_HSCT, "HSCT", "Health and Social Care Trust")

    # dimension == "lgd"
    return _process_matrix(_MATRIX_LGD, "LGD2014", "Local Government District")


def validate_stillbirths_data(df: pd.DataFrame) -> bool:
    """Validate stillbirths DataFrame for basic integrity.

    Args:
        df: DataFrame from :func:`get_latest_stillbirths`.

    Returns:
        True if validation passes.

    Raises:
        NISRAValidationError: If validation fails.

    Example:
        >>> import pandas as pd
        >>> validate_stillbirths_data(pd.DataFrame())
        Traceback (most recent call last):
            ...
        bolster.data_sources.nisra.stillbirths.NISRAValidationError: DataFrame is empty
    """
    required_cols = {"year", "geography", "stillbirths"}
    missing = required_cols - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    sb_non_null = df["stillbirths"].dropna()
    if len(sb_non_null) > 0 and (sb_non_null < 0).any():
        raise NISRAValidationError("Negative stillbirth counts found")

    # Annual NI totals should be within plausible range for NI
    ni = df[df["geography"] == "Northern Ireland"]
    if not ni.empty:
        annual = ni.groupby("year")["stillbirths"].sum()
        if (annual > 500).any():
            raise NISRAValidationError(f"Annual NI stillbirths implausibly high: {annual[annual > 500].to_dict()}")

    return True


def get_stillbirths_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter stillbirths data to a specific year.

    Args:
        df: DataFrame from :func:`get_latest_stillbirths`.
        year: Year to filter.

    Returns:
        Filtered DataFrame.

    Example:
        >>> df = get_latest_stillbirths()
        >>> df_2024 = get_stillbirths_by_year(df, 2024)
        >>> "stillbirths" in df_2024.columns
        True
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_annual_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate annual NI totals and trends for stillbirths.

    Args:
        df: DataFrame from :func:`get_latest_stillbirths`.

    Returns:
        DataFrame with columns:
            ``year``, ``total_stillbirths``, ``yoy_change``, ``yoy_pct_change``.

    Example:
        >>> df = get_latest_stillbirths()
        >>> summary = get_annual_summary(df)
        >>> sorted(summary.columns.tolist())
        ['total_stillbirths', 'year', 'yoy_change', 'yoy_pct_change']
    """
    ni = df[df["geography"] == "Northern Ireland"]
    annual = ni.groupby("year")["stillbirths"].sum().reset_index()
    annual = annual.rename(columns={"stillbirths": "total_stillbirths"})
    annual["yoy_change"] = annual["total_stillbirths"].diff()
    annual["yoy_pct_change"] = annual["total_stillbirths"].pct_change().mul(100).round(1)
    return annual.reset_index(drop=True)
