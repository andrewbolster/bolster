"""NISRA Young People Not in Education, Employment or Training (NEET) Module.

This module provides access to Northern Ireland NEET statistics derived from the
Labour Force Survey (LFS). NEET counts 16-24 year olds who are neither in
employment nor in any form of education or training.

NEET is a broader measure than youth unemployment: an unemployed young person who
is enrolled on a training course is not NEET, while an economically inactive young
person who is not studying is. The workbook publishes both components separately,
so the two can be reconciled (see :func:`get_neet_composition`).

Data Source:
    **Hub page**: https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare

    NEET is published as a standalone workbook alongside — but separate from — the
    main "Quarterly Labour Force Survey Tables" workbook that
    :mod:`~bolster.data_sources.nisra.labour_market` parses. Both files sit on the
    same publication page, so discovery reuses the shared
    :func:`~bolster.data_sources.nisra._base.find_publication_link` helper with a
    ``NEET`` filename filter.

    The asset URL encodes both the release month and a two-letter quarter code
    (e.g. ``2026-05/LFS-NEETs-Quarterly-Data-JM26.xlsx``), and NISRA's CMS
    occasionally appends a de-duplication suffix (``..._0.xlsx``). URLs are
    therefore always discovered by scraping, never constructed.

Update Frequency: Quarterly, published in February, May, August and November,
    roughly two months after the reference quarter ends.

Data Coverage: January-March 2013 to present (rolling quarterly series). Estimates
    are not seasonally adjusted and are rounded to the nearest thousand.

Workbook tables:
    - ``2.40`` — quarterly NEET series: counts and rates with 95% confidence
      intervals, split by sex
    - ``2.41`` — labour market status of all 16-24 year olds (latest quarter)
    - ``2.42`` — NEET rate, NI vs UK (latest quarter)
    - ``2.43`` — NEET split into its unemployed and economically inactive parts
      (latest quarter)

Examples:
    >>> from bolster.data_sources.nisra import neet
    >>> df = neet.get_quarterly_series()
    >>> int(df['year'].min())
    2013
    >>> neet.validate_data(df)
    True
    >>> comparison = neet.get_uk_comparison()
    >>> sorted(comparison['country'])
    ['NI', 'UK']

Note:
    Because LFS estimates come from a household sample survey, quarter-on-quarter
    movements are frequently within sampling error. The ``*_lower_pct`` and
    ``*_upper_pct`` columns carry the published 95% confidence interval and should
    be used before claiming a change is real.
"""

import logging
import re
from pathlib import Path

import pandas as pd

from bolster.data_sources.nisra._base import (
    NISRADataNotFoundError,
    download_file,
    find_publication_link,
)

logger = logging.getLogger(__name__)

HUB_URL = "https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare"

# The NEET workbook is republished each quarter with a new filename, so it is
# cached for a quarter rather than a day.
CACHE_TTL_HOURS = 24 * 90

_SHEET_SERIES = "2.40"
_SHEET_STATUS = "2.41"
_SHEET_UK = "2.42"
_SHEET_COMPOSITION = "2.43"

_QUARTER_STARTS = {
    "January": 1,
    "April": 4,
    "July": 7,
    "October": 10,
}

_QUARTER_CODES = {1: "Jan-Mar", 4: "Apr-Jun", 7: "Jul-Sep", 10: "Oct-Dec"}

_COUNT_COLUMNS = {
    "Male NEET": "male_neet",
    "Female NEET": "female_neet",
    "Total NEET": "total_neet",
    "Total NEET lower limit": "total_neet_lower",
    "Total NEET upper limit": "total_neet_upper",
}

_RATE_COLUMNS = {
    "Male NEET rate (%)": "male_neet_rate_pct",
    "Female NEET rate (%)": "female_neet_rate_pct",
    "Total NEET rate (%)": "total_neet_rate_pct",
    "Total NEET rate lower limit (%)": "total_neet_rate_lower_pct",
    "Total NEET rate upper limit (%)": "total_neet_rate_upper_pct",
}

_TABLES = {
    "quarterly": "Quarterly NEET counts and rates with confidence intervals (2013 to present)",
    "status": "Labour market status of all 16-24 year olds, latest quarter",
    "uk": "NEET rate for NI compared with the UK, latest quarter",
    "composition": "NEET split into unemployed and economically inactive, latest quarter",
}


