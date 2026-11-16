"""A Respect Index for Northern Ireland (Everyday Discrimination Scale).

The Respect Index is the share of adults who feel respected, measured by nine
Everyday Discrimination Scale questions in the Northern Ireland Life and Times
(NILT) survey. A respondent counts as respected only if they answered "Never"
to all nine questions, so the index is a stringent measure: anyone who reports
even occasional unfair treatment is counted as not respected. Results are
weighted by age, sex and location, and respondents with missing answers are
excluded.

Published as: A Respect Index for Northern Ireland (as measured by the Everyday Discrimination Scale).

Data Source:
    The Executive Office (TEO) and NISRA publish one workbook per release at
    https://www.executiveoffice-ni.gov.uk/topics/respect-index. The workbook
    file path changes between releases, so it is found by scraping the hub page
    for the newest publication and the ``data-tables`` workbook on it, never by
    building a URL.

Workbook worksheets (found by title, not position):
    - ``Respect Index for <years>``: one table per survey year, each giving the
      percentage who felt respected, the percentage who did not and the sample
      size for 13 groups (all adults, sex, five age bands, three religion
      groups and disability).
    - ``Responses to the individual questions``: the answers to each of the nine
      questions ("Never", "Occasionally", "Monthly or more often") for the most
      recent two survey years only.

Update Frequency: Annual, typically in the autumn.

Geographic Coverage: Northern Ireland

Reference Period: Survey years 2016 to the latest release.

Notes:
    Samples are about 1,150 to 1,350 adults a year, so the all-adult figure carries
    roughly +/-2 to 3 percentage points at 95% confidence (the PxStat cube
    ``RESPECTEQ`` publishes 2.1 to 2.75 for 2016 to 2023) and the smaller groups
    carry more; the workbook itself does not publish intervals. In 2020 NILT moved from in-person interviewing to a
    combination of web and telephone interviewing, and has used that format since,
    so comparisons spanning 2020 mix modes. The PxStat cubes ``RESPECTNI``,
    ``RESPECTEQ`` and ``INDRESPECTEQ`` hold the same indicator for 2016 to 2023 with
    more groups (marital status, ethnic group, sexual orientation, urban or rural
    and political opinion); this module reads only the workbook, and never
    substitutes one source for the other.

Example:
    >>> from bolster.data_sources.nisra import respect_index
    >>> df = respect_index.get_latest_respect_index()
    >>> sorted(df["group_type"].unique())[:3]
    ['age', 'all', 'disability']
"""

import logging
import re
from pathlib import Path

import pandas as pd

from bolster.data_sources.nisra._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    find_publication_link,
)
from bolster.utils.excel import parse_sheet

logger = logging.getLogger(__name__)

BASE_URL = "https://www.executiveoffice-ni.gov.uk"
HUB_URL = f"{BASE_URL}/topics/respect-index"

# One release a year, so the workbook is cached for a month.
CACHE_TTL_HOURS = 24 * 30

_INDEX_SHEET_TITLE = re.compile(r"^Worksheet\s+\d+:\s+Respect Index for\b", re.IGNORECASE)
_QUESTIONS_SHEET_TITLE = re.compile(r"^Worksheet\s+\d+:\s+Responses to the individual questions\b", re.IGNORECASE)
_INDEX_TABLE_TITLE = re.compile(r"^Table\s+\d+:\s+Respect Index\s+(\d{4})$", re.IGNORECASE)
_QUESTIONS_TABLE_TITLE = re.compile(
    r"^Table\s+\d+:\s+Responses to the individual questions.*?\b(\d{4})$",
    re.IGNORECASE,
)

_INDEX_HEADER = ["Group", "% who felt respected", "% who did not feel respected", "Sample size"]
_QUESTIONS_HEADER = ["Question", "Never (%)", "Occasionally (%)", "Monthly or more often (%)", "Sample size"]

INDEX_COLUMNS = ["year", "group", "group_type", "pct_respected", "pct_not_respected", "sample_size"]
QUESTION_COLUMNS = [
    "year",
    "question",
    "pct_never",
    "pct_occasionally",
    "pct_monthly_or_more",
    "sample_size",
]

_GROUP_TYPES = {
    "All": "all",
    "Male": "sex",
    "Female": "sex",
    "18-24 years": "age",
    "25-34 years": "age",
    "35-49 years": "age",
    "50-64 years": "age",
    "65+ years": "age",
    "Catholic": "religion",
    "Protestant": "religion",
    "Other religion/ None/ Missing": "religion",
    "With disability": "disability",
    "Without disability": "disability",
}

