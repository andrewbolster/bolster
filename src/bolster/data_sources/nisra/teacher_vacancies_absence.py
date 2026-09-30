"""Teacher Vacancies, Sickness Absence and Substitution Costs (NI).

Annual Department of Education (DE) statistics on teacher vacancies, days lost to
sickness, and the cost of substitute cover in grant-aided schools. Published as an
interactive NISRA "datavis" report alongside the teacher workforce bulletin; each
figure and table embeds its data as a real ``.xlsx`` file, which this module reads
(see :mod:`bolster.utils.embedded_downloads`).

Data covers:
    - Filled and unfilled vacancies by school type, and by grade of teacher (November collection)
    - Average days lost to sickness per teacher, by school type and over time, and by spell length
    - Substitution cover costs over time, as a proportion of teaching days, and the share
      provided by prematurely retired teachers

Distinct from :mod:`bolster.data_sources.nisra.teacher_workforce`, which counts teachers
and pupil:teacher ratios via PxStat.

Update Frequency: Annual (autumn)
Geographic Coverage: Northern Ireland (grant-aided schools)

Data Source:
    **Publication**: https://www.education-ni.gov.uk/publications/teacher-workforce-statistics-202526

    The publication page for each school year links to the datavis report; the report URL is
    discovered from it, walking back through school years until one is found.

Example:
    >>> from bolster.data_sources.nisra import teacher_vacancies_absence
    >>> df = teacher_vacancies_absence.get_vacancies_by_school_type()  # doctest: +SKIP
    >>> "All" in set(df["school_type"])  # doctest: +SKIP
    True
"""

import logging
import re

import pandas as pd

from bolster.utils.embedded_downloads import EmbeddedTable, clean_labels, coerce_numeric, read_tables
from bolster.utils.web import LinkNotFoundError, find_academic_year_publication_link, is_url_host, session

from ._base import NISRADataNotFoundError, NISRAValidationError

logger = logging.getLogger(__name__)

_PUBLICATION_URL = "https://www.education-ni.gov.uk/publications/teacher-workforce-statistics-{slug}"
_LINK_TEXT = "vacancy, sickness absence and substitution"
_YEAR_RANGE_RE = re.compile(r"\d{2,4}(?:/\d{2})?\s*-\s*\d{2,4}")
_ACADEMIC_YEAR_RE = re.compile(r"\b(\d{4})/(\d{2})\b")
_HISTORY_COLUMN_RE = re.compile(r"^(pct_filled|filled|unfilled)_(\d{4})$")


def get_latest_publication_url(force_refresh: bool = False) -> str:
    """Find the latest teacher vacancy, sickness absence and substitution report page.

    Walks school-year publication pages from the current year backwards until one links to the report.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        URL of the datavis report (e.g. ``https://datavis.nisra.gov.uk/DEstatistics/...``).

    Raises:
        NISRADataNotFoundError: If no recent publication page links to the report.
    """
    try:
        return find_academic_year_publication_link(
            _PUBLICATION_URL,
            lambda text, href: is_url_host(href, "datavis.nisra.gov.uk") and _LINK_TEXT in text.lower(),
            force_refresh=force_refresh,
        )
    except LinkNotFoundError as exc:
        raise NISRADataNotFoundError(
            "Could not find a teacher vacancy, sickness absence and substitution report"
        ) from exc


def get_tables(force_refresh: bool = False) -> dict[str, EmbeddedTable]:
    """Read every figure and table embedded in the latest report.

    ``Figure 1``-``Figure 7`` are the headline series (exposed by the ``get_*`` functions below);
    ``Table 1``-``Table 13b`` are the fuller statistical tables, including substitution costs by
    management and school type, which are returned here with cleaned column names but otherwise as published.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Mapping of label (``"Figure 1"``, ``"Table 13a"`` ...) to the raw table, in page order.

    Raises:
        NISRADataNotFoundError: If the report cannot be found or embeds no data files.
    """
    url = get_latest_publication_url(force_refresh=force_refresh)
    tables = read_tables(session.get(url, timeout=90, force_refresh=force_refresh).text)
    if not tables:
        raise NISRADataNotFoundError(f"No embedded data files found on {url}")
    logger.info("Read %d embedded tables from %s", len(tables), url)
    return tables


