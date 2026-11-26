"""NISRA Annual Business Inquiry (ABI) Module.

Provides turnover, purchases and approximate gross value added (aGVA) for Northern Ireland
businesses, by industry section and by two-digit SIC 2007 division, each with a 95% confidence
interval and a coefficient of variation. The ABI is a sample survey of the financial performance
of businesses. It is a different statistic from the Inter-Departmental Business Register
(:mod:`bolster.data_sources.nisra.business_register`), which counts registered businesses.

Data Source:
    NISRA PxStat API (https://data.nisra.gov.uk/), matrices:

    - ``ABI01`` -- by industry section (SIC 2007 sections A-S that the survey covers, plus ``ALL``)
    - ``ABI02`` -- by SIC 2007 two-digit division (plus ``ALL``)

    The reporting-unit matrix ``ABIRU`` is not used. It is published on a different cycle and ends
    at an earlier year than ``ABI01`` and ``ABI02``, so it cannot be combined with them by year.

    Publication page: https://www.nisra.gov.uk/statistics/business-statistics/annual-business-inquiry

Update Frequency: Annual. Each release adds the latest reference year and may revise earlier years.

Geographic Coverage: Northern Ireland (no sub-regional breakdown).

Published as: Results from the Northern Ireland Annual Business Inquiry.

Output shape:
    Every function returns one row per year, measure and industry code. Money is in pounds
    sterling, millions (nominal, not adjusted for inflation).

    - ``year``: reference year (int)
    - ``measure``: ``"turnover"``, ``"purchases"`` or ``"gva"``
    - ``sector_code`` / ``sector`` (sections) or ``sic2_code`` / ``industry`` (divisions): the
      PxStat code and its label. Join on the code; labels change letter case between releases.
    - ``value``: the estimate
    - ``ci_lower``, ``ci_upper``: 95% confidence interval bounds, same unit as ``value``
    - ``cv_pct``: coefficient of variation, percent

    Approximate GVA can be negative for a division, a confidence interval can extend below zero,
    and ``cv_pct`` takes the sign of its value. Turnover and purchases values are never negative.

Suppression:
    Cells NISRA suppresses for disclosure control are NaN, never zero. In the division matrix some
    divisions are suppressed entirely (value, interval and coefficient of variation) and some
    have a value with the interval and coefficient of variation suppressed. A missing value never
    carries an interval. Sums over divisions are therefore not comparable to ``ALL`` when any
    division is suppressed.

Example:
    >>> from bolster.data_sources.nisra import annual_business_inquiry
    >>> df = annual_business_inquiry.get_latest_data()
    >>> bool((df["year"] == annual_business_inquiry.get_latest_year()).all())
    True
"""

import logging
from collections.abc import Callable

import pandas as pd

from bolster.data_sources.nisra._base import NISRADataError, NISRADataNotFoundError, NISRAValidationError
from bolster.data_sources.nisra.pxstat import read_dataset

logger = logging.getLogger(__name__)

MEASURES = ("turnover", "purchases", "gva")

_YEAR_COLUMN = "TLIST(A1)"
_STATISTIC_COLUMN = "STATISTIC"
_MEASURE_COLUMN = "PARAMETER"
_VALUE_COLUMN = "VALUE"

# PxStat statistic codes are stable; their labels and the label column names are not.
_STATISTIC_NAMES = {
    "ABIVALUE": "value",
    "LOWER_CONF_INTERVAL": "ci_lower",
    "UPPER_CONF_INTERVAL": "ci_upper",
    "CV": "cv_pct",
}
_VALUE_COLUMNS = list(_STATISTIC_NAMES.values())

# level -> (matrix, PxStat code column, output code column, output label column)
_LEVELS = {
    "sector": ("ABI01", "RUSECTION", "sector_code", "sector"),
    "sic2": ("ABI02", "SIC2", "sic2_code", "industry"),
}


def _level_spec(level: str) -> tuple[str, str, str, str]:
    """Return the matrix, PxStat code column and output column names for a level.

    Raises:
        ValueError: If ``level`` is not ``"sector"`` or ``"sic2"``.
    """
    try:
        return _LEVELS[level]
    except KeyError:
        raise ValueError(f"level must be one of {sorted(_LEVELS)}, got {level!r}") from None


