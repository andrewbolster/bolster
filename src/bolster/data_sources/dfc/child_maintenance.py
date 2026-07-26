"""Northern Ireland Child Maintenance Service (CMS) Statistics.

Provides access to the Department for Communities quarterly Child Maintenance
Service statistics, covering the full lifecycle of a child maintenance case in
Northern Ireland: applications and how quickly they clear, the composition of
live arrangements, the children they cover, whether paying parents actually
pay, who those parents are, how much money is due versus paid, and what is
recovered through enforcement.

Eight tables are published in a single Excel workbook, one worksheet each. They
have incompatible shapes, so the parser flattens them into one tidy frame keyed
by a ``table`` discriminator:

- ``applications`` - applications received per quarter.
- ``clearances`` - how many applications cleared, and how fast.
- ``arrangements`` - live caseload split by service type.
- ``children_covered`` - children covered, split by paying status.
- ``paying_parents`` - parents due to pay and their compliance bands.
- ``paying_parent_characteristics`` - gender, age, children, cases.
- ``maintenance`` - maintenance due and paid, in pounds.
- ``enforcement`` - collections by enforcement mechanism, in pounds.

Each row is one (table, date, category, subcategory, measure) observation. The
``measure`` column says how to read ``value``: ``count`` for people and cases,
``proportion`` for rates in the 0-1 range, and ``amount_gbp`` for money.

Data Source:
    **Topic Page**:
    https://www.communities-ni.gov.uk/topics/child-maintenance-service-statistics

    The module scrapes this page for quarterly publications, then each
    publication page for its ``.xlsx`` tables file.

Update Frequency: Quarterly
Geographic Coverage: Northern Ireland
Reference Period: December 2019 - present (applications back to December 2015)

.. note::
    A single release does not carry the full back series. Most tables show the
    last few years, ``clearances`` only the last four quarters, and
    ``paying_parent_characteristics`` a single quarter. Use
    :func:`get_historical_data` to stitch releases together — it turns that
    one-quarter demographic snapshot into the full published run.

.. note::
    Worksheet numbering is not stable across releases. Paying Parent
    Characteristics was inserted as Table 6 in June 2024, pushing the money and
    enforcement tables down one, so sheets are identified by their title rather
    than their number.

.. note::
    Counts are rounded to the nearest 10 and money to the nearest 100, so
    components will not always sum exactly to their published totals.

Example:
    >>> from bolster.data_sources.dfc import child_maintenance
    >>> df = child_maintenance.get_latest_data()
    >>> "applications" in set(df["table"])
    True
    >>> set(df["measure"]) <= {"count", "proportion", "amount_gbp"}
    True
"""

import datetime
import io
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import bs4
import pandas as pd

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Topic page listing every quarterly publication
TOPIC_URL = "https://www.communities-ni.gov.uk/topics/child-maintenance-service-statistics"

# Publication slugs end "...-data-<month>-<year>", optionally with a status
# suffix ("-experimental", "-official-statistics-development")
_SLUG_PERIOD_RE = re.compile(
    r"data-(january|february|march|april|may|june|july|august|september|october|november|december)-(\d{4})"
)

_MONTH_NUMBERS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# Table titles -> table key, matched as casefolded substrings of the sheet's
# "Table N. <title>" line. Sheet *numbers* are not stable: Paying Parent
# Characteristics was inserted as Table 6 in the June 2024 release, shifting
# Money Due and Paid and Enforcement Collections down one, so keying on the
# worksheet name would file enforcement figures under maintenance for every
# earlier publication. Ordered because "Paying Parent Characteristics" must be
# tested before the looser "Paying Parents".
_TABLE_TITLE_PATTERNS = (
    ("applications to the northern ireland", "applications"),
    ("application clearances", "clearances"),
    ("composition of child maintenance arrangements", "arrangements"),
    ("children covered", "children_covered"),
    ("paying parent characteristics", "paying_parent_characteristics"),
    ("paying parents", "paying_parents"),
    ("due and paid", "maintenance"),
    ("enforcement collections", "enforcement"),
)