def get_latest_publication_url(force_refresh: bool = False) -> str:
    """Find the URL of the latest NEET quarterly data workbook.

    Args:
        force_refresh: If True, bypass the page-discovery cache.

    Returns:
        Absolute URL of the NEET Excel workbook.

    Raises:
        NISRADataNotFoundError: If the publication or file link cannot be found.

    Example:
        >>> url = get_latest_publication_url()
        >>> url.endswith('.xlsx')
        True
    """
    return find_publication_link(
        hub_url=HUB_URL,
        pub_text_contains="Quarterly Labour Force Survey Tables",
        file_href_contains="NEET",
        force_refresh=force_refresh,
    )


def _download(force_refresh: bool = False) -> Path:
    """Download the latest NEET workbook, using the shared cache."""
    url = get_latest_publication_url(force_refresh=force_refresh)
    return download_file(url, cache_ttl_hours=CACHE_TTL_HOURS, force_refresh=force_refresh)


def _parse_quarter(label: str) -> tuple[pd.Timestamp, int, str]:
    """Convert a quarter label into a period start, year and short code.

    Args:
        label: Quarter label as published, e.g. ``"January to March 2026"``.

    Returns:
        Tuple of (period start Timestamp, year, quarter code such as ``"Jan-Mar"``).

    Raises:
        NISRADataNotFoundError: If the label does not match the published format.

    Example:
        >>> start, year, code = _parse_quarter("January to March 2026")
        >>> start.strftime('%Y-%m-%d'), year, code
        ('2026-01-01', 2026, 'Jan-Mar')
    """
    match = re.match(r"^\s*(\w+) to \w+ (\d{4})\s*$", str(label))
    if not match or match.group(1) not in _QUARTER_STARTS:
        raise NISRADataNotFoundError(f"Unrecognised quarter label: {label!r}")

    month = _QUARTER_STARTS[match.group(1)]
    year = int(match.group(2))
    return pd.Timestamp(year=year, month=month, day=1), year, _QUARTER_CODES[month]


def _header_row(sheet: pd.DataFrame, first_header: str) -> int:
    """Return the index of the row whose first cell equals ``first_header``.

    NISRA prefixes every sheet with a variable number of preamble rows, so the
    header position cannot be hard-coded.

    Raises:
        NISRADataNotFoundError: If no row starts with the given header.
    """
    for idx, value in enumerate(sheet[0]):
        if isinstance(value, str) and value.strip() == first_header:
            return idx
    raise NISRADataNotFoundError(f"Could not locate header row {first_header!r}")


def _labelled_table(sheet: pd.DataFrame, label_column: str, value_column: str) -> pd.DataFrame:
    """Parse a simple two-column label/value table from a NEET sheet.

    Sheets 2.41 to 2.43 all share this shape: preamble rows, a header row, then
    one row per category with a numeric value in the second column.
    """
    start = _header_row(sheet, label_column)
    body = sheet.iloc[start + 1 :, [0, 1]].copy()
    body.columns = [label_column, value_column]
    body = body[body[label_column].notna() & body[value_column].notna()]
    body[label_column] = body[label_column].astype(str).str.replace(r"\s*\[[Nn]ote \d+\]", "", regex=True).str.strip()
    body[value_column] = pd.to_numeric(body[value_column], errors="coerce")
    return body[body[value_column].notna()].reset_index(drop=True)