_TABLES = {
    "index": "Respect Index by survey year and group (2016 to latest)",
    "questions": "Answers to each of the nine Everyday Discrimination Scale questions (latest two years)",
}

# Percentages published to full float precision should add to 100 to within rounding.
_PERCENT_TOLERANCE = 0.01


def get_latest_publication_url(force_refresh: bool = False) -> str:
    """Find the URL of the newest Respect Index data tables workbook.

    Args:
        force_refresh: If True, bypass the page-discovery cache.

    Returns:
        Absolute URL of the ``data-tables`` Excel workbook.

    Raises:
        NISRADataNotFoundError: If no publication or no workbook link is found.

    Example:
        >>> url = get_latest_publication_url()
        >>> url.endswith("data-tables.xlsx")
        True
    """
    return find_publication_link(
        hub_url=HUB_URL,
        pub_href_contains="/publications/respect-index",
        file_href_contains="data-tables",
        base_url=BASE_URL,
        force_refresh=force_refresh,
    )


def _download(force_refresh: bool = False) -> Path:
    """Download the latest workbook, using the shared cache."""
    url = get_latest_publication_url(force_refresh=force_refresh)
    return download_file(url, cache_ttl_hours=CACHE_TTL_HOURS, force_refresh=force_refresh)


def _clean(value: object) -> str:
    """Collapse whitespace in a cell value; blank for missing values."""
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split())


def _find_sheet(workbook: pd.ExcelFile, pattern: re.Pattern[str], what: str) -> pd.DataFrame:
    """Return the worksheet whose first cell matches ``pattern``.

    Raises:
        NISRADataNotFoundError: If no worksheet has a matching title.
    """
    for name in workbook.sheet_names:
        sheet = parse_sheet(workbook, str(name), header=None)
        if sheet.empty:
            continue
        if pattern.match(_clean(sheet.iloc[0, 0])):
            return sheet
    raise NISRADataNotFoundError(
        f"No worksheet titled like '{what}' in the Respect Index workbook (sheets: {list(workbook.sheet_names)})"
    )


def _title_cells(sheet: pd.DataFrame, pattern: re.Pattern[str]) -> list[tuple[int, int, int]]:
    """Locate table titles: ``(row, column, year)`` for every cell matching ``pattern``."""
    found: list[tuple[int, int, int]] = []
    for row in range(sheet.shape[0]):
        for col in range(sheet.shape[1]):
            match = pattern.match(_clean(sheet.iloc[row, col]))
            if match:
                found.append((row, col, int(match.group(1))))
    return found


def _read_block(sheet: pd.DataFrame, row: int, col: int, header: list[str], year: int) -> list[tuple[str, list[float]]]:
    """Read one table beneath its title cell: a label column then numeric columns.

    Raises:
        NISRADataNotFoundError: If the header row is not the expected one.
        NISRAValidationError: If a value cell is not numeric.
    """
    header_row = row + 1
    if header_row >= sheet.shape[0] or col + len(header) > sheet.shape[1]:
        raise NISRADataNotFoundError(f"The {year} table has no header row where one was expected")
    found = [_clean(sheet.iloc[header_row, col + i]) for i in range(len(header))]
    if [c.lower() for c in found] != [c.lower() for c in header]:
        raise NISRADataNotFoundError(f"The {year} table header is {found}, expected {header}")

    rows: list[tuple[str, list[float]]] = []
    for r in range(header_row + 1, sheet.shape[0]):
        label = _clean(sheet.iloc[r, col])
        if not label:
            break
        values: list[float] = []
        for i in range(1, len(header)):
            cell = sheet.iloc[r, col + i]
            try:
                value = float(cell)
            except (TypeError, ValueError):
                value = float("nan")
            if pd.isna(value):
                raise NISRAValidationError(
                    f"Non-numeric or missing value {cell!r} for {label!r}, column {header[i]!r}, in the {year} table"
                )
            values.append(value)
        rows.append((label, values))
    return rows


