"""Young people's experience of culture, arts, heritage and sport in Northern Ireland.

Findings from the Young Persons' Behaviour and Attitudes Survey (YPBAS), a school survey of
pupils in Years 8 to 12 run by NISRA's Central Survey Unit. The Department for Communities
(DfC) publishes its questions as two series of triennial releases, one for *culture* (culture,
arts and heritage: the arts, museums and science centres, the public library service,
heritage, Irish, Ulster-Scots and sign language) and one for *sport*. Each release is a set of
ODS workbooks of tables, broken down by sex, school year group, religious background,
disability and entitlement to free school meals.

Two tidy frames are provided:

- :func:`get_survey_tables`: every estimate of the wave, one row per table, item, breakdown
  and group, with a 95% confidence interval and the number of respondents (``base``) where
  the table publishes them.
- :func:`get_wave_comparisons`: the tables that compare the wave with the previous one, with
  the publisher's marker of whether the difference is statistically significant.

Published as: Experience of culture, arts and heritage by young people in Northern Ireland; Experience of sport by young people in Northern Ireland.

Data Source:
    **Hub pages** (one per series, listing every wave):

    - https://www.communities-ni.gov.uk/articles/culture-arts-and-heritage-statistics
    - https://www.communities-ni.gov.uk/articles/experience-sport-northern-ireland

    The module scrapes each hub for the publication page of every wave, then each publication
    page for its ``.ods`` workbooks. Neither the slug of a publication nor the name of a file
    is predictable from the year, so none is ever built from it.

Update Frequency: Triennial (2016, 2019, 2022, 2025)
Geographic Coverage: Northern Ireland (post-primary school pupils in Years 8 to 12)
Reference Period: Survey waves from 2016 (the culture series also carries a 2013 comparison)

.. note::
    **Survey, not census.** Figures are percentages of surveyed pupils, with sampling error.
    Use ``ci_lower`` and ``ci_upper`` and ``base`` before reading a small difference between
    groups or waves as real.

.. note::
    **Weighting changed in 2025.** The 2025 tables say the weighting methodology for the
    analysis by sex, year group and religious background changed, so comparisons of those
    breakdowns with earlier waves need caution. The overall (``All``) figures are not affected.

.. note::
    **Labels as published.** The wording of a category changes between waves: the sex
    breakdown is ``Gender`` in 2019 and 2022 and ``Sex`` in 2025, and the free school meals
    rows carry a typo ("Entitled to free to school meals"). The module normalises the
    breakdown and group labels it can identify with certainty (see :func:`clean_breakdown`
    and :func:`clean_group`) and leaves item wording alone.

.. note::
    **Significance markers.** The comparison tables mark a difference with a symbol: ``È``
    (significantly lower than the previous wave), ``Ç`` (significantly higher) and ``¬``
    or ``-`` (no significant difference). The publisher does not document the symbols in
    the workbook, so they are read from their direction against the figures of every 2019,
    2022 and 2025 table. The 2016 workbooks use a numeric marker (``-1``) whose meaning is not
    given and not guessed: those tables raise :class:`YoungPeopleLayoutError`.
    ``marker_consistent`` is ``False`` for a row whose marker contradicts the sign of the
    change: the publisher's 2022 sport table 13 marks the Protestant row (69% against 65%) as
    lower. The marker is kept as published and flagged.

Example:
    >>> from bolster.data_sources.dfc import young_people_culture_sport as yp
    >>> yp.clean_breakdown("Gender")
    'Sex'
    >>> yp.clean_group("Year 8")
    '8'
"""

import logging
import re
from typing import Any, cast

import pandas as pd
from bs4 import Tag  # noqa: TC002 (used inside `cast(...)`, evaluated at runtime)

from bolster.utils.cache import CachedDownloader, bind_download_file
from bolster.utils.excel import parse_sheet
from bolster.utils.web import fetch_soup, make_absolute_url, scrape_file_links

logger = logging.getLogger(__name__)

SITE_URL = "https://www.communities-ni.gov.uk"

# Series (topic) -> hub page listing the publication of every wave
HUB_URLS = {
    "culture": f"{SITE_URL}/articles/culture-arts-and-heritage-statistics",
    "sport": f"{SITE_URL}/articles/experience-sport-northern-ireland",
}
TOPICS = tuple(HUB_URLS)

_PUBLICATION_RE = re.compile(r"/publications/experience-[a-z-]*young-people-northern-ireland-(\d{4})/?$")
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_TABLE_TITLE_RE = re.compile(r"^\s*Table\s+([0-9]+[a-z]?(?:_[0-9]+[a-z]?)*)\s*:\s*(.*?)\s*$")
_TRAILING_YEARS_RE = re.compile(r"\s*(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?\s*$")
_BLOCK_TITLE_RE = re.compile(r"^\s*[a-z]\)\s*(?:by\s+)?(.*?)\s*$", re.IGNORECASE)
_TITLE_BY_RE = re.compile(r"\bby\s+([A-Za-z ]+?)\s*$")
_FILE_SUFFIX_RE = re.compile(r"-by-young-people(?:-in)?-northern-ireland-\d{4}$")
_BASE_HEADER_RE = re.compile(r"^\s*(?:(?:19|20)\d{2}\s+)?bases?\s*$", re.IGNORECASE)
# Lines that follow the data of a block: notes, the index of the other available blocks, a block title
_FOOTER_RE = re.compile(r"^\s*(?:note|data is available|percentages may|base is|source)\b|^\s*[a-z]\)", re.IGNORECASE)

