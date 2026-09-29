"""NI Civil Service Pay Statistics.

Annual pay statistics for the Northern Ireland Civil Service (NICS), published by
the NISRA HR statistics team each year for the position at 31 March. The
publication is an interactive "datavis" report rather than a spreadsheet, but
each figure embeds its data as a real ``.xlsx`` file, which is what this module
reads (see :mod:`bolster.utils.datavis`).

Data covers:
    - Median and quartile pay by analogous grade (latest year)
    - Median pay trend, 2016 to latest, overall and by grade
    - Gender pay gap by grade
    - Community background pay gap by grade
    - NI median pay compared with England, Scotland and Wales

Update Frequency: Annual (autumn)
Geographic Coverage: Northern Ireland
Reference Date: 31 March

Data Source:
    **Mother Page**: https://www.nisra.gov.uk/statistics/ni-civil-service-human-resources/pay-statistics

    The report URL changes every year, so it is discovered from the publication page.

Example:
    >>> from bolster.data_sources.nisra import nics_pay
    >>> df = nics_pay.get_pay_by_grade()  # doctest: +SKIP
    >>> "NICS Overall" in set(df["grade"])  # doctest: +SKIP
    True
"""

import logging
import re

import pandas as pd

from bolster.utils.datavis import DatavisTable, clean_labels, coerce_numeric, read_tables
from bolster.utils.web import LinkNotFoundError, find_publication_link, session

from ._base import NISRADataNotFoundError, NISRAValidationError

logger = logging.getLogger(__name__)

HUB_URL = "https://www.nisra.gov.uk/statistics/ni-civil-service-human-resources/pay-statistics"
_PUBLICATION_TEXT = "Pay in the Northern Ireland Civil Service"
_REPORT_HOST = "datavis.nisra.gov.uk"

# Tables are found by title, not by "Figure N", so a reordered report cannot silently return the wrong one.
_TITLE_KEYWORDS = {
    "pay_by_grade": ("quartile",),
    "trend": ("pay trend",),
    "history": ("median pay (£) by analogous grade",),
    "gender": ("pay gap", "sex"),
    "community": ("pay gap", "community background"),
    "uk": ("across the uk",),
}


def get_latest_publication_url(force_refresh: bool = False) -> str:
    """Find the latest NICS pay statistics report page.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        URL of the datavis report (e.g. ``https://datavis.nisra.gov.uk/nicshrstats/NICS-Pay-Statistics-2026-Report.html``).

    Raises:
        NISRADataNotFoundError: If the publication or its report link cannot be found.
    """
    try:
        return find_publication_link(
            HUB_URL,
            pub_text_contains=_PUBLICATION_TEXT,
            file_extension=".html",
            file_href_contains=_REPORT_HOST,
            force_refresh=force_refresh,
        )
    except LinkNotFoundError as exc:
        raise NISRADataNotFoundError(f"Could not find the NICS pay statistics report: {exc}") from exc


def get_tables(force_refresh: bool = False) -> dict[str, DatavisTable]:
    """Read every figure embedded in the latest NICS pay report.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Mapping of label (``"Figure 1"`` ...) to the raw table, in page order.

    Raises:
        NISRADataNotFoundError: If the report cannot be found or embeds no data files.
    """
    url = get_latest_publication_url(force_refresh=force_refresh)
    html = session.get(url, timeout=90, force_refresh=force_refresh).text
    tables = read_tables(html)
    if not tables:
        raise NISRADataNotFoundError(f"No embedded data files found on {url}")
    logger.info("Read %d embedded tables from %s", len(tables), url)
    return tables


def _find_table(tables: dict[str, DatavisTable], key: str) -> DatavisTable:
    keywords = _TITLE_KEYWORDS[key]
    for table in tables.values():
        title = table.title.lower()
        if all(word in title for word in keywords):
            return table
    raise NISRADataNotFoundError(f"No table with a title containing {keywords} in the NICS pay report")


def _reference_year(title: str) -> int:
    years = re.findall(r"\b((?:19|20)\d{2})\b", title)
    if not years:
        raise NISRAValidationError(f"No reference year in table title: {title!r}")
    return int(years[-1])


def _grade_table(table: DatavisTable) -> pd.DataFrame:
    """Tidy a one-row-per-grade table: first column becomes ``grade``, the rest numeric, plus ``year``."""
    df = table.data.copy()
    df = df.rename(columns={df.columns[0]: "grade"})
    df["grade"] = clean_labels(df["grade"])
    for column in df.columns[1:]:
        df[column] = coerce_numeric(df[column])
    df["year"] = _reference_year(table.title)
    return df


