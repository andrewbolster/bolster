"""Youth Justice Agency (YJA) annual workload statistics for Northern Ireland.

Provides access to the Department of Justice NI annual bulletin on the work of
the Youth Justice Agency: referrals of children to the Youth Justice Service,
how those referrals are resolved, and the children held in Woodlands Juvenile
Justice Centre (JJC).

The accessibility-format ODS workbook carries 36 numbered tables, almost all of
them a full back-series of financial years from 2008/09 to the latest
reference year, so a single download gives the complete history:

- **Referrals** - totals, individual children involved, rate per 1,000 of the
  10-17 population, referral type, gender, age, area of residence and
  statutory offence group (tables 5-13).
- **Custody** - admissions, movements and children in custody by status,
  gender, age, religion, looked-after status and area (tables 14-31).
- **Population** - average, monthly and daily custody population, and custody
  days (tables 32-35), plus the PACE-to-remand/sentence conversion estimate
  (table 36).
- **Referral schemes** - PSNI-referred CRN and sexting schemes (tables 1-4);
  these are short series (three years) or latest-year cross-tabs.

All tables are parsed into one long frame so heterogeneous layouts can be
queried uniformly, with typed accessors for the headline series.

Data Source:
    **Publication Page**:
    https://www.justice-ni.gov.uk/publications/youth-justice-agency-annual-workload-statistics-2025-26

    The workbook URL changes every year (folder and filename both vary), so
    the module resolves it by scraping the publication page for the ``.ods``
    attachment. Publication slugs follow
    ``youth-justice-agency-annual-workload-statistics-YYYY-YY``.

Update Frequency: Annual (September/October)
Geographic Coverage: Northern Ireland
Reference Period: Financial years 2008/09 - present

.. note::
    Table numbering is not guaranteed stable between editions, so typed
    accessors match on table title rather than table number. Footnote markers
    (``[Note N]``) are stripped from labels and suppressed cells become NaN.

Example:
    >>> from bolster.data_sources.justice import yja_workload
    >>> df = yja_workload.get_referrals_summary()  # doctest: +SKIP
    >>> df[["financial_year", "referrals", "rate_per_1000"]].tail(1)  # doctest: +SKIP
      financial_year  referrals  rate_per_1000
    17        2025/26       1325            3.4
"""

import logging
import re
from pathlib import Path
from typing import cast
from urllib.parse import urljoin

import pandas as pd
from bs4 import Tag  # noqa: TC002 (used inside `cast(...)`, evaluated at runtime)
from odf.opendocument import load as load_ods
from odf.table import Table

from bolster.utils.cache import CachedDownloader, bind_download_file
from bolster.utils.web import fetch_soup, scrape_file_links

from ._base import _label_column_count, _parse_value, _sheet_rows, _strip_note_refs

logger = logging.getLogger(__name__)

BASE_URL = "https://www.justice-ni.gov.uk"
TOPIC_URL = f"{BASE_URL}/topics/youth-justice"
PUBLICATION_SLUG = "youth-justice-agency-annual-workload-statistics"

# Worksheets open with "Table 5: Referrals to YJS, ..., 2008/09 to 2025/26"
_TABLE_TITLE_RE = re.compile(r"^Table\s+(\d+)\s*:\s*(.*)$", re.IGNORECASE)

# Publication slugs end in the reference financial year, e.g. "...-2025-26"
_PUBLICATION_HREF_RE = re.compile(rf"/publications/{PUBLICATION_SLUG}-(\d{{4}})-(\d{{2}})/?$")

# Financial year labels, e.g. "2008/09"
_FINANCIAL_YEAR_RE = re.compile(r"^(\d{4})/(\d{2})$")

# Combined footnote markers such as "[Note 4 and 5]" that the shared stripper does not cover
_MULTI_NOTE_RE = re.compile(r"\s*\[notes?\s+\d+(?:\s*(?:,|and|&)\s*\d+)+\]", re.IGNORECASE)

# Single-cell rows at the top of each worksheet that are commentary, not data
_COMMENTARY_PREFIXES = ("this worksheet", "some shorthand", "return to table of contents")

