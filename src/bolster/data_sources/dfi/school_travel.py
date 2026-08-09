"""YPBAS Travel to/from School Statistics.

Provides access to the travel module of the Young Persons' Behaviour and
Attitudes Survey (YPBAS), a survey of Northern Ireland school pupils in years
8-12 run by NISRA on behalf of the Department for Infrastructure.

Two views are available:

- **Latest detail** (:func:`get_latest_data`) - every question from the most
  recent survey, broken down by sex and school year group, with 95% confidence
  intervals around each percentage.
- **Historical trend** (:func:`get_trend_data`) - headline percentages for the
  eight core questions across all survey waves (2016, 2019, 2022, 2025).

Questions cover how pupils usually travel to and from school, how they would
*like* to travel, journey distance, whether they feel safe, and walking and
cycling participation.

Data Source:
    **Index Page**:
    https://www.infrastructure-ni.gov.uk/articles/young-persons-behaviour-and-attitude-survey

    The module scrapes this page for travel-to-school publications, then
    scrapes the newest publication page for its Excel tables workbook.

Update Frequency: Roughly every three years (2016, 2019, 2022, 2025)
Geographic Coverage: Northern Ireland
Reference Period: 2016 - present

Only the most recent workbook is parsed for detail. Earlier workbooks use an
incompatible (transposed) layout, so historical continuity comes from the
``Trend tables`` worksheet bundled with the latest release, which the
publisher revises for comparability.

Percentages that would disclose small counts are suppressed in the source with
``*``; these become ``NA`` with ``suppressed`` set to ``True``.

Example:
    >>> from bolster.data_sources.dfi import school_travel
    >>> df = school_travel.get_trend_data()
    >>> sorted(df["survey_year"].unique().tolist())
    [2016, 2019, 2022, 2025]
"""

import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import fetch_soup, scrape_file_links

logger = logging.getLogger(__name__)

BASE_URL = "https://www.infrastructure-ni.gov.uk"

# Index page listing every YPBAS module (travel, road safety, public transport)
INDEX_URL = f"{BASE_URL}/articles/young-persons-behaviour-and-attitude-survey"

# Worksheets in the latest workbook that hold no survey estimates
NON_DATA_SHEETS = {"Cover sheet", "Table of contents", "Trend tables"}
TREND_SHEET = "Trend tables"

# Header cells that mark the confidence-interval table within a worksheet
CI_MARKERS = ("lower 95%", "upper 95%")

# Value used in the source to suppress a disclosive estimate
SUPPRESSION_MARKER = "*"

# Shared downloader (workbooks are ~100KB and republished every few years)
_downloader = CachedDownloader("dfi_school_travel", timeout=120)


class SchoolTravelError(Exception):
    """Base exception for YPBAS school travel data errors."""

    pass


class SchoolTravelDataNotFoundError(SchoolTravelError):
    """Raised when the data file cannot be located or downloaded."""

    pass


class SchoolTravelValidationError(SchoolTravelError):
    """Raised when parsed data fails validation."""

    pass


def _txt(value) -> str:
    """Normalise a raw cell value to a stripped string ("" for blanks)."""
    return "" if pd.isna(value) else str(value).strip()


def _clean_question(text: str) -> str:
    """Strip the trailing ``(%)`` / ``(%)*`` marker and collapse whitespace."""
    return re.sub(r"\s*\(\s*%\s*\)\s*\*?\s*$", "", " ".join(text.split()))


def classify_breakdown(group: str) -> str:
    """Classify a respondent group label into a breakdown type.

    Args:
        group: Column group label from the workbook, e.g. "Male", "Year 10".

    Returns:
        One of ``"all"``, ``"sex"``, ``"year_group"`` or ``"other"``.

    Example:
        >>> classify_breakdown("All respondents")
        'all'
        >>> classify_breakdown("Year 10")
        'year_group'
        >>> classify_breakdown("Female")
        'sex'
    """
    lowered = group.strip().lower()
    if lowered.startswith("all"):
        return "all"
    if lowered in {"male", "female"}:
        return "sex"
    if re.match(r"^year\s+\d+$", lowered):
        return "year_group"
    return "other"