def get_pay_by_grade(force_refresh: bool = False) -> pd.DataFrame:
    """Median and quartile pay by analogous grade for the latest year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with columns ``grade``, ``median_pay``, ``lower_quartile``,
        ``upper_quartile`` (pounds) and ``year``. Includes an ``NICS Overall`` row.
    """
    df = _grade_table(_find_table(get_tables(force_refresh), "pay_by_grade"))
    validate_data(df)
    return df


def get_pay_trend(force_refresh: bool = False) -> pd.DataFrame:
    """NICS overall median pay by year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with columns ``year`` (int) and ``median_pay`` (pounds), one row per year.
    """
    table = _find_table(get_tables(force_refresh), "trend")
    df = table.data.copy()
    df.columns = ["year", "median_pay"]
    df["year"] = coerce_numeric(df["year"]).astype("int64")
    df["median_pay"] = coerce_numeric(df["median_pay"])
    return df


def get_pay_history_by_grade(force_refresh: bool = False) -> pd.DataFrame:
    """Median pay by analogous grade for every year in the report, in long form.

    Grades with no value in a year (a grade that did not exist yet) have no row for that year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with columns ``grade``, ``year`` (int) and ``median_pay`` (pounds).
    """
    table = _find_table(get_tables(force_refresh), "history")
    wide = table.data.copy()
    wide = wide.rename(columns={wide.columns[0]: "grade"})
    wide["grade"] = clean_labels(wide["grade"])
    long = wide.melt(id_vars="grade", var_name="year", value_name="median_pay")
    long["year"] = coerce_numeric(long["year"]).astype("int64")
    long["median_pay"] = coerce_numeric(long["median_pay"])
    return long.dropna(subset=["median_pay"]).sort_values(["grade", "year"]).reset_index(drop=True)


def get_gender_pay_gap_by_grade(force_refresh: bool = False) -> pd.DataFrame:
    """Male and female median pay and the pay gap, by analogous grade.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``grade``, ``male_median_pay``, ``female_median_pay``, ``gender_pay_gap``
        (percentage points; positive means men are paid more) and ``year``.
    """
    return _grade_table(_find_table(get_tables(force_refresh), "gender"))


def get_community_background_pay_gap_by_grade(force_refresh: bool = False) -> pd.DataFrame:
    """Protestant and Catholic median pay and the pay gap, by analogous grade.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``grade``, ``protestant_median_pay``, ``catholic_median_pay``,
        ``community_background_pay_gap`` (percentage points; positive means Protestant median pay is higher)
        and ``year``.
    """
    return _grade_table(_find_table(get_tables(force_refresh), "community"))


def get_uk_pay_comparison(force_refresh: bool = False) -> pd.DataFrame:
    """NI median civil service pay against England, Scotland and Wales, by grade.

    The comparison year lags the rest of the report by one year (the other nations publish later).

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``grade``, one ``*_median_pay`` column per nation/region, and ``year``.
    """
    return _grade_table(_find_table(get_tables(force_refresh), "uk"))


def validate_data(df: pd.DataFrame) -> bool:
    """Validate the :func:`get_pay_by_grade` table.

    Args:
        df: Output of :func:`get_pay_by_grade`.

    Returns:
        ``True`` if valid.

    Raises:
        NISRAValidationError: If columns are missing, there are too few grades, pay is negative,
            or a grade's quartiles do not bracket its median.
    """
    required = {"grade", "median_pay", "lower_quartile", "upper_quartile", "year"}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing expected columns: {sorted(missing)}")
    if len(df) < 10:
        raise NISRAValidationError(f"Too few grades: {len(df)}")
    if "NICS Overall" not in set(df["grade"]):
        raise NISRAValidationError("No 'NICS Overall' row")
    pay = df[["median_pay", "lower_quartile", "upper_quartile"]]
    if pay.isna().any().any() or (pay < 0).any().any():
        raise NISRAValidationError("Pay values must be present and non-negative")
    bad = df[(df["lower_quartile"] > df["median_pay"]) | (df["median_pay"] > df["upper_quartile"])]
    if not bad.empty:
        raise NISRAValidationError(f"Quartiles do not bracket the median for: {sorted(bad['grade'])}")
    return True
