"""PPS Statistical Bulletin.

Provides access to the Public Prosecution Service for Northern Ireland (PPS)
statistical bulletins: the annual account of what happens to every case the
police pass to prosecutors, from file receipt through prosecutorial decision to
court outcome.

Each bulletin publishes a workbook of numbered tables. Series 1 covers files
received, series 2-3 the decisions issued (prosecute, divert, or no
prosecution) with timeliness, series 4 summonses, series 5 court outcomes, and
series 6 the demographic breakdowns of suspects and defendants:

- ``1a`` / ``1b`` / ``1c`` - files received by region, offence, and police source.
- ``2`` - files received by PPS region and file type.
- ``3a`` / ``3b`` - prosecutorial decisions by region and by offence group.
- ``3c`` - decision timeliness in days (median and 80th percentile).
- ``3d`` - decisions issued cross-tabulated by offence group.
- ``4`` - summonses issued by service method.
- ``5a`` / ``5b`` - defendants dealt with at court, and conviction rates.
- ``6a``-``6h`` - suspects and defendants by age, sex, and outcome.

Every table reduces to the same tidy shape: one row per (table, financial year,
category, breakdown) observation.

Data Source:
    **Publication Page**: https://www.ppsni.gov.uk/pps-statistical-bulletin

    The module scrapes this page for bulletin pages, then locates the
    ``... Tables ....xlsx`` workbook published alongside each PDF bulletin.

Update Frequency: Annual (financial year, published the following June)
Geographic Coverage: Northern Ireland
Reference Period: 2016/17 - present

.. note::
    Machine-readable tables begin with the 2017-18 bulletin. Earlier bulletins
    (back to 2012-13) are PDF-only and are not accessible through this module.

.. note::
    ``value`` is not a single unit. Most rows are counts of files, persons, or
    summonses, but table ``3c`` reports **days** and the ``Conviction Rate (%)``
    rows of tables ``5a``/``5b``/``6h`` report a **fraction** between 0 and 1
    (0.86, not 86). Filter on ``table`` and ``category`` before aggregating.

.. note::
    PPS reorganised its regions between 2024/25 and 2025/26 — three regions
    (Belfast, Northern & Western, Southern & Eastern) replaced two (Belfast and
    Eastern, Western and Southern). ``breakdown`` is therefore free text and is
    not comparable across that boundary; ``All PPS`` totals are.

Example:
    >>> from bolster.data_sources.justice import pps_statistical_bulletin as pps
    >>> df = pps.get_latest_data()
    >>> "All PPS" in set(df["breakdown"])
    True
    >>> set(df.columns) >= {"table", "financial_year", "category", "value"}
    True
"""

import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

from bolster.utils.cache import CachedDownloader, bind_download_file, stitch_publications
from bolster.utils.web import fetch_soup, scrape_file_links

logger = logging.getLogger(__name__)

# Publication landing page listing every bulletin back to 2012-13
PUBLICATION_URL = "https://www.ppsni.gov.uk/pps-statistical-bulletin"

# Worksheets carrying front matter rather than statistical tables
_NON_DATA_SHEET_RE = re.compile(r"explanatory|metadata|contents|bulletin|^\d{4}[-/]\d{2}$", re.IGNORECASE)

# Sheet names look like "Table 3A"; the trailing key is normalised to "3a"
_SHEET_NAME_RE = re.compile(r"table\s*([0-9]+[a-z]?)\s*$", re.IGNORECASE)

# Financial years appear as "2025/26", sometimes prefixed "Q1-4 " or padded
_FINANCIAL_YEAR_RE = re.compile(r"(\d{4})\s*/\s*(\d{2})")

# Column-0 headers that introduce a year-block table. Older bulletins label the
# period column "Quarters" and newer ones "Financial Year".
_PERIOD_HEADERS = {"financial year", "quarters", "quarter"}

# Header cells that name a unit rather than a breakdown; the real label sits in
# a merged row above (older bulletins stack "Belfast and Eastern" over "Number")
_UNIT_LABELS = {"number", "%", "n", "rate"}

# Rows that close a table: percentage-change summaries and the contents link
_FOOTER_RE = re.compile(r"^\s*(%\s*change|contents\b|source\b)", re.IGNORECASE)
_DERIVED_COL_RE = re.compile(r"^%?\s*change\b", re.IGNORECASE)
_YEAR_MEASURE_RE = re.compile(r"^(\d{4}\s*/\s*\d{2})\s*\((.+)\)$")