def list_publications(index_url: str = INDEX_URL) -> list[dict]:
    """List the travel-to/from-school YPBAS publications, newest first.

    Scrapes the YPBAS index page for links to travel module publications and
    extracts the survey year from each URL. Entries without an identifiable
    year (legacy pages that no longer resolve) are skipped.

    Args:
        index_url: URL of the YPBAS index page.

    Returns:
        List of ``{"survey_year": int, "page_url": str}`` dicts, newest first.

    Raises:
        SchoolTravelDataNotFoundError: If the index page cannot be fetched or
            contains no dated travel publications.

    Example:
        >>> pubs = list_publications()
        >>> pubs[0]["survey_year"] >= 2025
        True
    """
    try:
        soup = fetch_soup(index_url)
    except Exception as e:
        raise SchoolTravelDataNotFoundError(f"Failed to fetch YPBAS index page {index_url}: {e}") from e

    publications: dict[int, str] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        lowered = href.lower()
        if "/publications/" not in lowered or "travel" not in lowered or "school" not in lowered:
            continue
        match = re.search(r"(19|20)\d{2}", lowered)
        if not match:
            # Undated legacy landing page - no way to order it, and it 404s
            continue
        year = int(match.group(0))
        publications.setdefault(year, urljoin(BASE_URL, href))

    if not publications:
        raise SchoolTravelDataNotFoundError(f"No dated travel-to-school publications found on {index_url}")

    return [{"survey_year": year, "page_url": publications[year]} for year in sorted(publications, reverse=True)]


def find_publication_xlsx(page_url: str) -> str:
    """Find the Excel tables workbook linked from a publication page.

    Args:
        page_url: URL of a YPBAS travel publication page.

    Returns:
        Absolute URL of the workbook.

    Raises:
        SchoolTravelDataNotFoundError: If the page cannot be fetched or links
            to no spreadsheet (some early releases published a PDF only).

    Example:
        >>> pubs = list_publications()
        >>> find_publication_xlsx(pubs[0]["page_url"]).endswith(".xlsx")
        True
    """
    try:
        # ".xls" is a substring of ".xlsx", so this matches both formats
        links = scrape_file_links(page_url, ".xls", base_url=BASE_URL)
    except Exception as e:
        raise SchoolTravelDataNotFoundError(f"Failed to fetch publication page {page_url}: {e}") from e

    if not links:
        raise SchoolTravelDataNotFoundError(f"No spreadsheet linked from {page_url}")

    return links[0]["url"]


def get_latest_publication_url(index_url: str = INDEX_URL) -> tuple[str, int]:
    """Find the workbook URL for the most recent survey wave with data.

    Walks the publications newest-first and returns the first one that
    actually links to a spreadsheet.

    Args:
        index_url: URL of the YPBAS index page.

    Returns:
        Tuple of (workbook URL, survey year).

    Raises:
        SchoolTravelDataNotFoundError: If no publication offers a workbook.

    Example:
        >>> url, year = get_latest_publication_url()
        >>> year >= 2025 and url.endswith(".xlsx")
        True
    """
    publications = list_publications(index_url)

    for publication in publications:
        try:
            url = find_publication_xlsx(publication["page_url"])
        except SchoolTravelDataNotFoundError:
            logger.debug(f"No workbook on {publication['page_url']}, trying older release")
            continue
        logger.info(f"Found YPBAS {publication['survey_year']} travel workbook: {url}")
        return url, publication["survey_year"]

    raise SchoolTravelDataNotFoundError("No YPBAS travel publication links to a spreadsheet")