def parse_respect_index(file_path: str | Path) -> pd.DataFrame:
    """Parse the per-year Respect Index tables from a workbook.

    Args:
        file_path: Path to a ``data-tables`` workbook.

    Returns:
        One row per year and group with columns ``year``, ``group``,
        ``group_type`` (``all``, ``sex``, ``age``, ``religion``, ``disability`` or
        ``other`` for a group this module does not recognise), ``pct_respected``,
        ``pct_not_respected`` and ``sample_size``.

    Raises:
        NISRADataNotFoundError: If the worksheet or its tables are not found.
        NISRAValidationError: If a year appears twice or a value is not numeric.
    """
    workbook = pd.ExcelFile(file_path)
    sheet = _find_sheet(workbook, _INDEX_SHEET_TITLE, "Respect Index for <years>")
    titles = _title_cells(sheet, _INDEX_TABLE_TITLE)
    if not titles:
        raise NISRADataNotFoundError("No 'Respect Index <year>' tables found on the Respect Index worksheet")

    records: list[dict] = []
    seen: set[int] = set()
    for row, col, year in titles:
        if year in seen:
            raise NISRAValidationError(f"The {year} table appears more than once in the workbook")
        seen.add(year)
        for label, (pct, pct_not, size) in _read_block(sheet, row, col, _INDEX_HEADER, year):
            group_type = _GROUP_TYPES.get(label)
            if group_type is None:
                logger.warning("Unrecognised group %r in the %d Respect Index table; labelled 'other'", label, year)
                group_type = "other"
            records.append(
                {
                    "year": year,
                    "group": label,
                    "group_type": group_type,
                    "pct_respected": pct,
                    "pct_not_respected": pct_not,
                    "sample_size": int(size),
                }
            )
    df = pd.DataFrame.from_records(records, columns=INDEX_COLUMNS)
    return df.sort_values("year", kind="stable").reset_index(drop=True)


def parse_question_responses(file_path: str | Path) -> pd.DataFrame:
    """Parse the per-question response tables from a workbook.

    Args:
        file_path: Path to a ``data-tables`` workbook.

    Returns:
        One row per year and question with columns ``year``, ``question``,
        ``pct_never``, ``pct_occasionally``, ``pct_monthly_or_more`` and
        ``sample_size``. "Occasionally" combines "Less than once a year" and "A few
        times a year"; "Monthly or more often" combines "A few times a month", "At
        least once a week" and "Almost every day".

    Raises:
        NISRADataNotFoundError: If the worksheet or its tables are not found.
        NISRAValidationError: If a year appears twice or a value is not numeric.
    """
    workbook = pd.ExcelFile(file_path)
    sheet = _find_sheet(workbook, _QUESTIONS_SHEET_TITLE, "Responses to the individual questions")
    titles = _title_cells(sheet, _QUESTIONS_TABLE_TITLE)
    if not titles:
        raise NISRADataNotFoundError("No 'Responses to the individual questions ... <year>' tables found")

    records: list[dict] = []
    seen: set[int] = set()
    for row, col, year in titles:
        if year in seen:
            raise NISRAValidationError(f"The {year} questions table appears more than once in the workbook")
        seen.add(year)
        for label, (never, occasionally, monthly, size) in _read_block(sheet, row, col, _QUESTIONS_HEADER, year):
            records.append(
                {
                    "year": year,
                    "question": label,
                    "pct_never": never,
                    "pct_occasionally": occasionally,
                    "pct_monthly_or_more": monthly,
                    "sample_size": int(size),
                }
            )
    df = pd.DataFrame.from_records(records, columns=QUESTION_COLUMNS)
    return df.sort_values("year", kind="stable").reset_index(drop=True)


def get_latest_respect_index(force_refresh: bool = False) -> pd.DataFrame:
    """Get the Respect Index for every survey year and group.

    Args:
        force_refresh: If True, re-discover the workbook and re-download it.

    Returns:
        DataFrame as described in :func:`parse_respect_index`.

    Raises:
        NISRADataNotFoundError: If the workbook cannot be found or parsed.

    Example:
        >>> df = get_latest_respect_index()
        >>> bool(validate_data(df))
        True
    """
    df = parse_respect_index(_download(force_refresh=force_refresh))
    logger.info("Loaded %d Respect Index rows for %d survey years", len(df), df["year"].nunique())
    return df


