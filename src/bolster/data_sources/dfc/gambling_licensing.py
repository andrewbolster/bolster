"""Northern Ireland Gambling Licensing and Industry Data (Department for Communities).

Annual statistics on gambling in Northern Ireland, published by the Department for
Communities (DfC) as one tables workbook per release. Two groups of series are
provided:

- **Licences and permits** (:func:`get_licences`): amusement permits and the gaming
  machines they cover (from the eleven district councils), and certificates,
  licences and registrations for gaming machines, lotteries, society lotteries,
  bingo clubs, bookmaking offices and bookmakers (from the Northern Ireland Courts and
  Tribunals Service and the councils). Each release carries a five-year window.
- **Industry** (:func:`get_industry`): registered gambling businesses (from 2013),
  people employed (from 2009), land-based gambling turnover in pounds million (from
  2015) and betting and gaming duty in pounds million (financial years from 1999-2000).

Published as: Northern Ireland Gambling Licensing and Industry Data.

Data Source:
    **Publication pages**:
    ``https://www.communities-ni.gov.uk/publications/northern-ireland-gambling-licensing-and-industry-data-<year>``
    for each release year from 2022.

    The tables workbook is found by scraping the publication page. The workbook's
    address contains an upload month that differs between releases, so it is never
    built from the year. The topic page
    https://www.communities-ni.gov.uk/topics/betting-gaming-lotteries-and-amusements
    links only the newest release.

Update Frequency: Annual (autumn)
Geographic Coverage: Northern Ireland
Reference Period: Calendar years for licences, businesses, employment and turnover; financial
    years for duty

.. note::
    The layout of the workbook changes between releases: the tables are numbered
    differently (bingo clubs are Table 2 in 2022 and Table 5 from 2023), the permit tiers
    sit side by side in 2022 to 2024 and one above another in 2025, and footnote numbers
    are attached to titles and row labels. Tables are found by title and rows by their
    wording. A table or row that is not recognised raises an error and is never skipped,
    so a release whose layout changes will not return a partial frame.

.. note::
    Amusement permits are named after the maximum prize allowed on a gaming machine.
    On 29 January 2025 the higher tier's maximum rose from 25 pounds to 500 pounds, so
    ``permit_tier`` is ``"£25"`` for 2021 to 2024 and ``"£500"`` for 2025. The lower tier is
    ``"£8"`` throughout. The tiers are kept as published and are not merged.

.. note::
    Gaming machine totals for Northern Ireland up to 2024 exclude Ards and North Down
    Borough Council, whose data was not available, and the count for Causeway Coast and
    Glens Borough Council in the 2025 release is its 2024 figure.

.. note::
    Betting and gaming duty is labelled "Turnover (pounds million)" in the 2025 workbook
    and "Betting and gaming duty (pounds million)" in earlier ones. The values are the
    duty in both, and the module identifies the series from the table title.

.. note::
    Turnover covers land-based operators only; online gambling is outside the series.
    Registered businesses are rounded to the nearest 5 and the employment and turnover
    figures come from samples (BRES and the Northern Ireland Annual Business Inquiry),
    so small changes between years are within sampling error.

Example:
    >>> from bolster.data_sources.dfc import gambling_licensing
    >>> gambling_licensing.parse_permit_tier("Amusement permit £252")
    '£25'
    >>> gambling_licensing.list_categories()[:3]
    ['amusement_permits', 'gaming_machine_certificates', 'lottery_certificates']
"""

import logging
import re
from datetime import date
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup, Tag

from bolster.utils.cache import CachedDownloader, bind_download_file, load_workbook
from bolster.utils.excel import parse_sheet
from bolster.utils.web import make_absolute_url, session

logger = logging.getLogger(__name__)

SITE_URL = "https://www.communities-ni.gov.uk"
TOPIC_URL = f"{SITE_URL}/topics/betting-gaming-lotteries-and-amusements"
PUBLICATION_URL = SITE_URL + "/publications/northern-ireland-gambling-licensing-and-industry-data-{year}"

# The first release published in this form; earlier years have no publication page
FIRST_RELEASE = 2022