def download_file(url: str, cache_ttl_hours: int = 24 * 30, force_refresh: bool = False) -> Path:
    """Download a YPBAS workbook with caching.

    Args:
        url: URL of the workbook.
        cache_ttl_hours: Cache validity in hours (default: 30 days, since the
            survey runs roughly every three years).
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        Path to the downloaded (or cached) file.

    Raises:
        SchoolTravelDataNotFoundError: If the download fails.
    """
    try:
        return _downloader.download(url, cache_ttl_hours=cache_ttl_hours, force_refresh=force_refresh)
    except DownloadError as e:
        raise SchoolTravelDataNotFoundError(str(e)) from e


def _parse_percentage(value) -> tuple[float | None, bool]:
    """Parse a percentage cell, flagging the suppression marker.

    Returns:
        Tuple of (value, suppressed). Suppressed and unparseable cells return
        a ``None`` value.
    """
    text = _txt(value)
    if text == SUPPRESSION_MARKER:
        return None, True
    try:
        return float(text), False
    except ValueError:
        return None, False


def _find_ci_header_row(sheet: pd.DataFrame) -> int | None:
    """Locate the row index holding the ``% | Lower 95% | Upper 95%`` headers."""
    for row_idx in range(len(sheet)):
        for col_idx in range(sheet.shape[1]):
            cell = _txt(sheet.iat[row_idx, col_idx]).lower()
            if any(marker in cell for marker in CI_MARKERS):
                return row_idx
    return None


def _extract_question(sheet: pd.DataFrame) -> str:
    """Pull the question text from the ``Worksheet N: ...`` title row."""
    for row_idx in range(min(4, len(sheet))):
        cell = _txt(sheet.iat[row_idx, 0])
        if cell.lower().startswith("worksheet"):
            return _clean_question(cell.split(":", 1)[1] if ":" in cell else cell)
    return ""


def _extract_total_respondents(sheet: pd.DataFrame, groups: list[str]) -> dict[str, int]:
    """Map each respondent group to its base count.

    The ``Total Respondents`` row is compact - one cell per group, in the same
    order the groups appear as column headers - rather than aligned to the
    three-column confidence-interval blocks.

    Args:
        sheet: Raw worksheet.
        groups: Ordered group labels taken from the header row.

    Returns:
        Mapping of group label to respondent count. Groups with no
        corresponding cell are omitted.
    """
    for row_idx in range(len(sheet)):
        if not _txt(sheet.iat[row_idx, 0]).lower().startswith("total respondent"):
            continue
        counts: dict[str, int] = {}
        values = [_txt(sheet.iat[row_idx, col]) for col in range(1, sheet.shape[1])]
        values = [v for v in values if v]
        for group, value in zip(groups, values, strict=False):
            try:
                counts[group] = int(round(float(value)))
            except ValueError:
                continue
        return counts
    return {}


def _parse_worksheet(sheet: pd.DataFrame, name: str) -> pd.DataFrame:
    """Parse one question worksheet into tidy long format.

    Args:
        sheet: Raw worksheet read with ``header=None``.
        name: Worksheet name, retained as the ``worksheet`` column.

    Returns:
        DataFrame of one row per (category, breakdown), or empty if the sheet
        holds no confidence-interval table.
    """
    header_idx = _find_ci_header_row(sheet)
    if not header_idx:
        # No CI table, or one starting at row 0 with no group labels above it
        return pd.DataFrame()

    question = _extract_question(sheet)

    # Group labels sit one row above the headers and are merged across the
    # three columns of each block, so carry the last seen label forward.
    group_columns: dict[int, str] = {}
    current_group = ""
    for col_idx in range(sheet.shape[1]):
        label = _txt(sheet.iat[header_idx - 1, col_idx])
        if label:
            current_group = label
        if _txt(sheet.iat[header_idx, col_idx]) == "%" and current_group:
            group_columns[col_idx] = current_group

    ordered_groups = list(dict.fromkeys(group_columns.values()))
    totals = _extract_total_respondents(sheet, ordered_groups)

    records = []
    for row_idx in range(header_idx + 1, len(sheet)):
        category = _txt(sheet.iat[row_idx, 0])
        if category.lower().startswith("table"):
            # Start of the next table block within the same worksheet
            break
        if not category or category.lower().startswith(("total", SUPPRESSION_MARKER)):
            continue

        for col_idx, group in group_columns.items():
            value, suppressed = _parse_percentage(sheet.iat[row_idx, col_idx])
            lower, _ = (
                _parse_percentage(sheet.iat[row_idx, col_idx + 1]) if col_idx + 1 < sheet.shape[1] else (None, False)
            )
            upper, _ = (
                _parse_percentage(sheet.iat[row_idx, col_idx + 2]) if col_idx + 2 < sheet.shape[1] else (None, False)
            )
            if value is None and not suppressed:
                continue
            records.append(
                {
                    "worksheet": name,
                    "question": question,
                    "category": _clean_question(category),
                    "breakdown_type": classify_breakdown(group),
                    "breakdown": group,
                    "value_pct": value,
                    "lower_ci": lower,
                    "upper_ci": upper,
                    "suppressed": suppressed,
                    "total_respondents": totals.get(group),
                }
            )

    return pd.DataFrame.from_records(records)


