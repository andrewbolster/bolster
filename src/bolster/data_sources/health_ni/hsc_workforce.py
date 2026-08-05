"""Health and Social Care workforce statistics for Northern Ireland.

Provides access to the Department of Health quarterly bulletin counting every
person employed directly by an HSC organisation, measured both as whole time
equivalent (WTE) and as headcount, and broken down by staff group, profession,
employing organisation and pay band.

Each bulletin carries ten sub-tables in two shapes:

- **Time series** - five years of history at the 31 March census point, e.g.
  the overall workforce, WTE by staff group and by organisation, plus six years
  of financial-year turnover (leavers, joiners and workforce stability).
- **Latest-period cross-tabs** - the reference quarter broken down by
  organisation against staff group, and by staff group against pay band.

All sub-tables are parsed into a single long frame so heterogeneous layouts can
be queried uniformly, with typed accessors for the series most often wanted.

Data Source:
    **Series Page**: https://www.health-ni.gov.uk/articles/staff-numbers

    The module scrapes this page for quarterly publications and follows through
    to the accessible CSV attached to each one. Every CSV carries its own five
    years of history, so a single download gives a complete series.

Update Frequency: Quarterly (March, June, September and December)
Geographic Coverage: Northern Ireland
Reference Period: 2021 - present (each bulletin covers ~5 years)

.. note::
    WTE counts posts rather than people. Because staff can hold more than one
    post, headcount is lower than active posts, and the difference is published
    explicitly as ``Individuals with multiple posts`` in the summary table.

.. note::
    Domiciliary care staff are excluded from the Social Services staff group
    here but *included* in the equivalent group in
    :mod:`~bolster.data_sources.health_ni.hsc_recruitment`, so vacancy rates
    are not directly divisible by these WTE figures.

Example:
    >>> from bolster.data_sources.health_ni import hsc_workforce
    >>> df = hsc_workforce.get_workforce_summary()  # doctest: +SKIP
    >>> df[df.measure == "WTE"].value.iloc[-1]  # doctest: +SKIP
    68341.3
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

SERIES_URL = "https://www.health-ni.gov.uk/articles/staff-numbers"

# Publication slugs end in the census month, e.g. "...-statistics-march-2026"
_SLUG_PATTERN = r"workforce-statistics-([a-z]+)-(\d{4})"

# Bulletins are quarterly, so a long cache is safe
_CACHE_TTL_HOURS = 24 * 60

_TURNOVER_TABLES = {
    "leavers": r"^HSC Leavers",
    "joiners": r"^Joiners",
    "stability": r"^Workforce Stability",
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
    """Find one bulletin by its census period.

    Args:
        period: Census point, e.g. ``"March 2026"``. Defaults to the most
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
    return find_publication_csv(publication_url, keyword="workforce")