_HEADER_SEARCH_ROWS = 8

# Breakdown names as the publisher words them, lower-cased -> the name used in every wave
_BREAKDOWN_ALIASES = {
    "all": "All",
    "sex": "Sex",
    "gender": "Sex",
    "year group": "Year Group",
    "religion": "Religious background",
    "religious background": "Religious background",
    "disability": "Disability",
    "entitled to free to school meals": "Entitlement to free school meals",
    "entitled to free school meals": "Entitlement to free school meals",
    "entitlement to free school meals": "Entitlement to free school meals",
    "free school meals entitlement": "Entitlement to free school meals",
}

# What the significance marker of a comparison table means, by the glyph the publisher uses
_SIGNIFICANCE = {
    "È": "lower",  # È
    "Ç": "higher",  # Ç
    "¬": "no_significant_difference",  # ¬
    "-": "no_significant_difference",
}

_ESTIMATE_COLUMNS = [
    "survey_year",
    "release_year",
    "topic",
    "workbook",
    "table_id",
    "table_title",
    "indicator",
    "item",
    "breakdown",
    "group",
    "percent",
    "ci_lower",
    "ci_upper",
    "base",
]
_COMPARISON_COLUMNS = [
    "survey_year",
    "comparison_year",
    "topic",
    "workbook",
    "table_id",
    "table_title",
    "indicator",
    "breakdown",
    "group",
    "percent",
    "base",
    "percent_comparison",
    "base_comparison",
    "change_points",
    "significance",
    "marker",
    "marker_consistent",
]

# A wave is published once every three years and never revised, so a long cache is safe
_CACHE_TTL_HOURS = 24 * 90
_downloader = CachedDownloader("dfc_young_people", timeout=60)


class YoungPeopleDataError(Exception):
    """Base error for the young people's culture and sport data source."""


class YoungPeopleDataNotFoundError(YoungPeopleDataError):
    """The requested wave, workbook or file could not be found or downloaded."""


class YoungPeopleLayoutError(YoungPeopleDataError):
    """A table's layout is not one this module recognises."""


class YoungPeopleValidationError(YoungPeopleDataError):
    """Parsed data fails validation."""


download_file = bind_download_file(_downloader, YoungPeopleDataNotFoundError, _CACHE_TTL_HOURS)


# ---------------------------------------------------------------------------
# Label cleaning
# ---------------------------------------------------------------------------


def clean_breakdown(label: str) -> str:
    """Return the standard name of a breakdown (``Gender`` and ``Sex`` are both ``Sex``).

    Labels without a known alias are returned with whitespace tidied and nothing else changed.

    Example:
        >>> clean_breakdown("Gender")
        'Sex'
        >>> clean_breakdown("entitled to free to school meals")
        'Entitlement to free school meals'
        >>> clean_breakdown("Language spoken")
        'Language spoken'
    """
    tidy = re.sub(r"\s+", " ", str(label)).strip()
    return _BREAKDOWN_ALIASES.get(tidy.lower(), tidy)


def clean_group(label: str) -> str:
    """Tidy a respondent group label so the same group has the same name in every table.

    Collapses whitespace, removes spaces around ``/``, drops the ``Year`` prefix from a year
    group (``Year 8`` is ``8``, as in the profile tables) and fixes the publisher's
    "free to school meals" typo.

    Example:
        >>> clean_group("Other/ None")
        'Other/None'
        >>> clean_group("Year 12")
        '12'
        >>> clean_group("Entitled to free to school meals")
        'Entitled to free school meals'
    """
    tidy = re.sub(r"\s+", " ", str(label)).strip()
    tidy = re.sub(r"\s*/\s*", "/", tidy)
    tidy = re.sub(r"^Year\s+(\d+)$", r"\1", tidy)
    return tidy.replace("free to school meals", "free school meals")


