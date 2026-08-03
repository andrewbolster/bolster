"""Teacher Workforce Statistics in Grant-Aided Schools (NI).

Provides access to Department of Education Northern Ireland teacher workforce
statistics via the NISRA PxStat API.  Three complementary views are available,
all broken down by Local Government District:

- **Headcount** (``DETNLGD``): Number of teachers by age band, sex and
  full-time/part-time working pattern.
- **Full-time equivalent** (``DETNFTELGD``): FTE teachers by school type,
  which accounts for part-time working and is the fairer basis for comparing
  staffing levels between districts.
- **Pupil:teacher ratio** (``DETNPTRLGD``): Pupils per FTE teacher by school
  type.

Original data source:
    https://www.education-ni.gov.uk/articles/education-workforce

PxStat matrices used:
    - DETNLGD    — teachers by characteristic and LGD
    - DETNFTELGD — FTE teachers by school type and LGD
    - DETNPTRLGD — pupil:teacher ratios by school type and LGD

Note:
    PxStat coverage runs to 2022/23.  The Department of Education publishes
    more recent academic years, but from 2021/22 onwards those releases are
    PDF infographics only with no accompanying machine-readable tables, so
    PxStat remains the authoritative structured source.

Update Frequency: Annual
Geographic Coverage: Northern Ireland (11 LGDs + NI total)
Reference Period: 2015/16 – 2022/23

Example:
    >>> from bolster.data_sources.nisra import teacher_workforce as tw
    >>> df = tw.get_headcount()
    >>> {"academic_year", "geography", "statistic", "value"}.issubset(df.columns)
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
_MATRIX_HEADCOUNT = "DETNLGD"
_MATRIX_FTE = "DETNFTELGD"
_MATRIX_PTR = "DETNPTRLGD"

DimensionType = Literal["headcount", "fte", "ptr", "all"]

# Map STATISTIC code to a stable snake_case label
_STATISTIC_LABELS = {
    "Allteach": "all_teachers",
    "teach29under": "aged_29_and_under",
    "teach30to59": "aged_30_to_59",
    "teach60over": "aged_60_and_over",
    "Maleteach": "male",
    "Femaleteach": "female",
    "FTteach": "full_time",
    "PTteach": "part_time",
}

# Map the school type dimension code to a stable snake_case label
_SCHOOL_TYPE_LABELS = {
    "Nursery": "nursery",
    "Primary": "primary",
    "Preparatory": "preparatory",
    "Secondary": "secondary",
    "Grammar": "grammar",
    "Special": "special",
    "All": "all",
}

NI_GEOGRAPHY = "Northern Ireland"


def _academic_year_start(academic_year: pd.Series) -> pd.Series:
    """Extract the starting calendar year from an academic year label.

    Args:
        academic_year: Series of labels such as ``"2015/16"``.

    Returns:
        Integer series of starting years, e.g. ``2015``.

    Example:
        >>> import pandas as pd
        >>> _academic_year_start(pd.Series(["2015/16", "2022/23"])).tolist()
        [2015, 2022]
    """
    return academic_year.str.slice(0, 4).astype(int)


def _process_headcount() -> pd.DataFrame:
    """Fetch and tidy the teacher headcount matrix.

    Returns:
        DataFrame with columns ``academic_year``, ``year_start``,
        ``geography_code``, ``geography``, ``statistic`` and ``value``.
    """
    df = read_dataset(_MATRIX_HEADCOUNT)
    df = df.rename(
        columns={
            "Academic year": "academic_year",
            "LGD2014": "geography_code",
            "Local Government District": "geography",
            "VALUE": "value",
        }
    )
    df["statistic"] = df["STATISTIC"].map(_STATISTIC_LABELS).fillna(df["STATISTIC"])
    df["year_start"] = _academic_year_start(df["academic_year"])

    result = df[
        [
            "academic_year",
            "year_start",
            "geography_code",
            "geography",
            "statistic",
            "value",
        ]
    ].copy()
    return result.sort_values(["statistic", "year_start", "geography"]).reset_index(drop=True)


def _process_by_school_type(matrix: str, measure: str) -> pd.DataFrame:
    """Fetch and tidy a school-type-dimensioned matrix.

    Args:
        matrix: PxStat matrix code.
        measure: Value stored in the ``measure`` column, e.g. ``"fte"``.

    Returns:
        DataFrame with columns ``academic_year``, ``year_start``,
        ``geography_code``, ``geography``, ``school_type``,
        ``school_type_label``, ``measure`` and ``value``.
    """
    df = read_dataset(matrix)
    df = df.rename(
        columns={
            "Academic year": "academic_year",
            "LGD2014": "geography_code",
            "Local Government District": "geography",
            "School type": "school_type_label",
            "VALUE": "value",
        }
    )
    df["school_type"] = df["TNschooltype"].map(_SCHOOL_TYPE_LABELS).fillna(df["TNschooltype"])
    df["year_start"] = _academic_year_start(df["academic_year"])
    df["measure"] = measure

    result = df[
        [
            "academic_year",
            "year_start",
            "geography_code",
            "geography",
            "school_type",
            "school_type_label",
            "measure",
            "value",
        ]
    ].copy()
    return result.sort_values(["year_start", "geography", "school_type"]).reset_index(drop=True)


def get_headcount(force_refresh: bool = False) -> pd.DataFrame:
    """Return teacher headcount by age band, sex and working pattern.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored —
        the PxStat API is called directly with no local cache layer.

    Args:
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns:

            - ``academic_year``: Academic year label, e.g. ``"2022/23"``
            - ``year_start``: Starting calendar year (int)
            - ``geography_code``: LGD2014 code
            - ``geography``: LGD name, or ``"Northern Ireland"``
            - ``statistic``: One of ``all_teachers``, ``aged_29_and_under``,
              ``aged_30_to_59``, ``aged_60_and_over``, ``male``, ``female``,
              ``full_time``, ``part_time``
            - ``value``: Teacher headcount

    Example:
        >>> df = get_headcount()
        >>> "all_teachers" in set(df["statistic"])
        True
    """
    return _process_headcount()


def get_fte(force_refresh: bool = False) -> pd.DataFrame:
    """Return full-time equivalent teachers by school type.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored.

    Args:
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns ``academic_year``, ``year_start``,
        ``geography_code``, ``geography``, ``school_type``,
        ``school_type_label``, ``measure`` and ``value``.

    Example:
        >>> df = get_fte()
        >>> set(df["measure"]) == {"fte"}
        True
    """
    return _process_by_school_type(_MATRIX_FTE, "fte")


def get_pupil_teacher_ratios(force_refresh: bool = False) -> pd.DataFrame:
    """Return pupil:teacher ratios by school type.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored.

    Args:
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns ``academic_year``, ``year_start``,
        ``geography_code``, ``geography``, ``school_type``,
        ``school_type_label``, ``measure`` and ``value``.

    Example:
        >>> df = get_pupil_teacher_ratios()
        >>> set(df["measure"]) == {"ptr"}
        True
    """
    return _process_by_school_type(_MATRIX_PTR, "ptr")


def get_latest_data(
    dimension: DimensionType = "all",
    force_refresh: bool = False,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """Download and return the latest teacher workforce data.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored —
        the PxStat API always returns current data.

    Args:
        dimension: Which view to return.  One of:

            - ``"headcount"`` — teachers by age band, sex, working pattern
            - ``"fte"`` — full-time equivalent teachers by school type
            - ``"ptr"`` — pupil:teacher ratios by school type
            - ``"all"`` — dict containing all three (default)

        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        A single DataFrame, or for ``"all"`` a dict keyed by
        ``"headcount"``, ``"fte"`` and ``"ptr"``.

    Raises:
        ValueError: If ``dimension`` is not a supported value.

    Example:
        >>> data = get_latest_data("all")
        >>> sorted(data.keys())
        ['fte', 'headcount', 'ptr']
    """
    valid = ("headcount", "fte", "ptr", "all")
    if dimension not in valid:
        raise ValueError(f"dimension must be one of {valid}, got {dimension!r}")

    if dimension == "headcount":
        return get_headcount()
    if dimension == "fte":
        return get_fte()
    if dimension == "ptr":
        return get_pupil_teacher_ratios()

    return {
        "headcount": get_headcount(),
        "fte": get_fte(),
        "ptr": get_pupil_teacher_ratios(),
    }


def get_ni_summary() -> pd.DataFrame:
    """Return the Northern Ireland headline series across all three views.

    Combines the NI-wide totals from each matrix into a single long frame,
    giving a compact overview of how the teaching workforce has changed.

    Returns:
        DataFrame with columns ``academic_year``, ``year_start``, ``measure``,
        ``category`` and ``value``, where ``measure`` is one of
        ``headcount``, ``fte`` or ``ptr``.

    Example:
        >>> df = get_ni_summary()
        >>> sorted(df["measure"].unique())
        ['fte', 'headcount', 'ptr']
    """
    head = get_headcount()
    head = head[head["geography"] == NI_GEOGRAPHY].copy()
    head["measure"] = "headcount"
    head = head.rename(columns={"statistic": "category"})

    frames = [head[["academic_year", "year_start", "measure", "category", "value"]]]

    for df in (get_fte(), get_pupil_teacher_ratios()):
        sub = df[df["geography"] == NI_GEOGRAPHY].copy()
        sub = sub.rename(columns={"school_type": "category"})
        frames.append(sub[["academic_year", "year_start", "measure", "category", "value"]])

    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(["measure", "year_start", "category"]).reset_index(drop=True)


def list_statistics() -> list[str]:
    """List the headcount statistic labels available.

    Returns:
        Sorted list of statistic labels.

    Example:
        >>> "all_teachers" in list_statistics()
        True
    """
    return sorted(_STATISTIC_LABELS.values())


def list_school_types() -> list[str]:
    """List the school type labels used by the FTE and PTR views.

    Returns:
        Sorted list of school type labels.

    Example:
        >>> "grammar" in list_school_types()
        True
    """
    return sorted(_SCHOOL_TYPE_LABELS.values())


def validate_data(df: pd.DataFrame, min_years: int = 5) -> bool:
    """Validate a parsed teacher workforce DataFrame.

    Args:
        df: DataFrame from any of the accessor functions.
        min_years: Minimum number of distinct academic years required.

    Returns:
        True if validation passes, False otherwise.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        False
    """
    if df is None or df.empty:
        logger.warning("Teacher workforce data is empty")
        return False

    required_cols = {"academic_year", "year_start", "geography", "value"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        logger.warning("Missing required columns: %s", missing)
        return False

    non_null_values = df["value"].dropna()
    if len(non_null_values) > 0 and (non_null_values < 0).any():
        logger.warning("Found negative values in teacher workforce data")
        return False

    if df["academic_year"].nunique() < min_years:
        logger.warning("Too few academic years of data: %d", df["academic_year"].nunique())
        return False

    return True
