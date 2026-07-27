"""Court prosecutions, convictions and out of court disposals in Northern Ireland.

Provides access to the Department of Justice NI annual bulletin covering every
route by which a criminal case is disposed of in Northern Ireland: prosecution
at the Crown Court or magistrates' courts, and the out of court disposals
(cautions, penalty notices, discretionary disposals, informed warnings) issued
without a court appearance.

The bulletin publishes roughly thirty sub-tables across sixteen worksheets,
split between two shapes:

- **Time series** - eleven years of history in one table, e.g. cases dealt
  with, prosecutions and convictions by court, out of court disposals by type,
  and diversionary disposals by gender and age band.
- **Latest-year cross-tabs** - the reference year broken down by defendant
  gender, age band, offence classification, sentencing disposal, and custody
  type.

All sub-tables are parsed into a single long frame so heterogeneous layouts
can be queried uniformly, with typed accessors provided for the series that
are most often wanted.

Data Source:
    **Series Page**:
    https://www.justice-ni.gov.uk/articles/court-prosecution-conviction-and-out-court-disposal-statistics

    The module scrapes this page for yearly publications and follows through
    to the accessibility-format ODS workbook attached to each one. Every
    workbook carries its own decade of history, so a single download gives a
    complete series.

Update Frequency: Annual
Geographic Coverage: Northern Ireland
Reference Period: 2007 - present (each bulletin covers ~11 years)

.. note::
    Table numbering is *not* stable across years - the 2018 bulletin opens at
    table 1a where 2022 onward opens at table 1. Typed accessors therefore
    match on table title rather than identifier, and older bulletins may omit
    tables introduced later.

Example:
    >>> from bolster.data_sources.justice import prosecutions_convictions as pcd
    >>> df = pcd.get_prosecutions_convictions()  # doctest: +SKIP
    >>> df[df.court == "Crown Court"].conviction_rate.iloc[-1]  # doctest: +SKIP
    0.869
"""

import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import bs4
import pandas as pd
from odf.opendocument import load as load_ods
from odf.table import Table

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import session

from ._base import _parse_value, _sheet_rows, _strip_note_refs

logger = logging.getLogger(__name__)

BASE_URL = "https://www.justice-ni.gov.uk"
SERIES_URL = f"{BASE_URL}/articles/court-prosecution-conviction-and-out-court-disposal-statistics"

# Each block within a worksheet opens with a "Table 2a: ..." marker row
_TABLE_MARKER_RE = re.compile(r"^Tables?\s*(\d+)\s*([a-z])?\s*[:,]", re.IGNORECASE)

# Worksheets open with "Worksheet 3: Tables 3a, 3b and 3c - <title>"
_WORKSHEET_RE = re.compile(r"^Worksheet\s+(\d+)\s*[:.]\s*Tables?\s*[\d a-z,and]*[-:]\s*(.*)$", re.IGNORECASE)

# Spreadsheet autofill leaves empty "Column1"/"Column2" headers past the data
_FILLER_COL_RE = re.compile(r"^Column\d+$", re.IGNORECASE)

# Publication slugs end in the reference year, e.g. "...-statistics-2021"
_YEAR_IN_SLUG_RE = re.compile(r"(?:^|[-/])(\d{4})(?:$|[-/])")

# Bulletins are annual, so a long cache is safe
_CACHE_TTL_HOURS = 24 * 180

_downloader = CachedDownloader("doj_prosecutions_convictions", timeout=60)


class ProsecutionsDataError(Exception):
    """Base exception for prosecutions and convictions data errors."""


class ProsecutionsDataNotFoundError(ProsecutionsDataError):
    """Raised when a publication, workbook, or table cannot be located."""


class ProsecutionsValidationError(ProsecutionsDataError):
    """Raised when parsed data fails validation."""