def parse_table_title(cell: object) -> tuple[str, str, str]:
    """Split a table's title cell into ``(table_id, title, indicator)``.

    ``indicator`` is the title without trailing year labels, so a single-wave table and its
    comparison table (``... 2025`` and ``... 2022-2025``) share one indicator.

    Raises:
        YoungPeopleLayoutError: If the cell is not of the form ``Table <id>: <title>``.

    Example:
        >>> parse_table_title("Table 7_1: Visited any historic building in the last year 2025")
        ('7_1', 'Visited any historic building in the last year 2025', 'Visited any historic building in the last year')
        >>> parse_table_title("Table 2: Participation in sport within the last year 2022-2025")[2]
        'Participation in sport within the last year'
    """
    match = _TABLE_TITLE_RE.match(str(cell))
    if not match:
        raise YoungPeopleLayoutError(f"Unrecognised table title {cell!r}; expected 'Table <id>: <title>'")
    title = match.group(2)
    return match.group(1), title, _TRAILING_YEARS_RE.sub("", title).strip()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def list_waves(topic: str = "sport", force_refresh: bool = False) -> list[dict]:
    """List the survey waves published for a series, newest first.

    Args:
        topic: ``"culture"`` or ``"sport"``.
        force_refresh: Bypass the page cache.

    Returns:
        Dicts with ``year`` (the survey wave), ``topic`` and ``url`` (the publication page).

    Raises:
        YoungPeopleDataNotFoundError: If the topic is unknown, the hub cannot be fetched or it lists no waves.
    """
    if topic not in HUB_URLS:
        raise YoungPeopleDataNotFoundError(f"Unknown topic {topic!r}; choose from {', '.join(TOPICS)}")
    hub_url = HUB_URLS[topic]
    try:
        soup = fetch_soup(hub_url, force_refresh=force_refresh)
    except Exception as e:
        raise YoungPeopleDataNotFoundError(f"Could not fetch {hub_url}: {e}") from e

    waves: dict[int, dict] = {}
    for anchor in cast("list[Tag]", soup.find_all("a", href=True)):
        href = cast("str", anchor["href"])
        match = _PUBLICATION_RE.search(href)
        if match:
            year = int(match.group(1))
            waves.setdefault(year, {"year": year, "topic": topic, "url": make_absolute_url(href, SITE_URL)})
    if not waves:
        raise YoungPeopleDataNotFoundError(f"No young people's publications found on {hub_url}")
    return [waves[year] for year in sorted(waves, reverse=True)]


def _resolve_wave(topic: str, year: int | None, force_refresh: bool) -> dict:
    waves = list_waves(topic, force_refresh=force_refresh)
    if year is None:
        return waves[0]
    for wave in waves:
        if wave["year"] == year:
            return wave
    available = ", ".join(str(wave["year"]) for wave in waves)
    raise YoungPeopleDataNotFoundError(f"No {topic} release for survey year {year}. Available waves: {available}")


def workbook_key(file_name: str) -> str:
    """Return the short key of a workbook from its file name.

    The key is the file name without its extension and without the ``-by-young-people-...-<year>``
    suffix, so each workbook of a wave has a distinct, year-independent key.

    Example:
        >>> workbook_key("experience-of-heritage-by-young-people-in-northern-ireland-2025.ods")
        'experience-of-heritage'
        >>> workbook_key("experience-sport-by-young-people-northern-ireland-2019.ods")
        'experience-sport'
    """
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", file_name.rsplit("/", 1)[-1])
    return _FILE_SUFFIX_RE.sub("", stem)


def list_workbooks(topic: str = "sport", year: int | None = None, force_refresh: bool = False) -> list[dict]:
    """List the ``.ods`` workbooks of one survey wave.

    Args:
        topic: ``"culture"`` or ``"sport"``.
        year: Survey wave (see :func:`list_waves`); the latest if omitted.
        force_refresh: Bypass the page cache.

    Returns:
        Dicts with ``year``, ``topic``, ``key`` (see :func:`workbook_key`), ``name`` and ``url``.

    Raises:
        YoungPeopleDataNotFoundError: If the wave does not exist or its page links no ``.ods`` file.
    """
    wave = _resolve_wave(topic, year, force_refresh)
    try:
        links = scrape_file_links(wave["url"], file_extension=".ods", force_refresh=force_refresh)
    except Exception as e:
        raise YoungPeopleDataNotFoundError(f"Could not fetch {wave['url']}: {e}") from e
    if not links:
        raise YoungPeopleDataNotFoundError(f"No .ods workbooks linked on {wave['url']}")
    return [
        {
            "year": wave["year"],
            "topic": topic,
            "key": workbook_key(link["url"]),
            "name": link["url"].rsplit("/", 1)[-1],
            "url": link["url"],
        }
        for link in links
    ]


