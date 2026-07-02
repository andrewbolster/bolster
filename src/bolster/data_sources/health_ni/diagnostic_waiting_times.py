"""NISRA Diagnostic Waiting Times Module.

Provides access to Northern Ireland's diagnostic waiting times statistics,
covering patients waiting for diagnostic tests across HSC Trusts, diagnostic
services, and categories of test.

Waiting Time Bands:
    - Total: All patients waiting (any duration)
    - 0–9 weeks: Patients waiting 0–9 weeks
    - >9 weeks: Patients waiting more than 9 weeks
    - >26 weeks: Patients waiting more than 26 weeks

Data Coverage:
    - Q4 2007/08 (quarter ending March 2008) to present
    - Quarterly frequency
    - 5 HSC Trusts: Belfast, Northern, South Eastern, Southern, Western
    - Categories: Imaging, Endoscopy, Physiological measurements (and 'All')
    - Individual diagnostic services (endoscopy, radiology, physiological, etc.)

HSC Trusts:
    Belfast, Northern, South Eastern, Southern, Western

Original data source:
    https://www.health-ni.gov.uk/articles/diagnostic-waiting-times

Data is fetched from the NISRA PxStat API using matrix ``DWT``.

Example:
    >>> from bolster.data_sources.nisra import diagnostic_waiting_times as dwt
    >>> df = dwt.get_latest_diagnostic_waiting_times()
    >>> sorted(df.columns.tolist())
    ['category', 'date', 'over_26_weeks', 'over_9_weeks', 'performance_rate', 'quarter', 'total_waiting', 'trust', 'within_9_weeks', 'year']
"""

import logging

import pandas as pd

from bolster.data_sources.nisra.pxstat import (
    PxStatError,  # noqa: F401
    read_dataset,
)

logger = logging.getLogger(__name__)

# PxStat matrix code
_MATRIX = "DWT"

# STATISTIC code values in the API
_STAT_TOTAL = "ALL"  # Total patients waiting (any duration)
_STAT_0_9 = "1"  # Patients waiting 0–9 weeks
_STAT_OVER_9 = "2"  # Patients waiting >9 weeks
_STAT_OVER_26 = "3"  # Patients waiting >26 weeks

# NI-wide aggregate — exclude from trust-level outputs
_NI_CODE = "N92000002"

# Codes meaning "all" in their dimension (to aggregate across)
_ALL_DIAG = "ALL"  # All diagnostic services
_ALL_COT = "ALL"  # All categories of test

EXPECTED_TRUSTS = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}


def _parse_tlist_quarter(tlist: str) -> pd.Timestamp:
    """Parse a TLIST(Q1) value like '2007/08Q4' into a pandas Timestamp.

    The quarter ending date is used: Q1→June, Q2→September, Q3→December,
    Q4→March of the *following* calendar year.

    Args:
        tlist: String in format 'YYYY/YYQn' (e.g. '2007/08Q4').

    Returns:
        pandas Timestamp for the last day of that quarter.
    """
    # Format: '2007/08Q4' → financial year 2007/08, quarter 4 (Jan–Mar 2008)
    # Quarter end months: Q1→Jun, Q2→Sep, Q3→Dec, Q4→Mar
    fy_part, q_part = tlist.split("Q")
    start_year = int(fy_part.split("/")[0])
    quarter = int(q_part)
    # Map financial year quarters to calendar year/month
    quarter_end = {1: (start_year, 6), 2: (start_year, 9), 3: (start_year, 12), 4: (start_year + 1, 3)}
    cal_year, cal_month = quarter_end[quarter]
    return pd.Timestamp(year=cal_year, month=cal_month, day=1)