# Releases are annual and are not revised in place, and a new release has a new address
_CACHE_TTL_HOURS = 24 * 90

# Leading rows searched for a table's header
_HEADER_SEARCH_ROWS = 8

_downloader = CachedDownloader("dfc_gambling_licensing", timeout=60)


class GamblingDataError(Exception):
    """Base exception for gambling licensing data errors."""

    pass


class GamblingDataNotFoundError(GamblingDataError):
    """Raised when a release, its workbook or a required table cannot be located or downloaded."""

    pass


class GamblingPageNotFoundError(GamblingDataNotFoundError):
    """Raised when a release year has no publication page (HTTP 404)."""

    pass


class GamblingValidationError(GamblingDataError):
    """Raised when a workbook has a table, row or value that is not recognised, or parsed data fails validation."""

    pass


# download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=False) -> Path,
# raising GamblingDataNotFoundError in place of DownloadError.
download_file = bind_download_file(_downloader, GamblingDataNotFoundError, _CACHE_TTL_HOURS)

# Table key -> title phrases that identify it (matched against the lower-cased, footnote-free title).
# Keys are in the order the module reports them.
_TABLE_TITLES: dict[str, tuple[str, ...]] = {
    "amusement_permits": ("amusement permits",),
    "gaming_machine_certificates": ("gaming machine certificates",),
    "lottery_certificates": ("lottery certificates",),
    "society_lotteries": ("society lotteries",),
    "bingo_clubs": ("bingo clubs",),
    "bookmaking_offices": ("bookmaking offices",),
    "bookmakers": ("bookmaker licences", "bookmakers' licences"),
    "registered_businesses": ("registered gambling businesses",),
    "employment": ("people employed",),
    "turnover": ("business turnover",),
    "duty": ("betting and gaming duty",),
}

_LICENCE_TABLES = (
    "amusement_permits",
    "gaming_machine_certificates",
    "lottery_certificates",
    "society_lotteries",
    "bingo_clubs",
    "bookmaking_offices",
    "bookmakers",
)

# Tables that first appear in a later release than the first
_TABLE_FIRST_RELEASE = {"gaming_machine_certificates": 2023, "society_lotteries": 2023}

# Maximum-prize tiers of amusement permit that the module recognises, longest amounts first
_PERMIT_TIER_AMOUNTS = ("500", "25", "8")

_AMUSEMENT_MEASURES = (
    ("existing amusement permits", "existing_permits"),
    ("gaming machines of each type", "gaming_machines"),
    ("new amusement permits granted", "new_permits_granted"),
    ("cancelled or revoked", "cancelled_or_revoked"),
    ("pleasure fair", "pleasure_fair_permits_granted"),
)

# Word -> measure, checked in this order after the disqualification rules
_LICENCE_MEASURE_WORDS = (
    ("operational", "operational"),
    ("renewals", "renewed"),
    ("renewed", "renewed"),
    ("granted", "granted"),
    ("transferred", "transferred"),
    ("revoked", "revoked"),
    ("cancelled", "cancelled"),
    ("refused", "refused"),
    ("registered", "registered"),
)

_LICENCE_COLUMNS = ["release", "year", "category", "permit_tier", "measure", "value"]
_INDUSTRY_COLUMNS = ["release", "period", "year", "series", "unit", "value"]

_YEAR_RE = re.compile(r"^(\d{4})$")
_PERIOD_RE = re.compile(r"^(\d{4})(?:-(\d{2}|\d{4}))?$")


def list_categories() -> list[str]:
    """Return the ``category`` values of :func:`get_licences`.

    Example:
        >>> list_categories()
        ['amusement_permits', 'gaming_machine_certificates', 'lottery_certificates', 'society_lotteries', 'bingo_clubs', 'bookmaking_offices', 'bookmakers']
    """
    return list(_LICENCE_TABLES)


