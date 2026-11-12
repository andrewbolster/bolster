"""Employment Vacancies notified to the Department for Communities (DfC).

Counts of vacancy positions that employers notify to DfC through the JobApplyNI
system, which Jobs & Benefits Offices and ``nidirect`` use to match people to
work. This is *notified* vacancies, a subset of all vacancies in the economy,
not a vacancy rate.

Two kinds of series are provided:

- **Quarterly and monthly, from the DfC factsheet** (scraped): the NI total by
  quarter over five financial years, and for the current financial year the
  split by vacancy type (full-time, part-time, casual), occupation (SOC 2020
  major group), industry (SIC 2007 section), Jobs & Benefits Office and
  deprivation quintile, plus a monthly view.
- **Annual by geography, from NISRA PxStat**: Local Government District,
  Assembly Area, Health and Social Care Trust (2014/15 onwards) and District
  Electoral Area (2018/19 onwards), by financial year (April to March).

Published as: Employment vacancies notified to DfC; Vacancies: Statistical Factsheet.

Data Source:
    **Topic Page**:
    https://www.communities-ni.gov.uk/topics/employment-vacancy-statistics

    The module scrapes this page for factsheet publications, then each
    publication page for its ``.ods`` tables file. The file name is not
    predictable, so it is never built from the date.

    **PxStat matrices**: ``EMPVACLGD``, ``EMPVACAA``, ``EMPVACHSCT``, ``EMPVACDEA``.

Update Frequency: Quarterly factsheets (February, May, August, November); annual PxStat
Geographic Coverage: Northern Ireland, with annual breakdowns by area
Reference Period: Quarterly from Q1 2022/23; annual from 2014/15

.. note::
    Quarters are financial-year quarters: Q1 is April to June, Q2 July to
    September, Q3 October to December and Q4 January to March. ``quarter_start``
    is the first day of the quarter's first month.

.. note::
    The breakdown tables (vacancy type, occupation, industry, office,
    deprivation, monthly) cover only the current financial year of each release.
    The NI total by quarter is the one series with a five-year history in a
    single release.

.. note::
    Category labels are as published, and the wording of a category can change
    between releases: the SIC section for administrative and support services is
    "Administrative & Support Service Activities" in one release and
    "Administrative and Support Service" in another. Normalise labels before
    combining breakdowns from different releases.

.. note::
    Area figures do not always sum to the NI total: vacancies that cannot be placed
    in an area are in the NI total only. The areas of each geography cover 95.9% to
    100% of it depending on the year (the districts 97.7% to 99.3%, and 99.3% in
    2025/26), and never exceed it.
    The factsheet layout also differs between releases, and a release whose
    layout is not recognised raises an error instead of returning a partial
    frame.

Example:
    >>> from bolster.data_sources.dfc import employment_vacancies
    >>> employment_vacancies.parse_quarter_label("Q2 2627")
    ('2026/27', 2, Timestamp('2026-07-01 00:00:00'))
"""

import logging
import re
from typing import cast

import pandas as pd
from bs4 import Tag  # noqa: TC002 (used inside `cast(...)`, evaluated at runtime)

from bolster.data_sources.nisra.pxstat import PxStatError, read_dataset
from bolster.utils.cache import CachedDownloader, bind_download_file
from bolster.utils.embedded_downloads import coerce_numeric
from bolster.utils.excel import find_marker_row, parse_sheet
from bolster.utils.web import fetch_soup, make_absolute_url, scrape_file_links

logger = logging.getLogger(__name__)

SITE_URL = "https://www.communities-ni.gov.uk"
TOPIC_URL = f"{SITE_URL}/topics/employment-vacancy-statistics"

# Factsheet publication slugs: "vacancies-statistical-factsheet-<month>-<year>"
_FACTSHEET_SLUG_RE = re.compile(
    r"vacancies-statistical-factsheet-"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)-(\d{4})"
)

_MONTH_NUMBERS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}

# Financial-year quarter codes in the "Quarterly" sheet: "Q1 2223" is Q1 of 2022/23
_QUARTER_CODE_RE = re.compile(r"^Q([1-4])\s*(\d{2})(\d{2})$")
# Column headers in the breakdown sheets: "Quarter 1 Vacancies Notified to DfC"
_QUARTER_HEADER_RE = re.compile(r"quarter\s*([1-4])", re.IGNORECASE)
_FINANCIAL_YEAR_RE = re.compile(r"(\d{4})/(\d{2})")

