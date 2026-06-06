"""Bank of England official Bank Rate (base rate).

Wraps the Bank of England's published base-rate spreadsheet to provide
standardised access to the UK policy interest rate:

- A **unified daily rate** series back to 1973, formed by coalescing the
  successive rate regimes the BoE has used (Minimum Lending Rate, Minimum
  Band 1 Dealing Rate, Repo Rate and the current Official Bank Rate) into a
  single continuous level.
- An **event-based history of rate changes** back to 1694, exposed via
  :func:`get_rate_changes`.

The base rate is a *level* (a standing interest rate), not a flow, so when it
is resampled to coarser resolutions the **last observation** in each period is
used rather than a sum or mean.

This is the second of three macroeconomic context modules and emits the same
**fixed output schema** as :mod:`bolster.data_sources.ons_cpi`, so that the
macro series can be joined and resampled against one another:

==========  ==========================================================
Column      Description
==========  ==========================================================
date        ``datetime64[ns]`` period-start (Jan 2024 -> 2024-01-01,
            Q1 2024 -> 2024-01-01, year 2024 -> 2024-01-01,
            a daily observation keeps its own date)
year        ``int`` calendar year
quarter     ``str`` "Q1".."Q4", or ``pd.NA`` for annual/monthly/daily
month       ``int`` 1-12, or ``pd.NA`` for quarterly/annual/daily
resolution  ``str`` "daily" | "monthly" | "quarterly" | "annual"
series      ``str`` always "base_rate"
value       ``float`` rate in per-cent
unit        ``str`` always "%"
geography   ``str`` always "UK"
source      ``str`` always "BoE"
==========  ==========================================================

.. note::
    The Bank of England's dynamic statistics API
    (``/boe-apps/statistics-api/``, ``/boe-apps/sdw/``) returns HTTP 403 for
    automated requests. The static spreadsheet linked below is the only
    reliable programmatic route and is what this module uses.

Source:
    https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp

Example:
    >>> from bolster.data_sources import boe_base_rate
    >>> df = boe_base_rate.get_latest_data(resolution="annual")  # doctest: +SKIP
    >>> sorted(df.columns)  # doctest: +SKIP
    ['date', 'geography', 'month', 'quarter', 'resolution', 'series', 'source', 'unit', 'value', 'year']
"""

import io
import logging

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

#: Static XLS published by the Bank of England (Excel 97-2003, needs ``xlrd``).
DATA_URL = "https://www.bankofengland.co.uk/-/media/boe/files/monetary-policy/baserate.xls"

#: Sheet holding the daily series (one column per historical rate regime).
RAW_DATA_SHEET = "Raw Data"

#: Sheet holding the irregular event-based rate changes since 1694.
HISTORICAL_SHEET = "HISTORICAL SINCE 1694"

#: Geography for all series exposed by this module.
GEOGRAPHY = "UK"

#: Data publisher.
SOURCE = "BoE"

#: Series identifier used across the macroeconomic modules.
SERIES = "base_rate"

#: Unit of the rate.
UNIT = "%"

#: Output schema column order shared across all macroeconomic modules.
SCHEMA_COLUMNS = [
    "date",
    "year",
    "quarter",
    "month",
    "resolution",
    "series",
    "value",
    "unit",
    "geography",
    "source",
]

#: Schema for :func:`get_rate_changes` (no period-resolution context).
RATE_CHANGES_COLUMNS = [
    "date",
    "year",
    "series",
    "value",
    "unit",
    "geography",
    "source",
]

#: Supported resolutions and how the period start maps to ``quarter``/``month``.
RESOLUTIONS = ("daily", "monthly", "quarterly", "annual")

#: Columns on the "Raw Data" sheet that carry a rate level (coalesced L->R).
_RATE_COLUMNS = [
    "Bank Rate",
    "Min Lending Rate",
    "Min Band 1 Dealing Rate",
    "Repo Rate",
    "Official Bank Rate",
]

#: Three-letter month abbreviation -> month number.
_MONTH_ABBR_TO_NUM = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

#: Quarter number -> label.
_QUARTER_LABELS = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}


class BoEDataError(Exception):
    """Base exception for Bank of England data errors."""


class BoEValidationError(BoEDataError):
    """Raised when a DataFrame fails :func:`validate_data`."""


def _download_workbook(force_refresh: bool = False) -> pd.ExcelFile:
    """Download the BoE base-rate workbook and return it as an ``ExcelFile``.

    The workbook is a binary ``.xls`` and is therefore not cached by the
    shared :class:`~bolster.utils.web.CachingSession` (which only caches HTML);
    ``force_refresh`` is accepted for API parity with the sibling macroeconomic
    modules but has no effect on this code path.

    Args:
        force_refresh: Accepted for API parity; binary downloads are not cached.

    Returns:
        A :class:`pandas.ExcelFile` opened with the ``xlrd`` engine.

    Raises:
        BoEDataError: If the download fails or the bytes are not a valid xls.
    """
    del force_refresh  # Binary responses are not cached; nothing to refresh.
    try:
        response = session.get(DATA_URL, timeout=60)
        response.raise_for_status()
        return pd.ExcelFile(io.BytesIO(response.content), engine="xlrd")
    except Exception as e:  # noqa: BLE001 - re-wrapped as a domain error
        raise BoEDataError(f"Failed to fetch BoE base rate workbook from {DATA_URL}: {e}") from e


