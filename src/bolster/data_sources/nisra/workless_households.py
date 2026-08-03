"""NISRA Working and Workless Households Module.

Household-level employment statistics for Northern Ireland, derived from the
Labour Force Survey household dataset. Where the headline labour market
statistics count *individuals*, this release counts *households*, classifying
each one by the combined economic activity status of its members:

    - **Work rich**: every adult aged 16-64 in the household is in employment
    - **Mixed**: at least one adult in work and at least one not in work
    - **Workless**: no adult aged 16-64 in the household is in employment

That distinction matters for policy. A rising individual employment rate can
coexist with a static workless-household rate if the new jobs go to households
that already had someone in work, so the two series answer different questions
about in-work poverty and concentrated worklessness.

Two complementary sources are used:

**ONS Table C** supplies the long time series. Northern Ireland appears as one
column in a UK-wide regional table covering April-June 1996 to the present, with
both household counts and percentage rates for all three statuses. This is the
source for :func:`get_regional_series` and :func:`get_northern_ireland_series`.

**The NISRA quarterly LFS Households workbook** supplies Northern Ireland detail
that the ONS regional table does not carry — household composition and female
economic activity broken down by dependent children. This is a single-quarter
snapshot rather than a series, and is the source for the remaining accessors.

Data Sources:
    - ONS Table C: https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/employmentandemployeetypes/datasets/workingandworklesshouseholdstablechouseholdsbyregionandcombinedeconomicactivitystatusofhouseholdmembers
    - NISRA LFS: https://www.nisra.gov.uk/statistics/work-pay-and-benefits/labour-force-survey

Update Frequency: Quarterly.

Examples:
    >>> from bolster.data_sources.nisra import workless_households as wh
    >>> ni = wh.get_northern_ireland_series()
    >>> 'workless_rate' in ni.columns
    True
    >>> df = wh.get_regional_series()
    >>> 'Northern Ireland' in set(df['region'])
    True
    >>> wh.get_economic_status_summary()['status'].tolist()
    ['work_rich', 'mixed', 'workless']
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import pandas as pd

from ._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    find_publication_link,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

ONS_TABLE_C_URL = (
    "https://www.ons.gov.uk/file?uri=/employmentandlabourmarket/peopleinwork/employmentandemployeetypes"
    "/datasets/workingandworklesshouseholdstablechouseholdsbyregionandcombinedeconomicactivitystatus"
    "ofhouseholdmembers/current/tablec.xlsx"
)

NISRA_LFS_HUB_URL = "https://www.nisra.gov.uk/statistics/work-pay-and-benefits/labour-force-survey"

# Table C splits each status across a level sheet and a rate sheet.
_ONS_SHEETS = {
    "working": ("1 Working Level", "2 Working Rate"),
    "mixed": ("3 Mixed Level", "4 Mixed Rate"),
    "workless": ("5 Workless Level", "6 Workless Rate"),
}

_HEADER_LABEL = "Time period and change"
_CHANGE_ROW_LABEL = "Change on year"

# LFS reference periods are named by their span, not by a quarter number.
_QUARTER_BY_PERIOD = {
    "January to March": 1,
    "April to June": 2,
    "July to September": 3,
    "October to December": 4,
}

_STATUS_BY_LABEL = {
    "work rich households": "work_rich",
    "mixed households": "mixed",
    "workless households": "workless",
}


def _strip_note_markers(text: str) -> str:
    """Remove ``[note N]`` markers and collapse whitespace in a cell label.

    Args:
        text: Raw cell text.

    Returns:
        Cleaned label.

    Example:
        >>> _strip_note_markers('Work rich households [note 2]')
        'Work rich households'
    """
    cleaned = re.sub(r"\[note\s*\d+\]", "", str(text))
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_period(period: str) -> tuple[int, int]:
    """Split an LFS reference period label into a year and quarter number.

    Args:
        period: Period label such as ``"January to March 2026"``.

    Returns:
        Tuple of ``(year, quarter)``.

    Raises:
        NISRAValidationError: If the label is not a recognised LFS period.

    Example:
        >>> parse_period('January to March 2026')
        (2026, 1)
        >>> parse_period('October to December 2019')
        (2019, 4)
        >>> parse_period('July to September 20232')
        (2023, 3)
    """
    text = re.sub(r"\s+", " ", str(period)).strip()
    # Trailing digits after the year are ONS footnote markers, e.g. "... 20232".
    match = re.match(r"^(.*?)\s+((?:19|20)\d{2})\d*$", text)
    if match is None:
        raise NISRAValidationError(f"Unrecognised LFS period label: {period!r}")

    span, year = match.group(1), int(match.group(2))
    quarter = _QUARTER_BY_PERIOD.get(span)
    if quarter is None:
        raise NISRAValidationError(f"Unrecognised LFS period span: {span!r}")

    return year, quarter


def _read_ons_sheet(path, sheet: str) -> pd.DataFrame:
    """Read one Table C worksheet into a tidy period-by-region frame.

    Args:
        path: Path to the downloaded Table C workbook.
        sheet: Worksheet name.

    Returns:
        DataFrame with ``period``, ``region``, ``geography_code`` and ``value``.

    Raises:
        NISRAValidationError: If the worksheet layout is not as expected.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None)

    header_rows = raw.index[raw[0].astype(str).str.strip() == _HEADER_LABEL]
    if len(header_rows) == 0:
        raise NISRAValidationError(f"Sheet {sheet!r} has no {_HEADER_LABEL!r} header row")
    header = header_rows[0]

    regions = [str(value).strip() for value in raw.iloc[header, 1:]]
    codes = [str(value).strip() for value in raw.iloc[header + 1, 1:]]

    body = raw.iloc[header + 2 :].copy()
    # The final row is a year-on-year delta, not an observation.
    body = body[body[0].astype(str).str.strip() != _CHANGE_ROW_LABEL]
    body = body[body[0].notna()]

    records = []
    for _, row in body.iterrows():
        # Footnote digits are appended inconsistently across sheets, so strip
        # them here to keep level/rate merges aligned.
        period = re.sub(r"((?:19|20)\d{2})\d+$", r"\1", str(row[0]).strip())
        for offset, (region, code) in enumerate(zip(regions, codes, strict=True), start=1):
            records.append(
                {
                    "period": period,
                    "region": region,
                    "geography_code": code,
                    # [w], [c] and [x] are ONS suppression markers, not numbers.
                    "value": pd.to_numeric(row[offset], errors="coerce"),
                }
            )

    return pd.DataFrame(records)


