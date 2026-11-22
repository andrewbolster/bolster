"""Northern Ireland General Dental Services (GDS) statistics.

Published as: General Dental Services Statistics.

NHS dental care in Northern Ireland as paid for by the Business Services
Organisation (BSO) Family Practitioner Services (FPS): patient registrations,
treatments (fillings, extractions, crowns and X-rays), and the dental practices
and dentists that provide them. Published jointly with the Department of Health
and NISRA on GOV.UK, by the same publisher and in the same layout as
:mod:`~bolster.data_sources.health_ni.ophthalmic_services`.

Two series are covered:

- **Quarterly** (the newest tables workbook carries the whole history): registrations
  and treatments by gender and age group, by Health Trust (BSO's "Local Commissioning
  Group") and by Local Government District, and registrations also by Assembly Area,
  from Q1 2017/18; dental practices and dentists by Trust, LGD and Assembly Area from
  Q1 2020/21. The cover sheet marks the whole quarterly series provisional.
- **Annual** (PxStat ``FPSGDSDR*``, ``FPSGDSDT*`` and ``FPSGDSDS*``): registrations by
  age band, treatments, and dentists and surgeries by financial year, by Trust, LGD,
  Assembly Area and District Electoral Area.

Definitions that change how the numbers can be read (from the PxStat notes):

- **Registrations** are counted in the year the registration was *paid*. The registration
  period was 15 months until August 2009 and has been 24 months since, which raised
  registration rates; registrations due to expire in 2020/21 to 2022/23 were extended
  because of Covid-19.
- **Treatments** are counted in the year the claim was *paid*, not necessarily when the
  treatment took place. A filling or extraction is one tooth per visit.
- **Dentists (annual)** are those on the dental list at 31 March, and a dentist working in
  several locations is *proportioned across them*, so annual counts are fractional. They are
  not the same measure as the quarterly "Headcount of Dentists", and the two should not be
  reconciled.

Note:
    Not every claim is placed in an area, so the Northern Ireland row exceeds the sum of its
    areas. Every geography frame has ``is_total`` marking the Northern Ireland row, so summing a
    column never double counts; use :func:`get_annual_unallocated` for the gap. Trust-level labels
    are BSO's "Local Commissioning Group (Health Trust)", called ``trust`` here for
    join-compatibility with the other ``health_ni`` modules.

Data Source:
    BSO/FPS publishes through GOV.UK. The newest quarterly publication is discovered at runtime
    through the GOV.UK Search and Content APIs, so a new release (and its new file-hosting asset
    hash) needs no code change. Tables are found by *title*, never by number.

Update Frequency: Quarterly, with an annual edition each summer
Geographic Coverage: Northern Ireland (Trust, Local Government District, Assembly Area; annual
    also District Electoral Area)
Reference Period: Financial quarters from Q1 2017/18; annual 2013/14 - present

Example:
    >>> from bolster.data_sources.health_ni import dental_services
    >>> df = dental_services.get_quarterly_treatments("fillings", "trust")  # doctest: +SKIP
    >>> df[df.is_total].tail(1).value.iloc[0] > 100_000  # doctest: +SKIP
    True
"""

import logging

import pandas as pd

from ._base import (
    download_file,
    find_govuk_xlsx_attachment,
    find_latest_govuk_publication,
)
from ._fps import (
    parse_quarterly_workbook,
    quarterly_series,
    read_annual_cube,
    unallocated,
    validate_series,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MEASURES",
    "find_latest_quarterly_url",
    "get_annual_dentists_and_surgeries",
    "get_annual_registrations",
    "get_annual_treatments",
    "get_annual_unallocated",
    "get_latest_quarterly_data",
    "get_quarterly_dentists",
    "get_quarterly_practices",
    "get_quarterly_registrations",
    "get_quarterly_table",
    "get_quarterly_treatments",
    "validate_data",
]

_QUARTERLY_QUERY = "general dental services statistics ni quarter"
_QUARTERLY_PREFIX = "/government/statistics/general-dental-services-statistics-for-ni-quarter"
_CACHE_TTL_HOURS = 24 * 7

_ANNUAL_CUBES = {
    "registrations": "FPSGDSDR",
    "treatments": "FPSGDSDT",
    "dentists_and_surgeries": "FPSGDSDS",
}