def _coalesce_daily(workbook: pd.ExcelFile) -> pd.DataFrame:
    """Build the unified daily rate series from the "Raw Data" sheet.

    The sheet has one column per successive rate regime; on any given day only
    the column for the regime then in force is populated. The unified rate is
    the right-most non-null value across the rate columns for each row.

    Args:
        workbook: Open BoE workbook.

    Returns:
        DataFrame with ``date`` (datetime64) and ``value`` (float) columns,
        sorted by date with one row per calendar day.

    Raises:
        BoEDataError: If the sheet is missing expected columns or yields no rows.
    """
    raw = workbook.parse(sheet_name=RAW_DATA_SHEET, header=1)

    if "Date" not in raw.columns:
        raise BoEDataError(f"'{RAW_DATA_SHEET}' sheet is missing a 'Date' column; got {list(raw.columns)}")

    present = [c for c in _RATE_COLUMNS if c in raw.columns]
    if not present:
        raise BoEDataError(f"'{RAW_DATA_SHEET}' sheet has no recognised rate columns; got {list(raw.columns)}")

    dates = pd.to_datetime(raw["Date"], errors="coerce")
    # Coerce each regime column to numeric first so the row-wise ffill operates
    # on float (not object) data, then take the right-most non-null value = the
    # rate in force that day.
    rates = raw[present].apply(pd.to_numeric, errors="coerce")
    value = rates.ffill(axis=1).iloc[:, -1]

    df = pd.DataFrame({"date": dates, "value": pd.to_numeric(value, errors="coerce")})
    df = df.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)

    if df.empty:
        raise BoEDataError(f"No usable rows parsed from '{RAW_DATA_SHEET}' sheet")

    df["value"] = df["value"].astype("float64")
    return df


def _empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical schema and dtypes."""
    df = pd.DataFrame(columns=SCHEMA_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["year"].astype("Int64")
    df["value"] = df["value"].astype("float64")
    return df


def _attach_schema(df: pd.DataFrame, resolution: str) -> pd.DataFrame:
    """Attach the shared schema columns to a ``date``/``value`` frame.

    Args:
        df: Frame with at least ``date`` and ``value`` columns. ``date`` must
            already be normalised to the period start for the resolution.
        resolution: One of :data:`RESOLUTIONS`.

    Returns:
        DataFrame conforming to :data:`SCHEMA_COLUMNS`.
    """
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["year"] = out["date"].dt.year.astype("Int64")

    if resolution == "monthly":
        out["month"] = out["date"].dt.month.astype("Int64")
        out["quarter"] = pd.NA
    elif resolution == "quarterly":
        out["quarter"] = out["date"].dt.quarter.map(_QUARTER_LABELS)
        out["month"] = pd.NA
    else:  # daily and annual carry neither a quarter nor a month label
        out["quarter"] = pd.NA
        out["month"] = pd.NA

    out["resolution"] = resolution
    out["series"] = SERIES
    out["value"] = out["value"].astype("float64")
    out["unit"] = UNIT
    out["geography"] = GEOGRAPHY
    out["source"] = SOURCE
    return out[SCHEMA_COLUMNS].reset_index(drop=True)


def get_latest_data(resolution: str = "monthly", force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the unified UK base rate at a given resolution.

    The base rate is a standing level, so coarser resolutions take the **last
    observation** in each period (i.e. the rate in force at period end).

    Args:
        resolution: "daily", "monthly" (default), "quarterly" or "annual".
        force_refresh: Accepted for API parity; binary downloads are not cached.

    Returns:
        DataFrame conforming to :data:`SCHEMA_COLUMNS`, sorted by ``date``.

    Raises:
        ValueError: If ``resolution`` is not recognised.
        BoEDataError: If the workbook download or parse fails.

    Example:
        >>> df = get_latest_data(resolution="annual")  # doctest: +SKIP
        >>> df.iloc[-1][["series", "unit", "geography", "source"]].tolist()  # doctest: +SKIP
        ['base_rate', '%', 'UK', 'BoE']
    """
    if resolution not in RESOLUTIONS:
        raise ValueError(f"Unknown resolution {resolution!r}. Valid: {sorted(RESOLUTIONS)}")

    workbook = _download_workbook(force_refresh=force_refresh)
    daily = _coalesce_daily(workbook)

    if daily.empty:
        return _empty_frame()

    if resolution == "daily":
        return _attach_schema(daily, "daily")

    freq = {"monthly": "MS", "quarterly": "QS", "annual": "YS"}[resolution]
    # Resample to the period start, taking the last rate observed in the period.
    resampled = daily.set_index("date")["value"].resample(freq).last().dropna()
    period = resampled.reset_index()
    period.columns = ["date", "value"]
    return _attach_schema(period, resolution)


