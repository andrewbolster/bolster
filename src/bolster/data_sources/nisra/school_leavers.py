"""NISRA School Leavers Survey Data Source.

Provides access to the Department of Education NI / NISRA School Leavers Survey
via the NISRA PxStat API.  The survey covers every grammar and secondary school
leaver in Northern Ireland, recording their highest attainment and their
destination on leaving school.

Two measures are published:

- **Attainment** — the proportion of leavers reaching each qualification
  threshold (3+ A-levels, 5+ GCSEs A*-C, etc.).
- **Destination** — where leavers went next (higher education, further
  education, employment, training, unemployed/unknown).

Both measures are broken down by free school meal entitlement (FSME) and are
available across five geographic dimensions.  A separate equality-group
breakdown reports attainment by sex, religion, and ethnic group.

Original data source:
    https://www.education-ni.gov.uk/articles/school-leavers-survey

PxStat matrices used:
    - ``DESLSAS`` / ``DESLSDS``     — settlement (NI, Urban, Rural), 2012/13-
    - ``DESLSALGD`` / ``DESLSDLGD`` — Local Government District, 2012/13-
    - ``DESLSAHSCT`` / ``DESLSDHSCT`` — HSC Trust, 2008/09-
    - ``DESLSAAA`` / ``DESLSDAA``   — Assembly Area, 2008/09-
    - ``DESLSADEA`` / ``DESLSDDEA`` — District Electoral Area, 2012/13-
    - ``SLSAEQ``                    — attainment by equality group, 2018/19-

Update Frequency: Annual (published May/June following the academic year end)
Geographic Coverage: Northern Ireland

Example:
    >>> from bolster.data_sources.nisra import school_leavers
    >>> df = school_leavers.get_latest_school_leavers("destination")
    >>> {"academic_year", "geography", "category", "count"}.issubset(df.columns)
    True
    >>> len(df) > 0
    True
"""

import logging
from typing import Literal

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

logger = logging.getLogger(__name__)

MeasureType = Literal["attainment", "destination"]
GeographyType = Literal["settlement", "lgd", "hsct", "aa", "dea"]
DimensionType = Literal["attainment", "destination", "equality", "all"]

_MATRIX_EQUALITY = "SLSAEQ"

# (measure, geography) -> (matrix code, geography code column, geography label column)
_MATRICES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("attainment", "settlement"): ("DESLSAS", "SETTLEMENT", "Settlement Label"),
    ("attainment", "lgd"): ("DESLSALGD", "LGD2014", "Local Government District"),
    ("attainment", "hsct"): ("DESLSAHSCT", "HSCT", "Health and Social Care Trust"),
    ("attainment", "aa"): ("DESLSAAA", "AA", "Assembly Area"),
    ("attainment", "dea"): ("DESLSADEA", "DEA2014", "District Electoral Area"),
    ("destination", "settlement"): ("DESLSDS", "SETTLEMENT", "Settlement Label"),
    ("destination", "lgd"): ("DESLSDLGD", "LGD2014", "Local Government District"),
    ("destination", "hsct"): ("DESLSDHSCT", "HSCT", "Health and Social Care Trust"),
    ("destination", "aa"): ("DESLSDAA", "AA", "Assembly Area"),
    ("destination", "dea"): ("DESLSDDEA", "DEA2014", "District Electoral Area"),
}

_MEASURES: tuple[str, ...] = ("attainment", "destination")
_GEOGRAPHIES: tuple[str, ...] = ("settlement", "lgd", "hsct", "aa", "dea")

# The category column differs by measure.
_CATEGORY_COLUMNS = {"attainment": "Attainment", "destination": "Destination Label"}

_FSME_LABELS = {
    "Free school meal entitled": "entitled",
    "Not free school meal entitled": "not_entitled",
    "All persons": "all",
}

_DESTINATION_PREFIX = "School leavers with destination: "

# STATISTIC codes are stable across every School Leavers Survey matrix.
_COUNT_CODE = "NumSL"
_PERCENTAGE_CODE = "PercSL"


def _academic_year_ending(academic_year: pd.Series) -> pd.Series:
    """Convert an academic year label to the calendar year it ends in.

    Args:
        academic_year: Series of labels such as ``"2024/25"``.

    Returns:
        Integer Series of ending calendar years (``2025`` for ``"2024/25"``).
    """
    return academic_year.str.slice(0, 4).astype(int) + 1