def parse_quarterly_series(file_path: str | Path) -> pd.DataFrame:
    """Parse the quarterly NEET time series from sheet 2.40.

    The sheet holds two tables side by side — counts (2.40a) on the left and rates
    (2.40b) on the right — sharing an identical quarter column. They are joined
    back into a single row per quarter.

    Args:
        file_path: Path to the downloaded NEET workbook.

    Returns:
        DataFrame with one row per quarter and columns ``quarter``,
        ``period_start``, ``year``, ``quarter_code``, the five count columns and
        the five rate columns.

    Example:
        >>> from bolster.data_sources.nisra import neet
        >>> df = parse_quarterly_series(neet._download())
        >>> df['quarter_code'].iloc[0]
        'Jan-Mar'
    """
    sheet = pd.read_excel(file_path, sheet_name=_SHEET_SERIES, header=None)
    start = _header_row(sheet, "Quarter")
    headers = list(sheet.iloc[start])

    counts = _side_table(sheet, headers, start, "Quarter", _COUNT_COLUMNS)
    rates = _side_table(sheet, headers, start, "Quarter", _RATE_COLUMNS, skip=1)

    df = counts.merge(rates, on="quarter", how="inner", validate="one_to_one")

    parsed = df["quarter"].apply(_parse_quarter)
    df["period_start"] = [p[0] for p in parsed]
    df["year"] = [p[1] for p in parsed]
    df["quarter_code"] = [p[2] for p in parsed]

    ordered = ["quarter", "period_start", "year", "quarter_code"]
    ordered += list(_COUNT_COLUMNS.values()) + list(_RATE_COLUMNS.values())
    return df[ordered].sort_values("period_start").reset_index(drop=True)


def _side_table(
    sheet: pd.DataFrame,
    headers: list,
    start: int,
    key_header: str,
    columns: dict[str, str],
    skip: int = 0,
) -> pd.DataFrame:
    """Extract one of the two side-by-side tables on sheet 2.40.

    Args:
        sheet: Raw sheet with no header applied.
        headers: The header row values, used to locate columns by name.
        start: Index of the header row.
        key_header: Header of the quarter key column.
        columns: Mapping of published header to output column name.
        skip: Number of ``key_header`` occurrences to skip before matching, so the
            right-hand table can be reached.

    Returns:
        DataFrame keyed on ``quarter`` with the requested columns renamed.
    """
    key_positions = [i for i, h in enumerate(headers) if isinstance(h, str) and h.strip() == key_header]
    if len(key_positions) <= skip:
        raise NISRADataNotFoundError(f"Expected at least {skip + 1} {key_header!r} columns on sheet {_SHEET_SERIES}")
    key_col = key_positions[skip]

    positions = {}
    for published, output in columns.items():
        matches = [i for i, h in enumerate(headers) if isinstance(h, str) and h.strip() == published]
        if not matches:
            raise NISRADataNotFoundError(f"Column {published!r} not found on sheet {_SHEET_SERIES}")
        positions[output] = matches[0]

    body = sheet.iloc[start + 1 :]
    out = pd.DataFrame({"quarter": body[key_col].astype(str).str.strip()})
    for output, col in positions.items():
        out[output] = pd.to_numeric(body[col], errors="coerce")

    out = out[out["quarter"].str.contains(r"\d{4}$", na=False)]
    return out.dropna(subset=list(positions)).reset_index(drop=True)


def get_quarterly_series(force_refresh: bool = False) -> pd.DataFrame:
    """Get the full quarterly NEET series with counts, rates and confidence intervals.

    Args:
        force_refresh: If True, re-download rather than using the cache.

    Returns:
        DataFrame with one row per quarter from January-March 2013 onwards.

    Example:
        >>> df = get_quarterly_series()
        >>> int(df['total_neet'].iloc[-1]) > 0
        True
    """
    return parse_quarterly_series(_download(force_refresh=force_refresh))


def get_labour_market_status(force_refresh: bool = False) -> pd.DataFrame:
    """Get the labour market status of all 16-24 year olds for the latest quarter.

    This is the denominator behind the NEET rate: employment, unemployment and
    economic inactivity for the whole 16-24 population, whether or not they are in
    education.

    Args:
        force_refresh: If True, re-download rather than using the cache.

    Returns:
        DataFrame with ``status`` and ``count`` columns.

    Example:
        >>> df = get_labour_market_status()
        >>> 'Total population (aged 16 to 24)' in set(df['status'])
        True
    """
    sheet = pd.read_excel(_download(force_refresh=force_refresh), sheet_name=_SHEET_STATUS, header=None)
    df = _labelled_table(sheet, "Labour Market Status", "Number")
    return df.rename(columns={"Labour Market Status": "status", "Number": "count"})