# Breakdown key -> accepted worksheet names (the Jobs & Benefits Office sheet was "J&BO" in older releases)
_BREAKDOWN_SHEETS: dict[str, tuple[str, ...]] = {
    "vacancy_type": ("FT-PT",),
    "soc": ("SOC",),
    "sic": ("SIC",),
    "jbo": ("JBO", "J&BO"),
    "nimdm": ("NIMDM",),
}

# Geography key -> (PxStat matrix, label column)
_GEOGRAPHIES: dict[str, tuple[str, str]] = {
    "lgd": ("EMPVACLGD", "Local Government District"),
    "assembly_area": ("EMPVACAA", "Assembly Area"),
    "hsct": ("EMPVACHSCT", "Health and Social Care Trust"),
    "dea": ("EMPVACDEA", "District Electoral Area"),
}

# Every PxStat matrix carries a Northern Ireland total row under this code
_NI_CODE = "N92000002"

# Share of the NI total the areas must cover; the shortfall is vacancies with no mappable area
_MIN_AREA_COVERAGE = 0.95

# Factsheets are published quarterly and not revised in place, and a new release has a new URL
_CACHE_TTL_HOURS = 24 * 90

# Leading rows searched for a table's header
_HEADER_SEARCH_ROWS = 8

_downloader = CachedDownloader("dfc_employment_vacancies", timeout=60)


class VacanciesDataError(Exception):
    """Base exception for employment vacancies data errors."""

    pass


class VacanciesDataNotFoundError(VacanciesDataError):
    """Raised when a publication, file, sheet or PxStat matrix cannot be located or downloaded."""

    pass


class VacanciesValidationError(VacanciesDataError):
    """Raised when parsed data fails validation."""

    pass


# download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=False) -> Path,
# raising VacanciesDataNotFoundError in place of DownloadError.
download_file = bind_download_file(_downloader, VacanciesDataNotFoundError, _CACHE_TTL_HOURS)


def list_breakdowns() -> list[str]:
    """Return the keys accepted by :func:`get_vacancy_breakdown`.

    Example:
        >>> list_breakdowns()
        ['vacancy_type', 'soc', 'sic', 'jbo', 'nimdm']
    """
    return list(_BREAKDOWN_SHEETS)


def list_geographies() -> list[str]:
    """Return the keys accepted by :func:`get_vacancies_by_geography`.

    Example:
        >>> list_geographies()
        ['lgd', 'assembly_area', 'hsct', 'dea']
    """
    return list(_GEOGRAPHIES)


def parse_quarter_label(label: str) -> tuple[str, int, pd.Timestamp]:
    """Parse a factsheet quarter code such as ``"Q1 2223"``.

    Args:
        label: Code of the form ``Q<quarter> <yy><yy>``, where the two year pairs
            are the start and end of the financial year.

    Returns:
        ``(financial_year, quarter, quarter_start)``, for example
        ``("2022/23", 1, Timestamp("2022-04-01"))``.

    Raises:
        VacanciesDataError: If the label is not of that form, or its year pairs
            are not consecutive.

    Example:
        >>> parse_quarter_label("Q1 2223")
        ('2022/23', 1, Timestamp('2022-04-01 00:00:00'))
        >>> parse_quarter_label("Q4 2223")[2]
        Timestamp('2023-01-01 00:00:00')
    """
    match = _QUARTER_CODE_RE.match(str(label).strip())
    if not match:
        raise VacanciesDataError(f"Unrecognised quarter label {label!r}; expected a code such as 'Q1 2223'")
    quarter, start, end = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if (start + 1) % 100 != end:
        raise VacanciesDataError(f"Quarter label {label!r} does not span consecutive years")
    return _financial_year_label(2000 + start), quarter, _quarter_start(2000 + start, quarter)


def _financial_year_label(start_year: int) -> str:
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def _quarter_start(start_year: int, quarter: int) -> pd.Timestamp:
    """First day of financial-year quarter ``quarter`` of the year starting April ``start_year``."""
    month = {1: 4, 2: 7, 3: 10, 4: 1}[quarter]
    year = start_year + 1 if quarter == 4 else start_year
    return cast("pd.Timestamp", pd.Timestamp(year=year, month=month, day=1))