# Quarterly treatment measure -> the table's descriptive title ("Number of Fillings by Gender, ...").
MEASURES = {
    "fillings": r"(?:Number of )?Fillings\b",
    "extractions": r"(?:Number of )?Extractions\b",
    "x_rays": r"(?:Number of )?X-Rays\b",
    "crowns": r"(?:Number of )?Crowns\b",
}

_REGISTRATIONS_TITLE = r"(?:Number of )?Patient Registrations\b"
_PRACTICES_TITLE = r"Number of Dental Practices\b"
_DENTISTS_TITLE = r"Headcount of Dentists\b"

_TREATMENT_LEVELS = ("trust", "lgd", "age_sex")
_REGISTRATION_LEVELS = ("trust", "lgd", "assembly_area", "age_sex")
_STAFFING_LEVELS = ("trust", "lgd", "assembly_area")


def find_latest_quarterly_url() -> str:
    """Find the URL of the most recent quarterly GDS tables workbook.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        NISRADataNotFoundError: If no quarterly publication, or no tables workbook on the newest
            one, is found. An older quarter is never substituted.

    Example:
        >>> find_latest_quarterly_url().endswith(".xlsx")  # doctest: +SKIP
        True
    """
    content = find_latest_govuk_publication(_QUARTERLY_QUERY, _QUARTERLY_PREFIX, label="General Dental Services")
    return find_govuk_xlsx_attachment(content, ("Tables",))


def get_latest_quarterly_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the newest quarterly GDS tables workbook.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        Long frame of every data sheet: ``sheet``, ``sheet_title``, ``table_id``, ``table_title``,
        ``row_group``, ``row_label``, ``column``, ``value``, ``financial_year``, ``quarter``,
        ``period`` and ``provisional``. The monthly payment tables have no quarter columns.
        See :func:`~bolster.data_sources.health_ni._fps.parse_quarterly_workbook`.

    Raises:
        NISRADataNotFoundError: If the newest workbook cannot be found or holds no tables.
    """
    path = download_file(find_latest_quarterly_url(), cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    return parse_quarterly_workbook(pd.ExcelFile(path, engine="openpyxl"))


def get_quarterly_table(title_pattern: str, level: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return any quarterly table found by its title.

    Args:
        title_pattern: Regex matched from the start of the table's descriptive title, without the
            ``Table N.M:`` prefix.
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"``, ``"age_sex"`` or ``None``.
        force_refresh: Bypass the download cache.

    Returns:
        See :func:`~bolster.data_sources.health_ni._fps.quarterly_series`.

    Raises:
        NISRADataNotFoundError: If no table matches.
    """
    return quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=title_pattern, level=level)


def get_quarterly_registrations(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get quarterly NHS dental patient registrations.

    Args:
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"age_sex"`` (by gender and age group).
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period`` (quarter end), ``financial_year``, ``quarter``, the geography column
        named after ``level`` (or ``sex`` and ``age_group``), ``value``, ``is_total`` and ``provisional``.

    Raises:
        ValueError: If ``level`` is not recognised.
        NISRADataNotFoundError: If the workbook has no matching table.
    """
    if level not in _REGISTRATION_LEVELS:
        raise ValueError(f"Unknown level {level!r}; choose from {list(_REGISTRATION_LEVELS)}")
    return quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=_REGISTRATIONS_TITLE, level=level)


def get_quarterly_treatments(
    measure: str = "fillings", level: str = "trust", force_refresh: bool = False
) -> pd.DataFrame:
    """Get quarterly fillings, extractions, X-rays or crowns.

    Args:
        measure: One of :data:`MEASURES`.
        level: ``"trust"``, ``"lgd"`` or ``"age_sex"`` (by gender and age group).
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``measure``, ``period``, ``financial_year``, ``quarter``, the geography column
        (or ``sex`` and ``age_group``), ``value``, ``is_total`` and ``provisional``. A ``trust``/``lgd``
        frame includes the Northern Ireland row and an ``Unknown`` area.

    Raises:
        ValueError: If ``measure`` or ``level`` is not recognised.
        NISRADataNotFoundError: If the workbook has no matching table.

    Example:
        >>> df = get_quarterly_treatments("fillings", "lgd")  # doctest: +SKIP
        >>> "Belfast" in set(df.lgd)  # doctest: +SKIP
        True
    """
    if measure not in MEASURES:
        raise ValueError(f"Unknown measure {measure!r}; choose from {sorted(MEASURES)}")
    if level not in _TREATMENT_LEVELS:
        raise ValueError(f"Unknown level {level!r}; choose from {list(_TREATMENT_LEVELS)}")
    out = quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=MEASURES[measure], level=level)
    out.insert(0, "measure", measure)
    return out


def get_quarterly_practices(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get the quarterly count of dental practices by geography.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"assembly_area"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``financial_year``, ``quarter``, the geography column, ``value``
        (practices), ``is_total`` and ``provisional``.

    Raises:
        ValueError: If ``level`` is not recognised.
        NISRADataNotFoundError: If the workbook has no matching table.
    """
    if level not in _STAFFING_LEVELS:
        raise ValueError(f"Unknown level {level!r}; choose from {list(_STAFFING_LEVELS)}")
    return quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=_PRACTICES_TITLE, level=level)