def list_series() -> list[str]:
    """Return the ``series`` values of :func:`get_industry`.

    Example:
        >>> list_series()
        ['registered_businesses', 'employment_full_time', 'employment_part_time', 'employment_total', 'land_based_turnover', 'betting_and_gaming_duty']
    """
    return [
        "registered_businesses",
        "employment_full_time",
        "employment_part_time",
        "employment_total",
        "land_based_turnover",
        "betting_and_gaming_duty",
    ]


def parse_permit_tier(label: str) -> str:
    """Return the maximum-prize tier named in an amusement permit label, such as ``"£25"``.

    The label carries a footnote marker that is glued to the amount in older releases
    (``"Amusement permit £252"`` is the 25 pound tier with footnote 2) or written as
    ``[Note 1]`` in the newest, so the amount is matched against the tiers the module
    knows, preferring an exact match.

    Args:
        label: A tier label from the amusement permits table.

    Returns:
        The tier, for example ``"£500"``, ``"£25"`` or ``"£8"``.

    Raises:
        GamblingValidationError: If the label has no amount, or the amount is not a known tier.

    Example:
        >>> parse_permit_tier("Amusement permit £500 [Note 1]")
        '£500'
        >>> parse_permit_tier("Amusement permit £252")
        '£25'
        >>> parse_permit_tier("Amusement permit £81")
        '£8'
    """
    text = re.sub(r"\[.*?\]", "", str(label))
    match = re.search(r"£\s*(\d+)", text)
    if not match:
        raise GamblingValidationError(f"No permit amount in label {label!r}")
    digits = match.group(1)
    if digits in _PERMIT_TIER_AMOUNTS:
        return f"£{digits}"
    for amount in _PERMIT_TIER_AMOUNTS:
        # A footnote marker is a single digit glued onto the amount
        if digits.startswith(amount) and len(digits) == len(amount) + 1:
            return f"£{amount}"
    raise GamblingValidationError(
        f"Unrecognised amusement permit tier in label {label!r}; known tiers are "
        + ", ".join(f"£{amount}" for amount in _PERMIT_TIER_AMOUNTS)
    )


def parse_measure(label: str, category: str) -> str:
    """Map a row label from a licence table to its measure name.

    Args:
        label: The row label, which may carry a ``[Note n]`` marker or a glued footnote digit.
        category: The table's category, because amusement permits use different measures.

    Returns:
        A measure such as ``"operational"``, ``"renewed"`` or ``"disqualification_orders_revocation"``.

    Raises:
        GamblingValidationError: If the label is not recognised.

    Example:
        >>> parse_measure("Number of bingo club renewals4", "bingo_clubs")
        'renewed'
        >>> parse_measure("Number of disqualification orders made in consequence of: the revocation of any licence", "bookmakers")
        'disqualification_orders_revocation'
    """
    text = _clean_label(label).lower()
    if category == "amusement_permits":
        for phrase, measure in _AMUSEMENT_MEASURES:
            if phrase in text:
                return measure
        raise GamblingValidationError(f"Unrecognised amusement permit measure {label!r}")
    if "disqualification" in text:
        if "revocation" in text:
            return "disqualification_orders_revocation"
        if "conviction" in text:
            return "disqualification_orders_conviction"
        return "disqualification_orders"
    for word, measure in _LICENCE_MEASURE_WORDS:
        if re.search(rf"\b{word}\b", text):
            return measure
    raise GamblingValidationError(f"Unrecognised {category} measure {label!r}")


def _clean_label(label: object) -> str:
    """Strip ``[Note n]`` markers, glued footnote digits and surrounding space from a row label."""
    text = re.sub(r"\s*\[.*?\]", "", str(label).replace("’", "'")).strip()
    return re.sub(r"\d+$", "", text).strip()