def get_latest_diagnostic_waiting_times(
    trust: str | None = None,
    year: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get diagnostic waiting times by HSC Trust and category of test.

    Returns aggregate-level data (all diagnostic services combined) pivoted
    so that each row represents one trust/quarter with waiting band columns.

    Args:
        trust: Optional HSC Trust name to filter (e.g. ``"Belfast"``).  If
            ``None`` all trusts are returned (NI-wide aggregate excluded).
        year: Optional calendar year filter.  If ``None`` all years returned.
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns:

        - ``date``: Timestamp (quarter end date)
        - ``quarter``: Quarter label (e.g. ``"2023/24Q1"``)
        - ``year``: Calendar year of the quarter end
        - ``trust``: HSC Trust name
        - ``category``: Category of test (``"All categories of test"`` for
          this aggregate view)
        - ``total_waiting``: Total patients waiting (any duration)
        - ``within_9_weeks``: Patients waiting 0–9 weeks
        - ``over_9_weeks``: Patients waiting >9 weeks
        - ``over_26_weeks``: Patients waiting >26 weeks

    Example:
        >>> df = get_latest_diagnostic_waiting_times()
        >>> "Belfast" in df["trust"].values
        True
        >>> "total_waiting" in df.columns
        True
    """
    raw = read_dataset(_MATRIX)

    # Convert STATISTIC to str for consistent comparison (mixed int/str in source)
    raw["STATISTIC"] = raw["STATISTIC"].astype(str)

    # Keep only NI Trust-level rows (exclude NI-wide aggregate)
    raw = raw[raw["HSCT"] != _NI_CODE].copy()

    # Keep only aggregate rows: all diagnostic services + all categories of test
    raw = raw[(raw["DIAG"] == _ALL_DIAG) & (raw["COT"] == _ALL_COT)].copy()

    trust_col = "Health and Social Care Trust"
    cot_col = "Category of Test"
    quarter_col = "TLIST(Q1)"

    pivot = raw.pivot_table(
        index=[quarter_col, trust_col, cot_col],
        columns="STATISTIC",
        values="VALUE",
        aggfunc="first",
    ).reset_index()
    pivot.columns.name = None

    # Rename columns to friendly names
    rename_map = {
        quarter_col: "quarter",
        trust_col: "trust",
        cot_col: "category",
        _STAT_TOTAL: "total_waiting",
        _STAT_0_9: "within_9_weeks",
        _STAT_OVER_9: "over_9_weeks",
        _STAT_OVER_26: "over_26_weeks",
    }
    pivot = pivot.rename(columns=rename_map)

    # Parse dates
    pivot["date"] = pivot["quarter"].apply(_parse_tlist_quarter)
    pivot["year"] = pivot["date"].dt.year

    # Coerce numeric columns
    for col in ("total_waiting", "within_9_weeks", "over_9_weeks", "over_26_weeks"):
        if col in pivot.columns:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

    # Derive performance rate: proportion seen within 9 weeks
    pivot["performance_rate"] = pivot["within_9_weeks"] / pivot["total_waiting"]

    # Apply optional filters
    if trust is not None:
        pivot = pivot[pivot["trust"] == trust].reset_index(drop=True)

    if year is not None:
        pivot = pivot[pivot["year"] == year].reset_index(drop=True)

    col_order = [
        "date",
        "quarter",
        "year",
        "trust",
        "category",
        "total_waiting",
        "within_9_weeks",
        "over_9_weeks",
        "over_26_weeks",
        "performance_rate",
    ]
    return pivot[col_order].sort_values(["date", "trust"]).reset_index(drop=True)


def validate_diagnostic_waiting_times(df: pd.DataFrame) -> bool:
    """Validate that diagnostic waiting times data is internally consistent.

    Checks that required columns are present, values are non-negative,
    performance rates are within 0–1, and there is sufficient data.

    Args:
        df: DataFrame as returned by :func:`get_latest_diagnostic_waiting_times`.

    Returns:
        ``True`` if all validation checks pass.

    Raises:
        ValueError: If any validation check fails.
    """
    required_columns = {
        "date",
        "quarter",
        "year",
        "trust",
        "category",
        "total_waiting",
        "within_9_weeks",
        "over_9_weeks",
        "over_26_weeks",
        "performance_rate",
    }
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if df.empty:
        raise ValueError("DataFrame is empty")

    if len(df) < 5:
        raise ValueError(f"DataFrame has too few records: {len(df)}")

    valid = df.dropna(subset=["total_waiting", "within_9_weeks", "over_9_weeks"]).copy()

    if len(valid) > 0:
        # Non-negative patient counts
        for col in ("total_waiting", "within_9_weeks", "over_9_weeks", "over_26_weeks"):
            col_valid = valid[col].dropna()
            if len(col_valid) > 0 and (col_valid < 0).any():
                raise ValueError(f"Negative values found in column '{col}'")

        # Performance rate within 0–1
        valid_rates = valid["performance_rate"].replace([float("inf"), float("-inf")], float("nan")).dropna()
        if len(valid_rates) > 0 and not ((valid_rates >= 0) & (valid_rates <= 1)).all():
            raise ValueError("performance_rate outside [0, 1] range")

    return True