# Suppression markers published in place of a count
_SUPPRESSION_MARKERS = {"*", "-", "#", "..", ":", "n/a", "na"}

# Footnote references trail labels as bare digits, e.g. "Type of Decision 3" or
# "Unknown/Not Applicable1,3". Only stripped after a letter or bracket so that
# genuine numeric labels such as "18-25" survive.
_FOOTNOTE_REF_RE = re.compile(r"(?<=[A-Za-z)\]])\s*\d+(\s*,\s*\d+)*\s*$")

# Bulletins are annual, so a cached workbook stays valid for a long time
_CACHE_TTL_HOURS = 24 * 90

_downloader = CachedDownloader("pps_statistical_bulletin", timeout=60)


class PPSDataError(Exception):
    """Base exception for PPS statistical bulletin errors."""

    pass


class PPSDataNotFoundError(PPSDataError):
    """Raised when a bulletin or its workbook cannot be located or downloaded."""

    pass


class PPSValidationError(PPSDataError):
    """Raised when parsed data fails validation."""

    pass


# download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=False) -> Path,
# raising PPSDataNotFoundError in place of DownloadError.
download_file = bind_download_file(_downloader, PPSDataNotFoundError, _CACHE_TTL_HOURS)


def _clean_label(text: str) -> str:
    """Normalise a row or column label from the workbook.

    Collapses whitespace and removes trailing footnote references, which PPS
    appends without a separator.

    Args:
        text: Raw cell text.

    Returns:
        Cleaned label.

    Example:
        >>> _clean_label("Type of Decision 3  ")
        'Type of Decision'
        >>> _clean_label("Unknown/Not Applicable1,3")
        'Unknown/Not Applicable'
        >>> _clean_label("18-25")
        '18-25'
        >>> _clean_label("76 over")
        '76 over'
    """
    collapsed = " ".join(str(text).split())
    return _FOOTNOTE_REF_RE.sub("", collapsed).strip()


def _parse_financial_year(text: str) -> str | None:
    """Extract a normalised financial year from a period label.

    Args:
        text: Period cell text, e.g. ``"Q1-4 2017/18"`` or ``" 2025/26"``.

    Returns:
        Financial year as ``"2017/18"``, or ``None`` if absent.

    Example:
        >>> _parse_financial_year("Q1-4 2017/18")
        '2017/18'
        >>> _parse_financial_year(" 2025/26 2")
        '2025/26'
        >>> _parse_financial_year("All Files") is None
        True
    """
    match = _FINANCIAL_YEAR_RE.search(str(text))
    return f"{match.group(1)}/{match.group(2)}" if match else None


def _parse_value(text: str) -> tuple[float, str | None]:
    """Convert a raw cell into a numeric value and a suppression marker.

    Args:
        text: Raw cell text.

    Returns:
        Tuple of (value, marker). ``value`` is NaN when the cell is suppressed
        or unparseable; ``marker`` carries the published symbol (``*``, ``-``,
        ``#``) when one was used, otherwise ``None``.

    Example:
        >>> _parse_value("1,234")
        (1234.0, None)
        >>> value, marker = _parse_value("#")
        >>> marker
        '#'
        >>> import math
        >>> math.isnan(value)
        True
    """
    cleaned = str(text).strip()
    if cleaned.lower() in _SUPPRESSION_MARKERS:
        return float("nan"), cleaned
    if not cleaned:
        return float("nan"), None

    try:
        return float(cleaned.replace(",", "").replace("%", "")), None
    except ValueError:
        return float("nan"), None


def _is_footer(label: str) -> bool:
    """Check whether a row label closes the data region of a sheet.

    Example:
        >>> _is_footer("% Change (Files Received)")
        True
        >>> _is_footer("All Files")
        False
    """
    return bool(_FOOTER_RE.match(str(label)))


def _sheet_rows(frame: pd.DataFrame) -> list[list[str]]:
    """Convert a header-less worksheet frame into rows of stripped strings."""
    return [["" if pd.isna(cell) else str(cell).strip() for cell in row] for row in frame.itertuples(index=False)]


