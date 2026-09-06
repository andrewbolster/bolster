"""European Central Bank key interest rates.

Wraps the ECB Data Portal's SDMX-JSON REST API to provide standardised access
to the Eurozone's three official policy rates:

- ``mrr_fr`` -- Main Refinancing Operations rate (the primary policy rate)
- ``dfr`` -- Deposit Facility Rate
- ``mlfr`` -- Marginal Lending Facility Rate

All three are *levels* (standing interest rates), not flows, so when resampled
to coarser resolutions the **last observation in force** at period end is used
rather than a sum or mean -- consistent with how :mod:`bolster.data_sources.boe_base_rate`
treats the UK base rate. The ECB only publishes discrete *change events*
(no native daily grid), so each series is filled forward through calendar time
before resampling: the rate stays "in force" at every period end until the
next recorded change, including all the way through to the present day.

This is the third of three macroeconomic context modules and emits the same
**fixed output schema** as :mod:`bolster.data_sources.ons_cpi` and
:mod:`bolster.data_sources.boe_base_rate`, so the macro series can be joined
and resampled against one another:

==========  ==========================================================
Column      Description
==========  ==========================================================
date        ``datetime64[ns]`` period-start (Jan 2024 -> 2024-01-01,
            Q1 2024 -> 2024-01-01, year 2024 -> 2024-01-01)
year        ``int`` calendar year
quarter     ``str`` "Q1".."Q4", or ``pd.NA`` for annual/monthly
month       ``int`` 1-12, or ``pd.NA`` for quarterly/annual
resolution  ``str`` "monthly" | "quarterly" | "annual"
series      ``str`` "mrr_fr" | "dfr" | "mlfr"
value       ``float`` rate in per-cent (may be negative -- the Deposit
            Facility Rate went as low as -0.5% during 2014-2022)
unit        ``str`` always "%"
geography   ``str`` always "Eurozone"
source      ``str`` always "ECB"
==========  ==========================================================

.. note::
    ``geography="Eurozone"`` is this library's first non-UK/NI macro series.
    It exists to enable UK/NI vs Eurozone policy-rate comparison alongside
    :mod:`bolster.data_sources.boe_base_rate` -- Northern Ireland's Windsor
    Framework arrangements keep it partially inside the EU single market for
    goods, giving Eurozone monetary policy more direct NI relevance than it
    would have for a GB-only dataset.

Source:
    API: https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.{RATE_CODE}.LEV?format=jsondata
    Portal: https://data.ecb.europa.eu/

Example:
    >>> from bolster.data_sources import ecb_interest_rates
    >>> df = ecb_interest_rates.get_latest_data(rate="dfr", resolution="annual")  # doctest: +SKIP
    >>> sorted(df.columns)  # doctest: +SKIP
    ['date', 'geography', 'month', 'quarter', 'resolution', 'series', 'source', 'unit', 'value', 'year']
"""

import logging

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

#: SDMX-JSON endpoint template; ``{rate_code}`` is one of :data:`RATE_CODES`' values.
DATA_URL_TEMPLATE = "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.{rate_code}.LEV?format=jsondata"

#: Geography for all series exposed by this module.
GEOGRAPHY = "Eurozone"

#: Data publisher.
SOURCE = "ECB"

#: Unit of the rate.
UNIT = "%"

#: Public ``rate`` values mapped to the ECB's own series identifiers.
RATE_CODES = {
    "mrr_fr": "MRR_FR",
    "dfr": "DFR",
    "mlfr": "MLFR",
}

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

#: Supported resolutions. No "daily" -- the ECB source is a sparse change-event
#: series, not a native daily grid; unlike BoE's, a "daily" reading here would
#: just be the same forward-filled value on 99%+ of days, giving no new signal.
RESOLUTIONS = ("monthly", "quarterly", "annual")

#: Quarter number -> label.
_QUARTER_LABELS = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}


class ECBDataError(Exception):
    """Base exception for ECB key interest rate data errors."""


class ECBValidationError(ECBDataError):
    """Raised when a DataFrame fails :func:`validate_data`."""