def get_latest_data(period: str | pd.Timestamp | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get every table from a bulletin in long format.

    Args:
        period: Census point, e.g. ``"March 2026"``. Defaults to the most
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
        period: Census point. Defaults to the most recent bulletin.
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

    Table identifiers have shifted between bulletins - joiners and stability
    were added as 7B and 7C after the series began - so titles are the stable
    key.

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


def _with_periods(table: pd.DataFrame) -> pd.DataFrame:
    """Keep the date columns of a time series and resolve them to timestamps.

    Time-series tables append derived ``% Change`` columns alongside the census
    points; those would break period coercion and are dropped.

    Args:
        table: Rows of one sub-table.

    Returns:
        The subset whose ``column`` is a date, with a ``period`` column added.
    """
    periods = table.column.map(parse_period_column)
    return table.assign(period=periods)[periods.notna()]


def get_workforce_summary(period: str | pd.Timestamp | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the headline workforce time series.

    Args:
        period: Census point. Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``measure`` and ``value`` columns. Measures
        are ``WTE``, ``Active Posts``, ``Individuals with multiple posts`` and
        ``Headcount``.
    """
    table = _with_periods(
        _select_table(
            get_latest_data(period=period, force_refresh=force_refresh), r"^HSC Workforce \(WTE, Active Posts"
        )
    )
    return (
        table.rename(columns={"row_label": "measure"})[["period", "measure", "value"]]
        .sort_values(["period", "measure"])
        .reset_index(drop=True)
    )


def get_workforce_by_staff_group(
    period: str | pd.Timestamp | None = None,
    sub: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the WTE time series broken down by staff group.

    Args:
        period: Census point. Defaults to the most recent bulletin.
        sub: Return the finer sub staff group / profession breakdown instead of
            the eight headline staff groups.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``staff_group`` and ``wte`` columns.
    """
    pattern = r"by Sub Staff Group" if sub else r"\(WTE\) by Staff Group,"
    table = _with_periods(_select_table(get_latest_data(period=period, force_refresh=force_refresh), pattern))
    return (
        table.rename(columns={"row_label": "staff_group", "value": "wte"})[["period", "staff_group", "wte"]]
        .sort_values(["period", "staff_group"])
        .reset_index(drop=True)
    )


def get_workforce_by_organisation(
    period: str | pd.Timestamp | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the WTE time series broken down by employing organisation.

    Args:
        period: Census point. Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``period``, ``organisation`` and ``wte`` columns.
    """
    table = _with_periods(
        _select_table(get_latest_data(period=period, force_refresh=force_refresh), r"\(WTE\) by HSC Organisation")
    )
    return (
        table.rename(columns={"row_label": "organisation", "value": "wte"})[["period", "organisation", "wte"]]
        .sort_values(["period", "organisation"])
        .reset_index(drop=True)
    )


def get_staff_group_by_organisation(
    period: str | pd.Timestamp | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get the reference-quarter cross-tab of organisation against staff group.

    The bulletin splits this across two tables, one for the regional trusts and
    one for the smaller arms-length bodies; both are returned together.

    Args:
        period: Census point. Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``organisation``, ``staff_group`` and ``wte`` columns.
    """
    table = _select_table(
        get_latest_data(period=period, force_refresh=force_refresh), r"\(WTE\) by (?:Regional|Other) HSC Trust"
    )
    return (
        table.rename(columns={"row_label": "organisation", "column": "staff_group", "value": "wte"})[
            ["organisation", "staff_group", "wte"]
        ]
        .sort_values(["organisation", "staff_group"])
        .reset_index(drop=True)
    )


def get_pay_band_distribution(period: str | pd.Timestamp | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the reference-quarter pay band profile of each staff group.

    Args:
        period: Census point. Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``staff_group``, ``pay_band`` and ``share`` columns.
        ``share`` is a proportion in [0, 1] of that group's WTE, except in the
        ``Total WTE`` row which carries the group's absolute WTE.
    """
    table = _select_table(
        get_latest_data(period=period, force_refresh=force_refresh), r"by Staff Group and Pay Band Group"
    )
    return (
        table.rename(columns={"row_label": "staff_group", "column": "pay_band", "value": "share"})[
            ["staff_group", "pay_band", "share"]
        ]
        .sort_values(["staff_group", "pay_band"])
        .reset_index(drop=True)
    )


def get_turnover(
    period: str | pd.Timestamp | None = None,
    measure: str = "leavers",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get a financial-year turnover time series.

    Args:
        period: Census point. Defaults to the most recent bulletin.
        measure: One of ``"leavers"``, ``"joiners"`` or ``"stability"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``financial_year``, ``metric`` and ``value`` columns.
        Rate metrics are proportions in [0, 1]; the rest are headcounts.

    Raises:
        ValueError: If ``measure`` is not a recognised series.
    """
    if measure not in _TURNOVER_TABLES:
        raise ValueError(f"Unknown measure {measure!r}, expected one of {sorted(_TURNOVER_TABLES)}")

    table = _select_table(get_latest_data(period=period, force_refresh=force_refresh), _TURNOVER_TABLES[measure])
    return (
        table.rename(columns={"column": "financial_year", "row_label": "metric"})[["financial_year", "metric", "value"]]
        .sort_values(["financial_year", "metric"])
        .reset_index(drop=True)
    )


def validate_data(df: pd.DataFrame, min_records: int = 400) -> bool:
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

    # Headcounts and WTE cannot be negative, but the derived "% Change" columns can
    counts = df[~df.column.str.contains("% Change", case=False, na=False)]
    if (counts.value.dropna() < 0).any():
        raise NISRAValidationError("Negative values found")

    if df.value.isna().mean() > 0.25:
        raise NISRAValidationError(f"Too many unparsed values: {df.value.isna().mean():.1%}")

    return True


def clear_cache() -> int:
    """Clear cached workforce bulletins.

    Returns:
        Number of files removed.
    """
    return _clear_cache("*workforce*")