def _column_labels(rows: list[list[str]], header_idx: int, first_value_col: int) -> dict[int, str]:
    """Resolve breakdown labels for each value column of a table.

    Older bulletins stack a merged region label above a units row, so a header
    cell reading ``"Number"`` means the real label is in a row above. Each
    column is therefore walked upwards until a meaningful label is found.

    Args:
        rows: All rows of the sheet.
        header_idx: Index of the header row.
        first_value_col: Index of the first column holding values.

    Returns:
        Mapping of column index to breakdown label, omitting unlabelled columns.
    """
    header = rows[header_idx]
    labels: dict[int, str] = {}

    for col in range(first_value_col, len(header)):
        label = _clean_label(header[col])
        row_idx = header_idx
        while (not label or label.lower() in _UNIT_LABELS) and row_idx > 0:
            row_idx -= 1
            above = rows[row_idx]
            candidate = _clean_label(above[col]) if col < len(above) else ""
            if candidate and candidate.lower() not in _UNIT_LABELS:
                label = candidate
                break
        if label and label.lower() not in _UNIT_LABELS:
            labels[col] = label

    return labels


def _parse_year_blocks(rows: list[list[str]]) -> list[dict]:
    """Parse a sheet laid out as period-labelled blocks.

    These sheets carry a header row whose first column is ``Financial Year``
    (or ``Quarters`` in older bulletins), the row dimension in the second
    column, and breakdowns across the remaining columns. The period is stated
    only on the first row of each year and is carried forward.

    Args:
        rows: All rows of the sheet.

    Returns:
        List of observation dicts, empty if the sheet has no such header.
    """
    header_indices = [idx for idx, row in enumerate(rows) if row and _clean_label(row[0]).lower() in _PERIOD_HEADERS]
    if not header_indices:
        return []

    records: list[dict] = []
    for block_no, header_idx in enumerate(header_indices):
        next_header = header_indices[block_no + 1] if block_no + 1 < len(header_indices) else len(rows)
        dimension = _clean_label(rows[header_idx][1]) if len(rows[header_idx]) > 1 else ""
        labels = _column_labels(rows, header_idx, first_value_col=2)
        financial_year = None

        for row in rows[header_idx + 1 : next_header]:
            if not row:
                continue
            if _is_footer(row[0]):
                break

            financial_year = _parse_financial_year(row[0]) or financial_year
            category = _clean_label(row[1]) if len(row) > 1 else ""
            if not category or not financial_year:
                continue

            for col, breakdown in labels.items():
                if col >= len(row):
                    continue
                value, marker = _parse_value(row[col])
                if pd.isna(value) and marker is None:
                    continue
                records.append(
                    {
                        "financial_year": financial_year,
                        "dimension": dimension or None,
                        "category": category,
                        "breakdown": breakdown,
                        "value": value,
                        "marker": marker,
                    }
                )

    return records


def _split_year_measure(label: str) -> tuple[str | None, str]:
    """Split a column header into its period and the measure it reports.

    Args:
        label: Cleaned column header.

    Returns:
        Tuple of financial year (``None`` when the header names no period) and
        the measure to use as the breakdown.

    >>> _split_year_measure("2025/26 (% Share)")
    ('2025/26', '% Share')
    >>> _split_year_measure("Q1-4 2017/18")
    ('2017/18', 'Number')
    >>> _split_year_measure("Belfast Region")
    (None, 'Belfast Region')
    """
    match = _YEAR_MEASURE_RE.match(label)
    if match:
        return _parse_financial_year(match.group(1)), match.group(2).strip()

    year = _parse_financial_year(label)
    if year:
        residual = _FINANCIAL_YEAR_RE.sub("", re.sub(r"q\s*\d+\s*(-\s*\d+)?", "", label, flags=re.IGNORECASE))
        if not re.search(r"[a-z0-9]", residual, re.IGNORECASE):
            return year, "Number"
    return None, label


