"""First Time Entrants to the Criminal Justice System in Northern Ireland.

Provides access to the Department of Justice (DoJ) official statistics on
*first time entrants* — people convicted at court or dealt with by a formal
diversionary disposal who have no previous conviction or diversion on record.

The bulletin measures how much of NI's justice caseload is made up of people
encountering the system for the first time, broken down four ways:

- ``age_band`` - 10 to 17 through 60 & over (Tables 1a-1d).
- ``gender`` - male and female (Tables 2a-2d).
- ``offence`` - offence classification, e.g. Motoring, Drugs (Tables 3a-3e).
- ``disposal`` - disposal category, e.g. Imprisonment, Caution (Tables 4a-4d).
- ``summary`` - the headline ten-year percentage series (Table 5).

Each breakdown is published as four tables measuring first offences or first
convictions against a different denominator (all convictions and diversions,
all convictions, or all diversions), which is why ``table`` is part of the
output rather than being flattened away — the same category appears in several
tables with legitimately different values.

Data Source:
    **Series Index**:
    https://www.justice-ni.gov.uk/articles/first-time-entrant-statistics

    The module scrapes this index for per-edition publication pages, then
    resolves each to its published tables spreadsheet (ODS or, for older
    editions, XLSX).

Update Frequency: Annual
Geographic Coverage: Northern Ireland
Reference Period: 2011-12 - present (headline series from 2015-16)

.. note::
    Percentages are returned on a 0-100 scale. Older editions publish them as
    fractions; :func:`parse_data` rescales those automatically.

.. note::
    Suppressed cells are published as ``[c]``, ``[d]`` or ``[low]`` and are
    returned as ``NaN``. Counts and totals in a suppressed row are unavailable
    even where the corresponding percentage is published.

Example:
    >>> from bolster.data_sources.justice import first_time_entrants
    >>> df = first_time_entrants.get_by_gender()
    >>> set(df["breakdown"]) == {"gender"}
    True
    >>> "value" in df.columns
    True
"""

import logging
import re
from pathlib import Path
from typing import cast
from urllib.parse import urljoin

import pandas as pd
from bs4 import Tag  # noqa: TC002 (used inside `cast(...)`, evaluated at runtime)

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import fetch_soup, scrape_file_links

logger = logging.getLogger(__name__)

# Series index page listing every annual edition
PUBLICATION_URL = "https://www.justice-ni.gov.uk/articles/first-time-entrant-statistics"

# Publication page slugs end in the financial year they cover, in one of three
# spellings: 202425, 2015-2016, or 2013-14.
_SLUG_YEAR_RES = (
    re.compile(r"(\d{4})(\d{2})$"),
    re.compile(r"(\d{4})-(\d{4})$"),
    re.compile(r"(\d{4})-(\d{2})$"),
)

# Table titles are the only stable identifier: worksheet names change between
# editions (``1``..``6`` in modern editions, ``financeyear_age`` in older ones)
# and worksheet numbering carries typos in the source.
_TABLE_RE = re.compile(r"\bTable\s+(\d+[a-z]?)\s*[-:]", re.IGNORECASE)

# Financial years appear as 2024-25 or 2024/25 depending on edition
_YEAR_RE = re.compile(r"(\d{4})\s*[-/]\s*(\d{2,4})")

# Footnote references embedded in labels, e.g. "Total [note 3]"
_NOTE_REF_RE = re.compile(r"\s*[\[{]note\s*\d+[\]}]", re.IGNORECASE)

# Suppression and non-applicable markers used in place of a value. The source
# publishes "[d}" with a mismatched brace, so match on the inner token.
_SUPPRESSED = {"", "-", "c", "d", "x", "z", "low", "n.a.", "na", "n/a", ":", "*"}
_MARKER_RE = re.compile(r"^[\[{]?\s*([a-z./]+)\s*[\]}]?$", re.IGNORECASE)

# Worksheets carrying front matter rather than data. The index sheet lists
# every table title, so it must be skipped or it shadows the real tables.
_NON_DATA_SHEETS = {"metadata", "index_of_tables", "notes", "cover_sheet", "contents"}

# Label column headers identify which breakdown a table belongs to
_BREAKDOWN_BY_LABEL = {
    "age band": "age_band",
    "gender": "gender",
    "offence classification": "offence",
    "disposal category": "disposal",
    "year": "summary",
}