_TABLE_KEYS = frozenset(table for _, table in _TABLE_TITLE_PATTERNS)

# Number of leading rows searched for a sheet's "Table N. <title>" line
_TITLE_SEARCH_ROWS = 8

# Money tables; everything else is people, cases or proportions
_AMOUNT_TABLES = {"maintenance", "enforcement"}

# Table 2 nests its row labels by indentation: the column a label sits in says
# which stage of the application journey it belongs to.
_CLEARANCE_CATEGORIES = {0: "Applications", 1: "Clearance", 2: "Timeliness"}

# Table 6 rows are grouped under bare header rows with no value beside them
_CHARACTERISTIC_GROUPS = {
    "Gender",
    "Age bands",
    "Number of Qualifing Children",
    "Number of Arrangements",
}

# Table 5's merged group header was reworded between releases. Without this the
# same column lands under two different categories and merging releases
# double-counts it.
_CATEGORY_ALIASES = {
    "parents using the collect & pay service who": "Collect & Pay",
}

# Table 7's rows were renamed from "Money ..." to "Maintenance ..." in the March
# 2025 release with the figures unchanged, so each series would otherwise appear
# twice in a merged history under both spellings.
_SUBCATEGORY_ALIASES = {
    ("maintenance", "money due to be paid through collect & pay"): "Maintenance due to be paid through Collect & Pay",
    ("maintenance", "money due to be paid through direct pay"): "Maintenance due to be paid through Direct Pay",
    ("maintenance", "money paid through collect & pay"): "Maintenance paid through Collect & Pay",
}

# Row label marking the end of the data block on every sheet
_SOURCE_PREFIX = "source:"

# Leading footnote digits ("6Regular Deduction Order") and trailing ones
# ("Children Covered1"). Both are anchored so genuinely numeric labels such as
# "1 Case", ">1 Case" and "20-29" survive intact.
_LEADING_NOTE_RE = re.compile(r"^\d+(?=[A-Z])")
_TRAILING_NOTE_RE = re.compile(r"(?<=[a-z])\d+$")

# Publications are quarterly and never revised in place
_CACHE_TTL_HOURS = 24 * 90

_downloader = CachedDownloader("dfc_child_maintenance", timeout=60)


class CMSDataError(Exception):
    """Base exception for Child Maintenance Service statistics errors."""

    pass


class CMSDataNotFoundError(CMSDataError):
    """Raised when a publication or workbook cannot be located or downloaded."""

    pass


class CMSValidationError(CMSDataError):
    """Raised when parsed data fails validation."""

    pass


def _clean_label(value: object) -> str:
    """Normalise a row or column label from the workbook.

    Strips footnote digits, collapses the double spaces that appear inside some
    published headers, and trims stray trailing whitespace. Source typos such as
    "Qualifing" are left alone so labels still match the publication.

    Args:
        value: Raw cell value.

    Returns:
        Cleaned label, or an empty string for missing values.

    Example:
        >>> _clean_label("6Regular Deduction Order")
        'Regular Deduction Order'
        >>> _clean_label("Children Covered1")
        'Children Covered'
        >>> _clean_label("Paid up to 90% of Child  Maintenance")
        'Paid up to 90% of Child Maintenance'
        >>> _clean_label(">1 Case")
        '>1 Case'
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    label = re.sub(r"\s+", " ", str(value)).strip()
    label = _LEADING_NOTE_RE.sub("", label)
    label = _TRAILING_NOTE_RE.sub("", label)
    return label.strip()


def _parse_quarter(value: object) -> pd.Timestamp | None:
    """Convert a quarter label into the quarter's end date.

    The workbook mixes real dates (stamped at the first of the quarter's final
    month) with strings like ``"Dec-20"``, sometimes in the same column. Both
    normalise to the last day of that month.

    Args:
        value: Raw cell value from a "Quarter Ending" column or header.

    Returns:
        Quarter end timestamp, or None if the value is not a quarter.

    Example:
        >>> _parse_quarter("Dec-20")
        Timestamp('2020-12-31 00:00:00')
        >>> _parse_quarter(pd.Timestamp("2026-03-01"))
        Timestamp('2026-03-31 00:00:00')
        >>> _parse_quarter("Quarter Ending") is None
        True
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    if isinstance(value, pd.Timestamp | datetime.date):
        stamp = pd.Timestamp(value)
    else:
        text = str(value).strip()
        try:
            stamp = pd.Timestamp(pd.to_datetime(text, format="%b-%y"))
        except ValueError:
            return None

    return stamp + pd.offsets.MonthEnd(0)


