"""NISRA Drug-Related and Drug Misuse Deaths Data Source.

Provides access to NISRA's annual statistics on drug-related deaths and deaths
due to drug misuse in Northern Ireland via the NISRA PxStat API.  Two geographic
breakdowns are available: HSC Trust and Local Government District.

NISRA distinguishes two related measures:

- **Drug-related deaths** (``DRDCOUNT``): All deaths where a drug was implicated,
  including prescription medicines, controlled drugs, and accidental/intentional
  poisonings.
- **Drug misuse deaths** (``MISUSECOUNT``): A narrower subset where the underlying
  cause is drug abuse/dependence or the death involved a controlled substance.

Original data source:
    https://www.nisra.gov.uk/statistics/death-statistics/drug-related-and-drug-misuse-deaths

PxStat matrices used:
    - DTHSDRHSCT — annual deaths by HSC Trust (6 trusts + NI total)
    - DTHSDRLGD  — annual deaths by LGD (11 districts + NI total)

Update Frequency: Annual (typically May)
Geographic Coverage: Northern Ireland

Example:
    >>> from bolster.data_sources.nisra import drug_related_deaths as drd
    >>> df = drd.get_latest_drug_related_deaths()
    >>> {"year", "geography", "statistic", "value"}.issubset(df.columns)
    True
    >>> len(df) > 0
    True
"""

import logging
from typing import Literal

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_HSCT = "DTHSDRHSCT"
_MATRIX_LGD = "DTHSDRLGD"

DimensionType = Literal["hsct", "lgd", "all"]

# Map STATISTIC code to a human-readable label
_STATISTIC_LABELS = {
    "DRDCOUNT": "drug_related",
    "MISUSECOUNT": "drug_misuse",
}


def _process_matrix(matrix: str, geo_col: str, geo_name_col: str) -> pd.DataFrame:
    """Fetch and tidy a drug deaths PxStat matrix.

    Args:
        matrix: PxStat matrix code.
        geo_col: Column name for the geography code.
        geo_name_col: Column name for the geography label.

    Returns:
        DataFrame with columns:
            - ``year``: Registration year (int)
            - ``geography_code``: geography identifier code
            - ``geography``: geography name label
            - ``statistic``: ``"drug_related"`` or ``"drug_misuse"``
            - ``value``: Count of deaths (int, NaN where suppressed)
    """
    df = read_dataset(matrix)
    df = df.rename(
        columns={
            geo_col: "geography_code",
            geo_name_col: "geography",
            "Year": "year",
            "VALUE": "value",
        }
    )
    df["statistic"] = df["STATISTIC"].map(_STATISTIC_LABELS).fillna(df["STATISTIC"])
    result = df[["year", "geography_code", "geography", "statistic", "value"]].copy()
    return result.sort_values(["statistic", "year", "geography"]).reset_index(drop=True)


def get_latest_drug_related_deaths(
    dimension: DimensionType = "all",
    force_refresh: bool = False,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """Download and return the latest NISRA drug-related deaths data.

    Fetches data from the NISRA PxStat API.  Both available geographic
    breakdowns are returned for ``dimension='all'``.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored —
        the PxStat API is called directly with no local cache layer.

    Args:
        dimension: Geographic breakdown to return.  One of:

            - ``"hsct"`` — 5 HSC Trusts + NI total
            - ``"lgd"``  — 11 Local Government Districts + NI total
            - ``"all"``  — dict containing both breakdowns (default)

        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        For ``"hsct"`` or ``"lgd"``: DataFrame with columns:

            - ``year``: Registration year (int)
            - ``geography_code``: geography identifier code
            - ``geography``: geography name label
            - ``statistic``: ``"drug_related"`` or ``"drug_misuse"``
            - ``value``: Count of deaths (int, NaN where suppressed)

        For ``"all"``: ``{"hsct": DataFrame, "lgd": DataFrame}``

    Raises:
        ValueError: If ``dimension`` is not a supported value.

    Example:
        >>> df = get_latest_drug_related_deaths("hsct")
        >>> {"year", "geography", "statistic", "value"}.issubset(df.columns)
        True
        >>> data = get_latest_drug_related_deaths("all")
        >>> sorted(data.keys())
        ['hsct', 'lgd']
    """
    valid = ("hsct", "lgd", "all")
    if dimension not in valid:
        raise ValueError(f"dimension must be one of {valid}, got {dimension!r}")

    if dimension == "hsct":
        return _process_matrix(_MATRIX_HSCT, "HSCT", "Health and Social Care Trust")

    if dimension == "lgd":
        return _process_matrix(_MATRIX_LGD, "LGD2014", "Local Government District")

    # dimension == "all"
    return {
        "hsct": _process_matrix(_MATRIX_HSCT, "HSCT", "Health and Social Care Trust"),
        "lgd": _process_matrix(_MATRIX_LGD, "LGD2014", "Local Government District"),
    }


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a parsed drug-related deaths DataFrame.

    Args:
        df: DataFrame from :func:`get_latest_drug_related_deaths` with a single
            geographic dimension.

    Returns:
        True if validation passes, False otherwise.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        False
    """
    if df is None or df.empty:
        logger.warning("Drug deaths data is empty")
        return False

    required_cols = {"year", "geography", "statistic", "value"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        logger.warning("Missing required columns: %s", missing)
        return False

    non_null_values = df["value"].dropna()
    if len(non_null_values) > 0 and (non_null_values < 0).any():
        logger.warning("Found negative values in drug deaths data")
        return False

    # Need at least a few years of data to be a useful time series.
    if df["year"].nunique() < 5:
        logger.warning("Too few years of data: %d", df["year"].nunique())
        return False

    return True