def list_publications() -> pd.DataFrame:
    """List every bulletin in the series.

    Returns:
        DataFrame with ``year``, ``title`` and ``url`` columns, most recent
        first.

    Raises:
        ProsecutionsDataNotFoundError: If the series page cannot be fetched or
            contains no publications.
    """
    try:
        response = session.get(SERIES_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise ProsecutionsDataNotFoundError(f"Failed to fetch series page {SERIES_URL}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, features="html.parser")

    records: dict[str, dict[str, object]] = {}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/publications/" not in href:
            continue
        title = link.get_text(strip=True)
        if "disposal" not in title.lower() and "conviction" not in title.lower():
            continue
        url = urljoin(BASE_URL, href)
        years = _YEAR_IN_SLUG_RE.findall(href)
        if not years:
            continue
        records.setdefault(url, {"year": int(years[-1]), "title": title, "url": url})

    if not records:
        raise ProsecutionsDataNotFoundError(f"No publications found on {SERIES_URL}")

    return pd.DataFrame(list(records.values())).sort_values("year", ascending=False).reset_index(drop=True)


def find_publication(year: int | None = None) -> dict[str, object]:
    """Locate a bulletin by reference year.

    Args:
        year: Reference year, e.g. ``2025``. Defaults to the most recent.

    Returns:
        Mapping with ``year``, ``title`` and ``url``.

    Raises:
        ProsecutionsDataNotFoundError: If no publication matches.
    """
    publications = list_publications()
    if year is not None:
        publications = publications[publications.year == year]
        if publications.empty:
            raise ProsecutionsDataNotFoundError(f"No publication found for year {year}")
    return publications.iloc[0].to_dict()


def get_data_file_url(publication_url: str) -> str:
    """Find the ODS workbook attached to a publication page.

    Args:
        publication_url: Publication page URL.

    Returns:
        Absolute URL of the ODS workbook.

    Raises:
        ProsecutionsDataNotFoundError: If the page has no ODS attachment.
    """
    try:
        response = session.get(publication_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise ProsecutionsDataNotFoundError(f"Failed to fetch publication page {publication_url}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, features="html.parser")
    candidates = [
        urljoin(BASE_URL, a["href"]) for a in soup.find_all("a", href=True) if a["href"].lower().endswith(".ods")
    ]

    if not candidates:
        raise ProsecutionsDataNotFoundError(f"No ODS workbook found on {publication_url}")

    # Prefer the accessibility-format tables when several workbooks are attached
    for url in candidates:
        if "accessib" in url.lower():
            return url
    return candidates[0]


def download_file(url: str, force_refresh: bool = False) -> Path:
    """Download and cache an ODS workbook.

    Args:
        url: Workbook URL.
        force_refresh: Bypass the cache.

    Returns:
        Path to the cached file.

    Raises:
        ProsecutionsDataNotFoundError: If the download fails.
    """
    try:
        return _downloader.download(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    except DownloadError as e:
        raise ProsecutionsDataNotFoundError(f"Failed to download {url}: {e}") from e


def _label_column_count(data_rows: list[list[str]]) -> int:
    """Count the leading columns that hold labels rather than values.

    Most tables carry a single label column, but breakdowns such as sentencing
    disposal by gender carry two. A column is a label column when every cell in
    it is non-empty and non-numeric.

    Args:
        data_rows: Body rows of one table block.

    Returns:
        Number of leading label columns, always at least 1.
    """
    width = max(len(row) for row in data_rows)
    count = 0
    for column in range(width):
        cells = [row[column] if column < len(row) else "" for row in data_rows]
        if all(cell.strip() and pd.isna(_parse_value(cell)) for cell in cells):
            count += 1
        else:
            break
    return max(count, 1)


def _split_blocks(rows: list[list[str]]) -> list[tuple[str | None, list[list[str]]]]:
    """Split a worksheet into (title, rows) blocks, one per sub-table.

    Sub-tables are stacked vertically and separated by single-cell marker rows
    such as ``Table 2b: ...``. Any other single-cell row is commentary.

    Args:
        rows: Worksheet rows, excluding the worksheet title row.

    Returns:
        List of (marker row text or None, body rows) pairs.
    """
    blocks: list[tuple[str | None, list[list[str]]]] = []
    title: str | None = None
    pending: list[list[str]] = []

    for row in rows:
        if len(row) == 1:
            if _TABLE_MARKER_RE.match(row[0]):
                if pending:
                    blocks.append((title, pending))
                    pending = []
                title = row[0]
            continue
        pending.append(row)

    if pending:
        blocks.append((title, pending))
    return blocks


def _parse_sheet(sheet_id: str, rows: list[list[str]]) -> list[dict[str, object]]:
    """Reshape one worksheet into long-format records.

    Args:
        sheet_id: Worksheet name, used as a fallback table identifier.
        rows: Raw worksheet rows.

    Returns:
        List of record dicts.
    """
    match = _WORKSHEET_RE.match(rows[0][0]) if rows else None
    worksheet_title = _strip_note_refs(match.group(2)) if match else ""

    records: list[dict[str, object]] = []
    for title, block in _split_blocks(rows[1:]):
        if len(block) < 2:
            continue

        header = [_strip_note_refs(cell) for cell in block[0]]
        body = block[1:]

        if title:
            marker = _TABLE_MARKER_RE.match(title)
            table_id = f"{marker.group(1)}{marker.group(2) or ''}" if marker else sheet_id
            table_title = _strip_note_refs(title.split(":", 1)[1] if ":" in title else title)
        else:
            table_id, table_title = sheet_id, worksheet_title

        label_count = _label_column_count(body)
        for row in body:
            row = row + [""] * (len(header) - len(row))
            labels = [_strip_note_refs(row[i]) for i in range(label_count)]
            for column in range(label_count, len(header)):
                name = header[column].strip()
                if not name or _FILLER_COL_RE.match(name):
                    continue
                records.append(
                    {
                        "table_id": table_id,
                        "table_title": table_title,
                        "row_label": labels[0],
                        "row_group": labels[1] if label_count > 1 else None,
                        "column": name,
                        "value": _parse_value(row[column]),
                    }
                )
    return records


def parse_data(path: Path) -> pd.DataFrame:
    """Parse an ODS workbook into a long frame.

    Args:
        path: Path to the workbook.

    Returns:
        DataFrame with ``table_id``, ``table_title``, ``row_label``,
        ``row_group``, ``column`` and ``value`` columns.

    Raises:
        ProsecutionsDataError: If the workbook cannot be read or holds no data.
    """
    try:
        doc = load_ods(str(path))
    except Exception as e:
        raise ProsecutionsDataError(f"Failed to read workbook {path}: {e}") from e

    tables = {table.getAttribute("name"): table for table in doc.spreadsheet.getElementsByType(Table)}
    data_sheets = sorted((name for name in tables if name.isdigit()), key=int)

    records: list[dict[str, object]] = []
    for name in data_sheets:
        records.extend(_parse_sheet(name, _sheet_rows(tables[name])))

    if not records:
        raise ProsecutionsDataError(f"No data tables found in {path}")

    return pd.DataFrame(records)


def get_latest_data(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get every table from a bulletin in long format.

    Args:
        year: Reference year of the bulletin. Defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame covering all sub-tables.
    """
    publication = find_publication(year)
    url = get_data_file_url(str(publication["url"]))
    logger.info("Using bulletin %s (%s)", publication["year"], url)
    return parse_data(download_file(url, force_refresh=force_refresh))


def list_tables(year: int | None = None) -> pd.DataFrame:
    """List the sub-tables available in a bulletin.

    Args:
        year: Reference year of the bulletin. Defaults to the most recent.

    Returns:
        DataFrame with ``table_id``, ``table_title`` and ``records`` columns.
    """
    df = get_latest_data(year=year)
    return (
        df.groupby("table_id")
        .agg(table_title=("table_title", "first"), records=("value", "size"))
        .reset_index()
        .sort_values("table_id", key=lambda s: s.map(lambda v: (int(re.match(r"\d+", v).group()), v)))
        .reset_index(drop=True)
    )


def _select_table(df: pd.DataFrame, pattern: str) -> pd.DataFrame:
    """Select one sub-table by matching its title.

    Table identifiers shift between bulletin years, so titles are the stable
    key.

    Args:
        df: Long-format frame from :func:`get_latest_data`.
        pattern: Case-insensitive regex matched against ``table_title``.

    Returns:
        The matching rows.

    Raises:
        ProsecutionsDataNotFoundError: If no table title matches.
    """
    matched = df[df.table_title.str.contains(pattern, case=False, regex=True, na=False)]
    if matched.empty:
        raise ProsecutionsDataNotFoundError(f"No table matching {pattern!r} in this bulletin")
    return matched


def _year_columns(table: pd.DataFrame) -> pd.DataFrame:
    """Keep only the bare year columns of a time-series table.

    Several time series append a ``Percentage 2025`` column alongside the
    yearly counts; those are derivable and would break year coercion.

    Args:
        table: Rows of one sub-table.

    Returns:
        The subset whose ``column`` is a four-digit year.
    """
    return table[table.column.str.fullmatch(r"\d{4}", na=False)]


def get_cases_dealt_with(year: int | None = None) -> pd.DataFrame:
    """Get the summary of cases dealt with at court and out of court.

    Args:
        year: Reference year of the bulletin. Defaults to the most recent.

    Returns:
        DataFrame with ``year``, ``category`` and ``cases`` columns.

    Raises:
        ProsecutionsDataNotFoundError: If the bulletin predates this table.
    """
    table = _year_columns(_select_table(get_latest_data(year=year), r"^Cases dealt with"))
    return (
        table.assign(year=table.column.astype(int), category=table.row_label, cases=table.value)[
            ["year", "category", "cases"]
        ]
        .sort_values(["year", "category"])
        .reset_index(drop=True)
    )


def get_prosecutions_convictions(year: int | None = None) -> pd.DataFrame:
    """Get the prosecutions and convictions time series by court type.

    Args:
        year: Reference year of the bulletin. Defaults to the most recent.

    Returns:
        DataFrame with ``year``, ``court``, ``convictions``, ``no_convictions``,
        ``total_findings`` and ``conviction_rate`` (a proportion in [0, 1]).
    """
    df = get_latest_data(year=year)
    table = _year_columns(_select_table(df, r"^Prosecutions and convictions in .* \d{4}\s*-\s*\d{4}$"))

    frames = []
    for title, group in table.groupby("table_title"):
        court = title.split(" in ", 1)[1].split(" in Northern Ireland")[0].strip()
        wide = group.pivot_table(index="column", columns="row_label", values="value", aggfunc="first")
        frames.append(
            pd.DataFrame(
                {
                    "year": wide.index.astype(int),
                    "court": court,
                    "convictions": wide.get("Conviction").to_numpy(),
                    "no_convictions": wide.get("No conviction").to_numpy(),
                    "total_findings": wide.get("Total findings").to_numpy(),
                    "conviction_rate": wide.get("% convictions").to_numpy() / 100,
                }
            )
        )

    return pd.concat(frames, ignore_index=True).sort_values(["year", "court"]).reset_index(drop=True)


def get_out_of_court_disposals(year: int | None = None) -> pd.DataFrame:
    """Get the out of court disposals time series by disposal type.

    Args:
        year: Reference year of the bulletin. Defaults to the most recent.

    Returns:
        DataFrame with ``year``, ``disposal_type`` and ``disposals`` columns.
    """
    table = _year_columns(_select_table(get_latest_data(year=year), r"^Out of court disposals by type"))
    return (
        table.assign(year=table.column.astype(int), disposal_type=table.row_label, disposals=table.value)[
            ["year", "disposal_type", "disposals"]
        ]
        .sort_values(["year", "disposal_type"])
        .reset_index(drop=True)
    )


def get_diversionary_disposals(year: int | None = None, by: str = "gender") -> pd.DataFrame:
    """Get the diversionary disposals time series.

    Args:
        year: Reference year of the bulletin. Defaults to the most recent.
        by: Breakdown to return, either ``"gender"`` or ``"age"``.

    Returns:
        DataFrame with ``year``, ``category`` and ``disposals`` columns.

    Raises:
        ValueError: If ``by`` is not a recognised breakdown.
    """
    patterns = {"gender": r"^Diversionary disposals by gender", "age": r"^Diversionary disposals by age"}
    if by not in patterns:
        raise ValueError(f"Unknown breakdown {by!r}, expected one of {sorted(patterns)}")

    table = _year_columns(_select_table(get_latest_data(year=year), patterns[by]))
    return (
        table.assign(year=table.column.astype(int), category=table.row_label, disposals=table.value)[
            ["year", "category", "disposals"]
        ]
        .sort_values(["year", "category"])
        .reset_index(drop=True)
    )


def validate_data(df: pd.DataFrame, min_records: int = 1000) -> bool:
    """Validate a parsed long frame.

    Args:
        df: Frame from :func:`get_latest_data`.
        min_records: Minimum acceptable record count.

    Returns:
        True if the frame passes every check.

    Raises:
        ProsecutionsValidationError: If the frame is malformed or too small.
    """
    if df is None or df.empty:
        raise ProsecutionsValidationError("DataFrame is empty")

    required = {"table_id", "table_title", "row_label", "row_group", "column", "value"}
    missing = required - set(df.columns)
    if missing:
        raise ProsecutionsValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise ProsecutionsValidationError(f"Too few records: expected at least {min_records}, got {len(df)}")

    if (df.value.dropna() < 0).any():
        raise ProsecutionsValidationError("Negative values found")

    if df.value.isna().mean() > 0.25:
        raise ProsecutionsValidationError(f"Too many unparsed values: {df.value.isna().mean():.1%}")

    return True


def clear_cache() -> int:
    """Clear cached workbooks.

    Returns:
        Number of files removed.
    """
    return _downloader.clear_cache()