def _pivot_statistics(df: pd.DataFrame, index_cols: list[str]) -> pd.DataFrame:
    """Pivot the long STATISTIC/VALUE pairs into ``count`` and ``percentage``.

    Every School Leavers Survey matrix publishes each cell twice — once as a
    count (``NumSL``) and once as a percentage (``PercSL``).

    Uses an explicit outer merge rather than :meth:`~pandas.DataFrame.pivot_table`,
    which would expand the index columns into their full cartesian product and
    invent observations that the source never published.

    Args:
        df: Raw PxStat frame with ``STATISTIC`` and ``VALUE`` columns.
        index_cols: Columns identifying a single observation.

    Returns:
        DataFrame with ``count`` and ``percentage`` columns replacing the
        ``STATISTIC``/``VALUE`` pair.
    """
    counts = df[df["STATISTIC"] == _COUNT_CODE][[*index_cols, "VALUE"]].rename(columns={"VALUE": "count"})
    percentages = df[df["STATISTIC"] == _PERCENTAGE_CODE][[*index_cols, "VALUE"]].rename(
        columns={"VALUE": "percentage"}
    )
    return counts.merge(percentages, on=index_cols, how="outer")


def get_latest_school_leavers(
    measure: MeasureType = "attainment",
    geography: GeographyType = "settlement",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download School Leavers Survey attainment or destination data.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored —
        the PxStat API is called directly with no local cache layer.

    Args:
        measure: ``"attainment"`` for qualification thresholds, or
            ``"destination"`` for post-school destinations.
        geography: Geographic breakdown.  One of:

            - ``"settlement"`` — Northern Ireland, Urban, Rural (default)
            - ``"lgd"``  — 11 Local Government Districts + NI
            - ``"hsct"`` — 5 HSC Trusts + NI
            - ``"aa"``   — 18 Assembly Areas + NI
            - ``"dea"``  — 80 District Electoral Areas + NI

        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns:

            - ``academic_year``: Academic year label (e.g. ``"2024/25"``)
            - ``year_ending``: Calendar year the academic year ends (int)
            - ``geography_code``: Geography identifier code
            - ``geography``: Geography name label
            - ``category``: Attainment threshold or destination
            - ``fsm_entitlement``: ``"entitled"``, ``"not_entitled"`` or ``"all"``
            - ``count``: Number of school leavers (NaN where suppressed)
            - ``percentage``: Percentage of school leavers (NaN where suppressed)

    Raises:
        ValueError: If ``measure`` or ``geography`` is not a supported value.

    Example:
        >>> df = get_latest_school_leavers("destination", "lgd")
        >>> "higher education" in set(df["category"])
        True
    """
    if measure not in _MEASURES:
        raise ValueError(f"measure must be one of {_MEASURES}, got {measure!r}")
    if geography not in _GEOGRAPHIES:
        raise ValueError(f"geography must be one of {_GEOGRAPHIES}, got {geography!r}")

    matrix, geo_code_col, geo_label_col = _MATRICES[(measure, geography)]
    df = read_dataset(matrix)

    df = df.rename(
        columns={
            geo_code_col: "geography_code",
            geo_label_col: "geography",
            _CATEGORY_COLUMNS[measure]: "category",
        }
    )

    # The DEA attainment matrix mislabels the FSME column as "Full school meal
    # entitlement" and the DEA destination matrix omits it entirely.
    fsme_col = next((c for c in df.columns if c.endswith("school meal entitlement")), None)
    if fsme_col is None:
        df["fsm_entitlement"] = "all"
    else:
        df["fsm_entitlement"] = df[fsme_col].map(_FSME_LABELS).fillna(df[fsme_col])
    if measure == "destination":
        df["category"] = df["category"].str.removeprefix(_DESTINATION_PREFIX)

    index_cols = ["Academic year", "geography_code", "geography", "category", "fsm_entitlement"]
    result = _pivot_statistics(df, index_cols)
    result = result.rename(columns={"Academic year": "academic_year"})
    result["year_ending"] = _academic_year_ending(result["academic_year"])

    result = result[
        [
            "academic_year",
            "year_ending",
            "geography_code",
            "geography",
            "category",
            "fsm_entitlement",
            "count",
            "percentage",
        ]
    ]
    return result.sort_values(["academic_year", "geography", "category", "fsm_entitlement"]).reset_index(drop=True)


def get_attainment_by_equality_group(force_refresh: bool = False) -> pd.DataFrame:
    """Download school leaver attainment broken down by equality group.

    Covers sex, religion, and ethnic group from 2018/19 onwards.  Unlike the
    geographic tables this breakdown has no free school meal dimension.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored.

    Args:
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns:

            - ``academic_year``: Academic year label (e.g. ``"2024/25"``)
            - ``year_ending``: Calendar year the academic year ends (int)
            - ``equality_type``: ``"Sex"``, ``"Religion"``, ``"Ethnic group"``
              or ``"Total"`` for the Northern Ireland row
            - ``equality_group``: Group label (e.g. ``"Female"``, ``"Catholic"``)
            - ``category``: Attainment threshold
            - ``count``: Number of school leavers (NaN where suppressed)
            - ``percentage``: Percentage of school leavers (NaN where suppressed)

    Example:
        >>> df = get_attainment_by_equality_group()
        >>> "Sex" in set(df["equality_type"])
        True
    """
    df = read_dataset(_MATRIX_EQUALITY)
    df = df.rename(columns={"Attainment": "category"})

    # Labels are "Sex - Female", "Religion - Catholic", etc.  The NI total row
    # has no separator and is tagged as "Total".
    split = df["Equality group"].str.split(" - ", n=1, expand=True)
    df["equality_type"] = split[0].where(split[1].notna(), "Total")
    df["equality_group"] = split[1].fillna(split[0])

    index_cols = ["Academic year", "equality_type", "equality_group", "category"]
    result = _pivot_statistics(df, index_cols)
    result = result.rename(columns={"Academic year": "academic_year"})
    result["year_ending"] = _academic_year_ending(result["academic_year"])

    result = result[
        [
            "academic_year",
            "year_ending",
            "equality_type",
            "equality_group",
            "category",
            "count",
            "percentage",
        ]
    ]
    return result.sort_values(["academic_year", "equality_type", "equality_group", "category"]).reset_index(drop=True)


def get_latest_data(
    dimension: DimensionType = "attainment",
    geography: GeographyType = "settlement",
    force_refresh: bool = False,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """Download School Leavers Survey data for one or all dimensions.

    Args:
        dimension: Which view to return.  One of:

            - ``"attainment"``  — qualification thresholds (default)
            - ``"destination"`` — post-school destinations
            - ``"equality"``    — attainment by sex, religion, ethnic group
            - ``"all"``         — dict containing all three

        geography: Geographic breakdown for the attainment and destination
            views.  Ignored for ``"equality"``.  See
            :func:`get_latest_school_leavers`.
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        A DataFrame for a single dimension, or for ``"all"`` a dict with keys
        ``"attainment"``, ``"destination"`` and ``"equality"``.

    Raises:
        ValueError: If ``dimension`` is not a supported value.

    Example:
        >>> data = get_latest_data("all")
        >>> sorted(data.keys())
        ['attainment', 'destination', 'equality']
    """
    valid = ("attainment", "destination", "equality", "all")
    if dimension not in valid:
        raise ValueError(f"dimension must be one of {valid}, got {dimension!r}")

    if dimension == "equality":
        return get_attainment_by_equality_group(force_refresh=force_refresh)

    if dimension == "all":
        return {
            "attainment": get_latest_school_leavers("attainment", geography, force_refresh),
            "destination": get_latest_school_leavers("destination", geography, force_refresh),
            "equality": get_attainment_by_equality_group(force_refresh=force_refresh),
        }

    return get_latest_school_leavers(dimension, geography, force_refresh)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a parsed School Leavers Survey DataFrame.

    Args:
        df: DataFrame from :func:`get_latest_school_leavers` or
            :func:`get_attainment_by_equality_group`.

    Returns:
        True if validation passes, False otherwise.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        False
    """
    if df is None or df.empty:
        logger.warning("School leavers data is empty")
        return False

    required_cols = {"academic_year", "year_ending", "category", "count", "percentage"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        logger.warning("Missing required columns: %s", missing)
        return False

    counts = df["count"].dropna()
    if len(counts) > 0 and (counts < 0).any():
        logger.warning("Found negative counts in school leavers data")
        return False

    percentages = df["percentage"].dropna()
    if len(percentages) > 0 and ((percentages < 0) | (percentages > 100)).any():
        logger.warning("Found percentages outside 0-100 in school leavers data")
        return False

    if df["academic_year"].nunique() < 5:
        logger.warning("Too few academic years of data: %d", df["academic_year"].nunique())
        return False

    return True