# Age bands are spelled inconsistently across editions, and the 2024-25 edition
# publishes "40 t0 49" with a zero.
_CATEGORY_ALIASES = {
    "40 t0 49": "40 to 49",
    "10 - 17": "10 to 17",
    "10-17": "10 to 17",
    "18 - 24": "18 to 24",
    "18-24": "18 to 24",
    "25 - 29": "25 to 29",
    "25-29": "25 to 29",
    "30 - 39": "30 to 39",
    "30-39": "30 to 39",
    "40 - 49": "40 to 49",
    "40-49": "40 to 49",
    "50 - 59": "50 to 59",
    "50-59": "50 to 59",
    "60 and over": "60 & over",
    "unknown": "Other/unknown",
    "other/unknown": "Other/unknown",
}

# Table 3e splits first offences by outcome, so its two count columns need
# qualifying to stay distinct.
_CONVICTIONS_QUALIFIER_RE = re.compile(r"^first offences[:\s]+convictions")
_DIVERSIONS_QUALIFIER_RE = re.compile(r"^first offences[:\s]+diversions")

# Editions are annual, so a long cache is safe
_CACHE_TTL_HOURS = 24 * 180

_downloader = CachedDownloader("first_time_entrants", timeout=60)


class FirstTimeEntrantsError(Exception):
    """Base exception for first time entrants errors."""

    pass


class FirstTimeEntrantsNotFoundError(FirstTimeEntrantsError):
    """Raised when a publication or file cannot be located or downloaded."""

    pass


class FirstTimeEntrantsValidationError(FirstTimeEntrantsError):
    """Raised when parsed data fails validation."""

    pass


def _clean(text: str) -> str:
    """Strip note references and collapse whitespace in a label.

    Args:
        text: Raw cell text.

    Returns:
        Cleaned single-spaced label.

    Example:
        >>> _clean("Total  [note 3] ")
        'Total'
    """
    return " ".join(_NOTE_REF_RE.sub("", str(text)).split())


def _normalise_year(text: str) -> str | None:
    """Extract a financial year from free text as ``YYYY-YY``.

    Args:
        text: Text possibly containing a financial year.

    Returns:
        Normalised year label, or None if no year is present.

    Example:
        >>> _normalise_year("First offences 2024/25")
        '2024-25'
        >>> _normalise_year("no year here") is None
        True
    """
    match = _YEAR_RE.search(str(text))
    if not match:
        return None
    start, end = match.group(1), match.group(2)
    return f"{start}-{end[-2:]}"


def _normalise_category(text: str) -> str:
    """Normalise a row label so categories join across editions.

    Args:
        text: Raw category label.

    Returns:
        Canonical category label.

    Example:
        >>> _normalise_category("40 t0 49")
        '40 to 49'
        >>> _normalise_category("unknown")
        'Other/unknown'
    """
    cleaned = _clean(text)
    return _CATEGORY_ALIASES.get(cleaned.lower(), cleaned)


def _parse_value(text: str) -> float:
    """Convert a published cell into a float, mapping suppression to NaN.

    Args:
        text: Raw cell text.

    Returns:
        Numeric value, or NaN where suppressed or unparseable.

    Example:
        >>> _parse_value("1,462")
        1462.0
        >>> import math
        >>> math.isnan(_parse_value("[d}"))
        True
    """
    raw = str(text).strip()
    marker = _MARKER_RE.match(raw)
    if marker and marker.group(1).lower() in _SUPPRESSED:
        return float("nan")
    if raw.lower() in _SUPPRESSED:
        return float("nan")
    try:
        return float(raw.replace(",", "").replace("%", "").strip())
    except ValueError:
        return float("nan")


def _measure_from_header(header: str) -> str:
    """Derive a measure name from a data column header.

    Column headers describe both the numerator and the denominator, e.g.
    ``"2024-25 First offences as % of all convictions and diversions"``. The
    denominator is captured by ``table`` rather than the measure name, so only
    the numerator and whether the column is a count or a percentage matter.

    Args:
        header: Raw column header text.

    Returns:
        One of ``first_count``, ``total_count``, ``first_pct``, or the
        Table 3e variants qualified by outcome.

    Example:
        >>> _measure_from_header("2024-25 All convictions and diversions")
        'total_count'
        >>> _measure_from_header("2024-25 First offences")
        'first_count'
        >>> _measure_from_header("First offences: Diversions")
        'first_diversions_count'
    """
    text = _clean(header)
    text = _YEAR_RE.sub("", text)
    text = " ".join(text.split()).lower()

    if text.startswith("all "):
        return "total_count"

    is_pct = "%" in text or "percentage" in text
    if _CONVICTIONS_QUALIFIER_RE.match(text):
        base = "first_convictions"
    elif _DIVERSIONS_QUALIFIER_RE.match(text):
        base = "first_diversions"
    else:
        base = "first"
    return f"{base}_pct" if is_pct else f"{base}_count"


