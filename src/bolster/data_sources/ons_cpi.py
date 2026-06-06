"""ONS UK inflation indices (CPI, CPIH, RPI).

Wraps the Office for National Statistics (ONS) open time-series API to provide
standardised access to the headline UK inflation measures:

- **CPIH** — Consumer Prices Index including owner-occupiers' housing costs
- **CPI** — Consumer Prices Index
- **RPI** — Retail Prices Index (longest run, back to 1948)

Each measure is available both as a 12-month annual rate (``%``) and as a price
index. Data is published at monthly, quarterly and annual resolutions.

This is the first of three macroeconomic context modules and emits a **fixed
output schema** so that inflation, and the other macro modules, can be joined
and resampled against one another:

==========  ==========================================================
Column      Description
==========  ==========================================================
date        ``datetime64[ns]`` period-start (Jan 2024 -> 2024-01-01,
            Q1 2024 -> 2024-01-01, year 2024 -> 2024-01-01)
year        ``int`` calendar year
quarter     ``str`` "Q1".."Q4", or ``pd.NA`` for annual/monthly
month       ``int`` 1-12, or ``pd.NA`` for quarterly/annual
resolution  ``str`` "annual" | "quarterly" | "monthly"
series      ``str`` ONS series code, e.g. "D7G7"
value       ``float`` observation value
unit        ``str`` e.g. "%" or "Index 2015=100"
geography   ``str`` always "UK"
source      ``str`` always "ONS"
==========  ==========================================================

Source:
    https://www.ons.gov.uk/economy/inflationandpriceindices

Example:
    >>> from bolster.data_sources import ons_cpi
    >>> df = ons_cpi.get_series("D7G7", resolution="annual")  # doctest: +SKIP
    >>> sorted(df.columns)  # doctest: +SKIP
    ['date', 'geography', 'month', 'quarter', 'resolution', 'series', 'source', 'unit', 'value', 'year']
"""

import logging

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

#: Base URL for the ONS time-series API. ``{code}`` is the lower-cased series id.
BASE_URL = "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/{code}/data"

#: Geography for all series exposed by this module.
GEOGRAPHY = "UK"

#: Data publisher.
SOURCE = "ONS"

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

#: Resolution name -> ONS response sub-array key.
_RESOLUTION_KEYS = {
    "monthly": "months",
    "quarterly": "quarters",
    "annual": "years",
}

#: Supported series codes with display name and unit.
SERIES = {
    "L55O": {"name": "CPIH annual rate", "unit": "%"},
    "L522": {"name": "CPIH index", "unit": "Index 2015=100"},
    "D7G7": {"name": "CPI annual rate", "unit": "%"},
    "D7BT": {"name": "CPI index", "unit": "Index 2015=100"},
    "CZBH": {"name": "RPI annual rate", "unit": "%"},
    "CHAW": {"name": "RPI index", "unit": "Index 1987=100"},
}

#: Month name -> month number, matching the ONS ``month`` field.
_MONTH_TO_NUM = {
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

#: Quarter label -> first month of that quarter.
_QUARTER_TO_MONTH = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}


class ONSDataError(Exception):
    """Base exception for ONS data errors."""


class ONSValidationError(ONSDataError):
    """Raised when a DataFrame fails :func:`validate_data`."""


def _fetch_series_json(code: str, force_refresh: bool = False) -> dict:
    """Fetch the raw JSON document for a single ONS series.

    The ONS API returns ``application/json``, which the shared
    :class:`~bolster.utils.web.CachingSession` does not cache (it only caches
    HTML). ``force_refresh`` is therefore accepted for API parity with the
    sibling macroeconomic modules but is a no-op on this code path.

    Args:
        code: ONS series code (case-insensitive), e.g. "D7G7".
        force_refresh: Accepted for API parity; has no effect (JSON is not cached).

    Returns:
        Parsed JSON document with ``months``/``quarters``/``years`` arrays.

    Raises:
        ONSDataError: If the request fails or the response is not valid JSON.
    """
    del force_refresh  # JSON responses are not cached; nothing to refresh.
    url = BASE_URL.format(code=code.lower())
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:  # noqa: BLE001 - re-wrapped as a domain error
        raise ONSDataError(f"Failed to fetch ONS series {code} from {url}: {e}") from e


def _row_to_record(row: dict, resolution: str, code: str, unit: str) -> dict | None:
    """Convert a single ONS observation into a schema row.

    Args:
        row: One element of a ``months``/``quarters``/``years`` array.
        resolution: "monthly", "quarterly" or "annual".
        code: ONS series code, stored in the ``series`` column.
        unit: Unit string for the ``unit`` column.

    Returns:
        A dict matching :data:`SCHEMA_COLUMNS`, or ``None`` if the value is
        missing/unparseable (such rows are dropped).
    """
    raw_value = row.get("value")
    if raw_value in (None, "", "-"):
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    try:
        year = int(row["year"])
    except (KeyError, TypeError, ValueError):
        return None

    quarter: object = pd.NA
    month: object = pd.NA

    if resolution == "monthly":
        month_name = str(row.get("month", "")).strip().lower()
        month_num = _MONTH_TO_NUM.get(month_name)
        if month_num is None:
            return None
        month = month_num
        date = pd.Timestamp(year=year, month=month_num, day=1)
    elif resolution == "quarterly":
        q_label = str(row.get("quarter", "")).strip().upper()
        start_month = _QUARTER_TO_MONTH.get(q_label)
        if start_month is None:
            return None
        quarter = q_label
        date = pd.Timestamp(year=year, month=start_month, day=1)
    else:  # annual
        date = pd.Timestamp(year=year, month=1, day=1)

    return {
        "date": date,
        "year": year,
        "quarter": quarter,
        "month": month,
        "resolution": resolution,
        "series": code,
        "value": value,
        "unit": unit,
        "geography": GEOGRAPHY,
        "source": SOURCE,
    }