def _parse_value(value: object) -> float | None:
    """Coerce a workbook cell into a number.

    Args:
        value: Raw cell value.

    Returns:
        Numeric value, or None if the cell is blank or non-numeric.

    Example:
        >>> _parse_value(1230)
        1230.0
        >>> _parse_value("1,230")
        1230.0
        >>> _parse_value("-") is None
        True
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, int | float):
        return float(value)

    text = str(value).strip().replace(",", "").replace("£", "")
    if not text or text in {"-", ":", "N/A", "n/a"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_source_row(value: object) -> bool:
    """Check whether a first-column cell marks the end of the data block."""
    return str(value).strip().lower().startswith(_SOURCE_PREFIX)


def _find_header_row(frame: pd.DataFrame, label: str = "Quarter Ending") -> int | None:
    """Locate the header row carrying a given first-column label.

    Args:
        frame: Raw sheet read with ``header=None``.
        label: Label to search for in the first column.

    Returns:
        Zero-based row index, or None if the label is absent.
    """
    for index, value in frame.iloc[:, 0].items():
        if _clean_label(value) == label:
            return int(index)
    return None


def _measure_for(table: str, subcategory: str) -> tuple[str, str]:
    """Resolve the measure for an observation, stripping any "(%)" marker.

    Proportions are flagged in the workbook by a "(%)" suffix on the column
    header (Table 5) or by the wording of the row label (Table 2). Stripping the
    suffix lets a count and its proportion share one subcategory.

    Args:
        table: Table key.
        subcategory: Cleaned leaf label.

    Returns:
        Tuple of (subcategory, measure).

    Example:
        >>> _measure_for("paying_parents", "Paid some Child Maintenance (%)")
        ('Paid some Child Maintenance', 'proportion')
        >>> _measure_for("enforcement", "Sanctions")
        ('Sanctions', 'amount_gbp')
        >>> _measure_for("clearances", "Proportion Currently Cleared")
        ('Proportion Currently Cleared', 'proportion')
    """
    if subcategory.endswith("(%)"):
        return subcategory[: -len("(%)")].strip(), "proportion"
    if subcategory.startswith("Proportion") or subcategory.startswith("Cleared within"):
        return subcategory, "proportion"
    if table in _AMOUNT_TABLES:
        return subcategory, "amount_gbp"
    return subcategory, "count"


def _canonical_category(table: str, category: str, subcategory: str) -> str:
    """Resolve a column's group header to a category name stable across releases.

    Older Table 5 releases word the merged "Collect & Pay" header differently and
    leave the Direct Pay column ungrouped entirely, so the raw header alone is
    not comparable between publications.

    Args:
        table: Table key.
        category: Group header above the column, if any.
        subcategory: The column's own label.

    Returns:
        Canonical category name.

    Example:
        >>> _canonical_category("paying_parents", "Parents using the Collect & Pay Service who", "")
        'Collect & Pay'
        >>> _canonical_category("paying_parents", "", "Parents due to pay through Direct Pay")
        'Direct Pay'
        >>> _canonical_category("applications", "", "New Applications")
        'Total'
    """
    alias = _CATEGORY_ALIASES.get(category.casefold())
    if alias:
        return alias
    if category:
        return category
    if table == "paying_parents" and "Direct Pay" in subcategory:
        return "Direct Pay"
    return "Total"


def _canonicalise_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse label spellings that differ only by case between releases.

    Table 4's "Collect & Pay - not paying" became "Collect & Pay - Not Paying",
    which would otherwise survive deduplication as two separate series. The
    first spelling encountered wins, so callers should pass newest-first.

    Args:
        df: Concatenated observations, newest publication first.

    Returns:
        The same frame with ``category`` and ``subcategory`` normalised.
    """
    for column in ("category", "subcategory"):
        seen: dict[tuple[str, str], str] = {}
        df[column] = [
            seen.setdefault((table, value.casefold()), value)
            for table, value in zip(df["table"], df[column], strict=False)
        ]
    return df