def _sheet_rows(frame: pd.DataFrame) -> list[list[str]]:
    """Convert a raw worksheet frame into trimmed text rows.

    Args:
        frame: Worksheet read with ``header=None``.

    Returns:
        List of rows, each a list of cell strings with trailing blanks removed.
    """
    rows = []
    for _, row in frame.iterrows():
        cells = ["" if pd.isna(cell) else str(cell) for cell in row.tolist()]
        while cells and not cells[-1].strip():
            cells.pop()
        rows.append(cells)
    return rows


def _find_header(rows: list[list[str]], start: int) -> int | None:
    """Locate the header row of a table starting at ``start``.

    Worksheets interleave prose (single-cell rows) between the table title and
    its header, and the gap varies by edition, so the header is identified by
    shape: the first multi-cell row whose data columns are all non-numeric.

    Args:
        rows: Worksheet rows.
        start: Index of the table title row.

    Returns:
        Index of the header row, or None if none is found before the next
        table title.
    """
    for idx in range(start + 1, len(rows)):
        cells = rows[idx]
        if idx > start and _TABLE_RE.search(cells[0] if cells else ""):
            return None
        if len(cells) < 2 or not cells[0].strip():
            continue
        if all(pd.isna(_parse_value(cell)) for cell in cells[1:] if cell.strip()):
            return idx
    return None


def _year_band(rows: list[list[str]], header_idx: int) -> dict[int, str]:
    """Read the year band row sitting above a header row.

    Editions up to 2016-17 put the reporting years in their own row above the
    column headers, spanning merged cells, so a header like ``"First offences"``
    carries no year of its own. Later editions embed the year in each header
    instead and have no band row.

    Args:
        rows: Worksheet rows.
        header_idx: Index of the table's header row.

    Returns:
        Mapping of column index to year label, forward-filled across the
        columns a merged year cell spans. Empty if there is no band row.

    Example:
        >>> _year_band([["", "2015/16", "2016/17"], ["Age band", "a", "b", "c"]], 1)
        {1: '2015-16', 2: '2016-17', 3: '2016-17'}
    """
    if header_idx == 0:
        return {}
    band_row = rows[header_idx - 1]
    years = {idx: _normalise_year(cell) for idx, cell in enumerate(band_row) if _normalise_year(cell)}
    if not years:
        return {}

    filled: dict[int, str] = {}
    current = None
    for idx in range(1, max(len(band_row), len(rows[header_idx]))):
        current = years.get(idx, current)
        if current:
            filled[idx] = current
    return filled


def _previous_year(year: str) -> str:
    """Step a ``YYYY-YY`` financial year label back by one year.

    Args:
        year: Financial year label.

    Returns:
        The preceding financial year label.

    Example:
        >>> _previous_year("2021-22")
        '2020-21'
    """
    start = int(year[:4])
    return f"{start - 1}-{str(start)[-2:]}"


def _fix_leading_year(columns: list[tuple[int, str | None, str]]) -> list[tuple[int, str | None, str]]:
    """Repair a leading comparison column whose header year is mislabelled.

    Every table in this series leads with a prior-year comparison before the
    reporting year's own columns. A handful of editions typo that header with
    the reporting year (Table 4d of the 2021-22 edition), which collides two
    distinct series onto one key. Where the leading column duplicates a later
    column's year and measure, its year is stepped back to the prior year.

    Args:
        columns: Column tuples of index, year and measure.

    Returns:
        Column tuples with any mislabelled leading year corrected.

    Example:
        >>> _fix_leading_year([(1, "2021-22", "first_pct"), (4, "2021-22", "first_pct")])
        [(1, '2020-21', 'first_pct'), (4, '2021-22', 'first_pct')]
    """
    if len(columns) < 2:
        return columns
    lead_idx, lead_year, lead_measure = columns[0]
    if lead_year and any(year == lead_year and measure == lead_measure for _, year, measure in columns[1:]):
        logger.debug("Leading column year %s duplicates a later column; treating as prior year", lead_year)
        return [(lead_idx, _previous_year(lead_year), lead_measure), *columns[1:]]
    return columns


