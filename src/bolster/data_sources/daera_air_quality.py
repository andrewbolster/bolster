"""Northern Ireland Air Quality Statistics (DAERA).

Annual mean pollutant concentrations from Northern Ireland's air quality
monitoring network: nitrogen dioxide (NO2), particulate matter (PM10) and
fine particulate matter (PM2.5). Figures are reported as the mean across
monitoring sites of a given type (urban background, urban traffic/roadside,
or rural) rather than per individual station — this workbook does not
publish station-level detail.

Data Source:
    **Discovery page**:
    https://www.daera-ni.gov.uk/articles/northern-ireland-environmental-statistics-report

    That article links to one publication page per report year
    (``northern-ireland-environmental-statistics-report-<year>``). This module
    scrapes the article to find the most recent publication, then scrapes that
    publication page for the data-tables workbook, so it keeps working when a
    new edition is published.

    Only the air-quality tables (3.1a, 3.2, 3.3) of this workbook are covered
    here — greenhouse gas emissions and waste recycling from the same report
    are already covered by :mod:`~bolster.data_sources.daera_greenhouse_gas`
    and :mod:`~bolster.data_sources.daera_waste` respectively.

Update Frequency:
    Annual, published mid-year.

Geographic Coverage:
    Northern Ireland, by monitoring site type (urban background, urban
    traffic, rural) rather than individual station.

Reference Period:
    NO2 2011 - present; PM10 2009 - present; PM2.5 2016 - present.

Example:
    >>> from bolster.data_sources import daera_air_quality
    >>> df = daera_air_quality.get_no2()
    >>> {'site_type', 'year', 'no2_ugm3'}.issubset(df.columns)
    True
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING, cast

import pandas as pd

from bolster.utils.cache import CachedDownloader, bind_download_file
from bolster.utils.web import fetch_soup, scrape_file_links

if TYPE_CHECKING:
    import bs4

logger = logging.getLogger(__name__)

# ── Public pages to scrape for the current workbook URL ──────────────────────
DAERA_ARTICLE_PAGE = "https://www.daera-ni.gov.uk/articles/northern-ireland-environmental-statistics-report"
DAERA_BASE_URL = "https://www.daera-ni.gov.uk"

# ── Cached downloader (namespace = "daera", shared with waste/greenhouse-gas) ─
_downloader = CachedDownloader("daera", timeout=60)

# Editions change once a year, so a long TTL is appropriate.
_CACHE_TTL_HOURS = 24 * 30

# Sheet name -> (pollutant, value column name). Every sheet shares the same
# shape: title row, unit row, a year-header row, then 2-3 site-type rows
# before the block ends at the "Source: DAERA" row.
_POLLUTANT_SHEETS: dict[str, tuple[str, str]] = {
    "Table 3.1a": ("NO2", "no2_ugm3"),
    "Table 3.2": ("PM10", "pm10_ugm3"),
    "Table 3.3": ("PM2.5", "pm25_ugm3"),
}

# Table 3.3 carries a "Number of sites in urban calculations" row alongside
# its two concentration rows -- a sample-size annotation, not a pollutant
# reading, so it's excluded from the concentration tables.
_NON_CONCENTRATION_LABELS = {"number of sites in urban calculations"}


class DAERADataNotFoundError(Exception):
    """DAERA air quality workbook or publication page could not be located."""


class DAERAValidationError(Exception):
    """DAERA air quality DataFrame failed validation checks."""


# download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=False) -> Path,
# raising DAERADataNotFoundError in place of DownloadError.
download_file = bind_download_file(_downloader, DAERADataNotFoundError, _CACHE_TTL_HOURS)


# ── Source discovery ─────────────────────────────────────────────────────────


def _absolute(href: str) -> str:
    """Resolve a possibly-relative DAERA href to an absolute URL.

    Example:
        >>> _absolute("/publications/foo")
        'https://www.daera-ni.gov.uk/publications/foo'
        >>> _absolute("https://example.com/bar")
        'https://example.com/bar'
    """
    return f"{DAERA_BASE_URL}{href}" if href.startswith("/") else href


def get_report_pages() -> dict[int, str]:
    """Return every published report edition keyed by its report year.

    Returns:
        Mapping of report year (e.g. ``2026``) to publication page URL,
        sorted with the most recent edition last.

    Raises:
        DAERADataNotFoundError: If the article page lists no report pages.
    """
    soup = fetch_soup(DAERA_ARTICLE_PAGE)

    pages: dict[int, str] = {}
    for anchor in cast("list[bs4.Tag]", soup.find_all("a", href=True)):
        href = cast("str", anchor["href"])
        if "/publications/northern-ireland-environmental-statistics-report-" in href:
            suffix = href.rsplit("-", 1)[-1]
            if suffix.isdigit() and len(suffix) == 4:
                pages[int(suffix)] = _absolute(href)

    if not pages:
        raise DAERADataNotFoundError(f"No environmental statistics report pages found on {DAERA_ARTICLE_PAGE}")

    logger.info(f"Found {len(pages)} environmental statistics report editions")
    return dict(sorted(pages.items()))


def get_workbook_url(year: int | None = None) -> str:
    """Return the data-tables workbook URL for a report edition.

    Args:
        year: Report year (e.g. ``2026``). Defaults to the most recent
            published edition.

    Returns:
        Absolute URL of the ``.xlsx`` data tables workbook.

    Raises:
        DAERADataNotFoundError: If the edition or its workbook cannot be found.
    """
    pages = get_report_pages()
    if year is None:
        year = max(pages)
    if year not in pages:
        raise DAERADataNotFoundError(f"No environmental statistics report published for {year}; have {sorted(pages)}")

    links = scrape_file_links(pages[year], ".xlsx", base_url=DAERA_BASE_URL)
    if not links:
        raise DAERADataNotFoundError(f"No .xlsx data tables workbook linked from {pages[year]}")

    return links[0]["url"]


@lru_cache(maxsize=4)
def _load_workbook(year: int | None = None, force_refresh: bool = False) -> pd.ExcelFile:
    """Download and open the report workbook, using the on-disk cache.

    Args:
        year: Report year; defaults to the most recent edition.
        force_refresh: Bypass the download cache.

    Returns:
        An open :class:`pandas.ExcelFile` for the workbook.

    Raises:
        DAERADataNotFoundError: If the workbook cannot be downloaded.
    """
    url = get_workbook_url(year)
    path = download_file(url, force_refresh=force_refresh)
    return pd.ExcelFile(path)


def _sheet(name: str, year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Read one workbook sheet as a header-less DataFrame."""
    workbook = _load_workbook(year, force_refresh)
    if name not in workbook.sheet_names:
        raise DAERADataNotFoundError(f"Sheet {name!r} missing from workbook; have {workbook.sheet_names}")
    return pd.read_excel(workbook, sheet_name=name, header=None)


