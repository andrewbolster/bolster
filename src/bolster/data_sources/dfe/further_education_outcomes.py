"""Further Education Outcomes (Department for the Economy).

Annual Department for the Economy (DfE) survey of what Further Education (FE)
college leavers did after finishing: how many were in work, in further learning,
unemployed or doing something else, where in Northern Ireland the workers are,
and the quality of that work. Published as an interactive NISRA "datavis" report;
each figure embeds its data as a real ``.xlsx`` file, which this module reads
(see :mod:`bolster.utils.embedded_downloads`).

Data covers:
    - Outcome activity of all leavers (employed, learning, unemployed, other)
    - Where employed leavers work, by Local Government District
    - Work quality indicators (permanent contract, guaranteed hours, Real Living Wage)

Update Frequency: Annual
Geographic Coverage: Northern Ireland

Data Source:
    **Publication**: https://www.economy-ni.gov.uk/publications/further-education-outcomes-202425

    The report URL is discovered from the publication page for the most recent academic year.
    The publication also links a Power BI-style dashboard and a methodology page; neither is used.

Example:
    >>> from bolster.data_sources.dfe import further_education_outcomes
    >>> df = further_education_outcomes.get_leaver_outcomes()  # doctest: +SKIP
    >>> set(df["outcome"]) >= {"employed", "learning"}  # doctest: +SKIP
    True
"""

import logging
import re

import pandas as pd

from bolster.utils.embedded_downloads import EmbeddedTable, clean_labels, coerce_numeric, read_tables
from bolster.utils.web import LinkNotFoundError, find_academic_year_publication_link, is_url_host, session

from ._base import DfEDataNotFoundError, DfEValidationError

logger = logging.getLogger(__name__)

_PUBLICATION_URL = "https://www.economy-ni.gov.uk/publications/further-education-outcomes-{slug}"
_ACADEMIC_YEAR_RE = re.compile(r"(\d{4})-(\d{2})")
_OUTCOMES = ("employed", "learning", "unemployed", "other")


def _is_report_link(text: str, href: str) -> bool:
    """The report page, not the dashboard or methodology page the publication also links."""
    lowered = f"{text} {href}".lower()
    return is_url_host(href, "datavis.nisra.gov.uk") and "dashboard" not in lowered and "methodology" not in lowered


def get_latest_publication_url(force_refresh: bool = False) -> str:
    """Find the latest FE Outcomes report page.

    Walks academic-year publication pages from the current year backwards until one links to the report.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        URL of the datavis report (e.g. ``https://datavis.nisra.gov.uk/economy/Further-Education-Outcomes-2024-25.html``).

    Raises:
        DfEDataNotFoundError: If no recent publication page links to the report.
    """
    try:
        return find_academic_year_publication_link(_PUBLICATION_URL, _is_report_link, force_refresh=force_refresh)
    except LinkNotFoundError as exc:
        raise DfEDataNotFoundError("Could not find a Further Education Outcomes report") from exc


def _academic_year(url: str) -> str:
    match = _ACADEMIC_YEAR_RE.search(url)
    if not match:
        raise DfEValidationError(f"No academic year (e.g. 2024-25) in report URL: {url}")
    return f"{match.group(1)}/{match.group(2)}"


def _load(force_refresh: bool) -> tuple[str, dict[str, EmbeddedTable]]:
    url = get_latest_publication_url(force_refresh=force_refresh)
    tables = read_tables(session.get(url, timeout=90, force_refresh=force_refresh).text)
    if not tables:
        raise DfEDataNotFoundError(f"No embedded data files found on {url}")
    logger.info("Read %d embedded tables from %s", len(tables), url)
    return url, tables


def get_tables(force_refresh: bool = False) -> dict[str, EmbeddedTable]:
    """Read every figure embedded in the latest FE Outcomes report.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Mapping of label (``"Figure 1"`` ...) to the raw table, in page order.

    Raises:
        DfEDataNotFoundError: If the report cannot be found or embeds no data files.
    """
    return _load(force_refresh)[1]


def _find_table(tables: dict[str, EmbeddedTable], *keywords: str) -> EmbeddedTable:
    for table in tables.values():
        if all(word in table.title.lower() for word in keywords):
            return table
    raise DfEDataNotFoundError(f"No figure with a title containing {keywords} in the FE Outcomes report")


def get_leaver_outcomes(force_refresh: bool = False) -> pd.DataFrame:
    """What FE leavers were doing when surveyed, as a percentage of all leavers.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``outcome`` (``employed``, ``learning``, ``unemployed``, ``other``), ``pct`` and
        ``academic_year`` (e.g. ``"2024/25"``). The published percentages are rounded and can sum to 99-101.
    """
    url, tables = _load(force_refresh)
    wide = _find_table(tables, "leavers by outcome").data
    long = wide.melt(var_name="outcome", value_name="pct")
    long["pct"] = coerce_numeric(long["pct"])
    df = long[long["outcome"].isin(_OUTCOMES)].reset_index(drop=True)
    df["academic_year"] = _academic_year(url)
    validate_data(df)
    return df


def get_leavers_working_by_lgd(force_refresh: bool = False) -> pd.DataFrame:
    """Where employed FE leavers work, as a percentage of those working in Northern Ireland.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``lgd`` (Local Government District, plus ``Don't know``), ``pct`` and ``academic_year``.
    """
    url, tables = _load(force_refresh)
    df = _find_table(tables, "working in ni by lgd").data.copy()
    df.columns = ["lgd", "pct"]
    df["lgd"] = clean_labels(df["lgd"])
    df["pct"] = coerce_numeric(df["pct"])
    df["academic_year"] = _academic_year(url)
    return df


def get_work_quality_indicators(force_refresh: bool = False) -> pd.DataFrame:
    """Quality of the work FE leavers are in, as the percentage answering yes to each question.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``indicator`` (the survey question), ``pct`` and ``academic_year``.
    """
    url, tables = _load(force_refresh)
    df = _find_table(tables, "work quality").data.copy()
    df.columns = ["indicator", "pct"]
    df["indicator"] = clean_labels(df["indicator"])
    df["pct"] = coerce_numeric(df["pct"])
    df["academic_year"] = _academic_year(url)
    return df


def validate_data(df: pd.DataFrame) -> bool:
    """Validate the :func:`get_leaver_outcomes` table.

    Args:
        df: Output of :func:`get_leaver_outcomes`.

    Returns:
        ``True`` if valid.

    Raises:
        DfEValidationError: If columns are missing, an outcome is absent, a percentage is missing or outside
            0-100, or the outcomes do not sum to roughly 100 (published figures are rounded).
    """
    required = {"outcome", "pct", "academic_year"}
    missing = required - set(df.columns)
    if missing:
        raise DfEValidationError(f"Missing expected columns: {sorted(missing)}")
    absent = set(_OUTCOMES) - set(df["outcome"])
    if absent:
        raise DfEValidationError(f"Missing outcomes: {sorted(absent)}")
    if df["pct"].isna().any() or not df["pct"].between(0, 100).all():
        raise DfEValidationError("Percentages must be present and within 0-100")
    total = df["pct"].sum()
    if not 97 <= total <= 103:
        raise DfEValidationError(f"Outcomes sum to {total}, expected about 100")
    return True