def get_question_responses(force_refresh: bool = False) -> pd.DataFrame:
    """Get the answers to each Everyday Discrimination Scale question.

    Args:
        force_refresh: If True, re-discover the workbook and re-download it.

    Returns:
        DataFrame as described in :func:`parse_question_responses`; the workbook
        carries only the two most recent survey years.

    Raises:
        NISRADataNotFoundError: If the workbook cannot be found or parsed.

    Example:
        >>> df = get_question_responses()
        >>> bool(validate_question_responses(df))
        True
    """
    return parse_question_responses(_download(force_refresh=force_refresh))


def list_tables() -> pd.DataFrame:
    """List the tables this module exposes.

    Returns:
        DataFrame with ``table`` and ``description`` columns.

    Example:
        >>> list_tables()["table"].tolist()
        ['index', 'questions']
    """
    return pd.DataFrame(sorted(_TABLES.items()), columns=["table", "description"])


def get_latest_data(table: str = "index", force_refresh: bool = False) -> pd.DataFrame:
    """Get a Respect Index table by name.

    Args:
        table: ``index`` or ``questions``.
        force_refresh: If True, re-discover the workbook and re-download it.

    Returns:
        The requested DataFrame.

    Raises:
        ValueError: If ``table`` is not a known table name.

    Example:
        >>> get_latest_data("index").columns.tolist() == INDEX_COLUMNS
        True
    """
    dispatch = {"index": get_latest_respect_index, "questions": get_question_responses}
    if table not in dispatch:
        raise ValueError(f"Unknown table {table!r}. Available: {', '.join(sorted(dispatch))}")
    return dispatch[table](force_refresh=force_refresh)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a Respect Index DataFrame from :func:`get_latest_respect_index`.

    Checks that the frame is non-empty with the expected columns, that both
    percentages are within 0 to 100 and add to 100, that sample sizes are
    positive, that every year has an all-adults row and that the years are
    contiguous.

    Args:
        df: DataFrame to validate.

    Returns:
        True if every check passes, False otherwise (with a logged reason).

    Example:
        >>> validate_data(pd.DataFrame())
        False
    """
    if df is None or df.empty:
        logger.warning("Respect Index validation failed: empty DataFrame")
        return False
    missing = set(INDEX_COLUMNS) - set(df.columns)
    if missing:
        logger.warning("Respect Index validation failed: missing columns %s", sorted(missing))
        return False
    for column in ("pct_respected", "pct_not_respected"):
        if not df[column].between(0, 100).all():
            logger.warning("Respect Index validation failed: %s outside 0-100", column)
            return False
    if ((df["pct_respected"] + df["pct_not_respected"] - 100).abs() > _PERCENT_TOLERANCE).any():
        logger.warning("Respect Index validation failed: percentages do not add to 100")
        return False
    if (df["sample_size"] <= 0).any():
        logger.warning("Respect Index validation failed: non-positive sample size")
        return False
    years = sorted(int(y) for y in df["year"].unique())
    if years != list(range(years[0], years[-1] + 1)):
        logger.warning("Respect Index validation failed: years %s are not contiguous", years)
        return False
    if set(years) - {int(y) for y in df.loc[df["group_type"] == "all", "year"]}:
        logger.warning("Respect Index validation failed: a year has no all-adults row")
        return False
    return True


def validate_question_responses(df: pd.DataFrame) -> bool:
    """Validate a question-responses DataFrame from :func:`get_question_responses`.

    Checks that the frame is non-empty with the expected columns, that the three
    answer percentages are within 0 to 100 and add to 100, and that sample sizes
    are positive.

    Args:
        df: DataFrame to validate.

    Returns:
        True if every check passes, False otherwise (with a logged reason).

    Example:
        >>> validate_question_responses(pd.DataFrame())
        False
    """
    if df is None or df.empty:
        logger.warning("Respect Index question validation failed: empty DataFrame")
        return False
    missing = set(QUESTION_COLUMNS) - set(df.columns)
    if missing:
        logger.warning("Respect Index question validation failed: missing columns %s", sorted(missing))
        return False
    answers = df[["pct_never", "pct_occasionally", "pct_monthly_or_more"]]
    if not answers.apply(lambda col: col.between(0, 100)).all().all():
        logger.warning("Respect Index question validation failed: a percentage is outside 0-100")
        return False
    if ((answers.sum(axis=1) - 100).abs() > _PERCENT_TOLERANCE).any():
        logger.warning("Respect Index question validation failed: answers do not add to 100")
        return False
    if (df["sample_size"] <= 0).any():
        logger.warning("Respect Index question validation failed: non-positive sample size")
        return False
    return True