def _parse_table(table_id: str, rows: list[list[str]], header_idx: int, default_year: str | None) -> list[dict]:
    """Reshape one table into tidy records.

    Args:
        table_id: Table identifier, e.g. ``"1a"``.
        rows: Worksheet rows.
        header_idx: Index of the table's header row.
        default_year: Year to attribute to columns whose header omits one.

    Returns:
        List of record dicts with table, breakdown, category, year, measure
        and value.
    """
    header = rows[header_idx]
    label = _clean(header[0]).lower()
    breakdown = _BREAKDOWN_BY_LABEL.get(label)
    if breakdown is None:
        breakdown = next((value for key, value in _BREAKDOWN_BY_LABEL.items() if key in label), "other")

    band = _year_band(rows, header_idx) if not any(_normalise_year(cell) for cell in header[1:]) else {}

    columns = []
    for col_idx, cell in enumerate(header[1:], start=1):
        if not cell.strip():
            continue
        year = _normalise_year(cell) or band.get(col_idx) or default_year
        columns.append((col_idx, year, _measure_from_header(cell)))
    if not columns:
        return []
    columns = _fix_leading_year(columns)

    records = []
    for row in rows[header_idx + 1 :]:
        if not row or not row[0].strip():
            break
        if _TABLE_RE.search(row[0]):
            break
        category = _normalise_category(row[0])
        for col_idx, year, measure in columns:
            if breakdown == "summary":
                # Table 5 carries its year in the label column, not the header
                year = _normalise_year(category) or year
                records.append(
                    {
                        "table": table_id,
                        "breakdown": breakdown,
                        "category": "Total",
                        "year": year,
                        "measure": measure,
                        "value": _parse_value(row[col_idx]) if col_idx < len(row) else float("nan"),
                    }
                )
                continue
            records.append(
                {
                    "table": table_id,
                    "breakdown": breakdown,
                    "category": category,
                    "year": year,
                    "measure": measure,
                    "value": _parse_value(row[col_idx]) if col_idx < len(row) else float("nan"),
                }
            )
    return records


def _rescale_percentages(df: pd.DataFrame) -> pd.DataFrame:
    """Rescale fractional percentages to 0-100.

    Editions up to 2016-17 publish shares as fractions. Every percentage in
    this bulletin is a share of a caseload that is materially above 1%, so a
    column whose maximum is at most 1.0 can only be fractional.

    Args:
        df: Parsed records.

    Returns:
        The frame with fractional percentage measures rescaled in place.
    """
    is_pct = df["measure"].str.endswith("_pct")
    values = df.loc[is_pct, "value"]
    if not values.empty and values.max(skipna=True) <= 1.0:
        df.loc[is_pct, "value"] = values * 100
    return df


def list_publications(base_url: str = PUBLICATION_URL) -> list[dict]:
    """List every annual edition linked from the series index.

    Args:
        base_url: URL of the first time entrant statistics index page.

    Returns:
        List of dicts with ``url`` and ``year`` (e.g. ``"2024-25"``), newest
        first.

    Raises:
        FirstTimeEntrantsNotFoundError: If the index cannot be fetched or no
            editions are found.

    Example:
        >>> pubs = list_publications()
        >>> pubs[0]["year"] >= pubs[-1]["year"]
        True
    """
    try:
        soup = fetch_soup(base_url)
    except Exception as e:
        raise FirstTimeEntrantsNotFoundError(f"Failed to fetch index page {base_url}: {e}") from e

    publications: dict[str, dict] = {}
    for anchor in cast("list[Tag]", soup.find_all("a", href=True)):
        href = cast("str", anchor["href"])
        if "/publications/" not in href:
            continue
        url = urljoin(base_url, href)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        for pattern in _SLUG_YEAR_RES:
            match = pattern.search(slug)
            if match:
                publications[url] = {"url": url, "year": f"{match.group(1)}-{match.group(2)[-2:]}"}
                break

    if not publications:
        raise FirstTimeEntrantsNotFoundError(f"No editions found on {base_url}")

    return sorted(publications.values(), key=lambda p: p["year"], reverse=True)


def find_latest_publication(base_url: str = PUBLICATION_URL) -> dict:
    """Find the most recent annual edition.

    Args:
        base_url: URL of the first time entrant statistics index page.

    Returns:
        Dict with ``url`` and ``year`` for the newest edition.

    Raises:
        FirstTimeEntrantsNotFoundError: If no edition can be located.

    Example:
        >>> latest = find_latest_publication()
        >>> len(latest["year"])
        7
    """
    latest = list_publications(base_url)[0]
    logger.info(f"Latest first time entrants edition: {latest['year']} ({latest['url']})")
    return latest