def _empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical schema and dtypes."""
    df = pd.DataFrame(columns=SCHEMA_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["year"].astype("Int64")
    df["value"] = df["value"].astype("float64")
    return df


def get_series(code: str, resolution: str = "monthly", force_refresh: bool = False) -> pd.DataFrame:
    """Fetch a single ONS inflation series at a given resolution.

    Args:
        code: ONS series code (case-insensitive). One of :data:`SERIES`.
        resolution: "monthly" (default), "quarterly" or "annual".
        force_refresh: Bypass the page cache and re-download.

    Returns:
        DataFrame conforming to :data:`SCHEMA_COLUMNS`, sorted by ``date``.

    Raises:
        ValueError: If ``code`` or ``resolution`` is not recognised.
        ONSDataError: If the underlying API request fails.

    Example:
        >>> df = get_series("D7G7", resolution="annual")  # doctest: +SKIP
        >>> df.iloc[-1][["series", "unit", "geography"]].tolist()  # doctest: +SKIP
        ['D7G7', '%', 'UK']
    """
    code = code.upper()
    if code not in SERIES:
        raise ValueError(f"Unknown series code {code!r}. Valid codes: {sorted(SERIES)}")
    if resolution not in _RESOLUTION_KEYS:
        raise ValueError(f"Unknown resolution {resolution!r}. Valid: {sorted(_RESOLUTION_KEYS)}")

    unit = SERIES[code]["unit"]
    payload = _fetch_series_json(code, force_refresh=force_refresh)
    rows = payload.get(_RESOLUTION_KEYS[resolution], []) or []

    records = [rec for row in rows if (rec := _row_to_record(row, resolution, code, unit)) is not None]
    if not records:
        return _empty_frame()

    df = pd.DataFrame.from_records(records, columns=SCHEMA_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["year"].astype("Int64")
    df["value"] = df["value"].astype("float64")
    return df.sort_values("date").reset_index(drop=True)


def get_latest_data(resolution: str = "monthly", force_refresh: bool = False) -> pd.DataFrame:
    """Fetch all supported series at a given resolution, concatenated.

    Args:
        resolution: "monthly" (default), "quarterly" or "annual".
        force_refresh: Bypass the page cache and re-download each series.

    Returns:
        DataFrame conforming to :data:`SCHEMA_COLUMNS` containing every code in
        :data:`SERIES`, sorted by ``series`` then ``date``.

    Raises:
        ValueError: If ``resolution`` is not recognised.

    Example:
        >>> df = get_latest_data(resolution="annual")  # doctest: +SKIP
        >>> sorted(df["series"].unique())  # doctest: +SKIP
        ['CHAW', 'CZBH', 'D7BT', 'D7G7', 'L522', 'L55O']
    """
    if resolution not in _RESOLUTION_KEYS:
        raise ValueError(f"Unknown resolution {resolution!r}. Valid: {sorted(_RESOLUTION_KEYS)}")

    frames = []
    for code in SERIES:
        try:
            frames.append(get_series(code, resolution=resolution, force_refresh=force_refresh))
        except ONSDataError as e:
            logger.warning("Skipping series %s: %s", code, e)

    frames = [f for f in frames if not f.empty]
    if not frames:
        return _empty_frame()

    df = pd.concat(frames, ignore_index=True)
    return df.sort_values(["series", "date"]).reset_index(drop=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate that a DataFrame conforms to the macroeconomic schema.

    Checks performed:

    - All :data:`SCHEMA_COLUMNS` are present.
    - At least one row is present.
    - ``geography`` is exclusively "UK" and ``source`` exclusively "ONS".
    - ``resolution`` only contains known values.
    - ``value`` is numeric with no nulls.

    Args:
        df: DataFrame to validate.

    Returns:
        ``True`` if all checks pass.

    Raises:
        ONSValidationError: If any check fails.

    Example:
        >>> df = get_series("D7G7", resolution="annual")  # doctest: +SKIP
        >>> validate_data(df)  # doctest: +SKIP
        True
    """
    missing = [c for c in SCHEMA_COLUMNS if c not in df.columns]
    if missing:
        raise ONSValidationError(f"Missing required columns: {missing}")

    if len(df) == 0:
        raise ONSValidationError("DataFrame is empty")

    bad_geo = set(df["geography"].unique()) - {GEOGRAPHY}
    if bad_geo:
        raise ONSValidationError(f"Unexpected geography values: {bad_geo}")

    bad_source = set(df["source"].unique()) - {SOURCE}
    if bad_source:
        raise ONSValidationError(f"Unexpected source values: {bad_source}")

    bad_res = set(df["resolution"].unique()) - set(_RESOLUTION_KEYS)
    if bad_res:
        raise ONSValidationError(f"Unexpected resolution values: {bad_res}")

    if not pd.api.types.is_numeric_dtype(df["value"]):
        raise ONSValidationError("Column 'value' must be numeric")

    if df["value"].isna().any():
        raise ONSValidationError("Column 'value' contains nulls")

    return True