def _parse_matrix(rows: list[list[str]]) -> list[dict]:
    """Parse a sheet laid out as a single cross-tabulation.

    These sheets state the period in the subtitle, then give row labels in the
    first column and breakdowns across the header row.

    Args:
        rows: All rows of the sheet.

    Returns:
        List of observation dicts, empty if no period or data region is found.
    """
    financial_year = next((fy for row in rows[:5] for cell in row if (fy := _parse_financial_year(cell))), None)
    if not financial_year:
        return []

    first_data_idx = next(
        (
            idx
            for idx, row in enumerate(rows)
            if len(row) > 2
            and not _is_footer(row[0])
            and _clean_label(row[0])
            and sum(1 for cell in row[1:] if not pd.isna(_parse_value(cell)[0])) >= 2
        ),
        None,
    )
    if first_data_idx is None or first_data_idx == 0:
        return []

    header_idx = next((idx for idx in range(first_data_idx - 1, -1, -1) if any(cell for cell in rows[idx][1:])), None)
    if header_idx is None:
        return []

    dimension = _clean_label(rows[header_idx][0]) or None
    labels = _column_labels(rows, header_idx, first_value_col=1)

    # Comparison tables (1b, 1c) key columns by period rather than breakdown, so
    # the period is carried forward across the measure columns that follow it.
    # Derived change columns are dropped: they are computable and belong to no
    # single period.
    columns: dict[int, tuple[str, str]] = {}
    current_year = financial_year
    for col in sorted(labels):
        label = labels[col]
        if _DERIVED_COL_RE.match(label):
            continue
        col_year, breakdown = _split_year_measure(label)
        if col_year:
            current_year = col_year
        columns[col] = (current_year, breakdown)

    records: list[dict] = []
    for row in rows[first_data_idx:]:
        if not row or _is_footer(row[0]):
            break
        category = _clean_label(row[0])
        if not category:
            continue
        for col, (col_year, breakdown) in columns.items():
            if col >= len(row):
                continue
            value, marker = _parse_value(row[col])
            if pd.isna(value) and marker is None:
                continue
            records.append(
                {
                    "financial_year": col_year,
                    "dimension": dimension,
                    "category": category,
                    "breakdown": breakdown,
                    "value": value,
                    "marker": marker,
                }
            )

    return records


def _parse_sheet(table: str, title: str, rows: list[list[str]]) -> pd.DataFrame:
    """Reshape one worksheet into tidy long format.

    Year-block layout is attempted first; sheets without a period header fall
    back to the cross-tabulation layout.

    Args:
        table: Normalised table key, e.g. ``"3a"``.
        title: Sheet title taken from its first row.
        rows: All rows of the sheet.

    Returns:
        DataFrame of observations, empty if the sheet has no parseable data.
    """
    records = _parse_year_blocks(rows) or _parse_matrix(rows)
    if not records:
        logger.warning(f"No parseable data in sheet 'Table {table}'; skipping")
        return pd.DataFrame()

    df = pd.DataFrame.from_records(records)
    df.insert(0, "table", table)
    df.insert(1, "title", title)
    df.insert(3, "year", df["financial_year"].str[:4].astype(int))
    return df


def list_publications(base_url: str = PUBLICATION_URL) -> list[dict]:
    """List every bulletin linked from the publication page.

    Args:
        base_url: URL of the PPS statistical bulletin listing page.

    Returns:
        List of dicts with ``title``, ``url``, ``financial_year``, ``year`` and
        ``quarters`` (``None`` for annual bulletins), newest first.

    Raises:
        PPSDataNotFoundError: If the page cannot be fetched or lists no
            bulletins.

    Example:
        >>> pubs = list_publications()
        >>> pubs[0]["year"] >= pubs[-1]["year"]
        True
        >>> pubs[0]["url"].startswith("https://www.ppsni.gov.uk")
        True
    """
    try:
        soup = fetch_soup(base_url)
    except Exception as e:
        raise PPSDataNotFoundError(f"Failed to fetch publication page {base_url}: {e}") from e

    publications: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        title = " ".join(anchor.get_text().split())
        if "statistical bulletin" not in title.lower():
            continue
        # Listing pages date bulletins as "2025-26"; tables use "2025/26"
        financial_year = _parse_financial_year(title.replace("-", "/"))
        if not financial_year:
            continue
        quarters = re.search(r"quarters?\s+([0-9]+(?:\s*-\s*[0-9]+)?)", title, re.IGNORECASE)
        url = urljoin(base_url, anchor["href"])
        publications[url] = {
            "title": title,
            "url": url,
            "financial_year": financial_year,
            "year": int(financial_year[:4]),
            "quarters": re.sub(r"\s+", "", quarters.group(1)) if quarters else None,
        }

    if not publications:
        raise PPSDataNotFoundError(f"No bulletins found on {base_url}")

    return sorted(
        publications.values(),
        key=lambda p: (p["year"], p["quarters"] or "zzz"),
        reverse=True,
    )