def _tidy(raw: pd.DataFrame, code_column: str, out_code: str, out_label: str) -> pd.DataFrame:
    """Pivot a raw ABI PxStat frame into one row per year, measure and industry code.

    Args:
        raw: Raw frame from :func:`~bolster.data_sources.nisra.pxstat.read_dataset`.
        code_column: PxStat code column of the industry dimension (``RUSECTION`` or ``SIC2``).
        out_code: Output name for the industry code column.
        out_label: Output name for the industry label column.

    Returns:
        DataFrame with ``year``, ``measure``, the code and label columns, then ``value``,
        ``ci_lower``, ``ci_upper`` and ``cv_pct``.

    Raises:
        NISRADataError: If an expected column or statistic is missing, a statistic is
            unrecognised, or a (year, measure, industry, statistic) cell is duplicated.
    """
    required = [_YEAR_COLUMN, _STATISTIC_COLUMN, _MEASURE_COLUMN, code_column, _VALUE_COLUMN]
    missing_columns = [c for c in required if c not in raw.columns]
    if missing_columns:
        raise NISRADataError(f"ABI response lacks expected columns {missing_columns}; found {list(raw.columns)}")

    statistics = set(raw[_STATISTIC_COLUMN])
    if statistics != set(_STATISTIC_NAMES):
        raise NISRADataError(
            f"ABI statistics are {sorted(statistics)}, expected {sorted(_STATISTIC_NAMES)}; "
            "the PxStat matrix layout has changed"
        )

    # PxStat writes each dimension as a code column immediately followed by its label column.
    label_column = raw.columns[raw.columns.get_loc(code_column) + 1]
    labels = raw.groupby(code_column, sort=False)[label_column].first()
    code_order = {code: position for position, code in enumerate(labels.index)}

    try:
        wide = raw.pivot(
            index=[_YEAR_COLUMN, _MEASURE_COLUMN, code_column], columns=_STATISTIC_COLUMN, values=_VALUE_COLUMN
        )
    except ValueError as e:
        raise NISRADataError(f"ABI response has duplicate (year, measure, {code_column}) cells: {e}") from e

    out = wide.rename(columns=_STATISTIC_NAMES)[_VALUE_COLUMNS].reset_index()
    out = out.rename(columns={_YEAR_COLUMN: "year", _MEASURE_COLUMN: "measure", code_column: out_code})
    out.columns.name = None
    out["year"] = out["year"].astype(int)
    out["measure"] = out["measure"].str.lower()
    out[out_label] = out[out_code].map(labels)
    out = out.sort_values(["year", "measure", out_code], key=_sort_key(code_order, out_code), kind="stable")
    return out[["year", "measure", out_code, out_label, *_VALUE_COLUMNS]].reset_index(drop=True)


def _sort_key(code_order: dict[str, int], out_code: str) -> Callable[[pd.Series], pd.Series]:
    """Sort by year, then by :data:`MEASURES` order, then by the order PxStat lists the industry codes."""
    measure_order = {measure: position for position, measure in enumerate(MEASURES)}

    def key(column: pd.Series) -> pd.Series:
        if column.name == out_code:
            return column.map(code_order)
        if column.name == "measure":
            return column.map(measure_order)
        return column

    return key


def _fetch(level: str) -> pd.DataFrame:
    """Download and tidy the ABI matrix for one level."""
    matrix, code_column, out_code, out_label = _level_spec(level)
    logger.info("Fetching Annual Business Inquiry %s data from PxStat matrix %s", level, matrix)
    return _tidy(read_dataset(matrix), code_column, out_code, out_label)


def _select(df: pd.DataFrame, year: int | None, measure: str | None) -> pd.DataFrame:
    """Filter a tidy frame to one year and/or one measure, raising when the year is absent."""
    if measure is not None:
        measure = measure.lower()
        if measure not in MEASURES:
            raise ValueError(f"measure must be one of {list(MEASURES)}, got {measure!r}")
        df = df[df["measure"] == measure]
    if year is not None:
        available = sorted(df["year"].unique())
        if year not in available:
            raise NISRADataNotFoundError(
                f"The Annual Business Inquiry has no data for {year}; it covers {available[0]} to {available[-1]}"
            )
        df = df[df["year"] == year]
    return df.reset_index(drop=True)


def get_by_sector(year: int | None = None, measure: str | None = None) -> pd.DataFrame:
    """Return ABI turnover, purchases and aGVA by industry section (PxStat ``ABI01``).

    Args:
        year: Reference year to return. ``None`` returns every year.
        measure: ``"turnover"``, ``"purchases"`` or ``"gva"``. ``None`` returns all three.

    Returns:
        DataFrame with ``year``, ``measure``, ``sector_code``, ``sector``, ``value``,
        ``ci_lower``, ``ci_upper`` and ``cv_pct``. ``sector_code`` is ``"ALL"`` for the
        all-industries total and a letter for each section.

    Raises:
        NISRADataNotFoundError: If ``year`` is not in the data.
        ValueError: If ``measure`` is not one of the three measures.

    Example:
        >>> df = get_by_sector(year=2025, measure="turnover")  # doctest: +SKIP
        >>> df[df["sector_code"] == "ALL"]["value"].iloc[0] > 0  # doctest: +SKIP
        True
    """
    return _select(_fetch("sector"), year, measure)