def get_rate_changes(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the event-based history of base-rate changes back to 1694.

    Each row is a rate *change* effective on a given date (the value is the new
    rate). The series is irregular by nature. Where the source records only a
    year and month (the earliest entries pre-date daily records), the change is
    dated to the first of that month.

    Args:
        force_refresh: Accepted for API parity; binary downloads are not cached.

    Returns:
        DataFrame with columns :data:`RATE_CHANGES_COLUMNS`, sorted by ``date``.

    Raises:
        BoEDataError: If the workbook download or parse fails, or no changes
            could be parsed.

    Example:
        >>> df = get_rate_changes()  # doctest: +SKIP
        >>> df.iloc[0][["date", "value"]].tolist()  # doctest: +SKIP
        [Timestamp('1694-10-01 00:00:00'), 6.0]
    """
    workbook = _download_workbook(force_refresh=force_refresh)
    raw = workbook.parse(sheet_name=HISTORICAL_SHEET, header=None)

    # Columns: 0=year, 1=day, 2=month abbr, 3=new rate. Year is sparse (only
    # filled on the first change of each year) so it is forward-filled.
    cols = raw.iloc[:, [0, 1, 2, 3]].copy()
    cols.columns = ["year", "day", "month", "value"]
    cols["year"] = cols["year"].ffill()

    cols["mnum"] = cols["month"].astype(str).str.strip().str[:3].str.title().map(_MONTH_ABBR_TO_NUM)
    cols = cols[cols["mnum"].notna()].copy()  # drops header rows and footnotes

    cols["day"] = pd.to_numeric(cols["day"], errors="coerce").fillna(1).astype(int)
    cols["year"] = pd.to_numeric(cols["year"], errors="coerce")
    cols["value"] = pd.to_numeric(cols["value"], errors="coerce")
    cols = cols.dropna(subset=["year", "value"])

    cols["date"] = pd.to_datetime(
        {"year": cols["year"].astype(int), "month": cols["mnum"].astype(int), "day": cols["day"]},
        errors="coerce",
    )
    cols = cols.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    if cols.empty:
        raise BoEDataError(f"No rate changes parsed from '{HISTORICAL_SHEET}' sheet")

    out = pd.DataFrame(
        {
            "date": cols["date"],
            "year": cols["date"].dt.year.astype("Int64"),
            "series": SERIES,
            "value": cols["value"].astype("float64"),
            "unit": UNIT,
            "geography": GEOGRAPHY,
            "source": SOURCE,
        }
    )
    return out[RATE_CHANGES_COLUMNS].reset_index(drop=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate that a DataFrame conforms to the macroeconomic schema.

    Checks performed:

    - All :data:`SCHEMA_COLUMNS` are present.
    - At least one row is present.
    - ``geography`` is exclusively "UK" and ``source`` exclusively "BoE".
    - ``series`` is exclusively "base_rate" and ``unit`` exclusively "%".
    - ``resolution`` only contains known values.
    - ``value`` is numeric, non-null and within a sane 0-25% range.

    Args:
        df: DataFrame to validate.

    Returns:
        ``True`` if all checks pass.

    Raises:
        BoEValidationError: If any check fails.

    Example:
        >>> df = get_latest_data(resolution="annual")  # doctest: +SKIP
        >>> validate_data(df)  # doctest: +SKIP
        True
    """
    missing = [c for c in SCHEMA_COLUMNS if c not in df.columns]
    if missing:
        raise BoEValidationError(f"Missing required columns: {missing}")

    if len(df) == 0:
        raise BoEValidationError("DataFrame is empty")

    bad_geo = set(df["geography"].unique()) - {GEOGRAPHY}
    if bad_geo:
        raise BoEValidationError(f"Unexpected geography values: {bad_geo}")

    bad_source = set(df["source"].unique()) - {SOURCE}
    if bad_source:
        raise BoEValidationError(f"Unexpected source values: {bad_source}")

    bad_series = set(df["series"].unique()) - {SERIES}
    if bad_series:
        raise BoEValidationError(f"Unexpected series values: {bad_series}")

    bad_unit = set(df["unit"].unique()) - {UNIT}
    if bad_unit:
        raise BoEValidationError(f"Unexpected unit values: {bad_unit}")

    bad_res = set(df["resolution"].unique()) - set(RESOLUTIONS)
    if bad_res:
        raise BoEValidationError(f"Unexpected resolution values: {bad_res}")

    if not pd.api.types.is_numeric_dtype(df["value"]):
        raise BoEValidationError("Column 'value' must be numeric")

    if df["value"].isna().any():
        raise BoEValidationError("Column 'value' contains nulls")

    if (df["value"] < 0).any() or (df["value"] > 25).any():
        raise BoEValidationError("Column 'value' has rates outside the plausible 0-25% range")

    return True