def find_publication_xlsx(publication_url: str) -> str:
    """Find the tables workbook published alongside a bulletin PDF.

    Args:
        publication_url: URL of a bulletin page from :func:`list_publications`.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        PPSDataNotFoundError: If the page cannot be fetched or carries no
            workbook. Bulletins before 2017-18 are PDF-only.

    Example:
        >>> pubs = list_publications()
        >>> find_publication_xlsx(pubs[0]["url"]).endswith(".xlsx")
        True
    """
    try:
        links = scrape_file_links(publication_url, ".xlsx")
    except Exception as e:
        raise PPSDataNotFoundError(f"Failed to fetch bulletin page {publication_url}: {e}") from e

    if not links:
        raise PPSDataNotFoundError(
            f"No tables workbook found on {publication_url} (bulletins before 2017-18 are PDF-only)"
        )

    return links[0]["url"]


def parse_data(file_path: Path) -> pd.DataFrame:
    """Parse every statistical table from a bulletin workbook.

    Args:
        file_path: Path to the ``.xlsx`` workbook.

    Returns:
        DataFrame with columns table, title, financial_year, year, dimension,
        category, breakdown, value, marker.

    Raises:
        PPSDataNotFoundError: If the workbook cannot be read.
        PPSDataError: If the workbook contains no parseable tables.
    """
    try:
        book = pd.read_excel(Path(file_path), sheet_name=None, header=None)
    except (OSError, ValueError) as e:
        raise PPSDataNotFoundError(f"Failed to read workbook {file_path}: {e}") from e

    frames = []
    for sheet_name, frame in book.items():
        match = _SHEET_NAME_RE.match(sheet_name.strip())
        if not match or _NON_DATA_SHEET_RE.search(sheet_name):
            continue
        rows = _sheet_rows(frame)
        if not rows:
            continue
        title = _clean_label(rows[0][0]) if rows[0] else ""
        parsed = _parse_sheet(match.group(1).lower(), title, rows)
        if not parsed.empty:
            frames.append(parsed)

    if not frames:
        raise PPSDataError(f"No parseable tables found in {file_path}")

    return pd.concat(frames, ignore_index=True)


