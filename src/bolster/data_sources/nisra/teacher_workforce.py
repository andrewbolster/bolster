"""NISRA Teacher Workforce Data Source.

Provides access to teacher workforce statistics for grant-aided schools in
Northern Ireland via the NISRA PxStat API, broken down by Local Government
District, school type, gender, contract type and age band.

The Department of Education collects this data each October as part of the
school census.  Headcount counts every teacher in post; full-time equivalent
(FTE) weights part-time teachers by the fraction of a full timetable they
work, so FTE is always at or below headcount.

Original data source:
    https://www.education-ni.gov.uk/articles/education-workforce

PxStat matrices used:
    - DETNLGD    — teacher headcount by LGD, gender, contract type and age band
    - DETNFTELGD — full-time equivalent teachers by LGD and school type
    - DETNPTRLGD — pupil:teacher ratios by LGD and school type

Update Frequency: Annual (academic year)
Geographic Coverage: Northern Ireland

Note:
    The Department publishes its own bulletins as PDF infographics only from
    2021/22 onwards, so PxStat is the sole machine-readable source and its
    coverage ends at the last year the underlying tables were released.

Example:
    >>> from bolster.data_sources.nisra import teacher_workforce
    >>> df = teacher_workforce.get_teacher_counts()
    >>> "all_teachers" in df.columns
    True

    >>> ni = df[df["geography"] == "Northern Ireland"]
    >>> bool((ni["all_teachers"] > 15000).all())
    True
"""

import logging

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

logger = logging.getLogger(__name__)

_MATRIX_HEADCOUNT = "DETNLGD"
_MATRIX_FTE = "DETNFTELGD"
_MATRIX_RATIO = "DETNPTRLGD"

_GEO_CODE_COL = "LGD2014"
_GEO_NAME_COL = "Local Government District"

#: Maps PxStat ``STATISTIC`` codes to the column names this module exposes.
HEADCOUNT_MEASURES = {
    "Allteach": "all_teachers",
    "Femaleteach": "female_teachers",
    "Maleteach": "male_teachers",
    "FTteach": "full_time_teachers",
    "PTteach": "part_time_teachers",
    "teach29under": "teachers_under_30",
    "teach30to59": "teachers_30_to_59",
    "teach60over": "teachers_60_and_over",
}

#: School types reported for FTE and pupil:teacher ratio breakdowns.
SCHOOL_TYPES = (
    "All schools",
    "Nursery",
    "Primary",
    "Preparatory departments of grammar schools",
    "Secondary (excluding grammar)",
    "Grammar",
    "Special",
)

#: Label used for the Northern Ireland aggregate row.
NI_TOTAL = "Northern Ireland"


class TeacherWorkforceValidationError(Exception):
    """Raised when teacher workforce data fails validation."""


def _rename_geography(df: pd.DataFrame) -> pd.DataFrame:
    """Give the PxStat geography columns this module's names."""
    return df.rename(
        columns={
            _GEO_CODE_COL: "geography_code",
            _GEO_NAME_COL: "geography",
            "Academic year": "academic_year",
        }
    )


def get_teacher_counts(force_refresh: bool = False) -> pd.DataFrame:
    """Get teacher headcount by district, gender, contract type and age band.

    Each row is one district in one academic year, with every published
    measure as its own column.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored —
        the PxStat API is called directly with no local cache layer.

    Args:
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns:
            - ``academic_year``: Academic year (e.g. ``"2022/23"``)
            - ``geography_code``: LGD2014 code, or blank for the NI total
            - ``geography``: District name, or ``"Northern Ireland"``
            - ``all_teachers``: Total teachers in post
            - ``female_teachers``, ``male_teachers``: Gender split
            - ``full_time_teachers``, ``part_time_teachers``: Contract split
            - ``teachers_under_30``, ``teachers_30_to_59``,
              ``teachers_60_and_over``: Age band split

    Example:
        >>> df = get_teacher_counts()
        >>> bool((df["female_teachers"] + df["male_teachers"] == df["all_teachers"]).all())
        True
    """
    df = _rename_geography(read_dataset(_MATRIX_HEADCOUNT))

    wide = df.pivot_table(
        index=["academic_year", "geography_code", "geography"],
        columns="STATISTIC",
        values="VALUE",
    ).reset_index()
    wide.columns.name = None

    wide = wide.rename(columns=HEADCOUNT_MEASURES)
    ordered = ["academic_year", "geography_code", "geography", *HEADCOUNT_MEASURES.values()]
    wide = wide[[column for column in ordered if column in wide.columns]]

    for column in HEADCOUNT_MEASURES.values():
        if column in wide.columns:
            wide[column] = wide[column].astype("Int64")

    return wide.sort_values(["academic_year", "geography"]).reset_index(drop=True)