def select_workbooks(workbooks: list[dict], workbook: str | None) -> list[dict]:
    """Choose the workbooks named by ``workbook``: all of them if it is ``None``.

    ``workbook`` matches a key exactly, or failing that is a substring of exactly one key.

    Raises:
        YoungPeopleDataNotFoundError: If nothing matches, or a substring matches several keys.

    Example:
        >>> books = [{"key": "experience-of-arts"}, {"key": "experience-of-heritage"}]
        >>> select_workbooks(books, "heritage")
        [{'key': 'experience-of-heritage'}]
        >>> len(select_workbooks(books, None))
        2
    """
    if workbook is None:
        return workbooks
    exact = [w for w in workbooks if w["key"] == workbook]
    if exact:
        return exact
    partial = [w for w in workbooks if workbook in w["key"]]
    if len(partial) == 1:
        return partial
    keys = ", ".join(w["key"] for w in workbooks)
    if partial:
        raise YoungPeopleDataNotFoundError(
            f"Workbook {workbook!r} matches several workbooks ({', '.join(w['key'] for w in partial)}); name one exactly"
        )
    raise YoungPeopleDataNotFoundError(f"No workbook matching {workbook!r}. Available workbooks: {keys}")


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def _text(value: object) -> str | None:
    """The stripped text of a cell, or ``None`` if it is empty."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _number(value: object) -> float:
    """A cell as a float; ``NaN`` for an empty or non-numeric cell (a suppressed value)."""
    number = pd.to_numeric(value, errors="coerce")
    return float("nan") if pd.isna(number) else float(number)


def _column_cells(raw: pd.DataFrame, header_start: int, data_start: int, column: int) -> list[str]:
    """The non-empty header cells of one column, top to bottom."""
    cells = (_text(raw.iat[row, column]) for row in range(header_start, data_start))
    return [cell for cell in cells if cell is not None]


def _find_profile_header(raw: pd.DataFrame) -> int | None:
    """Index of the ``Profile of respondent`` row near the top of the sheet, if there is one."""
    for row in range(min(_HEADER_SEARCH_ROWS, len(raw))):
        text = _text(raw.iat[row, 0])
        if text and text.lower().startswith("profile of respondent"):
            return row
    return None


def _first_data_row(raw: pd.DataFrame, header_start: int) -> int:
    """Index of the ``All`` row that starts the data under a profile header."""
    for row in range(header_start + 1, min(header_start + _HEADER_SEARCH_ROWS, len(raw))):
        text = _text(raw.iat[row, 0])
        if text and text.lower() == "all":
            return row
    raise YoungPeopleLayoutError("No 'All' row below the 'Profile of respondent' header")


def _classify_columns(raw: pd.DataFrame, header_start: int, data_start: int) -> list[dict]:
    """Work out what each value column of a profile table holds.

    Each column's own header cells decide its role: a confidence limit, a base, a significance
    marker, or otherwise a percentage. A year in a header is carried right onto the base
    column beside it, so ``2025 %`` and ``Base`` both belong to 2025.
    """
    columns: list[dict] = []
    last_year: int | None = None
    for column in range(1, raw.shape[1]):
        cells = _column_cells(raw, header_start, data_start, column)
        if not cells:
            continue
        joined = " ".join(cells)
        lowered = joined.lower()
        years = [int(y) for y in _YEAR_RE.findall(joined)]
        year = years[0] if years else None
        if "significant" in lowered:
            role = "marker"
        elif "lower limit" in lowered:
            role = "ci_lower"
        elif "upper limit" in lowered:
            role = "ci_upper"
        elif any(_BASE_HEADER_RE.match(cell) for cell in cells):
            role = "base"
            year = year if year is not None else last_year
        else:
            role = "percent"
        if role == "percent" and year is not None:
            last_year = year
        measure = re.sub(r"\s+", " ", _YEAR_RE.sub("", joined).replace("%", "")).strip()
        columns.append({"index": column, "role": role, "year": year, "measure": measure})
    return columns


def _profile_rows(raw: pd.DataFrame, data_start: int) -> list[tuple[str, str, int]]:
    """Walk a profile table's data rows, returning ``(breakdown, group, row_index)`` for each value row.

    The table has a heading row for each breakdown (``Sex``, ``Year Group``...) with no
    values, then one row per group. The first row, ``All``, is its own breakdown. The data ends
    at the first empty row.
    """
    rows: list[tuple[str, str, int]] = []
    breakdown = "All"
    for row in range(data_start, len(raw)):
        label = _text(raw.iat[row, 0])
        values = [raw.iat[row, c] for c in range(1, raw.shape[1])]
        if label is None and all(_text(v) is None for v in values):
            break
        if label is None:
            raise YoungPeopleLayoutError(f"A data row has values but no label (row {row})")
        if all(_text(v) is None for v in values):
            if label.lower().startswith("note"):
                break
            breakdown = clean_breakdown(label)
            continue
        rows.append((breakdown, clean_group(label), row))
    if not rows:
        raise YoungPeopleLayoutError("No data rows found under the header")
    return rows


def _parse_profile(
    raw: pd.DataFrame, header_start: int, context: dict[str, Any], table: tuple[str, str, str]
) -> tuple[str, pd.DataFrame]:
    data_start = _first_data_row(raw, header_start)
    columns = _classify_columns(raw, header_start, data_start)
    percent_columns = [c for c in columns if c["role"] == "percent"]
    if not percent_columns:
        raise YoungPeopleLayoutError("No percentage column found")
    table_id, title, indicator = table
    rows = _profile_rows(raw, data_start)

    if any(c["role"] == "marker" for c in columns):
        return "comparison", _parse_comparison(raw, columns, rows, context, table)

    by_role = {role: [c for c in columns if c["role"] == role] for role in ("ci_lower", "ci_upper", "base")}
    for role, found in by_role.items():
        if len(found) > 1:
            raise YoungPeopleLayoutError(f"More than one {role} column in a single-wave table")
    ci_lower, ci_upper, base = (
        by_role[r][0]["index"] if by_role[r] else None for r in ("ci_lower", "ci_upper", "base")
    )
    if len(percent_columns) > 1 and (ci_lower is not None or ci_upper is not None):
        raise YoungPeopleLayoutError("Confidence limits beside several percentage columns")

    records = []
    for breakdown, group, row in rows:
        for column in percent_columns:
            records.append(
                {
                    **context,
                    "table_id": table_id,
                    "table_title": title,
                    "indicator": indicator,
                    "item": column["measure"] or indicator,
                    "breakdown": breakdown,
                    "group": group,
                    "percent": _number(raw.iat[row, column["index"]]),
                    "ci_lower": _number(raw.iat[row, ci_lower]) if ci_lower is not None else float("nan"),
                    "ci_upper": _number(raw.iat[row, ci_upper]) if ci_upper is not None else float("nan"),
                    "base": _number(raw.iat[row, base]) if base is not None else float("nan"),
                }
            )
    return "estimates", pd.DataFrame(records)


def _parse_comparison(
    raw: pd.DataFrame,
    columns: list[dict],
    rows: list[tuple[str, str, int]],
    context: dict[str, Any],
    table: tuple[str, str, str],
) -> pd.DataFrame:
    table_id, title, indicator = table
    percent_columns = [c for c in columns if c["role"] == "percent"]
    base_columns = [c for c in columns if c["role"] == "base"]
    marker_columns = [c for c in columns if c["role"] == "marker"]
    if len(percent_columns) != 2 or len(base_columns) != 2 or len(marker_columns) != 1:
        raise YoungPeopleLayoutError(
            f"A comparison table needs two percentage, two base and one marker column; found "
            f"{len(percent_columns)}, {len(base_columns)} and {len(marker_columns)}"
        )
    years = [c["year"] for c in percent_columns]
    if None in years or years[0] == years[1]:
        raise YoungPeopleLayoutError(f"Cannot tell the two waves of a comparison table apart (years {years})")
    # Order the two waves as (this wave, the earlier one)
    current, previous = sorted(percent_columns, key=lambda c: cast("int", c["year"]), reverse=True)
    base_of = {b["year"]: b for b in base_columns}
    if current["year"] not in base_of or previous["year"] not in base_of:
        raise YoungPeopleLayoutError("A comparison table's base columns do not match its percentage columns")

    marker_index = marker_columns[0]["index"]
    records = []
    for breakdown, group, row in rows:
        marker = _text(raw.iat[row, marker_index])
        percent = _number(raw.iat[row, current["index"]])
        percent_previous = _number(raw.iat[row, previous["index"]])
        if marker is None:
            significance = None
        elif marker in _SIGNIFICANCE:
            significance = _SIGNIFICANCE[marker]
        else:
            raise YoungPeopleLayoutError(
                f"Unrecognised significance marker {marker!r} in table {table_id}: the workbook does not say what it "
                "means, so it is not guessed"
            )
        change = percent - percent_previous
        consistent = not ((significance == "lower" and change > 0) or (significance == "higher" and change < 0))
        if not consistent:
            logger.warning(
                "Table %s (%s %s), %s/%s: the marker %r means %s but the figures changed by %+g points; "
                "the marker is as published and marker_consistent is False",
                table_id,
                context["workbook"],
                context["release_year"],
                breakdown,
                group,
                marker,
                significance,
                change,
            )
        records.append(
            {
                "survey_year": context["survey_year"],
                "comparison_year": previous["year"],
                "topic": context["topic"],
                "workbook": context["workbook"],
                "table_id": table_id,
                "table_title": title,
                "indicator": indicator,
                "breakdown": breakdown,
                "group": group,
                "percent": percent,
                "base": _number(raw.iat[row, base_of[current["year"]]["index"]]),
                "percent_comparison": percent_previous,
                "base_comparison": _number(raw.iat[row, base_of[previous["year"]]["index"]]),
                "change_points": change,
                "significance": significance,
                "marker": marker,
                "marker_consistent": consistent,
            }
        )
    return pd.DataFrame(records)


def _parse_trend(
    raw: pd.DataFrame, header_row: int, context: dict[str, Any], table: tuple[str, str, str]
) -> pd.DataFrame:
    """Parse a table whose columns are survey waves (for example ``2013 %``, ``2016 %``...)."""
    table_id, title, indicator = table
    wave_columns = {}
    for column in range(1, raw.shape[1]):
        header = _text(raw.iat[header_row, column])
        years = _YEAR_RE.findall(header or "")
        if len(years) == 1:
            wave_columns[column] = int(years[0])
    records = []
    for row in range(header_row + 1, len(raw)):
        label = _text(raw.iat[row, 0])
        values = [raw.iat[row, c] for c in wave_columns]
        if label is None and all(_text(v) is None for v in values):
            break
        if label is None or label.lower().startswith("note"):
            break
        for column, year in wave_columns.items():
            value = _number(raw.iat[row, column])
            if value == value:  # not NaN
                records.append(
                    {
                        **context,
                        "survey_year": year,
                        "table_id": table_id,
                        "table_title": title,
                        "indicator": indicator,
                        "item": label,
                        "breakdown": "All",
                        "group": "All",
                        "percent": value,
                        "ci_lower": float("nan"),
                        "ci_upper": float("nan"),
                        "base": float("nan"),
                    }
                )
    if not records:
        raise YoungPeopleLayoutError("No values found in the trend table")
    return pd.DataFrame(records)


def _block_header(raw: pd.DataFrame, start: int) -> int | None:
    """The header row of an item block, or ``None`` if the block title is not followed by one.

    The header is the first non-empty row below the title. It must have a label in the first
    column and, beside it, only non-numeric labels (the groups: ``All %``, ``Boys %``...); a row
    of numbers is data, and another block title is an index line.
    """
    for row in range(start + 1, len(raw)):
        cells = [_text(raw.iat[row, c]) for c in range(raw.shape[1])]
        if all(cell is None for cell in cells):
            continue
        groups = [cell for cell in cells[1:] if cell is not None]
        if cells[0] is not None and groups and all(pd.isna(pd.to_numeric(cell, errors="coerce")) for cell in groups):
            return row
        return None
    return None


def _is_unit_row(raw: pd.DataFrame, row: int) -> bool:
    """A row under a block header that only repeats the unit (``%``) of each column."""
    if _text(raw.iat[row, 0]) is not None:
        return False
    cells = [_text(raw.iat[row, c]) for c in range(1, raw.shape[1])]
    return any(cells) and all(cell in (None, "%") for cell in cells)


def _parse_blocks(raw: pd.DataFrame, context: dict[str, Any], table: tuple[str, str, str]) -> pd.DataFrame:
    """Parse an item-by-group table: rows are items (a sport, a benefit), columns are groups.

    The table is made of blocks, one per breakdown, each introduced by a title such as
    ``a) by sex`` and a header row of group names. A table with no block titles is one
    block whose breakdown is named in the table title (``... by gender``). A row labelled
    ``Total`` holds the number of respondents of each group.
    """
    table_id, title, indicator = table
    # Older workbooks list the available blocks ("Data is available by: a) by gender ...") before the
    # data of the others; those index lines are followed by another title, not by a header row of groups.
    block_starts = [
        (row, match.group(1))
        for row in range(1, len(raw))
        if (text := _text(raw.iat[row, 0]))
        and text[1:2] == ")"
        and (match := _BLOCK_TITLE_RE.match(text))
        and _block_header(raw, row) is not None
    ]
    if not block_starts:
        by = _TITLE_BY_RE.search(title)
        if not by or by.group(1).strip().lower() not in _BREAKDOWN_ALIASES or _block_header(raw, 0) is None:
            raise YoungPeopleLayoutError(
                "Not a table this module recognises: no 'a) by <breakdown>' blocks, and the title does not name "
                "a known breakdown above a header row of groups"
            )
        block_starts = [(0, by.group(1))]

    records = []
    for position, (start, label) in enumerate(block_starts):
        end = block_starts[position + 1][0] if position + 1 < len(block_starts) else len(raw)
        header = cast("int", _block_header(raw, start))
        groups = {
            c: clean_group(re.sub(r"\s*%\s*$", "", cast("str", _text(raw.iat[header, c]))))
            for c in range(1, raw.shape[1])
            if _text(raw.iat[header, c]) is not None
        }
        first = header + 2 if _is_unit_row(raw, header + 1) else header + 1
        breakdown = clean_breakdown(label)
        items: list[tuple[str, int]] = []
        bases: dict[int, float] = {}
        for row in range(first, end):
            item = _text(raw.iat[row, 0])
            if item is None or _FOOTER_RE.match(item):
                break
            if item.lower() in ("total", "base", "bases"):
                bases = {c: _number(raw.iat[row, c]) for c in groups}
                continue
            items.append((item, row))
        for item, row in items:
            for column, group in groups.items():
                records.append(
                    {
                        **context,
                        "table_id": table_id,
                        "table_title": title,
                        "indicator": indicator,
                        "item": item,
                        "breakdown": breakdown,
                        "group": group,
                        "percent": _number(raw.iat[row, column]),
                        "ci_lower": float("nan"),
                        "ci_upper": float("nan"),
                        "base": bases.get(column, float("nan")),
                    }
                )
    if not records:
        raise YoungPeopleLayoutError("No values found in the item table")
    return pd.DataFrame(records)


def _trend_header(raw: pd.DataFrame) -> int | None:
    """Index of a header row whose columns are two or more survey waves, if the sheet has one."""
    for row in range(1, min(_HEADER_SEARCH_ROWS, len(raw))):
        if _text(raw.iat[row, 0]) is None:
            continue
        waves = [c for c in range(1, raw.shape[1]) if len(_YEAR_RE.findall(_text(raw.iat[row, c]) or "")) == 1]
        if len(waves) >= 2:
            return row
        return None
    return None


def parse_table(raw: pd.DataFrame, sheet_name: str, context: dict[str, Any]) -> tuple[str, pd.DataFrame]:
    """Parse one table sheet of a workbook.

    Args:
        raw: The sheet read with ``header=None``.
        sheet_name: The sheet's name, used in error messages.
        context: ``survey_year``, ``release_year``, ``topic`` and ``workbook``, copied onto every row.

    Returns:
        ``("estimates", frame)`` for a table of estimates or ``("comparison", frame)`` for a
        table that compares the wave with the previous one.

    Raises:
        YoungPeopleLayoutError: If the table's layout is not recognised.
        YoungPeopleValidationError: If a significance marker contradicts the figures.
    """
    try:
        table = parse_table_title(raw.iat[0, 0])
        header = _find_profile_header(raw)
        if header is not None:
            return _parse_profile(raw, header, context, table)
        trend_header = _trend_header(raw)
        if trend_header is not None:
            return "estimates", _parse_trend(raw, trend_header, context, table)
        return "estimates", _parse_blocks(raw, context, table)
    except YoungPeopleLayoutError as e:
        raise YoungPeopleLayoutError(f"{context['workbook']} {context['release_year']} sheet {sheet_name}: {e}") from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _load(
    topic: str, year: int | None, workbook: str | None, force_refresh: bool, strict: bool
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Download and parse the selected workbooks: estimates, comparisons and any skipped tables."""
    workbooks = select_workbooks(list_workbooks(topic, year, force_refresh), workbook)
    estimates: list[pd.DataFrame] = []
    comparisons: list[pd.DataFrame] = []
    skipped: list[dict] = []
    for book in workbooks:
        path = download_file(book["url"], force_refresh=force_refresh)
        excel = pd.ExcelFile(path, engine="odf")
        sheets = [str(s) for s in excel.sheet_names if re.match(r"^table[_ ]", str(s), re.IGNORECASE)]
        if not sheets:
            raise YoungPeopleLayoutError(f"{book['name']} has no table sheets (sheets: {excel.sheet_names})")
        context = {"survey_year": book["year"], "release_year": book["year"], "topic": topic, "workbook": book["key"]}
        for sheet in sheets:
            raw = parse_sheet(excel, sheet, header=None)
            try:
                kind, frame = parse_table(raw, sheet, context)
            except YoungPeopleLayoutError as e:
                if strict:
                    raise
                skipped.append({"workbook": book["key"], "sheet": sheet, "reason": str(e)})
                continue
            (estimates if kind == "estimates" else comparisons).append(frame)
    return (
        pd.concat(estimates, ignore_index=True)[_ESTIMATE_COLUMNS]
        if estimates
        else pd.DataFrame(columns=_ESTIMATE_COLUMNS),
        pd.concat(comparisons, ignore_index=True)[_COMPARISON_COLUMNS]
        if comparisons
        else pd.DataFrame(columns=_COMPARISON_COLUMNS),
        skipped,
    )