def find_data_file(publication_url: str) -> str:
    """Resolve an edition's publication page to its published tables file.

    Args:
        publication_url: URL of a per-edition publication page.

    Returns:
        URL of the spreadsheet (``.ods`` preferred, ``.xlsx`` otherwise).

    Raises:
        FirstTimeEntrantsNotFoundError: If the page cannot be fetched or holds
            no spreadsheet.

    Example:
        >>> url = find_data_file(find_latest_publication()["url"])
        >>> url.lower().endswith((".ods", ".xlsx"))
        True
    """
    # ODS is the accessible format and is preferred where both are published
    for extension in (".ods", ".xls"):
        try:
            links = scrape_file_links(publication_url, extension)
        except Exception as e:
            raise FirstTimeEntrantsNotFoundError(f"Failed to fetch publication page {publication_url}: {e}") from e
        if links:
            return links[0]["url"]

    raise FirstTimeEntrantsNotFoundError(f"No spreadsheet linked from {publication_url}")


def download_file(url: str, cache_ttl_hours: int = _CACHE_TTL_HOURS, force_refresh: bool = False) -> Path:
    """Download a published tables file with caching.

    Args:
        url: URL of the spreadsheet.
        cache_ttl_hours: Cache validity in hours (default: 180 days).
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        Path to the downloaded (or cached) file.

    Raises:
        FirstTimeEntrantsNotFoundError: If the download fails.
    """
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise FirstTimeEntrantsNotFoundError(str(e)) from e


def parse_data(file_path: Path) -> pd.DataFrame:
    """Parse every table in a published tables file into one tidy frame.

    Tables are located by scanning each worksheet for ``Table Na:`` titles
    rather than by worksheet name, because worksheet names and numbering are
    not stable across editions.

    Args:
        file_path: Path to the ODS or XLSX file.

    Returns:
        DataFrame with columns table, breakdown, category, year, measure,
        value.

    Raises:
        FirstTimeEntrantsError: If the workbook contains no parseable tables.
    """
    path = Path(file_path)
    engine = "odf" if path.suffix.lower() == ".ods" else None
    sheets = pd.read_excel(path, sheet_name=None, engine=engine, header=None)

    records: list[dict] = []
    for name, frame in sheets.items():
        if re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") in _NON_DATA_SHEETS:
            continue
        rows = _sheet_rows(frame)
        sheet_year = next((_normalise_year(row[0]) for row in rows[:2] if row and _normalise_year(row[0])), None)

        seen: set[str] = set()
        for idx, cells in enumerate(rows):
            if not cells or not cells[0].strip():
                continue
            match = _TABLE_RE.search(cells[0])
            if not match:
                continue
            table_id = match.group(1).lower()
            if table_id in seen:
                continue
            header_idx = _find_header(rows, idx)
            if header_idx is None:
                logger.warning(f"No header found for Table {table_id} in sheet {name}")
                continue
            table_year = _normalise_year(cells[0]) or sheet_year
            parsed = _parse_table(table_id, rows, header_idx, table_year)
            if parsed:
                seen.add(table_id)
                records.extend(parsed)

    if not records:
        raise FirstTimeEntrantsError(f"No tables found in {file_path}")

    return _rescale_percentages(pd.DataFrame.from_records(records))