def _get_by_school_type(matrix: str, value_column: str, school_type: str | None) -> pd.DataFrame:
    """Shape a school-type-dimensioned matrix and optionally filter it."""
    if school_type is not None and school_type not in SCHOOL_TYPES:
        raise ValueError(f"school_type must be one of {SCHOOL_TYPES}, got {school_type!r}")

    df = _rename_geography(read_dataset(matrix))
    df = df.rename(columns={"School type": "school_type", "VALUE": value_column})
    df = df[["academic_year", "geography_code", "geography", "school_type", value_column]]

    if school_type is not None:
        df = df[df["school_type"] == school_type]

    return df.sort_values(["academic_year", "geography", "school_type"]).reset_index(drop=True)


def get_fte_teachers(school_type: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get full-time equivalent teacher numbers by district and school type.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored.

    Args:
        school_type: Restrict to one entry from :data:`SCHOOL_TYPES`.  When
            omitted every school type is returned, including the
            ``"All schools"`` aggregate.
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns ``academic_year``, ``geography_code``,
        ``geography``, ``school_type`` and ``fte_teachers``.

    Raises:
        ValueError: If ``school_type`` is not a published school type.

    Example:
        >>> df = get_fte_teachers("Primary")
        >>> sorted(df["school_type"].unique())
        ['Primary']
    """
    return _get_by_school_type(_MATRIX_FTE, "fte_teachers", school_type)


def get_pupil_teacher_ratios(school_type: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get pupil:teacher ratios by district and school type.

    A ratio of zero means the district had no schools of that type in that
    year rather than a genuine ratio of zero.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored.

    Args:
        school_type: Restrict to one entry from :data:`SCHOOL_TYPES`.
        force_refresh: Ignored.  Retained for API compatibility.

    Returns:
        DataFrame with columns ``academic_year``, ``geography_code``,
        ``geography``, ``school_type`` and ``pupil_teacher_ratio``.

    Raises:
        ValueError: If ``school_type`` is not a published school type.

    Example:
        >>> df = get_pupil_teacher_ratios()
        >>> bool(df["pupil_teacher_ratio"].max() < 50)
        True
    """
    return _get_by_school_type(_MATRIX_RATIO, "pupil_teacher_ratio", school_type)


def validate_teacher_workforce_data(df: pd.DataFrame) -> bool:
    """Validate a teacher headcount DataFrame for basic integrity.

    Args:
        df: DataFrame from :func:`get_teacher_counts`.

    Returns:
        True if validation passes.

    Raises:
        TeacherWorkforceValidationError: If validation fails.

    Example:
        >>> import pandas as pd
        >>> validate_teacher_workforce_data(pd.DataFrame(columns=["academic_year", "geography", "all_teachers"]))
        Traceback (most recent call last):
            ...
        bolster.data_sources.nisra.teacher_workforce.TeacherWorkforceValidationError: DataFrame is empty
    """
    required = {"academic_year", "geography", "all_teachers"}
    missing = required - set(df.columns)
    if missing:
        raise TeacherWorkforceValidationError(f"Missing required columns: {sorted(missing)}")

    if df.empty:
        raise TeacherWorkforceValidationError("DataFrame is empty")

    counts = df[[column for column in HEADCOUNT_MEASURES.values() if column in df.columns]]
    if (counts.fillna(0) < 0).to_numpy().any():
        raise TeacherWorkforceValidationError("Negative teacher counts found")

    if {"female_teachers", "male_teachers"} <= set(df.columns):
        gendered = df["female_teachers"] + df["male_teachers"]
        if not gendered.equals(df["all_teachers"]):
            raise TeacherWorkforceValidationError("Gender breakdown does not sum to all teachers")

    ni = df[df["geography"] == NI_TOTAL]
    if not ni.empty and (ni["all_teachers"] > 50000).any():
        raise TeacherWorkforceValidationError(f"NI teacher headcount implausibly high: {ni['all_teachers'].max()}")

    return True


def get_workforce_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Summarise the Northern Ireland headcount trend and workforce mix.

    Args:
        df: DataFrame from :func:`get_teacher_counts`.

    Returns:
        DataFrame with one row per academic year and columns
        ``academic_year``, ``all_teachers``, ``yoy_change``,
        ``yoy_pct_change``, ``female_pct`` and ``part_time_pct``.

    Example:
        >>> summary = get_workforce_summary(get_teacher_counts())
        >>> "female_pct" in summary.columns
        True
    """
    ni = df[df["geography"] == NI_TOTAL].sort_values("academic_year").reset_index(drop=True)

    summary = ni[["academic_year", "all_teachers"]].copy()
    summary["yoy_change"] = summary["all_teachers"].diff().astype("Int64")
    summary["yoy_pct_change"] = summary["all_teachers"].pct_change().mul(100).round(1)
    summary["female_pct"] = (ni["female_teachers"] / ni["all_teachers"] * 100).round(1)
    summary["part_time_pct"] = (ni["part_time_teachers"] / ni["all_teachers"] * 100).round(1)

    return summary