def _fetch_change_events(rate: str, force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the SDMX-JSON change-event series for one ECB rate.

    Args:
        rate: One of :data:`RATE_CODES`' keys ("mrr_fr", "dfr", "mlfr").
        force_refresh: Bypass the shared session's page cache and re-download.

    Returns:
        DataFrame with ``date`` (datetime64) and ``value`` (float) columns,
        one row per recorded rate change, sorted by date.

    Raises:
        ValueError: If ``rate`` is not recognised.
        ECBDataError: If the download fails, or the response isn't the
            expected SDMX-JSON shape, or no observations are found.
    """
    if rate not in RATE_CODES:
        raise ValueError(f"Unknown rate {rate!r}. Valid: {sorted(RATE_CODES)}")

    url = DATA_URL_TEMPLATE.format(rate_code=RATE_CODES[rate])
    try:
        response = session.get(url, timeout=30, force_refresh=force_refresh)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:  # noqa: BLE001 - re-wrapped as a domain error
        raise ECBDataError(f"Failed to fetch ECB {rate!r} series from {url}: {e}") from e

    try:
        dates = payload["structure"]["dimensions"]["observation"][0]["values"]
        series_key = next(iter(payload["dataSets"][0]["series"]))
        observations = payload["dataSets"][0]["series"][series_key]["observations"]
    except (KeyError, IndexError, StopIteration) as e:
        raise ECBDataError(f"Unexpected SDMX-JSON shape from {url}: {e}") from e

    records = []
    for i, date_meta in enumerate(dates):
        obs = observations.get(str(i))
        if obs is None or obs[0] is None:
            continue
        records.append({"date": pd.to_datetime(date_meta["id"]), "value": float(obs[0])})

    if not records:
        raise ECBDataError(f"No observations parsed for rate {rate!r} from {url}")

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


def _daily_filled(events: pd.DataFrame) -> pd.Series:
    """Expand sparse change events into a daily series, forward-filled to today.

    The ECB only records the dates rates *changed*; the rate stays in force at
    every date in between. Filling forward to today (not just to the last
    recorded change) is what lets ``get_series`` report "no change since the
    last event" correctly for the current month/quarter/year, rather than the
    resampled series silently stopping at whatever period the last change fell
    in.

    Args:
        events: Output of :func:`_fetch_change_events`.

    Returns:
        A ``float64`` Series indexed by every calendar day from the first
        change event to today, holding the rate in force on that day.
    """
    s = events.set_index("date")["value"].sort_index()
    full_index = pd.date_range(s.index.min(), pd.Timestamp.now().normalize(), freq="D")
    return s.reindex(full_index).ffill()


def _attach_schema(df: pd.DataFrame, resolution: str, rate: str) -> pd.DataFrame:
    """Attach the shared schema columns to a ``date``/``value`` frame.

    Args:
        df: Frame with at least ``date`` and ``value`` columns. ``date`` must
            already be normalised to the period start for the resolution.
        resolution: One of :data:`RESOLUTIONS`.
        rate: One of :data:`RATE_CODES`' keys; becomes the ``series`` value.

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
    else:  # annual carries neither a quarter nor a month label
        out["quarter"] = pd.NA
        out["month"] = pd.NA

    out["resolution"] = resolution
    out["series"] = rate
    out["value"] = out["value"].astype("float64")
    out["unit"] = UNIT
    out["geography"] = GEOGRAPHY
    out["source"] = SOURCE
    return out[SCHEMA_COLUMNS].reset_index(drop=True)


def get_rate_changes(rate: str, force_refresh: bool = False) -> pd.DataFrame:
    """Fetch the raw event-based history of changes for one ECB key rate.

    Each row is a rate *change* effective on a given date (the value is the
    new rate), exactly as published -- no forward-filling or resampling.

    Args:
        rate: One of "mrr_fr", "dfr", "mlfr".
        force_refresh: Bypass the shared session's page cache and re-download.

    Returns:
        DataFrame with columns :data:`RATE_CHANGES_COLUMNS`, sorted by ``date``.

    Raises:
        ValueError: If ``rate`` is not recognised.
        ECBDataError: If the download or parse fails.

    Example:
        >>> df = get_rate_changes("dfr")  # doctest: +SKIP
        >>> df.iloc[0][["date", "value"]].tolist()  # doctest: +SKIP
        [Timestamp('1999-01-01 00:00:00'), 2.0]
    """
    events = _fetch_change_events(rate, force_refresh=force_refresh)
    out = pd.DataFrame(
        {
            "date": events["date"],
            "year": events["date"].dt.year.astype("Int64"),
            "series": rate,
            "value": events["value"].astype("float64"),
            "unit": UNIT,
            "geography": GEOGRAPHY,
            "source": SOURCE,
        }
    )
    return out[RATE_CHANGES_COLUMNS].reset_index(drop=True)


def get_series(rate: str, resolution: str = "monthly", force_refresh: bool = False) -> pd.DataFrame:
    """Fetch a single ECB key rate at a given resolution.

    The rate is a standing level, so coarser resolutions take the **last
    observation** in each period (i.e. the rate in force at period end),
    forward-filled through to the present day.

    Args:
        rate: One of "mrr_fr", "dfr", "mlfr".
        resolution: "monthly" (default), "quarterly" or "annual".
        force_refresh: Bypass the shared session's page cache and re-download.

    Returns:
        DataFrame conforming to :data:`SCHEMA_COLUMNS`, sorted by ``date``.

    Raises:
        ValueError: If ``rate`` or ``resolution`` is not recognised.
        ECBDataError: If the download or parse fails.

    Example:
        >>> df = get_series("mrr_fr", resolution="annual")  # doctest: +SKIP
        >>> df.iloc[-1][["series", "unit", "geography", "source"]].tolist()  # doctest: +SKIP
        ['mrr_fr', '%', 'Eurozone', 'ECB']
    """
    if resolution not in RESOLUTIONS:
        raise ValueError(f"Unknown resolution {resolution!r}. Valid: {sorted(RESOLUTIONS)}")

    events = _fetch_change_events(rate, force_refresh=force_refresh)
    daily = _daily_filled(events)

    freq = {"monthly": "MS", "quarterly": "QS", "annual": "YS"}[resolution]
    resampled = daily.resample(freq).last().dropna()
    period = resampled.reset_index()
    period.columns = ["date", "value"]
    return _attach_schema(period, resolution, rate)


def get_latest_data(rate: str = "all", resolution: str = "monthly", force_refresh: bool = False) -> pd.DataFrame:
    """Fetch one or all three ECB key interest rates at a given resolution.

    Args:
        rate: "mrr_fr", "dfr", "mlfr", or "all" (default) for all three,
            concatenated.
        resolution: "monthly" (default), "quarterly" or "annual".
        force_refresh: Bypass the shared session's page cache and re-download.

    Returns:
        DataFrame conforming to :data:`SCHEMA_COLUMNS`.

    Raises:
        ValueError: If ``rate`` or ``resolution`` is not recognised.
        ECBDataError: If any download or parse fails.

    Example:
        >>> df = get_latest_data(rate="dfr", resolution="annual")  # doctest: +SKIP
        >>> set(df["series"])  # doctest: +SKIP
        {'dfr'}
    """
    if rate == "all":
        frames = [get_series(r, resolution=resolution, force_refresh=force_refresh) for r in RATE_CODES]
        return pd.concat(frames, ignore_index=True)
    if rate not in RATE_CODES:
        raise ValueError(f"Unknown rate {rate!r}. Valid: {sorted(RATE_CODES)} or 'all'")
    return get_series(rate, resolution=resolution, force_refresh=force_refresh)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate that a DataFrame conforms to the macroeconomic schema.

    Checks performed:

    - All :data:`SCHEMA_COLUMNS` are present.
    - At least one row is present.
    - ``geography`` is exclusively "Eurozone" and ``source`` exclusively "ECB".
    - ``series`` only contains known rate keys and ``unit`` is exclusively "%".
    - ``resolution`` only contains known values.
    - ``value`` is numeric, non-null and within a sane range (-1% to 25% --
      the Deposit Facility Rate has been negative, unlike the UK base rate).

    Args:
        df: DataFrame to validate.

    Returns:
        ``True`` if all checks pass.

    Raises:
        ECBValidationError: If any check fails.

    Example:
        >>> df = get_latest_data(rate="mrr_fr", resolution="annual")  # doctest: +SKIP
        >>> validate_data(df)  # doctest: +SKIP
        True
    """
    missing = [c for c in SCHEMA_COLUMNS if c not in df.columns]
    if missing:
        raise ECBValidationError(f"Missing required columns: {missing}")

    if len(df) == 0:
        raise ECBValidationError("DataFrame is empty")

    bad_geo = set(df["geography"].unique()) - {GEOGRAPHY}
    if bad_geo:
        raise ECBValidationError(f"Unexpected geography values: {bad_geo}")

    bad_source = set(df["source"].unique()) - {SOURCE}
    if bad_source:
        raise ECBValidationError(f"Unexpected source values: {bad_source}")

    bad_series = set(df["series"].unique()) - set(RATE_CODES)
    if bad_series:
        raise ECBValidationError(f"Unexpected series values: {bad_series}")

    bad_unit = set(df["unit"].unique()) - {UNIT}
    if bad_unit:
        raise ECBValidationError(f"Unexpected unit values: {bad_unit}")

    bad_res = set(df["resolution"].unique()) - set(RESOLUTIONS)
    if bad_res:
        raise ECBValidationError(f"Unexpected resolution values: {bad_res}")

    if not pd.api.types.is_numeric_dtype(df["value"]):
        raise ECBValidationError("Column 'value' must be numeric")

    if df["value"].isna().any():
        raise ECBValidationError("Column 'value' contains nulls")

    if (df["value"] < -1).any() or (df["value"] > 25).any():
        raise ECBValidationError("Column 'value' has rates outside the plausible -1% to 25% range")

    return True