def parse_data(file_path: Path, survey_year: int | None = None) -> pd.DataFrame:
    """Parse every question worksheet in a YPBAS workbook.

    Args:
        file_path: Path to the workbook.
        survey_year: Survey year to stamp on each row. Optional.

    Returns:
        DataFrame with columns: survey_year, worksheet, question, category,
        breakdown_type, breakdown, value_pct, lower_ci, upper_ci, suppressed,
        total_respondents.

    Raises:
        SchoolTravelValidationError: If no worksheet yields any estimates.
    """
    workbook = pd.ExcelFile(Path(file_path))

    frames = [
        _parse_worksheet(workbook.parse(name, header=None), name)
        for name in workbook.sheet_names
        if name not in NON_DATA_SHEETS
    ]
    frames = [frame for frame in frames if not frame.empty]

    if not frames:
        raise SchoolTravelValidationError(f"No question worksheets could be parsed from {file_path}")

    df = pd.concat(frames, ignore_index=True)
    df.insert(0, "survey_year", survey_year)
    return df


def parse_trend_data(file_path: Path) -> pd.DataFrame:
    """Parse the historical trend worksheet from a YPBAS workbook.

    The trend worksheet stacks eight tables vertically, each headed
    ``Table N. <question> (%)`` followed by a row of survey years, the
    category percentages, and a ``Total respondents`` base row.

    Args:
        file_path: Path to the workbook.

    Returns:
        DataFrame with columns: survey_year, table, question, category,
        value_pct, total_respondents.

    Raises:
        SchoolTravelValidationError: If the trend worksheet is missing or
            yields no records.
    """
    file_path = Path(file_path)
    workbook = pd.ExcelFile(file_path)
    if TREND_SHEET not in workbook.sheet_names:
        raise SchoolTravelValidationError(f"No '{TREND_SHEET}' worksheet in {file_path}")

    sheet = workbook.parse(TREND_SHEET, header=None)

    records = []
    totals: dict[tuple[str, int], int] = {}
    table = question = None
    year_columns: dict[int, int] = {}

    row_idx = 0
    while row_idx < len(sheet):
        first_cell = _txt(sheet.iat[row_idx, 0])
        heading = re.match(r"^Table\s+(\d+)\.\s*(.+)$", first_cell)
        if heading:
            table, question = heading.group(1), _clean_question(heading.group(2))
            year_columns = {}
            for col_idx in range(1, sheet.shape[1]):
                try:
                    year_columns[col_idx] = int(float(_txt(sheet.iat[row_idx + 1, col_idx])))
                except ValueError:
                    continue
            row_idx += 2
            continue

        if table and first_cell and year_columns:
            is_base_row = first_cell.lower().startswith("total respondent")
            for col_idx, year in year_columns.items():
                value, _ = _parse_percentage(sheet.iat[row_idx, col_idx])
                if value is None:
                    continue
                if is_base_row:
                    totals[(table, year)] = int(round(value))
                else:
                    records.append(
                        {
                            "survey_year": year,
                            "table": table,
                            "question": question,
                            "category": first_cell,
                            "value_pct": value,
                        }
                    )
        row_idx += 1

    if not records:
        raise SchoolTravelValidationError(f"No trend records parsed from {file_path}")

    df = pd.DataFrame.from_records(records)
    df["total_respondents"] = [totals.get((t, y)) for t, y in zip(df["table"], df["survey_year"], strict=True)]
    return df.sort_values(["table", "survey_year", "category"]).reset_index(drop=True)


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the latest YPBAS travel-to-school detail tables.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        DataFrame with columns: survey_year, worksheet, question, category,
        breakdown_type, breakdown, value_pct, lower_ci, upper_ci, suppressed,
        total_respondents.

    Example:
        >>> df = get_latest_data()
        >>> set(df["breakdown_type"]) >= {"all", "sex", "year_group"}
        True
    """
    url, survey_year = get_latest_publication_url()
    return parse_data(download_file(url, force_refresh=force_refresh), survey_year=survey_year)


def get_trend_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the historical trend tables.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        DataFrame with columns: survey_year, table, question, category,
        value_pct, total_respondents - covering every survey wave.

    Example:
        >>> df = get_trend_data()
        >>> len(df["survey_year"].unique()) >= 4
        True
    """
    url, _ = get_latest_publication_url()
    return parse_trend_data(download_file(url, force_refresh=force_refresh))