def get_survey_tables(
    topic: str = "sport",
    year: int | None = None,
    workbook: str | None = None,
    force_refresh: bool = False,
    strict: bool = True,
) -> pd.DataFrame:
    """Every estimate of one survey wave as a tidy frame.

    Args:
        topic: ``"culture"`` (culture, arts and heritage) or ``"sport"``.
        year: Survey wave (2016, 2019, 2022 or 2025; see :func:`list_waves`); the latest if omitted.
        workbook: A workbook key or unique part of one (see :func:`list_workbooks`); all of the wave's if omitted.
        force_refresh: Bypass the caches.
        strict: Raise on a table whose layout is not recognised. If ``False`` the table is skipped
            and listed in ``frame.attrs["skipped_tables"]``.

    Returns:
        One row per table, item, breakdown and group, with ``survey_year``, ``release_year``, ``topic``,
        ``workbook``, ``table_id``, ``table_title``, ``indicator``, ``item``, ``breakdown``, ``group``,
        ``percent``, ``ci_lower``, ``ci_upper`` (``NaN`` where the table has none) and ``base``
        (the number of respondents). ``item`` is the answer or sport the percentage is for; for a
        table of one percentage it is the table's indicator.

    Raises:
        YoungPeopleDataNotFoundError: If the wave or workbook does not exist or cannot be downloaded.
        YoungPeopleLayoutError: If a table's layout is not recognised and ``strict`` is true.
    """
    estimates, _, skipped = _load(topic, year, workbook, force_refresh, strict)
    estimates.attrs["skipped_tables"] = skipped
    return estimates