def _parse_row_oriented(frame: pd.DataFrame, table: str) -> list[dict]:
    """Parse a sheet laid out with quarters down the first column.

    Covers every table except ``clearances`` and
    ``paying_parent_characteristics``. ``paying_parents`` additionally carries a
    merged group header one row above the column labels, which becomes
    ``category``.

    Args:
        frame: Raw sheet read with ``header=None``.
        table: Table key.

    Returns:
        List of observation dicts.
    """
    header_index = _find_header_row(frame)
    if header_index is None:
        return []

    columns: dict[int, str] = {}
    for position in range(1, frame.shape[1]):
        label = _clean_label(frame.iat[header_index, position])
        if label:
            columns[position] = label
    if not columns:
        return []

    # Table 5 groups its columns under "Direct Pay" / "Collect & Pay"; the
    # group cell is merged so only its first column is populated.
    groups: dict[int, str] = {}
    if header_index > 0:
        running = ""
        for position in range(1, frame.shape[1]):
            label = _clean_label(frame.iat[header_index - 1, position])
            if label:
                running = label
            groups[position] = running

    records = []
    for row_index in range(header_index + 1, frame.shape[0]):
        first = frame.iat[row_index, 0]
        if _is_source_row(first):
            break
        date = _parse_quarter(first)
        if date is None:
            continue
        for position, label in columns.items():
            value = _parse_value(frame.iat[row_index, position])
            if value is None:
                continue
            subcategory, measure = _measure_for(table, label)
            subcategory = _SUBCATEGORY_ALIASES.get((table, subcategory.casefold()), subcategory)
            records.append(
                {
                    "table": table,
                    "date": date,
                    "category": _canonical_category(table, groups.get(position, ""), subcategory),
                    "subcategory": subcategory,
                    "measure": measure,
                    "value": value,
                }
            )
    return records


def _parse_clearances(frame: pd.DataFrame) -> list[dict]:
    """Parse Table 2, which runs quarters across the columns.

    Row labels are indented into columns 0-2, and that indentation is the only
    signal of which stage of the application journey a label belongs to.

    Args:
        frame: Raw sheet read with ``header=None``.

    Returns:
        List of observation dicts.
    """
    header_index = _find_header_row(frame)
    if header_index is None:
        return []

    dates: dict[int, pd.Timestamp] = {}
    for position in range(1, frame.shape[1]):
        date = _parse_quarter(frame.iat[header_index, position])
        if date is not None:
            dates[position] = date
    if not dates:
        return []

    records = []
    for row_index in range(header_index + 1, frame.shape[0]):
        if _is_source_row(frame.iat[row_index, 0]):
            break
        for depth, category in _CLEARANCE_CATEGORIES.items():
            label = _clean_label(frame.iat[row_index, depth])
            if not label:
                continue
            subcategory, measure = _measure_for("clearances", label)
            for position, date in dates.items():
                value = _parse_value(frame.iat[row_index, position])
                if value is None:
                    continue
                records.append(
                    {
                        "table": "clearances",
                        "date": date,
                        "category": category,
                        "subcategory": subcategory,
                        "measure": measure,
                        "value": value,
                    }
                )
            break
    return records