def get_quarterly_dentists(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get the quarterly headcount of dentists by geography.

    This is a headcount. The annual PxStat dentist figures are a different measure (proportioned across
    locations), see :func:`get_annual_dentists_and_surgeries`.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"assembly_area"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``financial_year``, ``quarter``, the geography column, ``value``
        (dentists), ``is_total`` and ``provisional``.

    Raises:
        ValueError: If ``level`` is not recognised.
        NISRADataNotFoundError: If the workbook has no matching table.
    """
    if level not in _STAFFING_LEVELS:
        raise ValueError(f"Unknown level {level!r}; choose from {list(_STAFFING_LEVELS)}")
    return quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=_DENTISTS_TITLE, level=level)


def get_annual_registrations(level: str = "trust") -> pd.DataFrame:
    """Get annual NHS dental registrations by age band from PxStat.

    Args:
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame with ``financial_year``, ``period`` (31 March), ``area_code``, the geography column,
        ``measure``, ``age_group`` (``Age 0 to 2``, ``Age 3 to 5``, ``Age 6 to 17``, ``Age 18+`` and
        ``All Registrations``), ``value`` and ``is_total``. The age bands add up to ``All Registrations``.

    Raises:
        ValueError: If ``level`` is not recognised.
    """
    return read_annual_cube(_ANNUAL_CUBES["registrations"], level)


def get_annual_treatments(level: str = "trust") -> pd.DataFrame:
    """Get annual fillings, extractions, crowns and X-rays from PxStat.

    Args:
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame with ``financial_year``, ``period``, ``area_code``, the geography column, ``measure``
        (``Fillings``, ``Extractions``, ``Crowns``, ``XRays``), ``value`` and ``is_total``.

    Raises:
        ValueError: If ``level`` is not recognised.
    """
    return read_annual_cube(_ANNUAL_CUBES["treatments"], level)


def get_annual_dentists_and_surgeries(level: str = "trust") -> pd.DataFrame:
    """Get annual dentists and dental surgeries from PxStat.

    ``Dentists`` are those on the dental list at 31 March, with a dentist who works in several
    locations proportioned across them, so the values are fractional.

    Args:
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame with ``financial_year``, ``period``, ``area_code``, the geography column, ``measure``
        (``Dentists``, ``Dental surgeries``), ``value`` and ``is_total``.

    Raises:
        ValueError: If ``level`` is not recognised.
    """
    return read_annual_cube(_ANNUAL_CUBES["dentists_and_surgeries"], level)


def get_annual_unallocated(series: str = "treatments", level: str = "trust") -> pd.DataFrame:
    """Get annual activity that is in the Northern Ireland total but in no area.

    Args:
        series: ``"treatments"``, ``"registrations"`` or ``"dentists_and_surgeries"``.
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame per ``financial_year`` and ``measure`` (and ``age_group`` for registrations) with
        ``total`` (the Northern Ireland row), ``area_sum`` and ``unallocated`` (the difference).

    Raises:
        ValueError: If ``series`` or ``level`` is not recognised.
    """
    if series not in _ANNUAL_CUBES:
        raise ValueError(f"Unknown series {series!r}; choose from {sorted(_ANNUAL_CUBES)}")
    df = read_annual_cube(_ANNUAL_CUBES[series], level)
    by = ["financial_year", "measure"] + (["age_group"] if "age_group" in df.columns else [])
    return unallocated(df, level=level, by=by)


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a frame returned by this module is structurally sound.

    Args:
        df: Any frame returned by this module's ``get_*`` functions.

    Returns:
        True if every check passes.

    Raises:
        NISRAValidationError: If the frame is empty, lacks ``period`` or ``value``, or holds a negative count.
    """
    return validate_series(df, label="Dental services")