def get_wave_comparisons(
    topic: str = "sport",
    year: int | None = None,
    workbook: str | None = None,
    force_refresh: bool = False,
    strict: bool = True,
) -> pd.DataFrame:
    """The tables that compare a wave with the previous one, as a tidy frame.

    Args:
        topic: ``"culture"`` or ``"sport"``.
        year: Survey wave; the latest if omitted.
        workbook: A workbook key or unique part of one; all of the wave's if omitted.
        force_refresh: Bypass the caches.
        strict: As for :func:`get_survey_tables`.

    Returns:
        One row per table and group, with ``survey_year``, ``comparison_year`` (the previous wave),
        ``percent`` and ``base`` for each, ``change_points`` (this wave minus the previous),
        ``significance`` (``"lower"``, ``"higher"`` or ``"no_significant_difference"``, from the
        publisher's marker) and the raw ``marker``. Rows with no marker (a group too small to
        compare) have ``significance`` ``None``.

    Raises:
        YoungPeopleDataNotFoundError: If the wave or workbook does not exist or cannot be downloaded.
        YoungPeopleLayoutError: If a table's layout is not recognised and ``strict`` is true.
        YoungPeopleValidationError: If a marker contradicts the sign of the change.
    """
    _, comparisons, skipped = _load(topic, year, workbook, force_refresh, strict)
    comparisons.attrs["skipped_tables"] = skipped
    return comparisons