def _find_table(
    tables: dict[str, EmbeddedTable], *keywords: str, kind: str, ranged: bool | None = None
) -> EmbeddedTable:
    """Find the ``kind`` ("Figure"/"Table") whose title has every keyword.

    ``ranged`` selects between a single-year title (``False``) and a multi-year one (``True``).
    Titles are matched, not labels, so a reordered report cannot silently return the wrong table.
    """
    for table in tables.values():
        title = table.title.lower()
        if not table.label.startswith(kind) or not all(word in title for word in keywords):
            continue
        if ranged is None or bool(_YEAR_RANGE_RE.search(title)) == ranged:
            return table
    raise NISRADataNotFoundError(f"No {kind} with a title containing {keywords} (ranged={ranged}) in the report")


def _academic_year(title: str) -> str:
    match = _ACADEMIC_YEAR_RE.search(title)
    if not match:
        raise NISRAValidationError(f"No academic year (e.g. 2024/25) in title: {title!r}")
    return match.group(0)


def _collection_year(title: str) -> int:
    match = re.search(r"\b((?:19|20)\d{2})\b", title)
    if not match:
        raise NISRAValidationError(f"No year in title: {title!r}")
    return int(match.group(1))


def _numeric(df: pd.DataFrame, exclude: tuple[str, ...] = ()) -> pd.DataFrame:
    """Coerce every column except ``exclude`` to numbers."""
    for column in df.columns:
        if column not in exclude:
            df[column] = coerce_numeric(df[column])
    return df


def get_vacancies_by_school_type(force_refresh: bool = False) -> pd.DataFrame:
    """Filled and unfilled teacher vacancies by school type for the November collection.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``school_type``, ``filled``, ``unfilled``, ``total`` (positions) and ``year``.
        Includes an ``All`` row.
    """
    table = _find_table(get_tables(force_refresh), "vacancies by school type", kind="Figure")
    df = table.data.copy()
    df["school_type"] = clean_labels(df["school_type"])
    df = _numeric(df, exclude=("school_type",))
    df["year"] = _collection_year(table.title)
    validate_data(df)
    return df


def get_vacancies_by_grade(force_refresh: bool = False) -> pd.DataFrame:
    """Permanent and temporary vacancies by school type and grade of teacher for the latest year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``school_type``, ``grade_of_teacher``, the ``permanent_positions_*`` and
        ``temporary_positions_*`` columns (filled, unfilled, ``pct_*_filled``) and ``year``.
    """
    table = _find_table(get_tables(force_refresh), "vacancies in grant-aided schools", kind="Table", ranged=False)
    df = table.data.copy()
    df["school_type"] = clean_labels(df["school_type"].ffill())
    df["grade_of_teacher"] = clean_labels(df["grade_of_teacher"])
    df = _numeric(df, exclude=("school_type", "grade_of_teacher"))
    df["year"] = _collection_year(table.title)
    return df


def get_vacancies_history_by_grade(force_refresh: bool = False) -> pd.DataFrame:
    """Filled and unfilled teacher positions (permanent and temporary combined) by school type, grade and year.

    Matches the ``all_positions_*`` columns of :func:`get_vacancies_by_grade` for the latest year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``school_type``, ``grade_of_teacher``, ``year`` (int), ``filled``, ``unfilled`` and
        ``pct_filled``, one row per school type, grade and year.
    """
    table = _find_table(get_tables(force_refresh), "vacancies in grant-aided schools", kind="Table", ranged=True)
    wide = table.data.copy()
    wide["school_type"] = clean_labels(wide["school_type"].ffill())
    wide["grade_of_teacher"] = clean_labels(wide["grade_of_teacher"])
    measures = {col: _HISTORY_COLUMN_RE.match(col) for col in wide.columns}
    measure_columns = [col for col, match in measures.items() if match]
    if not measure_columns:
        raise NISRAValidationError(f"No filled/unfilled/pct_filled_YYYY columns in {list(wide.columns)}")
    long = wide.melt(
        id_vars=["school_type", "grade_of_teacher"], value_vars=measure_columns, var_name="measure", value_name="value"
    )
    long["year"] = long["measure"].map(lambda col: int(measures[col].group(2)))  # type: ignore[union-attr]
    long["measure"] = long["measure"].map(lambda col: measures[col].group(1))  # type: ignore[union-attr]
    long["value"] = coerce_numeric(long["value"])
    tidy = long.pivot_table(
        index=["school_type", "grade_of_teacher", "year"], columns="measure", values="value", aggfunc="first"
    )
    tidy = tidy.reset_index()
    tidy.columns.name = None
    return tidy[["school_type", "grade_of_teacher", "year", "filled", "unfilled", "pct_filled"]]