# The bulletin is annual, so a long cache is safe
_CACHE_TTL_HOURS = 24 * 90

_downloader = CachedDownloader("doj_yja_workload", timeout=60)


class YouthJusticeDataError(Exception):
    """Base exception for Youth Justice Agency workload data errors."""


class YouthJusticeDataNotFoundError(YouthJusticeDataError):
    """Raised when a publication, workbook, or table cannot be located."""


class YouthJusticeValidationError(YouthJusticeDataError):
    """Raised when parsed data fails validation."""


def _clean_label(text: str) -> str:
    """Strip footnote markers (and the commas they leave behind) from a label.

    Example:
        >>> _clean_label("Community Orders [Note 6], [Note 7]")
        'Community Orders'
        >>> _clean_label("Rate per 1000 [Note 4 and 5], 2008/09")
        'Rate per 1000, 2008/09'
    """
    return _strip_note_refs(_MULTI_NOTE_RE.sub("", text)).rstrip(", ").strip()


def financial_year_label(year_start: int) -> str:
    """Format a financial year start as the label DoJ uses.

    Example:
        >>> financial_year_label(2025)
        '2025/26'
        >>> financial_year_label(1999)
        '1999/00'
    """
    return f"{year_start}/{(year_start + 1) % 100:02d}"


def _year_start(label: str) -> int | None:
    """Extract the starting year from a financial year label, or None.

    Example:
        >>> _year_start("2008/09 [Note 6]")
        2008
        >>> _year_start("Total") is None
        True
    """
    match = _FINANCIAL_YEAR_RE.match(_clean_label(label))
    return int(match.group(1)) if match else None


def list_publications() -> pd.DataFrame:
    """List the annual bulletins linked from the DoJ youth justice topic page.

    The topic page links only the current bulletin; earlier years can still be
    requested by number through :func:`find_publication`.

    Returns:
        DataFrame with ``year_start``, ``financial_year`` and ``url`` columns,
        most recent first.

    Raises:
        YouthJusticeDataNotFoundError: If the topic page cannot be fetched or
            links no bulletin.
    """
    try:
        soup = fetch_soup(TOPIC_URL)
    except Exception as e:
        raise YouthJusticeDataNotFoundError(f"Failed to fetch topic page {TOPIC_URL}: {e}") from e

    records: dict[int, dict[str, object]] = {}
    for link in cast("list[Tag]", soup.find_all("a", href=True)):
        href = cast("str", link["href"])
        match = _PUBLICATION_HREF_RE.search(href)
        if not match:
            continue
        year_start = int(match.group(1))
        records.setdefault(
            year_start,
            {
                "year_start": year_start,
                "financial_year": financial_year_label(year_start),
                "url": urljoin(BASE_URL, href),
            },
        )

    if not records:
        raise YouthJusticeDataNotFoundError(f"No workload statistics publication linked from {TOPIC_URL}")

    return pd.DataFrame(list(records.values())).sort_values("year_start", ascending=False).reset_index(drop=True)


def find_publication(year: int | None = None) -> dict[str, object]:
    """Locate a bulletin by the starting year of its financial year.

    Args:
        year: Start of the financial year, e.g. ``2025`` for 2025/26. Defaults
            to the most recent bulletin linked from the topic page.

    Returns:
        Mapping with ``year_start``, ``financial_year`` and ``url``.

    Raises:
        YouthJusticeDataNotFoundError: If no bulletin can be located.
    """
    if year is None:
        return list_publications().iloc[0].to_dict()

    return {
        "year_start": year,
        "financial_year": financial_year_label(year),
        "url": f"{BASE_URL}/publications/{PUBLICATION_SLUG}-{financial_year_label(year).replace('/', '-')}",
    }


