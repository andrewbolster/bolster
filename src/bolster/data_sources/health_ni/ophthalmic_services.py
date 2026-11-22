"""Northern Ireland General Ophthalmic Services (GOS) statistics.

Published as: General Ophthalmic Services Statistics.

NHS-funded eye care in Northern Ireland as paid for by the Business Services
Organisation (BSO) Family Practitioner Services (FPS): sight tests, vouchers
(for glasses and contact lenses), repairs and replacements, the ophthalmic
practices and practitioners that claim for them, and the enhanced eye-care
services. Published jointly with the Department of Health and NISRA on GOV.UK,
by the same publisher as :mod:`~bolster.data_sources.health_ni.gms`.

Two series are covered:

- **Quarterly** (the newest tables workbook carries the whole history): sight
  tests, vouchers and repairs by gender and age group, by Health Trust (BSO's
  "Local Commissioning Group") and by Local Government District from Q1 2017/18;
  practices and practitioners from Q4 2020/21; and the enhanced-service tables
  (``get_latest_quarterly_data`` holds all of them). The cover sheet marks the whole
  quarterly series provisional.
- **Annual** (PxStat ``FPSGOSOT*`` and ``FPSGOSOP*``): the same activity and the
  practice count by financial year, by Trust, LGD, Assembly Area and District
  Electoral Area.

Claims are counted in the financial year in which BSO paid them, not the date of the
sight test, so a quarter's figure can include tests from the one before.

Note:
    Not every test is placed in an area: the Trust and LGD tables carry an
    ``Unknown`` row (quarterly) and the annual Northern Ireland total exceeds the sum of
    its areas by the same amount. Every geography frame has ``is_total`` marking the
    Northern Ireland row, so summing a column never double counts; use
    :func:`get_annual_unallocated` for what is missing from the area sum. Trust-level
    area labels are BSO's "Local Commissioning Group (Health Trust)" and are called
    ``trust`` here for join-compatibility with the other ``health_ni`` modules.

Data Source:
    BSO/FPS publishes through GOV.UK. The newest quarterly publication is
    discovered at runtime through the GOV.UK Search and Content APIs, so a new
    release (and its new file-hosting asset hash) needs no code change. Tables
    are found by *title*, never by number: table numbers have moved between
    editions.

Update Frequency: Quarterly, with an annual edition each summer
Geographic Coverage: Northern Ireland (Trust, Local Government District; annual also
    Assembly Area and District Electoral Area)
Reference Period: Financial quarters from Q1 2017/18 (enhanced services from 2013/14);
    annual 2017/18 - present

Example:
    >>> from bolster.data_sources.health_ni import ophthalmic_services
    >>> df = ophthalmic_services.get_quarterly_activity("sight_tests", "trust")  # doctest: +SKIP
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
    "get_annual_activity",
    "get_annual_practices",
    "get_annual_unallocated",
    "get_latest_quarterly_data",
    "get_quarterly_activity",
    "get_quarterly_practices",
    "get_quarterly_practitioners",
    "get_quarterly_table",
    "validate_data",
]

_QUARTERLY_QUERY = "general ophthalmic services statistics ni quarter"
_QUARTERLY_PREFIX = "/government/statistics/general-ophthalmic-services-statistics-for-ni-quarter"
_CACHE_TTL_HOURS = 24 * 7

# Geographies the quarterly workbook breaks activity and practices down by (it has no Assembly Area table).
_AREA_LEVELS = ("trust", "lgd")

_ANNUAL_ACTIVITY_CUBE = "FPSGOSOT"
_ANNUAL_PRACTICES_CUBE = "FPSGOSOP"

# Quarterly activity measure -> the table's descriptive title ("Number of Sight Tests by Gender, ...").
MEASURES = {
    "sight_tests": r"(?:Number of )?Sight Tests\b",
    "vouchers": r"(?:Number of )?Vouchers\b",
    "repairs_replacements": r"(?:Number of )?Repairs and Replacements\b",
}

_PRACTICES_TITLE = r"(?:Number of )?Ophthalmic Practices\b"
_PRACTITIONERS_TITLE = r"Number of Ophthalmic Medical Practitioners\b"


def find_latest_quarterly_url() -> str:
    """Find the URL of the most recent quarterly GOS tables workbook.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        NISRADataNotFoundError: If no quarterly publication, or no tables workbook on the newest
            one, is found. An older quarter is never substituted.

    Example:
        >>> find_latest_quarterly_url().endswith(".xlsx")  # doctest: +SKIP
        True
    """
    content = find_latest_govuk_publication(_QUARTERLY_QUERY, _QUARTERLY_PREFIX, label="General Ophthalmic Services")
    return find_govuk_xlsx_attachment(content, ("Tables",))


def get_latest_quarterly_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the newest quarterly GOS tables workbook.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        Long frame of every data sheet, including the enhanced-service tables:
        ``sheet``, ``sheet_title``, ``table_id``, ``table_title``, ``row_group``, ``row_label``,
        ``column``, ``value``, ``financial_year``, ``quarter``, ``period`` and ``provisional``.
        See :func:`~bolster.data_sources.health_ni._fps.parse_quarterly_workbook`.

    Raises:
        NISRADataNotFoundError: If the newest workbook cannot be found or holds no tables.
    """
    path = download_file(find_latest_quarterly_url(), cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    return parse_quarterly_workbook(pd.ExcelFile(path, engine="openpyxl"))


def get_quarterly_table(title_pattern: str, level: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return any quarterly table found by its title (for example an enhanced service).

    Args:
        title_pattern: Regex matched from the start of the table's descriptive title, without the
            ``Table N.M:`` prefix, e.g. ``r"Number of Assessments at Northern Ireland Primary Eyecare"``.
        level: ``"trust"``, ``"lgd"``, ``"age_sex"`` or ``None`` for a table with no geography.
        force_refresh: Bypass the download cache.

    Returns:
        See :func:`~bolster.data_sources.health_ni._fps.quarterly_series`.

    Raises:
        NISRADataNotFoundError: If no table matches.
    """
    return quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=title_pattern, level=level)


def get_quarterly_activity(
    measure: str = "sight_tests", level: str = "trust", force_refresh: bool = False
) -> pd.DataFrame:
    """Get quarterly sight tests, vouchers or repairs and replacements.

    Args:
        measure: One of :data:`MEASURES`.
        level: ``"trust"``, ``"lgd"`` or ``"age_sex"`` (by gender and age group).
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``measure``, ``period`` (quarter end), ``financial_year``, ``quarter``, the
        geography column named after ``level`` (or ``sex`` and ``age_group`` for ``"age_sex"``),
        ``value``, ``is_total`` and ``provisional``. A ``trust``/``lgd`` frame includes the Northern
        Ireland row (``is_total``) and an ``Unknown`` area for tests with no recorded area.

    Raises:
        ValueError: If ``measure`` or ``level`` is not recognised.
        NISRADataNotFoundError: If the workbook has no matching table.

    Example:
        >>> df = get_quarterly_activity("sight_tests", "trust")  # doctest: +SKIP
        >>> {"Belfast", "Northern Ireland"} <= set(df.trust)  # doctest: +SKIP
        True
    """
    if measure not in MEASURES:
        raise ValueError(f"Unknown measure {measure!r}; choose from {sorted(MEASURES)}")
    if level not in (*_AREA_LEVELS, "age_sex"):
        raise ValueError(f"Unknown level {level!r}; choose from ['trust', 'lgd', 'age_sex']")
    out = quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=MEASURES[measure], level=level)
    out.insert(0, "measure", measure)
    return out


def get_quarterly_practices(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get the quarterly count of ophthalmic practices by geography.

    Args:
        level: ``"trust"`` or ``"lgd"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``financial_year``, ``quarter``, the geography column,
        ``value`` (practices), ``is_total`` and ``provisional``, from Q4 2020/21.

    Raises:
        ValueError: If ``level`` is not ``"trust"`` or ``"lgd"``.
        NISRADataNotFoundError: If the workbook has no matching table.
    """
    if level not in _AREA_LEVELS:
        raise ValueError(f"Unknown level {level!r}; choose from ['trust', 'lgd']")
    return quarterly_series(get_latest_quarterly_data(force_refresh), title_pattern=_PRACTICES_TITLE, level=level)


def get_quarterly_practitioners(force_refresh: bool = False) -> pd.DataFrame:
    """Get the quarterly headcount of ophthalmic medical practitioners and optometrists.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``financial_year``, ``quarter``, ``practitioner_type``
        (``"Ophthalmic Medical Practitioners"``, ``"Optometrists"`` or ``"Total"``), ``value``,
        ``is_total`` (the ``Total`` row) and ``provisional``.

    Raises:
        NISRADataNotFoundError: If the workbook has no matching table.
    """
    out = quarterly_series(
        get_latest_quarterly_data(force_refresh),
        title_pattern=_PRACTITIONERS_TITLE,
        level=None,
        area_column="practitioner_type",
    )
    out["is_total"] = out["practitioner_type"].eq("Total")
    return out


def get_annual_activity(level: str = "trust") -> pd.DataFrame:
    """Get annual sight tests, domiciliary sight tests, vouchers and repairs from PxStat.

    Args:
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame with ``financial_year``, ``period`` (31 March), ``area_code``, the geography column,
        ``measure`` (``Sight Tests``, ``Domiciliary Sight Tests``, ``Vouchers``,
        ``Repairs & Replacements``), ``value`` and ``is_total``. Includes the Northern Ireland row.

    Raises:
        ValueError: If ``level`` is not recognised.
    """
    return read_annual_cube(_ANNUAL_ACTIVITY_CUBE, level)


def get_annual_practices(level: str = "trust") -> pd.DataFrame:
    """Get the annual count of ophthalmic practices from PxStat.

    Args:
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame with the same columns as :func:`get_annual_activity`, from 2013/14.

    Raises:
        ValueError: If ``level`` is not recognised.
    """
    return read_annual_cube(_ANNUAL_PRACTICES_CUBE, level)


def get_annual_unallocated(level: str = "trust") -> pd.DataFrame:
    """Get annual activity that is in the Northern Ireland total but in no area.

    Args:
        level: ``"trust"``, ``"lgd"``, ``"assembly_area"`` or ``"dea"``.

    Returns:
        DataFrame per ``financial_year`` and ``measure`` with ``total`` (the Northern Ireland row),
        ``area_sum`` (all areas added) and ``unallocated`` (the difference).

    Raises:
        ValueError: If ``level`` is not recognised.
    """
    return unallocated(get_annual_activity(level), level=level, by=["financial_year", "measure"])


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a frame returned by this module is structurally sound.

    Args:
        df: Any frame returned by this module's ``get_*`` functions.

    Returns:
        True if every check passes.

    Raises:
        NISRAValidationError: If the frame is empty, lacks ``period`` or ``value``, or holds a negative count.
    """
    return validate_series(df, label="Ophthalmic services")