# ── Sheet parsing ────────────────────────────────────────────────────────────


def _parse_pollutant_sheet(sheet_name: str, value_name: str, year: int | None, force_refresh: bool) -> pd.DataFrame:
    """Parse one air-quality sheet into tidy long format.

    Row 2 (0-indexed) holds the year header; data rows run from row 3 until
    the "Source: DAERA" row.

    Args:
        sheet_name: Workbook sheet to read, e.g. ``"Table 3.1a"``.
        value_name: Name for the concentration column, e.g. ``"no2_ugm3"``.
        year: Report year; defaults to the most recent edition.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``site_type``, ``year`` and ``value_name``.

    Raises:
        DAERAValidationError: If no site-type data rows are found.
    """
    sheet = _sheet(sheet_name, year, force_refresh)

    year_columns = [int(float(v)) for v in sheet.iloc[2, 1:]]
    rows: list[int] = []
    for index in range(3, len(sheet)):
        label = sheet.iat[index, 0]
        if not isinstance(label, str) or label.strip().lower().startswith("source"):
            break
        rows.append(index)

    if not rows:
        raise DAERAValidationError(f"No site-type data rows found in {sheet_name!r}")

    block = sheet.loc[rows].copy()
    block.columns = ["site_type", *year_columns]
    block["site_type"] = block["site_type"].astype(str).str.strip()
    block = block[~block["site_type"].str.lower().isin(_NON_CONCENTRATION_LABELS)]

    long = block.melt(id_vars=["site_type"], value_vars=year_columns, var_name="year", value_name=value_name)
    long["year"] = long["year"].astype(int)
    long[value_name] = pd.to_numeric(long[value_name], errors="coerce")
    return long.sort_values(["site_type", "year"]).reset_index(drop=True)