def get_by_sic2(year: int | None = None, measure: str | None = None) -> pd.DataFrame:
    """Return ABI turnover, purchases and aGVA by SIC 2007 division (PxStat ``ABI02``).

    Suppressed cells are NaN; see the module docstring.

    Args:
        year: Reference year to return. ``None`` returns every year.
        measure: ``"turnover"``, ``"purchases"`` or ``"gva"``. ``None`` returns all three.

    Returns:
        DataFrame with ``year``, ``measure``, ``sic2_code``, ``industry``, ``value``,
        ``ci_lower``, ``ci_upper`` and ``cv_pct``. ``sic2_code`` is ``"ALL"`` for the
        all-industries total and a two-digit string (``"01"``, ``"10"``...) for each division.

    Raises:
        NISRADataNotFoundError: If ``year`` is not in the data.
        ValueError: If ``measure`` is not one of the three measures.
    """
    return _select(_fetch("sic2"), year, measure)


def get_latest_year(level: str = "sector") -> int:
    """Return the most recent reference year present in the ABI matrix for a level.

    Args:
        level: ``"sector"`` (``ABI01``) or ``"sic2"`` (``ABI02``).

    Returns:
        The latest reference year.

    Raises:
        ValueError: If ``level`` is not ``"sector"`` or ``"sic2"``.
    """
    return int(_fetch(level)["year"].max())


def get_latest_data(level: str = "sector") -> pd.DataFrame:
    """Return every measure for the latest reference year.

    The ``year`` column of the result states the year served. Nothing is substituted from
    another year: the latest year is whatever the matrix holds.

    Args:
        level: ``"sector"`` (``ABI01``) or ``"sic2"`` (``ABI02``).

    Returns:
        DataFrame in the shape of :func:`get_by_sector` or :func:`get_by_sic2`, for one year.

    Raises:
        ValueError: If ``level`` is not ``"sector"`` or ``"sic2"``.
    """
    df = _fetch(level)
    latest = int(df["year"].max())
    logger.info("Annual Business Inquiry %s data: serving reference year %d", level, latest)
    return df[df["year"] == latest].reset_index(drop=True)


def validate_data(df: pd.DataFrame, level: str = "sector") -> bool:
    """Validate the structure of an ABI frame.

    Checks the columns, that the frame is non-empty, that every year from the earliest to the
    latest is present, that the all-industries total exists for every year and measure, that
    turnover and purchases are not negative, that a coefficient of variation is negative only
    when its value is, that confidence intervals bracket their value, and that a suppressed
    value never has an interval. Approximate GVA may legitimately be negative.

    Args:
        df: Frame from :func:`get_by_sector`, :func:`get_by_sic2` or :func:`get_latest_data`.
        level: ``"sector"`` or ``"sic2"``.

    Returns:
        True if validation passes.

    Raises:
        NISRAValidationError: If a check fails.
        ValueError: If ``level`` is not ``"sector"`` or ``"sic2"``.
    """
    _, _, out_code, out_label = _level_spec(level)
    expected = ["year", "measure", out_code, out_label, *_VALUE_COLUMNS]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    years = sorted(df["year"].unique())
    gaps = sorted(set(range(years[0], years[-1] + 1)) - set(years))
    if gaps:
        raise NISRAValidationError(f"Years missing between {years[0]} and {years[-1]}: {gaps}")

    totals = df[df[out_code] == "ALL"].groupby(["year", "measure"]).size()
    groups = df.groupby(["year", "measure"]).size()
    absent = groups.index.difference(totals.index)
    if len(absent):
        raise NISRAValidationError(f"No all-industries ('ALL') row for (year, measure): {list(absent)[:5]}")

    negative_money = df[df["measure"].isin(["turnover", "purchases"]) & (df["value"] < 0)]
    if len(negative_money):
        raise NISRAValidationError(f"turnover or purchases has {len(negative_money)} negative values")

    wrong_sign_cv = df[(df["cv_pct"] < 0) & (df["value"] >= 0)]
    if len(wrong_sign_cv):
        raise NISRAValidationError(f"{len(wrong_sign_cv)} rows have a negative cv_pct with a non-negative value")

    with_interval = df.dropna(subset=["value", "ci_lower", "ci_upper"])
    below_lower = with_interval["value"] < with_interval["ci_lower"]
    above_upper = with_interval["value"] > with_interval["ci_upper"]
    outside = with_interval[below_lower | above_upper]
    if len(outside):
        raise NISRAValidationError(
            f"{len(outside)} rows have a value outside its confidence interval, e.g. {outside.head(3).to_dict('records')}"
        )

    orphan = df[df["value"].isna() & df[["ci_lower", "ci_upper", "cv_pct"]].notna().any(axis=1)]
    if len(orphan):
        raise NISRAValidationError(f"{len(orphan)} rows have an interval or CV but no value")

    logger.info("Validation passed: %d rows, years %d-%d", len(df), years[0], years[-1])
    return True