def get_latest_data(topic: str = "sport", force_refresh: bool = False) -> pd.DataFrame:
    """The estimates of the latest wave of a series (see :func:`get_survey_tables`)."""
    return get_survey_tables(topic=topic, force_refresh=force_refresh)


def validate_survey_tables(df: pd.DataFrame) -> bool:
    """Validate a frame from :func:`get_survey_tables`.

    Checks the columns, that there are rows, that every percentage is between 0 and 100, that
    every confidence interval brackets its percentage (allowing for rounding of 1 point), that
    every base is positive and that no table repeats a (item, breakdown, group) row.

    Raises:
        YoungPeopleValidationError: On the first failure.

    Example:
        >>> row = dict(survey_year=2025, release_year=2025, topic="sport", workbook="w", table_id="1",
        ...            table_title="t", indicator="i", item="i", breakdown="All", group="All",
        ...            percent=98.0, ci_lower=97.0, ci_upper=99.0, base=2997.0)
        >>> validate_survey_tables(pd.DataFrame([row]))
        True
    """
    missing = [c for c in _ESTIMATE_COLUMNS if c not in df.columns]
    if missing:
        raise YoungPeopleValidationError(f"Missing columns: {missing}")
    if df.empty:
        raise YoungPeopleValidationError("No survey estimates")
    percent = df["percent"].dropna()
    if ((percent < 0) | (percent > 100)).any():
        raise YoungPeopleValidationError("Percentages outside 0 to 100")
    with_interval = df.dropna(subset=["percent", "ci_lower", "ci_upper"])
    outside = with_interval[
        (with_interval["percent"] < with_interval["ci_lower"] - 1)
        | (with_interval["percent"] > with_interval["ci_upper"] + 1)
    ]
    if not outside.empty:
        raise YoungPeopleValidationError(f"{len(outside)} confidence intervals do not bracket their percentage")
    if (df["base"].dropna() <= 0).any():
        raise YoungPeopleValidationError("Non-positive base")
    key = ["survey_year", "workbook", "table_id", "item", "breakdown", "group"]
    duplicated = df[df.duplicated(key, keep=False)]
    if not duplicated.empty:
        raise YoungPeopleValidationError(f"{len(duplicated)} duplicated rows on {key}")
    return True


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a frame from :func:`get_latest_data` (see :func:`validate_survey_tables`)."""
    return validate_survey_tables(df)


def validate_wave_comparisons(df: pd.DataFrame, allow_inconsistent_markers: bool = False) -> bool:
    """Validate a frame from :func:`get_wave_comparisons`.

    Checks the columns, that there are rows, that percentages are between 0 and 100, that
    ``change_points`` is this wave minus the previous, and that no marker contradicts the sign
    of the change (``marker_consistent`` is true for every row).

    Args:
        df: The frame to check.
        allow_inconsistent_markers: Accept rows whose marker contradicts the figures. The
            publisher has made this mistake (see the module notes), so a caller reading an
            older wave opts in knowingly.

    Raises:
        YoungPeopleValidationError: On the first failure.

    Example:
        >>> row = dict(survey_year=2025, comparison_year=2022, topic="sport", workbook="w", table_id="2",
        ...            table_title="t", indicator="i", breakdown="All", group="All", percent=92.0, base=2992.0,
        ...            percent_comparison=94.0, base_comparison=3720.0, change_points=-2.0,
        ...            significance="lower", marker="È", marker_consistent=True)
        >>> validate_wave_comparisons(pd.DataFrame([row]))
        True
    """
    missing = [c for c in _COMPARISON_COLUMNS if c not in df.columns]
    if missing:
        raise YoungPeopleValidationError(f"Missing columns: {missing}")
    if df.empty:
        raise YoungPeopleValidationError("No wave comparisons")
    for column in ("percent", "percent_comparison"):
        values = df[column].dropna()
        if ((values < 0) | (values > 100)).any():
            raise YoungPeopleValidationError(f"{column} outside 0 to 100")
    delta = (df["percent"] - df["percent_comparison"] - df["change_points"]).abs().dropna()
    if (delta > 1e-9).any():
        raise YoungPeopleValidationError("change_points is not percent minus percent_comparison")
    contradicted = ((df["significance"] == "lower") & (df["change_points"] > 0)) | (
        (df["significance"] == "higher") & (df["change_points"] < 0)
    )
    if (contradicted != ~df["marker_consistent"].astype(bool)).any():
        raise YoungPeopleValidationError("marker_consistent does not match the markers and the sign of the change")
    if contradicted.any() and not allow_inconsistent_markers:
        raise YoungPeopleValidationError(
            f"{int(contradicted.sum())} significance markers contradict the sign of the change"
        )
    return True