def _parse_characteristics(frame: pd.DataFrame) -> list[dict]:
    """Parse Table 6, a single-quarter breakdown of paying parents.

    The sheet has no "Quarter Ending" label: the reporting date sits alone above
    the "Number" / "Percentage" column headers. Characteristic rows follow bare
    group headers ("Gender", "Age bands") that carry no values of their own.

    Args:
        frame: Raw sheet read with ``header=None``.

    Returns:
        List of observation dicts.
    """
    header_index = None
    for index in range(frame.shape[0]):
        if _clean_label(frame.iat[index, 1]) == "Number":
            header_index = index
            break
    if header_index is None:
        return []

    date = None
    for index in range(header_index):
        date = _parse_quarter(frame.iat[index, 1])
        if date is not None:
            break
    if date is None:
        return []

    measures = {1: "count", 2: "proportion"}

    records = []
    category = "Total"
    for row_index in range(header_index + 1, frame.shape[0]):
        label = _clean_label(frame.iat[row_index, 0])
        if not label or _is_source_row(label):
            break
        if label in _CHARACTERISTIC_GROUPS:
            category = label
            continue
        for position, measure in measures.items():
            value = _parse_value(frame.iat[row_index, position])
            if value is None:
                continue
            records.append(
                {
                    "table": "paying_parent_characteristics",
                    "date": date,
                    "category": category,
                    "subcategory": label,
                    "measure": measure,
                    "value": value,
                }
            )
    return records