def list_publications(force_refresh: bool = False) -> list[dict]:
    """List the quarterly factsheet publications on the DfC topic page, newest first.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Dicts with ``release`` (``"YYYY-MM"``, the month of publication), ``year``,
        ``month`` and ``url`` (the publication page).

    Raises:
        VacanciesDataNotFoundError: If the topic page cannot be fetched or lists no factsheets.
    """
    try:
        soup = fetch_soup(TOPIC_URL, force_refresh=force_refresh)
    except Exception as e:
        raise VacanciesDataNotFoundError(f"Could not fetch {TOPIC_URL}: {e}") from e

    publications: dict[str, dict] = {}
    for anchor in cast("list[Tag]", soup.find_all("a", href=True)):
        href = cast("str", anchor["href"])
        match = _FACTSHEET_SLUG_RE.search(href)
        if not match:
            continue
        month, year = _MONTH_NUMBERS[match.group(1)], int(match.group(2))
        release = f"{year}-{month:02d}"
        publications.setdefault(
            release,
            {"release": release, "year": year, "month": month, "url": make_absolute_url(href, SITE_URL)},
        )

    if not publications:
        raise VacanciesDataNotFoundError(f"No factsheet publications found on {TOPIC_URL}")
    return sorted(publications.values(), key=lambda p: (p["year"], p["month"]), reverse=True)


def _resolve_publication(release: str | None, force_refresh: bool) -> dict:
    publications = list_publications(force_refresh=force_refresh)
    if release is None:
        return publications[0]
    for publication in publications:
        if publication["release"] == release:
            return publication
    available = ", ".join(p["release"] for p in publications)
    raise VacanciesDataNotFoundError(f"No factsheet for release {release!r}. Available releases: {available}")


def get_factsheet_url(release: str | None = None, force_refresh: bool = False) -> str:
    """Return the URL of a factsheet's ``.ods`` tables file.

    Args:
        release: ``"YYYY-MM"`` month of publication (see :func:`list_publications`); the latest if omitted.
        force_refresh: Bypass the page cache.

    Raises:
        VacanciesDataNotFoundError: If the release does not exist or its page links no ``.ods`` file.
    """
    publication = _resolve_publication(release, force_refresh)
    try:
        links = scrape_file_links(publication["url"], file_extension=".ods", force_refresh=force_refresh)
    except Exception as e:
        raise VacanciesDataNotFoundError(f"Could not fetch {publication['url']}: {e}") from e
    if not links:
        raise VacanciesDataNotFoundError(f"No .ods tables file linked on {publication['url']}")
    return links[0]["url"]


def _open_factsheet(release: str | None, force_refresh: bool) -> tuple[pd.ExcelFile, str]:
    """Download a factsheet and open it; returns the workbook and the release it came from."""
    publication = _resolve_publication(release, force_refresh)
    path = download_file(get_factsheet_url(publication["release"], force_refresh), force_refresh=force_refresh)
    return pd.ExcelFile(path, engine="odf"), publication["release"]


def _find_sheet(workbook: pd.ExcelFile, names: tuple[str, ...], release: str) -> str:
    wanted = {name.casefold() for name in names}
    for sheet in workbook.sheet_names:
        if str(sheet).casefold() in wanted:
            return str(sheet)
    raise VacanciesDataNotFoundError(
        f"The {release} factsheet has no {' / '.join(names)!r} sheet (sheets: {workbook.sheet_names}). "
        "Older releases use a different layout; try a later release."
    )


def _title(sheet: pd.DataFrame, label: str) -> tuple[int, str, int]:
    """Locate a table's title row: its index, the financial year it names and that year's start.

    The title is the first row in the leading rows that names a financial year such as ``2026/27``.
    It is usually the first row, but a release has carried a banner line above it.
    """
    for index in range(min(_HEADER_SEARCH_ROWS, len(sheet))):
        match = _FINANCIAL_YEAR_RE.search(str(sheet.iat[index, 0]))
        if match:
            return index, f"{match.group(1)}/{match.group(2)}", int(match.group(1))
    raise VacanciesDataError(f"{label}: no title naming a financial year such as '2026/27'")


def _header_row(sheet: pd.DataFrame, label: str, title_row: int) -> int:
    """Index of a table's header: the first row after the title with a leading label."""
    body = sheet.iloc[title_row + 1 :].reset_index(drop=True)
    index = find_marker_row(body, lambda v: bool(pd.notna(v)), max_rows=_HEADER_SEARCH_ROWS)
    if index is None:
        raise VacanciesDataError(f"{label}: no header row in the {_HEADER_SEARCH_ROWS} rows after the title")
    return title_row + 1 + index


def _is_end_of_table(label: object) -> bool:
    return bool(pd.isna(label)) or str(label).strip().casefold().startswith("notes")