def get_regional_series(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the full UK regional working/mixed/workless household series.

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with one row per period, region and status, containing
        ``period``, ``year``, ``quarter``, ``region``, ``geography_code``,
        ``status``, ``households`` and ``rate``.

    Example:
        >>> df = get_regional_series()
        >>> sorted(df['status'].unique())
        ['mixed', 'working', 'workless']
        >>> 'Northern Ireland' in set(df['region'])
        True
    """
    path = download_file(ONS_TABLE_C_URL, cache_ttl_hours=24, force_refresh=force_refresh)

    frames = []
    for status, (level_sheet, rate_sheet) in _ONS_SHEETS.items():
        levels = _read_ons_sheet(path, level_sheet).rename(columns={"value": "households"})
        rates = _read_ons_sheet(path, rate_sheet).rename(columns={"value": "rate"})
        merged = levels.merge(rates, on=["period", "region", "geography_code"], how="outer")
        merged["status"] = status
        frames.append(merged)

    df = pd.concat(frames, ignore_index=True)

    parsed = df["period"].map(parse_period)
    df["year"] = [year for year, _ in parsed]
    df["quarter"] = [quarter for _, quarter in parsed]

    df = df[["period", "year", "quarter", "region", "geography_code", "status", "households", "rate"]]
    return df.sort_values(["year", "quarter", "region", "status"]).reset_index(drop=True)


def get_northern_ireland_series(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the Northern Ireland household economic status series.

    A convenience wrapper around :func:`get_regional_series` that filters to
    Northern Ireland and pivots the three statuses into columns.

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with one row per period and columns ``period``, ``year``,
        ``quarter``, and ``{working,mixed,workless}_{households,rate}``.

    Example:
        >>> df = get_northern_ireland_series()
        >>> 'workless_rate' in df.columns
        True
        >>> int(df['year'].min())
        1996
    """
    regional = get_regional_series(force_refresh=force_refresh)
    ni = regional[regional["region"] == "Northern Ireland"]

    wide = ni.pivot(index=["period", "year", "quarter"], columns="status", values=["households", "rate"])
    wide.columns = [f"{status}_{measure}" for measure, status in wide.columns]
    wide = wide.reset_index()

    ordered = ["period", "year", "quarter"] + [
        f"{status}_{measure}" for status in ("working", "mixed", "workless") for measure in ("households", "rate")
    ]
    return wide[ordered].sort_values(["year", "quarter"]).reset_index(drop=True)


def get_latest_publication_url(force_refresh: bool = False) -> str:
    """Discover the URL of the latest NISRA LFS Households workbook.

    Walks from the LFS hub page to the current quarterly tables publication,
    then to the Households workbook hosted on that page.

    Args:
        force_refresh: If ``True``, bypass the page cache.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        NISRADataNotFoundError: If the workbook cannot be located.

    Example:
        >>> url = get_latest_publication_url()
        >>> url.endswith('.xlsx')
        True
    """
    return find_publication_link(
        NISRA_LFS_HUB_URL,
        pub_href_contains="quarterly-labour-force-survey-tables",
        file_extension=".xlsx",
        file_href_contains="LFS-Households-Quarterly",
        force_refresh=force_refresh,
    )


def _read_nisra_table(sheet: str, force_refresh: bool = False) -> pd.DataFrame:
    """Read one sheet of the NISRA Households workbook below its preamble.

    Args:
        sheet: Worksheet name (e.g. ``"2.44"``).
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame of the table body, with the header row as columns.

    Raises:
        NISRAValidationError: If the sheet has no recognisable table body.
    """
    url = get_latest_publication_url(force_refresh=force_refresh)
    path = download_file(url, cache_ttl_hours=24, force_refresh=force_refresh)

    raw = pd.read_excel(path, sheet_name=sheet, header=None)

    # Every sheet opens with four lines of preamble, then a header row whose
    # second cell names the measure. That second cell is the only reliable
    # anchor, since the label in column 0 differs from sheet to sheet.
    header_rows = raw.index[raw[0].notna() & raw[1].notna()]
    if len(header_rows) == 0:
        raise NISRAValidationError(f"Sheet {sheet!r} has no header row")
    header = header_rows[0]

    body = raw.iloc[header + 1 :].copy()
    body = body[body[0].notna()]
    body.columns = [_strip_note_markers(value) for value in raw.iloc[header]]
    return body.reset_index(drop=True)


def get_household_types(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the Northern Ireland household composition breakdown (table 2.43).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with ``household_type`` and ``percentage``.

    Example:
        >>> df = get_household_types()
        >>> 'One person' in set(df['household_type'])
        True
    """
    body = _read_nisra_table("2.43", force_refresh=force_refresh)
    df = pd.DataFrame(
        {
            "household_type": body.iloc[:, 0].map(_strip_note_markers),
            "percentage": pd.to_numeric(body.iloc[:, 1], errors="coerce"),
        }
    )
    return df.reset_index(drop=True)


def get_economic_status_summary(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the current work rich / mixed / workless split (table 2.44).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with ``status`` (``work_rich``, ``mixed`` or ``workless``),
        ``label`` as published, and ``percentage``.

    Example:
        >>> df = get_economic_status_summary()
        >>> df['status'].tolist()
        ['work_rich', 'mixed', 'workless']
    """
    body = _read_nisra_table("2.44", force_refresh=force_refresh)
    labels = body.iloc[:, 0].map(_strip_note_markers)
    return pd.DataFrame(
        {
            "status": labels.str.lower().map(_STATUS_BY_LABEL),
            "label": labels,
            "percentage": pd.to_numeric(body.iloc[:, 1], errors="coerce"),
        }
    ).reset_index(drop=True)


def get_female_activity_by_children(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch female economic activity by number of dependent children (2.45).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with ``dependent_children`` and ``activity_rate``.

    Example:
        >>> df = get_female_activity_by_children()
        >>> 'None' in set(df['dependent_children'])
        True
    """
    body = _read_nisra_table("2.45", force_refresh=force_refresh)
    return pd.DataFrame(
        {
            "dependent_children": body.iloc[:, 0].map(_strip_note_markers),
            "activity_rate": pd.to_numeric(body.iloc[:, 1], errors="coerce"),
        }
    ).reset_index(drop=True)


def get_female_activity_by_age(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch female economic activity by age and dependent children (2.46).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with ``age_group``, ``with_dependent_children`` and
        ``without_dependent_children``.

    Example:
        >>> df = get_female_activity_by_age()
        >>> '25 to 34' in set(df['age_group'])
        True
    """
    body = _read_nisra_table("2.46", force_refresh=force_refresh)
    return pd.DataFrame(
        {
            "age_group": body.iloc[:, 0].map(_strip_note_markers),
            "with_dependent_children": pd.to_numeric(body.iloc[:, 1], errors="coerce"),
            "without_dependent_children": pd.to_numeric(body.iloc[:, 2], errors="coerce"),
        }
    ).reset_index(drop=True)


def get_female_activity_by_youngest_child(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch female economic activity by age of youngest child (table 2.47).

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame with ``youngest_child_age`` and ``activity_rate``.

    Example:
        >>> df = get_female_activity_by_youngest_child()
        >>> '0 to 4' in set(df['youngest_child_age'])
        True
    """
    body = _read_nisra_table("2.47", force_refresh=force_refresh)
    return pd.DataFrame(
        {
            "youngest_child_age": body.iloc[:, 0].map(_strip_note_markers),
            "activity_rate": pd.to_numeric(body.iloc[:, 1], errors="coerce"),
        }
    ).reset_index(drop=True)


_TABLES: dict[str, Callable[..., pd.DataFrame]] = {
    "regional": get_regional_series,
    "northern-ireland": get_northern_ireland_series,
    "household-types": get_household_types,
    "status": get_economic_status_summary,
    "female-activity-children": get_female_activity_by_children,
    "female-activity-age": get_female_activity_by_age,
    "female-activity-youngest": get_female_activity_by_youngest_child,
}


def list_tables() -> list[str]:
    """List the table names accepted by :func:`get_latest_data`.

    Returns:
        Sorted table names.

    Example:
        >>> 'northern-ireland' in list_tables()
        True
    """
    return sorted(_TABLES)


def get_latest_data(table: str = "northern-ireland", force_refresh: bool = False) -> pd.DataFrame:
    """Fetch one table by name.

    Args:
        table: One of the names returned by :func:`list_tables`.
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        The requested DataFrame.

    Raises:
        NISRADataNotFoundError: If ``table`` is not a known table name.

    Example:
        >>> df = get_latest_data('status')
        >>> 'percentage' in df.columns
        True
    """
    accessor = _TABLES.get(table)
    if accessor is None:
        raise NISRADataNotFoundError(f"Unknown table {table!r}. Available: {', '.join(list_tables())}")
    return accessor(force_refresh=force_refresh)


def validate_data(df: pd.DataFrame, required_columns: list[str] | None = None) -> bool:
    """Validate a workless households DataFrame.

    Args:
        df: DataFrame to validate.
        required_columns: Columns that must be present.

    Returns:
        ``True`` if the DataFrame passes validation.

    Raises:
        NISRAValidationError: If the DataFrame is empty, is missing a required
            column, or contains a percentage outside 0-100.

    Example:
        >>> validate_data(get_economic_status_summary())
        True
    """
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if required_columns:
        missing = [column for column in required_columns if column not in df.columns]
        if missing:
            raise NISRAValidationError(f"Missing required columns: {missing}")

    for column in ("percentage", "rate", "activity_rate", "with_dependent_children", "without_dependent_children"):
        if column not in df.columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if not values.empty and ((values < 0) | (values > 100)).any():
            raise NISRAValidationError(f"Column {column!r} has values outside 0-100")

    return True