# ── Public accessors ─────────────────────────────────────────────────────────


def get_no2(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return annual mean nitrogen dioxide (NO2) concentrations (Table 3.1a).

    Args:
        year: Report year to read; defaults to the most recent edition.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``site_type`` (``"Urban background sites
        mean"`` or ``"Urban traffic sites mean"``), ``year`` and
        ``no2_ugm3``.

    Example:
        >>> df = get_no2()
        >>> bool((df['year'] >= 2011).all())
        True
    """
    return _parse_pollutant_sheet("Table 3.1a", "no2_ugm3", year, force_refresh)


def get_pm10(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return annual mean PM10 particulate matter concentrations (Table 3.2).

    Args:
        year: Report year to read; defaults to the most recent edition.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``site_type`` (``"Urban sites mean"`` or
        ``"Rural (Lough Navar)"``), ``year`` and ``pm10_ugm3``.

    Example:
        >>> df = get_pm10()
        >>> bool((df['year'] >= 2009).all())
        True
    """
    return _parse_pollutant_sheet("Table 3.2", "pm10_ugm3", year, force_refresh)


def get_pm25(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return annual mean PM2.5 fine particulate matter concentrations (Table 3.3).

    Args:
        year: Report year to read; defaults to the most recent edition.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``site_type`` (``"Urban sites mean"`` or
        ``"Rural (Lough Navar)"``), ``year`` and ``pm25_ugm3``. Rural
        monitoring only began in 2018, so earlier rural rows are absent
        rather than null.

    Example:
        >>> df = get_pm25()
        >>> bool((df['year'] >= 2016).all())
        True
    """
    return _parse_pollutant_sheet("Table 3.3", "pm25_ugm3", year, force_refresh)


def get_all_pollutants(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return all three pollutants combined into one tidy long-format frame.

    Args:
        year: Report year to read; defaults to the most recent edition.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``pollutant`` (``"NO2"``, ``"PM10"`` or
        ``"PM2.5"``), ``site_type``, ``year`` and ``value_ugm3``.

    Example:
        >>> df = get_all_pollutants()
        >>> set(df['pollutant']) == {'NO2', 'PM10', 'PM2.5'}
        True
    """
    frames = []
    for sheet_name, (pollutant, value_name) in _POLLUTANT_SHEETS.items():
        df = _parse_pollutant_sheet(sheet_name, value_name, year, force_refresh)
        df = df.rename(columns={value_name: "value_ugm3"})
        df.insert(0, "pollutant", pollutant)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_data(df: pd.DataFrame, value_column: str | None = None) -> bool:
    """Check that a parsed air quality DataFrame is structurally sound.

    Args:
        df: DataFrame returned by any of this module's accessors.
        value_column: Concentration column to check; inferred from the frame
            when omitted.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        DAERAValidationError: If the frame is empty, missing its
            concentration column, has no non-null values, contains
            implausible years, or contains negative concentrations.

    Example:
        >>> validate_data(get_no2())
        True
    """
    if df.empty:
        raise DAERAValidationError("DataFrame is empty")

    if value_column is None:
        candidates = [column for column in df.columns if column.endswith("_ugm3")]
        if not candidates:
            raise DAERAValidationError(f"No concentration column found in {list(df.columns)}")
        value_column = candidates[0]

    if value_column not in df.columns:
        raise DAERAValidationError(f"Missing expected column {value_column!r}")

    if df[value_column].notna().sum() == 0:
        raise DAERAValidationError(f"Column {value_column!r} contains no values")

    if (df[value_column].dropna() < 0).any():
        raise DAERAValidationError(f"Column {value_column!r} contains negative concentrations")

    if "year" in df.columns and not df["year"].between(2000, 2100).all():
        raise DAERAValidationError("Year column contains implausible values")

    return True