def _normalise_title(raw: object) -> str:
    """Lower-case a sheet's title without its ``Table n`` prefix, footnote markers or trailing digits."""
    text = re.sub(r"\[.*?\]", "", str(raw).replace("’", "'"))
    text = re.sub(r"^\s*table\s+\d+\s*:?\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"[\d,\s]+$", "", text).strip().lower()


def _table_key(title: str) -> str | None:
    for key, phrases in _TABLE_TITLES.items():
        if any(phrase in title for phrase in phrases):
            return key
    return None


def _as_year(value: object) -> int | None:
    """Return ``value`` as a four-digit year, or ``None`` if it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float) and not pd.isna(value) and float(value).is_integer():
        text = str(int(value))
    else:
        text = str(value).strip()
    match = _YEAR_RE.match(text)
    return int(match.group(1)) if match else None


def _is_blank(value: object) -> bool:
    return value is None or bool(pd.isna(value)) or str(value).strip() == ""


def _number(value: object, where: str) -> float:
    """Return a cell as a number, or raise naming where the cell is."""
    if isinstance(value, bool):
        raise GamblingValidationError(f"Non-numeric value {value!r} at {where}")
    if isinstance(value, int | float):
        if pd.isna(value):
            raise GamblingValidationError(f"Missing value at {where}")
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        raise GamblingValidationError(f"Non-numeric value {value!r} at {where}") from None


def _find_header_row(sheet: pd.DataFrame, sheet_name: str) -> int:
    """Index of the first row whose cells after the label are all years."""
    for index in range(1, min(len(sheet), _HEADER_SEARCH_ROWS)):
        cells = [value for value in sheet.iloc[index, 1:].tolist() if not _is_blank(value)]
        if cells and all(_as_year(value) is not None for value in cells):
            return index
    raise GamblingValidationError(f"No year header found in the first {_HEADER_SEARCH_ROWS} rows of {sheet_name!r}")


def _parse_year_across(sheet: pd.DataFrame, sheet_name: str, category: str, release: int) -> list[dict[str, Any]]:
    """Rows of a table with a measure per row and a year per column."""
    header = _find_header_row(sheet, sheet_name)
    year_columns = {
        column: _as_year(value)
        for column, value in enumerate(sheet.iloc[header].tolist())
        if column > 0 and _as_year(value) is not None
    }
    rows: list[dict[str, Any]] = []
    for index in range(header + 1, len(sheet)):
        label = sheet.iat[index, 0]
        cells = {column: sheet.iat[index, column] for column in year_columns}
        if _is_blank(label) or all(_is_blank(value) for value in cells.values()):
            if rows:
                break
            continue
        measure = parse_measure(str(label), category)
        for column, year in year_columns.items():
            where = f"{sheet_name!r} row {str(label)[:50]!r} year {year}"
            rows.append(_licence_row(release, year, category, None, measure, _number(cells[column], where)))
    if not rows:
        raise GamblingValidationError(f"No measure rows found in {sheet_name!r}")
    return rows


def _licence_row(
    release: int, year: int | None, category: str, tier: str | None, measure: str, value: float
) -> dict[str, Any]:
    return {
        "release": release,
        "year": year,
        "category": category,
        "permit_tier": tier,
        "measure": measure,
        "value": value,
    }


def _is_tier_label(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith("amusement permit")


def _parse_amusement_permits(sheet: pd.DataFrame, sheet_name: str, release: int) -> list[dict[str, Any]]:
    """Rows of the amusement permits table, whichever way the tiers are laid out."""
    category = "amusement_permits"
    vertical = [index for index in range(len(sheet)) if _is_tier_label(sheet.iat[index, 0])]
    rows: list[dict[str, Any]] = []
    if vertical:
        # Tiers stacked one above another: the tier label sits in the header row, with its years
        for start in vertical:
            tier = parse_permit_tier(str(sheet.iat[start, 0]))
            years = {
                column: _as_year(value)
                for column, value in enumerate(sheet.iloc[start].tolist())
                if column > 0 and _as_year(value) is not None
            }
            if not years:
                raise GamblingValidationError(f"No years beside the {tier} permit tier in {sheet_name!r}")
            for index in range(start + 1, len(sheet)):
                label = sheet.iat[index, 0]
                if _is_blank(label):
                    break
                for column, year in years.items():
                    where = f"{sheet_name!r} row {str(label)[:50]!r} tier {tier} year {year}"
                    value = _number(sheet.iat[index, column], where)
                    rows.append(_licence_row(release, year, category, tier, parse_measure(str(label), category), value))
        return rows

    # Tiers side by side: one row of years, one row of tier labels, blocks of columns per tier
    header = _find_header_row(sheet, sheet_name)
    year_columns = [
        (column, _as_year(value))
        for column, value in enumerate(sheet.iloc[header].tolist())
        if column > 0 and _as_year(value) is not None
    ]
    tier_row = next(
        (
            index
            for index in range(header, min(header + 3, len(sheet)))
            if any(_is_tier_label(value) for value in sheet.iloc[index, 1:].tolist())
        ),
        None,
    )
    if tier_row is None:
        raise GamblingValidationError(f"No permit tier labels found below the year header of {sheet_name!r}")
    tiers = [parse_permit_tier(str(value)) for value in sheet.iloc[tier_row, 1:].tolist() if _is_tier_label(value)]
    blocks: list[list[tuple[int, int]]] = []
    previous: int | None = None
    for column, year in year_columns:
        assert year is not None
        if previous is None or year >= previous:
            blocks.append([])
        blocks[-1].append((column, year))
        previous = year
    if len(blocks) != len(tiers):
        raise GamblingValidationError(
            f"{sheet_name!r} has {len(tiers)} permit tier labels but {len(blocks)} blocks of years"
        )
    for index in range(tier_row + 1, len(sheet)):
        label = sheet.iat[index, 0]
        if _is_blank(label) or all(_is_blank(sheet.iat[index, column]) for column, _ in year_columns):
            if rows:
                break
            continue
        measure = parse_measure(str(label), category)
        for tier, block in zip(tiers, blocks, strict=True):
            for column, year in block:
                where = f"{sheet_name!r} row {str(label)[:50]!r} tier {tier} year {year}"
                rows.append(
                    _licence_row(release, year, category, tier, measure, _number(sheet.iat[index, column], where))
                )
    return rows


def _parse_period(value: object, where: str) -> tuple[str, int]:
    """Return ``(period label, start year)`` for a calendar year or a financial year such as ``"2024-25"``."""
    year = _as_year(value)
    if year is not None:
        return str(year), year
    match = _PERIOD_RE.match(str(value).strip())
    if not match or not match.group(2):
        raise GamblingValidationError(f"Unrecognised period {value!r} at {where}")
    start = int(match.group(1))
    return str(value).strip(), start


def _parse_industry(sheet: pd.DataFrame, sheet_name: str, key: str, release: int) -> list[dict[str, Any]]:
    """Rows of one of the long series tables (businesses, employment, turnover, duty)."""
    header_row = next(
        (
            index
            for index in range(1, min(len(sheet), _HEADER_SEARCH_ROWS))
            if str(sheet.iat[index, 0]).strip().lower() in {"year", "financial year"}
        ),
        None,
    )
    if header_row is None:
        raise GamblingValidationError(
            f"No 'Year' header found in the first {_HEADER_SEARCH_ROWS} rows of {sheet_name!r}"
        )
    headers = [re.sub(r"\[.*?\]", "", str(value)).strip().lower() for value in sheet.iloc[header_row].tolist()]
    if key == "employment":
        wanted = {"full-time": "employment_full_time", "part-time": "employment_part_time", "total": "employment_total"}
        columns = {}
        for column, header in enumerate(headers):
            if header in wanted:
                columns[column] = (wanted[header], "people")
        if len(columns) != len(wanted):
            raise GamblingValidationError(
                f"{sheet_name!r} has columns {headers}; expected full-time, part-time and total"
            )
    else:
        series, unit = {
            "registered_businesses": ("registered_businesses", "businesses"),
            "turnover": ("land_based_turnover", "£m"),
            "duty": ("betting_and_gaming_duty", "£m"),
        }[key]
        value_columns = [column for column, header in enumerate(headers) if column > 0 and header and header != "nan"]
        if len(value_columns) != 1:
            raise GamblingValidationError(f"{sheet_name!r} has columns {headers}; expected one value column")
        columns = {value_columns[0]: (series, unit)}

    rows: list[dict[str, Any]] = []
    for index in range(header_row + 1, len(sheet)):
        first = sheet.iat[index, 0]
        if _is_blank(first) or all(_is_blank(sheet.iat[index, column]) for column in columns):
            if rows:
                break
            continue
        if _as_year(first) is None and not _PERIOD_RE.match(str(first).strip()):
            break
        where = f"{sheet_name!r} period {first!s}"
        period, year = _parse_period(first, where)
        for column, (series, unit) in columns.items():
            rows.append(
                {
                    "release": release,
                    "period": period,
                    "year": year,
                    "series": series,
                    "unit": unit,
                    "value": _number(sheet.iat[index, column], f"{where} column {headers[column]!r}"),
                }
            )
    if not rows:
        raise GamblingValidationError(f"No data rows found in {sheet_name!r}")
    return rows


def list_releases(force_refresh: bool = False) -> list[int]:
    """Return the release years that have a publication page, oldest first.

    Each candidate year from :data:`FIRST_RELEASE` to next year is probed once. A year with
    no page is left out; any other failure raises.

    Args:
        force_refresh: Bypass the cached pages.

    Returns:
        The release years found, for example ``[2022, 2023, 2024, 2025]``.

    Raises:
        GamblingDataNotFoundError: If no release is found, or a page cannot be fetched.
    """
    found = []
    for year in range(FIRST_RELEASE, date.today().year + 2):
        try:
            _workbook_url(year, force_refresh=force_refresh)
        except GamblingPageNotFoundError:
            continue
        found.append(year)
    if not found:
        raise GamblingDataNotFoundError(
            f"No Gambling Licensing and Industry Data publication found from {FIRST_RELEASE}"
        )
    return found


def _workbook_url(release: int, force_refresh: bool = False) -> str:
    """Address of a release's tables workbook, scraped from its publication page."""
    page = PUBLICATION_URL.format(year=release)
    response = session.get(page, timeout=60, force_refresh=force_refresh)
    if response.status_code != 200:
        message = (
            f"No Gambling Licensing and Industry Data publication page for {release} at {page} "
            f"(HTTP {response.status_code})"
        )
        if response.status_code == 404:
            raise GamblingPageNotFoundError(message)
        raise GamblingDataNotFoundError(message)
    soup = BeautifulSoup(response.text, "html.parser")
    links = [
        make_absolute_url(str(tag["href"]), SITE_URL) for tag in soup.find_all("a", href=True) if isinstance(tag, Tag)
    ]
    tables = [url for url in links if url.lower().split("?")[0].endswith(".xlsx") and "tables" in url.lower()]
    if not tables:
        raise GamblingDataNotFoundError(f"The {release} publication page {page} lists no tables workbook (.xlsx)")
    return tables[0]


def _resolve_release(release_year: int | None, force_refresh: bool) -> int:
    if release_year is None:
        return list_releases(force_refresh=force_refresh)[-1]
    return release_year


def _read_release(release: int, force_refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse one release into ``(licences, industry)`` frames."""
    url = _workbook_url(release, force_refresh=force_refresh)
    workbook = load_workbook(url, download_file, force_refresh=force_refresh)

    sheets: dict[str, tuple[str, pd.DataFrame]] = {}
    for name in workbook.sheet_names:
        if not str(name).lower().startswith("table "):
            continue
        sheet = parse_sheet(workbook, str(name), header=None, dtype=object)
        title = _normalise_title(sheet.iat[0, 0])
        key = _table_key(title)
        if key is None:
            raise GamblingValidationError(f"Unrecognised table {name!r} titled {title!r} in the {release} workbook")
        if key in sheets:
            raise GamblingValidationError(
                f"The {release} workbook has two tables for {key!r}: {sheets[key][0]!r} and {name!r}"
            )
        sheets[key] = (str(name), sheet)

    missing = [
        key for key in _TABLE_TITLES if key not in sheets and release >= _TABLE_FIRST_RELEASE.get(key, FIRST_RELEASE)
    ]
    if missing:
        raise GamblingDataNotFoundError(f"The {release} workbook has no table for: {', '.join(missing)}")

    licence_rows: list[dict[str, Any]] = []
    industry_rows: list[dict[str, Any]] = []
    for key, (name, sheet) in sheets.items():
        if key == "amusement_permits":
            licence_rows += _parse_amusement_permits(sheet, name, release)
        elif key in _LICENCE_TABLES:
            licence_rows += _parse_year_across(sheet, name, key, release)
        else:
            industry_rows += _parse_industry(sheet, name, key, release)

    licences = pd.DataFrame(licence_rows, columns=_LICENCE_COLUMNS)
    licences["year"] = licences["year"].astype("int64")
    licences["permit_tier"] = licences["permit_tier"].astype("string")
    licences["value"] = licences["value"].astype("Int64")
    order = {category: position for position, category in enumerate(_LICENCE_TABLES)}
    licences = licences.assign(_order=licences["category"].map(order)).sort_values(
        ["_order", "permit_tier", "measure", "year"], kind="stable"
    )
    licences = licences.drop(columns="_order").reset_index(drop=True)

    industry = pd.DataFrame(industry_rows, columns=_INDUSTRY_COLUMNS)
    industry["year"] = industry["year"].astype("int64")
    industry["value"] = industry["value"].astype("float64")
    series_order = {series: position for position, series in enumerate(list_series())}
    industry = industry.assign(_order=industry["series"].map(series_order)).sort_values(
        ["_order", "year"], kind="stable"
    )
    industry = industry.drop(columns="_order").reset_index(drop=True)
    return licences, industry


def get_licences(release_year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return licences, permits and registrations by category, measure and year.

    One row per category, permit tier, measure and year, for the five calendar years a release
    covers (three for society lotteries, which start in 2023).

    Args:
        release_year: The release to read, for example ``2025``. Defaults to the latest.
        force_refresh: Bypass the cached pages and workbook.

    Returns:
        DataFrame with columns ``release``, ``year``, ``category`` (see :func:`list_categories`),
        ``permit_tier`` (amusement permits only, otherwise missing), ``measure`` and ``value``
        (a count).

    Raises:
        GamblingDataNotFoundError: If the release has no publication page or workbook, or a table is missing.
        GamblingValidationError: If the workbook has a table, row or value that is not recognised.
    """
    release = _resolve_release(release_year, force_refresh)
    licences, _ = _read_release(release, force_refresh=force_refresh)
    return licences


def get_industry(release_year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return registered businesses, employment, turnover and duty by year.

    Args:
        release_year: The release to read, for example ``2025``. Defaults to the latest.
        force_refresh: Bypass the cached pages and workbook.

    Returns:
        DataFrame with columns ``release``, ``period`` (a year or a financial year such as
        ``"2024-25"``), ``year`` (the calendar year, or the year the financial year starts),
        ``series`` (see :func:`list_series`), ``unit`` and ``value``.

    Raises:
        GamblingDataNotFoundError: If the release has no publication page or workbook, or a table is missing.
        GamblingValidationError: If the workbook has a table, row or value that is not recognised.
    """
    release = _resolve_release(release_year, force_refresh)
    _, industry = _read_release(release, force_refresh=force_refresh)
    return industry


def get_latest_data(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Return the licence and industry frames of the latest release.

    Returns:
        ``{"licences": ..., "industry": ...}``, as returned by :func:`get_licences` and :func:`get_industry`.
    """
    release = list_releases(force_refresh=force_refresh)[-1]
    licences, industry = _read_release(release, force_refresh=force_refresh)
    return {"licences": licences, "industry": industry}


def get_all_releases(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Return every release's frames stacked, with the ``release`` column telling them apart.

    Releases overlap and a later release can revise an earlier year, so the same year and
    measure can appear in several releases. Nothing is merged or replaced: choose the release
    you want, for example the latest value per year with
    ``df.sort_values("release").drop_duplicates(keys, keep="last")``.

    Returns:
        ``{"licences": ..., "industry": ...}`` covering every release from :func:`list_releases`.
    """
    licences, industries = [], []
    for release in list_releases(force_refresh=force_refresh):
        frame_licences, frame_industry = _read_release(release, force_refresh=force_refresh)
        licences.append(frame_licences)
        industries.append(frame_industry)
    return {
        "licences": pd.concat(licences, ignore_index=True),
        "industry": pd.concat(industries, ignore_index=True),
    }


def validate_licences(df: pd.DataFrame) -> bool:
    """Validate a licences frame.

    Checks the columns, that categories are known, that counts are non-negative whole numbers,
    that only amusement permits carry a tier, and that no release repeats a measure for a year.

    Raises:
        GamblingValidationError: If a check fails.

    Returns:
        True if every check passes.

    Example:
        >>> frame = pd.DataFrame(
        ...     {"release": [2025], "year": [2025], "category": ["bingo_clubs"], "permit_tier": [pd.NA],
        ...      "measure": ["operational"], "value": [37]}
        ... )
        >>> validate_licences(frame)
        True
    """
    missing = [column for column in _LICENCE_COLUMNS if column not in df.columns]
    if missing:
        raise GamblingValidationError(f"Licences frame is missing columns: {missing}")
    if df.empty:
        raise GamblingValidationError("Licences frame is empty")
    unknown = sorted(set(df["category"]) - set(_LICENCE_TABLES))
    if unknown:
        raise GamblingValidationError(f"Unknown categories: {unknown}")
    values = pd.to_numeric(df["value"], errors="coerce")
    if values.isna().any() or (values < 0).any() or ((values % 1) != 0).any():
        raise GamblingValidationError("Licence counts must be non-negative whole numbers")
    has_tier = df["permit_tier"].notna()
    if (has_tier & (df["category"] != "amusement_permits")).any() or (
        ~has_tier & (df["category"] == "amusement_permits")
    ).any():
        raise GamblingValidationError("Only amusement permits carry a permit tier, and every one must")
    keys = ["release", "year", "category", "permit_tier", "measure"]
    duplicated = df.assign(permit_tier=df["permit_tier"].astype("object").fillna("-")).duplicated(subset=keys)
    if duplicated.any():
        raise GamblingValidationError(
            f"{int(duplicated.sum())} repeated release, year, category, tier and measure rows"
        )
    return True


def validate_industry(df: pd.DataFrame) -> bool:
    """Validate an industry frame.

    Checks the columns, that series are known, that values are non-negative, that no release
    repeats a series for a period, and that total employment equals full-time plus part-time.

    Raises:
        GamblingValidationError: If a check fails.

    Returns:
        True if every check passes.

    Example:
        >>> frame = pd.DataFrame(
        ...     {"release": [2025] * 3, "period": ["2024"] * 3, "year": [2024] * 3,
        ...      "series": ["employment_full_time", "employment_part_time", "employment_total"],
        ...      "unit": ["people"] * 3, "value": [1188.0, 859.0, 2047.0]}
        ... )
        >>> validate_industry(frame)
        True
    """
    missing = [column for column in _INDUSTRY_COLUMNS if column not in df.columns]
    if missing:
        raise GamblingValidationError(f"Industry frame is missing columns: {missing}")
    if df.empty:
        raise GamblingValidationError("Industry frame is empty")
    unknown = sorted(set(df["series"]) - set(list_series()))
    if unknown:
        raise GamblingValidationError(f"Unknown series: {unknown}")
    if (pd.to_numeric(df["value"], errors="coerce").isna() | (df["value"] < 0)).any():
        raise GamblingValidationError("Industry values must be non-negative numbers")
    if df.duplicated(subset=["release", "period", "series"]).any():
        raise GamblingValidationError("Repeated release, period and series rows")
    employment = df[df["series"].str.startswith("employment_")].pivot_table(
        index=["release", "period"], columns="series", values="value", aggfunc="first"
    )
    if not employment.empty and {"employment_full_time", "employment_part_time", "employment_total"} <= set(
        employment.columns
    ):
        gap = (
            employment["employment_full_time"] + employment["employment_part_time"] - employment["employment_total"]
        ).abs()
        if (gap > 1).any():
            raise GamblingValidationError("Total employment is not full-time plus part-time in some periods")
    return True