def get_latest_data(table: str = "all", force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the most recent bulletin.

    Each annual bulletin restates the prior financial year alongside the
    current one, so a single download covers two years.

    Args:
        table: Table key to return (see :func:`list_tables`), or ``"all"``.
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of observations.

    Raises:
        PPSDataNotFoundError: If ``table`` is not present in the bulletin.

    Example:
        >>> df = get_latest_data("3a")
        >>> set(df["table"]) == {"3a"}
        True
    """
    latest = list_publications()[0]
    url = find_publication_xlsx(latest["url"])
    df = parse_data(download_file(url, force_refresh=force_refresh))

    if table == "all":
        return df

    available = sorted(df["table"].unique())
    if table.lower() not in available:
        raise PPSDataNotFoundError(f"Unknown table '{table}'. Available: {', '.join(available)}")

    return df[df["table"] == table.lower()].reset_index(drop=True)


def get_historical_data(max_publications: int = 5, force_refresh: bool = False) -> pd.DataFrame:
    """Stitch several annual bulletins into one long series.

    Annual bulletins are read newest-first and overlapping years are resolved
    in favour of the more recent publication. Quarterly bulletins are skipped
    because their part-year figures are not comparable with annual totals.

    Args:
        max_publications: Maximum number of annual bulletins to download.
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame spanning every year covered by those bulletins.

    Raises:
        PPSDataNotFoundError: If no bulletin could be parsed.

    Example:
        >>> df = get_historical_data(max_publications=2)
        >>> df["financial_year"].nunique() >= 2
        True
    """
    annual = [p for p in list_publications() if p["quarters"] is None]

    def fetch_one(publication: dict) -> pd.DataFrame:
        url = find_publication_xlsx(publication["url"])
        return parse_data(download_file(url, force_refresh=force_refresh))

    try:
        combined = stitch_publications(
            annual[:max_publications],
            fetch_one,
            dedup_keys=["table", "financial_year", "category", "breakdown"],
            sort_keys=["year", "table", "category", "breakdown"],
            errors=(PPSDataError,),
            sort_kind="stable",
        )
    except ValueError as e:
        raise PPSDataNotFoundError("No bulletins could be parsed") from e
    return combined


def list_tables(force_refresh: bool = False) -> list[str]:
    """List the table keys available in the latest bulletin.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Sorted list of table keys, e.g. ``["1a", "1b", ...]``.

    Example:
        >>> "3a" in list_tables()
        True
    """
    return sorted(get_latest_data(force_refresh=force_refresh)["table"].unique())


def get_files_received(force_refresh: bool = False) -> pd.DataFrame:
    """Get files received from police by PPS region and file type (Table 1a).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of file counts by region and file type.

    Example:
        >>> df = get_files_received()
        >>> "All Files" in set(df["category"])
        True
    """
    return get_latest_data("1a", force_refresh=force_refresh)


def get_decisions(force_refresh: bool = False) -> pd.DataFrame:
    """Get prosecutorial decisions issued by region (Table 3a).

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of decision counts, covering prosecution, diversion, and
        no-prosecution outcomes.

    Example:
        >>> df = get_decisions()
        >>> "Total Prosecution" in set(df["category"])
        True
    """
    return get_latest_data("3a", force_refresh=force_refresh)


def get_timeliness(force_refresh: bool = False) -> pd.DataFrame:
    """Get decision timeliness in days (Table 3c).

    Values are **days** from receipt of an investigation file to the issue of a
    decision, reported as a median and an 80th percentile.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame with ``breakdown`` of ``Median`` or ``80th Percentile``.

    Example:
        >>> df = get_timeliness()
        >>> "Median" in set(df["breakdown"])
        True
    """
    return get_latest_data("3c", force_refresh=force_refresh)


def get_court_outcomes(force_refresh: bool = False) -> pd.DataFrame:
    """Get defendants dealt with at court, with conviction rates (Table 5a).

    The ``Conviction Rate (%)`` rows are fractions between 0 and 1, not
    percentages — a published rate of 86% appears as ``0.86``.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Tidy DataFrame of court outcomes by PPS region.

    Example:
        >>> df = get_court_outcomes()
        >>> "Acquitted" in set(df["category"])
        True
    """
    return get_latest_data("5a", force_refresh=force_refresh)


def validate_data(df: pd.DataFrame, min_records: int = 100) -> bool:
    """Validate a parsed PPS bulletin DataFrame.

    Checks structure and sanity:

    - Required columns are present.
    - There are at least ``min_records`` rows.
    - Years fall within a plausible range (2010 onwards).
    - Financial years are well formed.
    - All non-null values are non-negative.

    Args:
        df: DataFrame to validate.
        min_records: Minimum acceptable number of rows.

    Returns:
        True if the data passes all checks.

    Raises:
        PPSValidationError: If any validation check fails.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        Traceback (most recent call last):
        ...
        bolster.data_sources.justice.pps_statistical_bulletin.PPSValidationError: DataFrame is empty
    """
    if df is None or df.empty:
        raise PPSValidationError("DataFrame is empty")

    required = {"table", "financial_year", "year", "category", "breakdown", "value"}
    missing = required - set(df.columns)
    if missing:
        raise PPSValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise PPSValidationError(f"Too few records: {len(df)} < {min_records}")

    if df["year"].min() < 2010 or df["year"].max() > 2100:
        raise PPSValidationError(f"Year range out of bounds: {df['year'].min()}-{df['year'].max()}")

    malformed = df.loc[~df["financial_year"].str.match(r"^\d{4}/\d{2}$"), "financial_year"].unique()
    if len(malformed):
        raise PPSValidationError(f"Malformed financial years: {sorted(malformed)}")

    values = df["value"].dropna()
    if (values < 0).any():
        raise PPSValidationError("Negative values found in column 'value'")

    return True


def clear_cache() -> int:
    """Clear all cached PPS bulletin workbooks.

    Returns:
        Number of files deleted.
    """
    return _downloader.clear()