def get_latest_data(breakdown: str = "all", force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the latest annual edition.

    Args:
        breakdown: Breakdown to return (see :func:`list_breakdowns`), or
            ``"all"`` for every breakdown in one frame.
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame with columns table, breakdown, category, year, measure,
        value.

    Raises:
        FirstTimeEntrantsNotFoundError: If ``breakdown`` is not recognised.

    Example:
        >>> df = get_latest_data("age_band")
        >>> set(df["breakdown"]) == {"age_band"}
        True
    """
    latest = find_latest_publication()
    df = parse_data(download_file(find_data_file(latest["url"]), force_refresh=force_refresh))

    if breakdown == "all":
        return df

    available = sorted(df["breakdown"].unique())
    if breakdown not in available:
        raise FirstTimeEntrantsNotFoundError(f"Unknown breakdown '{breakdown}'. Available: {', '.join(available)}")

    return df[df["breakdown"] == breakdown].reset_index(drop=True)


def list_breakdowns(force_refresh: bool = False) -> list[str]:
    """List the breakdowns available in the latest edition.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Sorted list of breakdown keys.

    Example:
        >>> "gender" in list_breakdowns()
        True
    """
    return sorted(get_latest_data(force_refresh=force_refresh)["breakdown"].unique())


def get_by_age(force_refresh: bool = False) -> pd.DataFrame:
    """Get first offences and convictions by age band (Tables 1a-1d).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of counts and percentages by age band.

    Example:
        >>> df = get_by_age()
        >>> "10 to 17" in set(df["category"])
        True
    """
    return get_latest_data("age_band", force_refresh=force_refresh)


def get_by_gender(force_refresh: bool = False) -> pd.DataFrame:
    """Get first offences and convictions by gender (Tables 2a-2d).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of counts and percentages by gender.

    Example:
        >>> df = get_by_gender()
        >>> set(df["breakdown"]) == {"gender"}
        True
    """
    return get_latest_data("gender", force_refresh=force_refresh)


def get_by_offence(force_refresh: bool = False) -> pd.DataFrame:
    """Get first offences and convictions by offence classification.

    Covers Tables 3a-3d plus Table 3e, which splits first offences into
    convictions and diversions against a common denominator.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of counts and percentages by offence classification.

    Example:
        >>> df = get_by_offence()
        >>> "Motoring" in set(df["category"])
        True
    """
    return get_latest_data("offence", force_refresh=force_refresh)


def get_by_disposal(force_refresh: bool = False) -> pd.DataFrame:
    """Get first offences and convictions by disposal category (Tables 4a-4d).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of counts and percentages by disposal category.

    Example:
        >>> df = get_by_disposal()
        >>> "Imprisonment" in set(df["category"])
        True
    """
    return get_latest_data("disposal", force_refresh=force_refresh)


def get_headline_series(force_refresh: bool = False) -> pd.DataFrame:
    """Get the headline first time offender percentage series (Table 5).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        DataFrame with one row per year, sorted oldest first, giving first time
        offenders as a percentage of all offenders dealt with.

    Example:
        >>> df = get_headline_series()
        >>> len(df) >= 10
        True
        >>> df["year"].is_monotonic_increasing
        True
    """
    df = get_latest_data("summary", force_refresh=force_refresh)
    return df.sort_values("year").reset_index(drop=True)


def validate_data(df: pd.DataFrame, min_records: int = 500) -> bool:
    """Validate a parsed first time entrants DataFrame.

    Checks structure and sanity:

    - Required columns are present.
    - There are at least ``min_records`` rows.
    - Years are well formed and within a plausible range.
    - Percentage measures fall between 0 and 100.
    - Counts are non-negative.

    Args:
        df: DataFrame to validate.
        min_records: Minimum acceptable number of rows.

    Returns:
        True if the data passes all checks.

    Raises:
        FirstTimeEntrantsValidationError: If any validation check fails.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        Traceback (most recent call last):
        ...
        bolster.data_sources.justice.first_time_entrants.FirstTimeEntrantsValidationError: DataFrame is empty
    """
    if df is None or df.empty:
        raise FirstTimeEntrantsValidationError("DataFrame is empty")

    required = {"table", "breakdown", "category", "year", "measure", "value"}
    missing = required - set(df.columns)
    if missing:
        raise FirstTimeEntrantsValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise FirstTimeEntrantsValidationError(f"Too few records: {len(df)} < {min_records}")

    years = df["year"].dropna()
    if years.empty:
        raise FirstTimeEntrantsValidationError("No years parsed")
    if not years.str.fullmatch(r"\d{4}-\d{2}").all():
        raise FirstTimeEntrantsValidationError("Malformed year labels found")
    starts = years.str[:4].astype(int)
    if starts.min() < 2000 or starts.max() > 2100:
        raise FirstTimeEntrantsValidationError(f"Year range out of bounds: {starts.min()}-{starts.max()}")

    percentages = df.loc[df["measure"].str.endswith("_pct"), "value"].dropna()
    if not percentages.empty and (percentages.min() < 0 or percentages.max() > 100):
        raise FirstTimeEntrantsValidationError(f"Percentage out of bounds: {percentages.min()}-{percentages.max()}")

    counts = df.loc[df["measure"].str.endswith("_count"), "value"].dropna()
    if (counts < 0).any():
        raise FirstTimeEntrantsValidationError("Negative counts found")

    return True


def clear_cache() -> int:
    """Clear all cached first time entrants files.

    Returns:
        Number of files deleted.
    """
    return _downloader.clear()
