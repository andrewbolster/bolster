"""Health and Social Care active recruitment statistics for Northern Ireland.

Provides access to the Department of Health quarterly bulletin counting HSC
posts that are vacant *and* actively being recruited to, broken down by staff
group, profession, pay band, employing organisation and - for doctors - by
clinical specialty.

Each bulletin carries thirteen sub-tables in two shapes:

- **Time series** - nine years of quarterly history since 31 March 2017,
  covering both vacancy counts and vacancy rates by staff group, profession and
  organisation, plus six years of consultant, locum consultant and SAS doctor
  vacancies by specialty.
- **Latest-quarter cross-tabs** - the reference quarter broken down by staff
  group or profession against pay band and against organisation.

All sub-tables are parsed into a single long frame so heterogeneous layouts can
be queried uniformly, with typed accessors for the series most often wanted.

Data Source:
    **Series Page**: https://www.health-ni.gov.uk/articles/staff-vacancies

    The module scrapes this page for quarterly publications and follows through
    to the accessible CSV attached to each one. Every CSV carries its own full
    history, so a single download gives a complete series.

Update Frequency: Quarterly (March, June, September and December)
Geographic Coverage: Northern Ireland
Reference Period: 2017 - present

.. note::
    A vacancy is only counted while it is *actively being recruited*, so these
    figures understate total unfilled establishment. Posts frozen for budgetary
    reasons, or awaiting a business case, do not appear.

.. note::
    The Social Services staff group here *includes* domiciliary care, whereas
    the matching group in
    :mod:`~bolster.data_sources.health_ni.hsc_workforce` excludes it. Vacancy
    rates published in table 4A already account for this, so prefer them over
    dividing counts by workforce WTE.

Example:
    >>> from bolster.data_sources.health_ni import hsc_recruitment
    >>> df = hsc_recruitment.get_vacancies_by_pay_band()  # doctest: +SKIP
    >>> df[df.pay_band == "Total"].vacancies.sum()  # doctest: +SKIP
    6236.0
"""

import logging

import pandas as pd

from ._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    find_publication_csv,
    list_dated_publications,
    parse_csv_tables,
    parse_period_column,
)
from ._base import clear_cache as _clear_cache

logger = logging.getLogger(__name__)

SERIES_URL = "https://www.health-ni.gov.uk/articles/staff-vacancies"

# Publication slugs end in the reference month, e.g. "...-statistics-march-2026"
_SLUG_PATTERN = r"active-recruitment-statistics-([a-z]+)-(\d{4})"

# Bulletins are quarterly, so a long cache is safe
_CACHE_TTL_HOURS = 24 * 60

_DOCTOR_GRADES = {
    "consultant": r"^Consultant Vacancies",
    "locum": r"^Direct Employment Locum Consultant",
    "sas": r"^SAS Doctor Vacancies",
}


def list_publications() -> pd.DataFrame:
    """List every bulletin advertised on the series page.

    Returns:
        DataFrame with ``period``, ``title`` and ``url`` columns, most recent
        first.

    Raises:
        NISRADataNotFoundError: If the series page cannot be fetched or holds
            no publications.
    """
    return list_dated_publications(SERIES_URL, _SLUG_PATTERN)


def find_publication(period: str | pd.Timestamp | None = None) -> pd.Series:
    """Find one bulletin by its reference period.

    Args:
        period: Reference quarter, e.g. ``"March 2026"``. Defaults to the most
            recent bulletin.

    Returns:
        Row of :func:`list_publications` with ``period``, ``title`` and ``url``.

    Raises:
        NISRADataNotFoundError: If no bulletin matches ``period``.
    """
    publications = list_publications()
    if period is None:
        return publications.iloc[0]

    wanted = pd.Timestamp(period).to_period("M").to_timestamp()
    matched = publications[publications.period == wanted]
    if matched.empty:
        available = ", ".join(publications.period.dt.strftime("%B %Y"))
        raise NISRADataNotFoundError(f"No bulletin for {wanted:%B %Y}; available: {available}")
    return matched.iloc[0]