def _to_int(value: object) -> int | None:
    number = coerce_numeric(pd.Series([value])).iloc[0]
    return None if pd.isna(number) else int(number)


def get_quarterly_vacancies(release: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """NI vacancies notified to DfC by quarter, from a factsheet's ``Quarterly`` sheet.

    Args:
        release: ``"YYYY-MM"`` month of publication; the latest if omitted.
        force_refresh: Bypass the caches.

    Returns:
        Columns ``financial_year`` (``"2022/23"``), ``quarter`` (1-4), ``quarter_start``
        (Timestamp) and ``vacancies``, oldest first.

    Raises:
        VacanciesDataNotFoundError: If the release or its ``Quarterly`` sheet is missing.
        VacanciesDataError: If a quarter label cannot be read.
    """
    workbook, used = _open_factsheet(release, force_refresh)
    name = _find_sheet(workbook, ("Quarterly",), used)
    sheet = parse_sheet(workbook, name, header=None)
    title_row, _, _ = _title(sheet, f"{used} {name}")
    header = _header_row(sheet, f"{used} {name}", title_row)

    rows = []
    for index in range(header + 1, len(sheet)):
        label = sheet.iat[index, 0]
        if _is_end_of_table(label):
            break
        financial_year, quarter, start = parse_quarter_label(str(label))
        count = _to_int(sheet.iat[index, 1])
        if count is None:
            raise VacanciesDataError(f"{used} {name}: no vacancy count for {label!r}")
        rows.append({"financial_year": financial_year, "quarter": quarter, "quarter_start": start, "vacancies": count})
    if not rows:
        raise VacanciesDataError(f"{used} {name}: no quarterly rows found")
    return pd.DataFrame(rows)


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """The NI quarterly vacancy series from the latest factsheet (see :func:`get_quarterly_vacancies`)."""
    return get_quarterly_vacancies(force_refresh=force_refresh)


def get_vacancy_breakdown(breakdown: str, release: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Vacancies for the current financial year of a factsheet, split by a category.

    Args:
        breakdown: One of :func:`list_breakdowns`: ``vacancy_type`` (full-time, part-time, casual),
            ``soc`` (SOC 2020 major group), ``sic`` (SIC 2007 section), ``jbo`` (Jobs & Benefits
            Office) or ``nimdm`` (deprivation quintile).
        release: ``"YYYY-MM"`` month of publication; the latest if omitted.
        force_refresh: Bypass the caches.

    Returns:
        Columns ``breakdown``, ``financial_year``, ``quarter``, ``quarter_start``, ``category``,
        ``vacancies`` and ``share`` (of that quarter's published total, 0 to 1). The published
        ``Total`` row is used for the shares and left out of the rows.

    Raises:
        VacanciesDataError: If ``breakdown`` is unknown or the sheet's layout is not recognised.
        VacanciesDataNotFoundError: If the release or sheet is missing.
    """
    if breakdown not in _BREAKDOWN_SHEETS:
        raise VacanciesDataError(f"Unknown breakdown {breakdown!r}; choose from {', '.join(_BREAKDOWN_SHEETS)}")
    workbook, used = _open_factsheet(release, force_refresh)
    name = _find_sheet(workbook, _BREAKDOWN_SHEETS[breakdown], used)
    label = f"{used} {name}"
    sheet = parse_sheet(workbook, name, header=None)

    title_row, financial_year, start_year = _title(sheet, label)
    header_row = _header_row(sheet, label, title_row)

    quarter_columns: dict[int, int] = {}
    for column in range(1, sheet.shape[1]):
        text = str(sheet.iat[header_row, column])
        match = _QUARTER_HEADER_RE.search(text)
        if match and "percent" not in text.casefold() and "%" not in text:
            quarter_columns[column] = int(match.group(1))
    if not quarter_columns:
        raise VacanciesDataError(
            f"{label}: no 'Quarter N' count columns in the header row; this release's layout is not supported"
        )

    totals: dict[int, int] = {}
    records: list[dict] = []
    for index in range(header_row + 1, len(sheet)):
        row_label = sheet.iat[index, 0]
        if _is_end_of_table(row_label):
            break
        category = str(row_label).strip()
        for column, quarter in quarter_columns.items():
            count = _to_int(sheet.iat[index, column])
            if count is None:
                raise VacanciesDataError(f"{label}: no count for {category!r} in quarter {quarter}")
            if category.casefold() == "total":
                totals[quarter] = count
            else:
                records.append(
                    {
                        "breakdown": breakdown,
                        "financial_year": financial_year,
                        "quarter": quarter,
                        "quarter_start": _quarter_start(start_year, quarter),
                        "category": category,
                        "vacancies": count,
                    }
                )
    if not records:
        raise VacanciesDataError(f"{label}: no category rows found")

    df = pd.DataFrame(records)
    # Derive the share from the counts: the published percentages mix "6%" strings with 0-1 fractions
    denominator = df["quarter"].map(totals).fillna(df.groupby("quarter")["vacancies"].transform("sum"))
    df["share"] = df["vacancies"] / denominator
    return df.sort_values(["quarter", "category"]).reset_index(drop=True)


def get_monthly_vacancies(release: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Vacancies notified in each month of a factsheet's current financial year, by vacancy type.

    Args:
        release: ``"YYYY-MM"`` month of publication; the latest if omitted.
        force_refresh: Bypass the caches.

    Returns:
        Columns ``month`` (first day of the month), ``full_time``, ``part_time``, ``casual`` and ``total``.

    Raises:
        VacanciesDataNotFoundError: If the release or its ``Monthly`` sheet is missing.
        VacanciesDataError: If the header or a month label cannot be read.
    """
    workbook, used = _open_factsheet(release, force_refresh)
    name = _find_sheet(workbook, ("Monthly",), used)
    label = f"{used} {name}"
    sheet = parse_sheet(workbook, name, header=None)
    title_row, _, _ = _title(sheet, label)
    header_row = _header_row(sheet, label, title_row)

    headers = {str(sheet.iat[header_row, c]).strip().casefold().replace("-", "_"): c for c in range(1, sheet.shape[1])}
    missing = {"full_time", "part_time", "casual", "total"} - set(headers)
    if missing:
        raise VacanciesDataError(f"{label}: missing columns {sorted(missing)} (found {sorted(headers)})")

    records = []
    for index in range(header_row + 1, len(sheet)):
        month_label = sheet.iat[index, 0]
        if _is_end_of_table(month_label):
            break
        month = pd.to_datetime(str(month_label).strip(), format="%b %Y", errors="coerce")
        if pd.isna(month):
            raise VacanciesDataError(f"{label}: unrecognised month {month_label!r}")
        record: dict = {"month": month}
        for key in ("full_time", "part_time", "casual", "total"):
            count = _to_int(sheet.iat[index, headers[key]])
            if count is None:
                raise VacanciesDataError(f"{label}: no {key} count for {month_label!r}")
            record[key] = count
        records.append(record)
    if not records:
        raise VacanciesDataError(f"{label}: no monthly rows found")
    return pd.DataFrame(records)


def _read_matrix(matrix: str) -> pd.DataFrame:
    try:
        return read_dataset(matrix)
    except PxStatError as e:
        raise VacanciesDataNotFoundError(f"PxStat matrix {matrix} unavailable: {e}") from e


def get_annual_vacancies() -> pd.DataFrame:
    """The NI total of vacancies notified to DfC for each financial year, from PxStat.

    Returns:
        Columns ``financial_year`` (``"2014/15"``) and ``vacancies``, oldest first.

    Raises:
        VacanciesDataNotFoundError: If the PxStat matrix is unavailable or has no NI rows.
    """
    matrix, label_column = _GEOGRAPHIES["hsct"]
    df = _read_matrix(matrix)
    code_column = df.columns[df.columns.get_loc(label_column) - 1]
    ni = df[df[code_column] == _NI_CODE]
    if ni.empty:
        raise VacanciesDataNotFoundError(f"PxStat matrix {matrix} has no Northern Ireland total rows")
    out = ni[["Financial Year", "VALUE"]].rename(columns={"Financial Year": "financial_year", "VALUE": "vacancies"})
    return out.sort_values("financial_year").reset_index(drop=True)


def get_vacancies_by_geography(geography: str = "lgd") -> pd.DataFrame:
    """Annual vacancies notified to DfC by area, from PxStat.

    Args:
        geography: One of :func:`list_geographies`: ``lgd`` (Local Government District),
            ``assembly_area``, ``hsct`` (Health and Social Care Trust) or ``dea``
            (District Electoral Area, 2018/19 onwards).

    Returns:
        Columns ``financial_year``, ``geography_code``, ``geography`` and ``vacancies``. The NI total
        row PxStat includes in every matrix is left out (see :func:`get_annual_vacancies`); the areas
        sum to no more than it, and usually a little less.

    Raises:
        VacanciesDataError: If ``geography`` is unknown.
        VacanciesDataNotFoundError: If the PxStat matrix is unavailable.
    """
    if geography not in _GEOGRAPHIES:
        raise VacanciesDataError(f"Unknown geography {geography!r}; choose from {', '.join(_GEOGRAPHIES)}")
    matrix, label_column = _GEOGRAPHIES[geography]
    df = _read_matrix(matrix)
    code_column = df.columns[df.columns.get_loc(label_column) - 1]
    areas = df[df[code_column] != _NI_CODE]
    out = areas.rename(
        columns={
            "Financial Year": "financial_year",
            code_column: "geography_code",
            label_column: "geography",
            "VALUE": "vacancies",
        }
    )[["financial_year", "geography_code", "geography", "vacancies"]]
    return out.sort_values(["financial_year", "geography_code"]).reset_index(drop=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a quarterly frame from :func:`get_quarterly_vacancies`.

    Checks the columns, that counts are positive integers, that no quarter repeats,
    and that the quarters are consecutive with no gap.

    Raises:
        VacanciesValidationError: If any check fails.
    """
    required = {"financial_year", "quarter", "quarter_start", "vacancies"}
    missing = required - set(df.columns)
    if missing:
        raise VacanciesValidationError(f"Missing columns: {sorted(missing)}")
    if df.empty:
        raise VacanciesValidationError("No quarterly rows")
    if (df["vacancies"] <= 0).any():
        raise VacanciesValidationError("Vacancy counts must be positive")
    if df["quarter_start"].duplicated().any():
        raise VacanciesValidationError("Duplicate quarters")
    ordered = df.sort_values("quarter_start")["quarter_start"]
    gaps = ordered.diff().dropna().dt.days
    if (gaps < 89).any() or (gaps > 92).any():
        raise VacanciesValidationError("Quarters are not consecutive")
    return True


def validate_breakdown(df: pd.DataFrame) -> bool:
    """Validate a frame from :func:`get_vacancy_breakdown`.

    Checks the columns, that counts are not negative, and that each quarter's shares sum to 1
    (within the rounding of a published total).

    Raises:
        VacanciesValidationError: If any check fails.
    """
    required = {"breakdown", "financial_year", "quarter", "quarter_start", "category", "vacancies", "share"}
    missing = required - set(df.columns)
    if missing:
        raise VacanciesValidationError(f"Missing columns: {sorted(missing)}")
    if df.empty:
        raise VacanciesValidationError("No breakdown rows")
    if (df["vacancies"] < 0).any():
        raise VacanciesValidationError("Vacancy counts must not be negative")
    if df.duplicated(["quarter", "category"]).any():
        raise VacanciesValidationError("Duplicate (quarter, category) rows")
    sums = df.groupby("quarter")["share"].sum()
    if ((sums - 1).abs() > 0.01).any():
        raise VacanciesValidationError(f"Shares do not sum to 1 for every quarter: {sums.round(4).to_dict()}")
    return True


def validate_geography(df: pd.DataFrame, annual: pd.DataFrame | None = None) -> bool:
    """Validate a frame from :func:`get_vacancies_by_geography`.

    Checks the columns, non-negative counts and no repeated (year, area). With ``annual`` (from
    :func:`get_annual_vacancies`), also checks that for every year the areas sum to no more than the
    NI total and to at least 95% of it.

    Raises:
        VacanciesValidationError: If any check fails.
    """
    required = {"financial_year", "geography_code", "geography", "vacancies"}
    missing = required - set(df.columns)
    if missing:
        raise VacanciesValidationError(f"Missing columns: {sorted(missing)}")
    if df.empty:
        raise VacanciesValidationError("No geography rows")
    if (df["vacancies"] < 0).any():
        raise VacanciesValidationError("Vacancy counts must not be negative")
    if df.duplicated(["financial_year", "geography_code"]).any():
        raise VacanciesValidationError("Duplicate (financial_year, geography_code) rows")
    if annual is not None:
        totals = annual.set_index("financial_year")["vacancies"]
        sums = df.groupby("financial_year")["vacancies"].sum()
        for year, total in sums.items():
            if year not in totals.index:
                raise VacanciesValidationError(f"No NI total for {year}")
            coverage = total / totals[year]
            if coverage > 1 or coverage < _MIN_AREA_COVERAGE:
                raise VacanciesValidationError(
                    f"{year}: areas sum to {total} against an NI total of {totals[year]} ({coverage:.1%})"
                )
    return True