def get_data_file_url(publication_url: str) -> str:
    """Find the ODS workbook attached to a publication page.

    Args:
        publication_url: Publication page URL.

    Returns:
        Absolute URL of the ODS workbook.

    Raises:
        YouthJusticeDataNotFoundError: If the page is missing or has no ODS
            attachment.
    """
    try:
        candidates = [link["url"] for link in scrape_file_links(publication_url, ".ods", base_url=BASE_URL)]
    except Exception as e:
        raise YouthJusticeDataNotFoundError(f"Failed to fetch publication page {publication_url}: {e}") from e

    if not candidates:
        raise YouthJusticeDataNotFoundError(f"No ODS workbook found on {publication_url}")
    return candidates[0]


# download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=False) -> Path,
# raising YouthJusticeDataNotFoundError in place of DownloadError.
download_file = bind_download_file(_downloader, YouthJusticeDataNotFoundError, _CACHE_TTL_HOURS)


def _split_blocks(rows: list[list[str]]) -> list[tuple[str, list[str], list[list[str]]]]:
    """Split a worksheet body into (block label, header, data rows) triples.

    A worksheet holds one or two stacked tables. When there are two, each is
    introduced by a single-cell label row such as ``Count of Referrals`` or
    ``Percentage of Referrals``; a lone table has no label. The first
    multi-cell row after a label (or the worksheet preamble) is the header.

    Args:
        rows: Worksheet rows after the title row.

    Returns:
        List of (block label, header cells, data rows).
    """
    blocks: list[tuple[str, list[str], list[list[str]]]] = []
    label = ""
    header: list[str] | None = None
    body: list[list[str]] = []

    def flush() -> None:
        if header is not None and body:
            blocks.append((label, header, body))

    for row in rows:
        if len(row) == 1:
            if row[0].strip().lower().startswith(_COMMENTARY_PREFIXES):
                continue
            flush()
            label, header, body = _clean_label(row[0]), None, []
        elif header is None:
            header = [_clean_label(cell) for cell in row]
        else:
            body.append(row)
    flush()
    return blocks


def _parse_sheet(rows: list[list[str]]) -> list[dict[str, object]]:
    """Reshape one worksheet into long-format records.

    Args:
        rows: Raw worksheet rows.

    Returns:
        List of record dicts; empty when the worksheet is not a numbered table.
    """
    match = _TABLE_TITLE_RE.match(rows[0][0]) if rows and rows[0] else None
    if not match:
        return []
    table_id = int(match.group(1))
    table_title = _clean_label(match.group(2))

    records: list[dict[str, object]] = []
    for block, header, body in _split_blocks(rows[1:]):
        label_count = _label_column_count(body)
        for row in body:
            row = row + [""] * (len(header) - len(row))
            labels = [_clean_label(row[i]) for i in range(label_count)]
            for column in range(label_count, len(header)):
                records.append(
                    {
                        "table_id": table_id,
                        "table_title": table_title,
                        "block": block,
                        "row_label": labels[0],
                        "row_group": labels[1] if label_count > 1 else None,
                        "column": header[column].strip(),
                        "value": _parse_value(row[column]),
                    }
                )
    return records


def parse_data(path: Path) -> pd.DataFrame:
    """Parse an ODS workbook into a long frame.

    Args:
        path: Path to the workbook.

    Returns:
        DataFrame with ``table_id``, ``table_title``, ``block``, ``row_label``,
        ``row_group``, ``column`` and ``value`` columns. For year-indexed tables
        ``row_label`` is the financial year and ``column`` the series; for
        area and offence-group tables it is the other way round.

    Raises:
        YouthJusticeDataError: If the workbook cannot be read or holds no data.
    """
    try:
        doc = load_ods(str(path))
    except Exception as e:
        raise YouthJusticeDataError(f"Failed to read workbook {path}: {e}") from e

    records: list[dict[str, object]] = []
    for table in doc.spreadsheet.getElementsByType(Table):
        records.extend(_parse_sheet(_sheet_rows(table)))

    if not records:
        raise YouthJusticeDataError(f"No data tables found in {path}")

    return pd.DataFrame(records)