def list_publications(topic_url: str = TOPIC_URL) -> list[dict]:
    """List every quarterly publication linked from the topic page.

    Args:
        topic_url: URL of the CMS statistics topic page.

    Returns:
        List of dicts with ``url``, ``year``, ``month`` and ``quarter``,
        newest first.

    Raises:
        CMSDataNotFoundError: If the page cannot be fetched or lists no
            publications.

    Example:
        >>> pubs = list_publications()
        >>> pubs[0]["year"] >= pubs[-1]["year"]
        True
        >>> pubs[0]["quarter"] in {1, 2, 3, 4}
        True
    """
    try:
        response = session.get(topic_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise CMSDataNotFoundError(f"Failed to fetch topic page {topic_url}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, features="html.parser")

    publications: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "/publications/" not in href or "child-maintenance" not in href.lower():
            continue
        match = _SLUG_PERIOD_RE.search(href.lower())
        if not match:
            continue
        url = urljoin(topic_url, href)
        month = _MONTH_NUMBERS[match.group(1)]
        publications[url] = {
            "url": url,
            "year": int(match.group(2)),
            "month": month,
            "quarter": (month - 1) // 3 + 1,
        }

    if not publications:
        raise CMSDataNotFoundError(f"No CMS publications found on {topic_url}")

    return sorted(publications.values(), key=lambda p: (p["year"], p["month"]), reverse=True)


def find_publication_xlsx(publication_url: str) -> str:
    """Find the tables workbook linked from a publication page.

    Args:
        publication_url: URL of a single quarterly publication page.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        CMSDataNotFoundError: If the page cannot be fetched or has no workbook.
    """
    try:
        response = session.get(publication_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise CMSDataNotFoundError(f"Failed to fetch publication {publication_url}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, features="html.parser")
    for anchor in soup.find_all("a", href=True):
        if anchor["href"].lower().endswith(".xlsx"):
            return urljoin(publication_url, anchor["href"])

    raise CMSDataNotFoundError(f"No xlsx workbook found on {publication_url}")


def download_file(url: str, cache_ttl_hours: int = _CACHE_TTL_HOURS, force_refresh: bool = False) -> Path:
    """Download a tables workbook with caching.

    Args:
        url: URL of the xlsx workbook.
        cache_ttl_hours: Cache validity in hours (default: 90 days).
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        Path to the downloaded (or cached) file.

    Raises:
        CMSDataNotFoundError: If the download fails.
    """
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise CMSDataNotFoundError(str(e)) from e


def _table_for_sheet(frame: pd.DataFrame) -> str | None:
    """Identify which statistical table a worksheet holds, from its title line.

    Args:
        frame: Raw worksheet, read with ``header=None``.

    Returns:
        Table key, or None for front matter and unrecognised sheets.

    Example:
        >>> import pandas as pd
        >>> sheet = pd.DataFrame([["Back to Contents"], ["Table 7. Enforcement Collections"]])
        >>> _table_for_sheet(sheet)
        'enforcement'
    """
    for _, row in frame.head(_TITLE_SEARCH_ROWS).iterrows():
        for cell in row:
            if not isinstance(cell, str):
                continue
            title = cell.strip().casefold()
            if not title.startswith("table"):
                continue
            for pattern, table in _TABLE_TITLE_PATTERNS:
                if pattern in title:
                    return table
    return None


def parse_workbook(file_path: Path) -> pd.DataFrame:
    """Parse every statistical table from a workbook into one tidy frame.

    Args:
        file_path: Path to the xlsx workbook.

    Returns:
        DataFrame with columns table, date, year, quarter, category,
        subcategory, measure, value.

    Raises:
        CMSDataError: If the workbook contains no parseable tables.
    """
    content = Path(file_path).read_bytes()
    workbook = pd.ExcelFile(io.BytesIO(content))

    records: list[dict] = []
    for sheet in workbook.sheet_names:
        frame = workbook.parse(sheet, header=None)
        table = _table_for_sheet(frame)
        if table is None:
            continue
        if table == "clearances":
            parsed = _parse_clearances(frame)
        elif table == "paying_parent_characteristics":
            parsed = _parse_characteristics(frame)
        else:
            parsed = _parse_row_oriented(frame, table)
        if not parsed:
            logger.warning("No rows parsed from sheet %s", sheet)
        records.extend(parsed)

    if not records:
        raise CMSDataError(f"No parseable tables found in {file_path}")

    df = pd.DataFrame(records)
    df["year"] = df["date"].dt.year
    df["quarter"] = df["date"].dt.quarter
    columns = ["table", "date", "year", "quarter", "category", "subcategory", "measure", "value"]
    return df[columns].sort_values(["table", "date", "category", "subcategory", "measure"]).reset_index(drop=True)


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Get every table from the most recent quarterly publication.

    Args:
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        DataFrame of all eight tables in tidy long format.

    Raises:
        CMSDataNotFoundError: If the publication cannot be located.
        CMSDataError: If the workbook cannot be parsed.

    Example:
        >>> df = get_latest_data()
        >>> len(df) > 400
        True
        >>> df["date"].max() > pd.Timestamp("2024-01-01")
        True
    """
    publications = list_publications()
    url = find_publication_xlsx(publications[0]["url"])
    return parse_workbook(download_file(url, force_refresh=force_refresh))


def get_historical_data(max_publications: int = 8, force_refresh: bool = False) -> pd.DataFrame:
    """Merge several publications to extend the short tables' back series.

    Tables 2, 4 and 6 show only a window of recent quarters, so each release
    carries observations the next one drops. Merging releases recovers them.
    Where releases disagree — figures are revised, especially the most recent
    quarter — the newer release wins.

    Args:
        max_publications: How many publications to merge, newest first.
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        DataFrame in the same shape as :func:`get_latest_data`, deduplicated on
        (table, date, category, subcategory, measure).

    Raises:
        CMSDataNotFoundError: If no publications can be located.
        CMSDataError: If no workbook can be parsed.
    """
    publications = list_publications()[:max_publications]

    frames = []
    for publication in publications:
        try:
            url = find_publication_xlsx(publication["url"])
            frames.append(parse_workbook(download_file(url, force_refresh=force_refresh)))
        except (CMSDataError, ValueError) as e:
            logger.warning("Skipping publication %s: %s", publication["url"], e)

    if not frames:
        raise CMSDataError("No publications could be parsed")

    df = _canonicalise_labels(pd.concat(frames, ignore_index=True))
    keys = ["table", "date", "category", "subcategory", "measure"]
    return df.drop_duplicates(subset=keys, keep="first").sort_values(keys).reset_index(drop=True)


def list_tables(df: pd.DataFrame | None = None) -> list[str]:
    """List the available table keys.

    Args:
        df: Optional parsed frame. If omitted, returns every known table.

    Returns:
        Sorted list of table keys.

    Example:
        >>> "enforcement" in list_tables()
        True
    """
    if df is None:
        return sorted(_TABLE_KEYS)
    return sorted(df["table"].unique())


def _get_table(table: str, df: pd.DataFrame | None, force_refresh: bool) -> pd.DataFrame:
    """Filter a frame to one table, fetching the latest data if needed."""
    if df is None:
        df = get_latest_data(force_refresh=force_refresh)
    return df[df["table"] == table].reset_index(drop=True)


def get_applications(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get applications received per quarter."""
    return _get_table("applications", df, force_refresh)


def get_clearances(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get application clearance volumes and timeliness."""
    return _get_table("clearances", df, force_refresh)


def get_arrangements(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the composition of live maintenance arrangements."""
    return _get_table("arrangements", df, force_refresh)


def get_children_covered(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get children covered by arrangements, split by paying status."""
    return _get_table("children_covered", df, force_refresh)


def get_paying_parents(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get paying parents and their compliance bands."""
    return _get_table("paying_parents", df, force_refresh)


def get_characteristics(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get paying parent gender, age and caseload characteristics."""
    return _get_table("paying_parent_characteristics", df, force_refresh)


def get_maintenance(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get child maintenance due and paid, in pounds."""
    return _get_table("maintenance", df, force_refresh)


def get_enforcement(df: pd.DataFrame | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get enforcement collections by mechanism, in pounds."""
    return _get_table("enforcement", df, force_refresh)


def validate_data(df: pd.DataFrame, min_records: int = 400) -> bool:
    """Validate a parsed frame for structure and plausible values.

    Args:
        df: DataFrame to validate.
        min_records: Minimum acceptable row count.

    Returns:
        True if validation passes.

    Raises:
        CMSValidationError: If any check fails.

    Example:
        >>> validate_data(pd.DataFrame())
        Traceback (most recent call last):
            ...
        bolster.data_sources.dfc.child_maintenance.CMSValidationError: DataFrame is empty
    """
    if df.empty:
        raise CMSValidationError("DataFrame is empty")

    required = {"table", "date", "year", "quarter", "category", "subcategory", "measure", "value"}
    missing = required - set(df.columns)
    if missing:
        raise CMSValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise CMSValidationError(f"Expected at least {min_records} records, got {len(df)}")

    unknown_tables = set(df["table"]) - _TABLE_KEYS
    if unknown_tables:
        raise CMSValidationError(f"Unknown tables: {sorted(unknown_tables)}")

    unknown_measures = set(df["measure"]) - {"count", "proportion", "amount_gbp"}
    if unknown_measures:
        raise CMSValidationError(f"Unknown measures: {sorted(unknown_measures)}")

    if not df["year"].between(2012, 2100).all():
        raise CMSValidationError("Year values outside plausible range 2012-2100")

    if not df["quarter"].isin({1, 2, 3, 4}).all():
        raise CMSValidationError("Quarter values outside range 1-4")

    if (df["value"] < 0).any():
        raise CMSValidationError("Negative values found")

    proportions = df[df["measure"] == "proportion"]["value"]
    if not proportions.empty and proportions.max() > 1.0:
        raise CMSValidationError("Proportion values exceed 1.0")

    return True


def clear_cache() -> int:
    """Clear cached CMS workbooks.

    Returns:
        Number of cache entries removed.
    """
    return _downloader.clear()