def get_data_file_url(publication_url: str) -> str:
    """Find the accessible CSV attached to a publication.

    Args:
        publication_url: Publication page URL.

    Returns:
        Absolute URL of the CSV.

    Raises:
        NISRADataNotFoundError: If the page carries no CSV.
    """
    return find_publication_csv(publication_url, keyword="vacanc")


def get_latest_data(period: str | pd.Timestamp | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get every table from a bulletin in long format.

    Args:
        period: Reference quarter, e.g. ``"March 2026"``. Defaults to the most
            recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame with ``table_id``, ``table_title``, ``row_group``,
        ``row_label``, ``column`` and ``value`` columns.
    """
    publication = find_publication(period)
    url = get_data_file_url(str(publication["url"]))
    logger.info("Using bulletin %s (%s)", publication["period"], url)
    return parse_csv_tables(download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh))


def list_tables(period: str | pd.Timestamp | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """List the sub-tables available in a bulletin.

    Args:
        period: Reference quarter. Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``table_id``, ``table_title`` and ``records`` columns.
    """
    df = get_latest_data(period=period, force_refresh=force_refresh)
    return (
        df.groupby("table_id")
        .agg(table_title=("table_title", "first"), records=("value", "size"))
        .reset_index()
        .sort_values("table_id")
        .reset_index(drop=True)
    )


def _select_table(df: pd.DataFrame, pattern: str) -> pd.DataFrame:
    """Select one sub-table by matching its title.

    Args:
        df: Long-format frame from :func:`get_latest_data`.
        pattern: Case-insensitive regex matched against ``table_title``.

    Returns:
        The matching rows.

    Raises:
        NISRADataNotFoundError: If no table title matches.
    """
    matched = df[df.table_title.str.contains(pattern, case=False, regex=True, na=False)]
    if matched.empty:
        raise NISRADataNotFoundError(f"No table matching {pattern!r} in this bulletin")
    return matched


def _as_series(table: pd.DataFrame, label: str, value: str) -> pd.DataFrame:
    """Reshape a quarterly time-series table into tidy rows.

    Args:
        table: Rows of one sub-table.
        label: Name to give the ``row_label`` column.
        value: Name to give the ``value`` column.

    Returns:
        DataFrame with ``period``, ``label`` and ``value`` columns, restricted
        to columns that resolve to a quarter-end date.
    """
    periods = table.column.map(parse_period_column)
    return (
        table.assign(period=periods)[periods.notna()]
        .rename(columns={"row_label": label, "value": value})[["period", label, value]]
        .sort_values(["period", label])
        .reset_index(drop=True)
    )


def get_vacancies_by_pay_band(
    period: str | pd.Timestamp | None = None,
    sub: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the reference-quarter vacancy cross-tab against pay band.

    Args:
        period: Reference quarter. Defaults to the most recent bulletin.
        sub: Return the finer sub staff group / profession breakdown instead of
            the headline staff groups.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``staff_group``, ``pay_band`` and ``vacancies`` columns.
    """
    pattern = r"by Sub Staff Group / Profession & Pay Band" if sub else r"by Staff Group & Pay Band"
    table = _select_table(get_latest_data(period=period, force_refresh=force_refresh), pattern)
    return (
        table.rename(columns={"row_label": "staff_group", "column": "pay_band", "value": "vacancies"})[
            ["staff_group", "pay_band", "vacancies"]
        ]
        .sort_values(["staff_group", "pay_band"])
        .reset_index(drop=True)
    )


def get_vacancies_by_organisation(
    period: str | pd.Timestamp | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the vacancy count time series by employing organisation.

    Args:
        period: Reference quarter. Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``organisation`` and ``vacancies`` columns.
    """
    table = _select_table(
        get_latest_data(period=period, force_refresh=force_refresh), r"Recruited by HSC Organisation, 31 March"
    )
    return _as_series(table, "organisation", "vacancies")


def get_vacancies_by_staff_group(
    period: str | pd.Timestamp | None = None,
    sub: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the vacancy count time series by staff group.

    Args:
        period: Reference quarter. Defaults to the most recent bulletin.
        sub: Return the finer sub staff group / profession breakdown instead of
            the headline staff groups.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``staff_group`` and ``vacancies`` columns.
    """
    pattern = r"Recruited by Sub Staff Group / Profession, 31 March" if sub else r"Recruited by Staff Group, 31 March"
    table = _select_table(get_latest_data(period=period, force_refresh=force_refresh), pattern)
    return _as_series(table, "staff_group", "vacancies")


def get_vacancy_rates(
    period: str | pd.Timestamp | None = None,
    sub: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the vacancy rate time series by staff group.

    Args:
        period: Reference quarter. Defaults to the most recent bulletin.
        sub: Return the finer sub staff group / profession breakdown instead of
            the headline staff groups.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``staff_group`` and ``vacancy_rate`` columns.
        Rates are proportions in [0, 1] of the staff group's establishment.
    """
    pattern = r"Vacancy Rates by Sub Staff Group" if sub else r"Vacancy Rates by Staff Group"
    table = _select_table(get_latest_data(period=period, force_refresh=force_refresh), pattern)
    return _as_series(table, "staff_group", "vacancy_rate")


def get_vacancies_by_profession(period: str | pd.Timestamp | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the vacancy count time series by individual profession.

    Args:
        period: Reference quarter. Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``staff_group``, ``profession`` and
        ``vacancies`` columns.
    """
    table = _select_table(
        get_latest_data(period=period, force_refresh=force_refresh), r"Recruited by Profession, 31 March"
    )
    periods = table.column.map(parse_period_column)
    return (
        table.assign(period=periods)[periods.notna()]
        .rename(columns={"row_group": "staff_group", "row_label": "profession", "value": "vacancies"})[
            ["period", "staff_group", "profession", "vacancies"]
        ]
        .sort_values(["period", "staff_group", "profession"])
        .reset_index(drop=True)
    )


def get_doctor_vacancies(
    period: str | pd.Timestamp | None = None,
    grade: str = "consultant",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the medical vacancy time series by clinical specialty.

    Args:
        period: Reference quarter. Defaults to the most recent bulletin.
        grade: One of ``"consultant"``, ``"locum"`` (directly employed locum
            consultants) or ``"sas"`` (specialty and associate specialist
            doctors).
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``specialty`` and ``vacancies`` columns.

    Raises:
        ValueError: If ``grade`` is not a recognised series.
    """
    if grade not in _DOCTOR_GRADES:
        raise ValueError(f"Unknown grade {grade!r}, expected one of {sorted(_DOCTOR_GRADES)}")

    table = _select_table(get_latest_data(period=period, force_refresh=force_refresh), _DOCTOR_GRADES[grade])
    return _as_series(table, "specialty", "vacancies")


def validate_data(df: pd.DataFrame, min_records: int = 5000) -> bool:
    """Validate a parsed long frame.

    Args:
        df: Frame from :func:`get_latest_data`.
        min_records: Minimum acceptable record count.

    Returns:
        True if the frame passes every check.

    Raises:
        NISRAValidationError: If the frame is malformed or too small.
    """
    if df is None or df.empty:
        raise NISRAValidationError("DataFrame is empty")

    required = {"table_id", "table_title", "row_group", "row_label", "column", "value"}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise NISRAValidationError(f"Too few records: expected at least {min_records}, got {len(df)}")

    if (df.value.dropna() < 0).any():
        raise NISRAValidationError("Negative values found")

    if df.value.isna().mean() > 0.25:
        raise NISRAValidationError(f"Too many unparsed values: {df.value.isna().mean():.1%}")

    return True


def clear_cache() -> int:
    """Clear cached vacancy bulletins.

    Returns:
        Number of files removed.
    """
    return _clear_cache("*vacanc*")