def get_latest_data(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get every table from a bulletin in long format.

    Args:
        year: Start of the financial year to fetch (``2025`` for 2025/26).
            Defaults to the most recent bulletin.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame covering all numbered tables.
    """
    publication = find_publication(year)
    url = get_data_file_url(str(publication["url"]))
    logger.info("Using bulletin %s (%s)", publication["financial_year"], url)
    return parse_data(download_file(url, force_refresh=force_refresh))


def list_tables(year: int | None = None) -> pd.DataFrame:
    """List the tables available in a bulletin.

    Args:
        year: Start of the financial year to fetch. Defaults to the most recent.

    Returns:
        DataFrame with ``table_id``, ``table_title`` and ``records`` columns.
    """
    df = get_latest_data(year=year)
    return (
        df.groupby("table_id")
        .agg(table_title=("table_title", "first"), records=("value", "size"))
        .reset_index()
        .sort_values("table_id")
        .reset_index(drop=True)
    )


def _select_table(df: pd.DataFrame, pattern: str, block: str | None = None) -> pd.DataFrame:
    """Select one table (optionally one stacked block of it) by title.

    Args:
        df: Long-format frame from :func:`get_latest_data`.
        pattern: Case-insensitive regex matched against ``table_title``.
        block: Case-insensitive regex matched against the block label, used to
            pick the count block over the percentage block.

    Returns:
        The matching rows.

    Raises:
        YouthJusticeDataNotFoundError: If nothing matches.
    """
    matched = df[df.table_title.str.contains(pattern, case=False, regex=True, na=False)]
    if block is not None:
        matched = matched[matched.block.str.contains(block, case=False, regex=True, na=False)]
    if matched.empty:
        raise YouthJusticeDataNotFoundError(f"No table matching {pattern!r} in this bulletin")
    return matched


def _by_year(table: pd.DataFrame, series_name: str, value_name: str, drop_total: bool = True) -> pd.DataFrame:
    """Reshape a year-indexed table (years in rows) into tidy long form."""
    out = table.assign(
        financial_year=table.row_label.map(_clean_label),
        year_start=table.row_label.map(_year_start),
        **{series_name: table.column, value_name: table.value},
    )
    out = out[out.year_start.notna()]
    if drop_total:
        out = out[~out[series_name].str.startswith("Total")]
    return (
        out[["financial_year", "year_start", series_name, value_name]]
        .astype({"year_start": int})
        .sort_values(["year_start", series_name])
        .reset_index(drop=True)
    )


def get_referrals_summary(year: int | None = None) -> pd.DataFrame:
    """Get total referrals, children involved and the rate per 1,000 children.

    Args:
        year: Start of the financial year to fetch. Defaults to the most recent.

    Returns:
        DataFrame with ``financial_year``, ``year_start``, ``referrals``,
        ``children``, ``population_10_17`` and ``rate_per_1000`` columns.
    """
    table = _select_table(get_latest_data(year=year), r"^Referrals to YJS, Number of Children Involved")
    wide = table.assign(year_start=table.row_label.map(_year_start)).pivot_table(
        index=["row_label", "year_start"], columns="column", values="value", aggfunc="first"
    )
    wide = wide.reset_index()
    column_for = {
        "referrals": "Total referrals to the YJS",
        "children": "Individual children involved",
        "population_10_17": "NI population aged 10 to 17",
        "rate_per_1000": "Rate per 1,000",
    }
    frame = pd.DataFrame(
        {
            "financial_year": wide.row_label.map(_clean_label),
            "year_start": wide.year_start.astype(int),
            **{name: wide[source].to_numpy() for name, source in column_for.items()},
        }
    )
    return frame.sort_values("year_start").reset_index(drop=True)


def get_referrals_by_type(year: int | None = None) -> pd.DataFrame:
    """Get referral counts by type (diversionary, court ordered, and so on).

    Args:
        year: Start of the financial year to fetch. Defaults to the most recent.

    Returns:
        DataFrame with ``financial_year``, ``year_start``, ``referral_type`` and
        ``referrals`` columns. Types a given year did not use are NaN.
    """
    table = _select_table(get_latest_data(year=year), r"^Referrals by Type", block=r"^Count of")
    return _by_year(table, "referral_type", "referrals")


def get_referrals_by_area(year: int | None = None) -> pd.DataFrame:
    """Get referral counts by the child's local government district.

    Args:
        year: Start of the financial year to fetch. Defaults to the most recent.

    Returns:
        DataFrame with ``financial_year``, ``year_start``, ``area`` and
        ``referrals`` columns, excluding the all-NI total.
    """
    table = _select_table(get_latest_data(year=year), r"^Referrals To YJS By Area Of Residence")
    out = table.assign(
        financial_year=table.column,
        year_start=table.column.map(_year_start),
        area=table.row_label,
        referrals=table.value,
    )
    out = out[out.year_start.notna() & (out.area != "Total")]
    return (
        out[["financial_year", "year_start", "area", "referrals"]]
        .astype({"year_start": int})
        .sort_values(["year_start", "area"])
        .reset_index(drop=True)
    )


def get_children_in_custody_by_age(year: int | None = None) -> pd.DataFrame:
    """Get the number of children in custody over the year by age band.

    Args:
        year: Start of the financial year to fetch. Defaults to the most recent.

    Returns:
        DataFrame with ``financial_year``, ``year_start``, ``age_band`` and
        ``children`` columns.
    """
    table = _select_table(get_latest_data(year=year), r"^Children In Custody By Age", block=r"^Count of")
    return _by_year(table, "age_band", "children")


def get_custody_population(year: int | None = None) -> pd.DataFrame:
    """Get the average daily custody population by legal status.

    Args:
        year: Start of the financial year to fetch. Defaults to the most recent.

    Returns:
        DataFrame with ``financial_year``, ``year_start``, ``status`` (PACE,
        Remand or Sentence) and ``average_population`` columns.
    """
    table = _select_table(get_latest_data(year=year), r"^Average Population By Status")
    return _by_year(table, "status", "average_population")


def get_pace_conversion(year: int | None = None) -> pd.DataFrame:
    """Get how many PACE admissions go on to remand or a custodial sentence.

    Args:
        year: Start of the financial year to fetch. Defaults to the most recent.

    Returns:
        DataFrame with ``financial_year``, ``year_start``, ``pace_admissions``,
        ``pace_to_remand_sentence`` and ``conversion_rate`` (a proportion in
        [0, 1]) columns.
    """
    table = _select_table(get_latest_data(year=year), r"^PACE To Remand/Sentence Conversion")
    wide = table.assign(year_start=table.row_label.map(_year_start)).pivot_table(
        index=["row_label", "year_start"], columns="column", values="value", aggfunc="first"
    )
    wide = wide.reset_index()
    frame = pd.DataFrame(
        {
            "financial_year": wide.row_label.map(_clean_label),
            "year_start": wide.year_start.astype(int),
            "pace_admissions": wide["PACE admissions"].to_numpy(),
            "pace_to_remand_sentence": wide["PACE to remand/sentence"].to_numpy(),
            "conversion_rate": wide["Conversion rate (%)"].to_numpy() / 100,
        }
    )
    return frame.sort_values("year_start").reset_index(drop=True)


def validate_data(df: pd.DataFrame, min_records: int = 1000) -> bool:
    """Validate a parsed long frame.

    Args:
        df: Frame from :func:`get_latest_data`.
        min_records: Minimum acceptable record count.

    Returns:
        True if the frame passes every check.

    Raises:
        YouthJusticeValidationError: If the frame is malformed or too small.
    """
    if df is None or df.empty:
        raise YouthJusticeValidationError("DataFrame is empty")

    required = {"table_id", "table_title", "block", "row_label", "row_group", "column", "value"}
    missing = required - set(df.columns)
    if missing:
        raise YouthJusticeValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise YouthJusticeValidationError(f"Too few records: expected at least {min_records}, got {len(df)}")

    if (df.value.dropna() < 0).any():
        raise YouthJusticeValidationError("Negative values found")

    if df.value.isna().mean() > 0.25:
        raise YouthJusticeValidationError(f"Too many unparsed values: {df.value.isna().mean():.1%}")

    return True


def clear_cache() -> int:
    """Clear cached workbooks.

    Returns:
        Number of files removed.
    """
    return _downloader.clear()