def get_sickness_absence_by_school_type(force_refresh: bool = False) -> pd.DataFrame:
    """Average working days lost to sickness per teacher, by school type, for the latest year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``school_type``, ``avg_days_lost`` and ``academic_year`` (e.g. ``"2024/25"``).
    """
    table = _find_table(get_tables(force_refresh), "days lost due to sickness per teacher", kind="Figure", ranged=False)
    df = table.data.copy()
    df.columns = ["school_type", "avg_days_lost"]
    df["school_type"] = clean_labels(df["school_type"])
    df["avg_days_lost"] = coerce_numeric(df["avg_days_lost"])
    df["academic_year"] = _academic_year(table.title)
    return df


def get_sickness_absence_trend(force_refresh: bool = False) -> pd.DataFrame:
    """Average working days lost to sickness per teacher, by academic year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``academic_year`` (e.g. ``"2020/21"``) and ``avg_days_lost``.
    """
    table = _find_table(get_tables(force_refresh), "days lost due to sickness per teacher", kind="Figure", ranged=True)
    df = table.data.copy()
    df.columns = ["academic_year", "avg_days_lost"]
    df["avg_days_lost"] = coerce_numeric(df["avg_days_lost"])
    return df


def get_sickness_absence_by_duration(force_refresh: bool = False) -> pd.DataFrame:
    """Share of sickness days lost, by length of spell, by academic year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``academic_year`` and ``pct_5_days_or_less``, ``pct_6_to_20_days``,
        ``pct_20_days_or_more`` (percentages summing to about 100).
    """
    table = _find_table(get_tables(force_refresh), "sickness by duration", kind="Figure")
    df = table.data.copy()
    df.columns = ["academic_year", "pct_5_days_or_less", "pct_6_to_20_days", "pct_20_days_or_more"]
    return _numeric(df, exclude=("academic_year",))


def get_substitution_costs(force_refresh: bool = False) -> pd.DataFrame:
    """Total cost of teacher substitute cover, by academic year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``academic_year`` and ``total_cost`` (pounds).
    """
    table = _find_table(get_tables(force_refresh), "costs in northern ireland", kind="Figure")
    df = table.data.copy()
    df.columns = ["academic_year", "total_cost"]
    df["total_cost"] = coerce_numeric(df["total_cost"])
    return df


def get_substitution_days_proportion(force_refresh: bool = False) -> pd.DataFrame:
    """Substitution days as a percentage of total teaching days, by academic year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``academic_year`` and ``pct_of_teaching_days``.
    """
    table = _find_table(get_tables(force_refresh), "proportion of total teaching days", kind="Figure")
    df = table.data.copy()
    df.columns = ["academic_year", "pct_of_teaching_days"]
    df["pct_of_teaching_days"] = coerce_numeric(df["pct_of_teaching_days"])
    return df


def get_retired_teacher_cover_proportion(force_refresh: bool = False) -> pd.DataFrame:
    """Share of substitute cover provided by prematurely retired teachers, by academic year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``academic_year`` and ``pct_of_cover``.
    """
    table = _find_table(get_tables(force_refresh), "prematurely retired", kind="Figure")
    df = table.data.copy()
    df.columns = ["academic_year", "pct_of_cover"]
    df["pct_of_cover"] = coerce_numeric(df["pct_of_cover"])
    return df


def validate_data(df: pd.DataFrame) -> bool:
    """Validate the :func:`get_vacancies_by_school_type` table.

    Args:
        df: Output of :func:`get_vacancies_by_school_type`.

    Returns:
        ``True`` if valid.

    Raises:
        NISRAValidationError: If columns are missing, there is no ``All`` row, counts are negative or missing,
            filled plus unfilled does not equal the total, or the ``All`` row is not the sum of the school types.
    """
    required = {"school_type", "filled", "unfilled", "total", "year"}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing expected columns: {sorted(missing)}")
    if "All" not in set(df["school_type"]):
        raise NISRAValidationError("No 'All' row")
    counts = df[["filled", "unfilled", "total"]]
    if counts.isna().any().any() or (counts < 0).any().any():
        raise NISRAValidationError("Vacancy counts must be present and non-negative")
    if not (df["filled"] + df["unfilled"] == df["total"]).all():
        raise NISRAValidationError("filled + unfilled does not equal total")
    parts = df[df["school_type"] != "All"]
    if len(parts) and parts["total"].sum() != df.loc[df["school_type"] == "All", "total"].iloc[0]:
        raise NISRAValidationError("School types do not sum to the 'All' total")
    return True