def list_questions(force_refresh: bool = False) -> list[str]:
    """List the questions available in the latest detail tables.

    Args:
        force_refresh: If True, bypass the cache and download fresh data.

    Returns:
        Question texts, in worksheet order.

    Example:
        >>> questions = list_questions()
        >>> any("travel" in q.lower() for q in questions)
        True
    """
    return list(dict.fromkeys(get_latest_data(force_refresh=force_refresh)["question"]))


def validate_data(df: pd.DataFrame, min_records: int = 100) -> bool:
    """Validate a parsed detail DataFrame.

    Checks structure and sanity:

    - Required columns are present.
    - There are at least ``min_records`` rows.
    - Percentages fall between 0 and 100.
    - Confidence bounds bracket their point estimate.
    - Suppressed rows carry no value.

    Args:
        df: DataFrame returned by :func:`parse_data` or :func:`get_latest_data`.
        min_records: Minimum acceptable number of rows.

    Returns:
        True if the data passes all checks.

    Raises:
        SchoolTravelValidationError: If any check fails.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        Traceback (most recent call last):
        ...
        bolster.data_sources.dfi.school_travel.SchoolTravelValidationError: DataFrame is empty
    """
    if df is None or df.empty:
        raise SchoolTravelValidationError("DataFrame is empty")

    required = {"question", "category", "breakdown", "value_pct", "lower_ci", "upper_ci", "suppressed"}
    missing = required - set(df.columns)
    if missing:
        raise SchoolTravelValidationError(f"Missing required columns: {missing}")

    if len(df) < min_records:
        raise SchoolTravelValidationError(f"Too few records: {len(df)} < {min_records}")

    values = df["value_pct"].dropna()
    if not values.between(0, 100).all():
        raise SchoolTravelValidationError("Percentages outside the 0-100 range")

    bounded = df.dropna(subset=["value_pct", "lower_ci", "upper_ci"])
    if (bounded["lower_ci"] > bounded["value_pct"]).any() or (bounded["upper_ci"] < bounded["value_pct"]).any():
        raise SchoolTravelValidationError("Confidence bounds do not bracket their point estimate")

    if df.loc[df["suppressed"], "value_pct"].notna().any():
        raise SchoolTravelValidationError("Suppressed rows must not carry a value")

    return True


def clear_cache() -> int:
    """Clear all cached YPBAS workbooks.

    Returns:
        Number of files deleted.
    """
    return _downloader.clear()