def get_uk_comparison(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest-quarter NEET rate for Northern Ireland alongside the UK.

    Args:
        force_refresh: If True, re-download rather than using the cache.

    Returns:
        DataFrame with ``country`` and ``neet_rate_pct`` columns.

    Example:
        >>> df = get_uk_comparison()
        >>> len(df)
        2
    """
    sheet = pd.read_excel(_download(force_refresh=force_refresh), sheet_name=_SHEET_UK, header=None)
    df = _labelled_table(sheet, "Country", "NEET rate (%) [Note 1]")
    return df.rename(columns={"Country": "country", "NEET rate (%) [Note 1]": "neet_rate_pct"})


def get_neet_composition(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest quarter's NEET total split into its two components.

    NEET young people are either unemployed (seeking and available for work) or
    economically inactive, in both cases while not in education or training.

    Args:
        force_refresh: If True, re-download rather than using the cache.

    Returns:
        DataFrame with ``status`` and ``count`` columns, including the total row.

    Example:
        >>> df = get_neet_composition()
        >>> int(df['count'].max()) > 0
        True
    """
    sheet = pd.read_excel(_download(force_refresh=force_refresh), sheet_name=_SHEET_COMPOSITION, header=None)
    df = _labelled_table(sheet, "Labour Market Status", "Number")
    return df.rename(columns={"Labour Market Status": "status", "Number": "count"})


def get_gender_gap(force_refresh: bool = False) -> pd.DataFrame:
    """Get the male-minus-female NEET rate gap for each quarter.

    Args:
        force_refresh: If True, re-download rather than using the cache.

    Returns:
        DataFrame with ``quarter``, ``period_start``, ``year``, the two rates and a
        ``gap_pp`` column in percentage points (positive means males are higher).

    Example:
        >>> df = get_gender_gap()
        >>> 'gap_pp' in df.columns
        True
    """
    df = get_quarterly_series(force_refresh=force_refresh)
    df = df[["quarter", "period_start", "year", "male_neet_rate_pct", "female_neet_rate_pct"]].copy()
    df["gap_pp"] = (df["male_neet_rate_pct"] - df["female_neet_rate_pct"]).round(1)
    return df


def list_tables() -> pd.DataFrame:
    """List the tables this module exposes.

    Returns:
        DataFrame with ``table`` and ``description`` columns.

    Example:
        >>> len(list_tables())
        4
    """
    return pd.DataFrame(sorted(_TABLES.items()), columns=["table", "description"])


def get_latest_data(table: str = "quarterly", force_refresh: bool = False) -> pd.DataFrame:
    """Get a NEET table by name.

    Args:
        table: One of ``quarterly``, ``status``, ``uk`` or ``composition``.
        force_refresh: If True, re-download rather than using the cache.

    Returns:
        The requested DataFrame.

    Raises:
        ValueError: If ``table`` is not a known table name.

    Example:
        >>> df = get_latest_data('uk')
        >>> 'neet_rate_pct' in df.columns
        True
    """
    dispatch = {
        "quarterly": get_quarterly_series,
        "status": get_labour_market_status,
        "uk": get_uk_comparison,
        "composition": get_neet_composition,
    }
    if table not in dispatch:
        raise ValueError(f"Unknown table {table!r}. Available: {', '.join(sorted(dispatch))}")
    return dispatch[table](force_refresh=force_refresh)


def validate_data(df: pd.DataFrame, required_columns: list[str] | None = None) -> bool:
    """Validate a NEET DataFrame.

    Checks that the frame is non-empty, has the required columns, and that any
    count or rate columns hold sensible non-negative values with rates capped at
    100 percent.

    Args:
        df: DataFrame to validate.
        required_columns: Columns that must be present. Defaults to none beyond a
            non-empty frame.

    Returns:
        True if the DataFrame passes all checks, False otherwise.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame())
        False
        >>> validate_data(pd.DataFrame({'total_neet_rate_pct': [11.6]}))
        True
    """
    if df is None or df.empty:
        logger.warning("NEET validation failed: empty DataFrame")
        return False

    for column in required_columns or []:
        if column not in df.columns:
            logger.warning("NEET validation failed: missing column %s", column)
            return False

    for column in df.columns:
        if not column.endswith(("_neet", "_lower", "_upper", "_pct", "count")):
            continue
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if (values < 0).any():
            logger.warning("NEET validation failed: negative values in %s", column)
            return False
        if column.endswith("_pct") and (values > 100).any():
            logger.warning("NEET validation failed: rate above 100%% in %s", column)
            return False

    return True
