"""Northern Ireland Planning Activity Statistics.

Annual planning application statistics for Northern Ireland, published by
the Department for Infrastructure (DfI). Provides counts of planning
applications received, decided, approved and withdrawn, broken down by
Local Government District or NI-wide totals.

Data is fetched from the NISRA PxStat API. Coverage begins 2015/16.

Original data source:
    https://www.infrastructure-ni.gov.uk/articles/planning-activity-statistics

PxStat matrices used:
    - PALGD: Annual planning applications by Local Government District
    - PAPLGD: Annual approved planning applications by LGD and application type
    - PADAA: Annual planning applications by Assembly Area

Update Frequency:
    Annual (financial year April-March).

Geographic Coverage:
    Northern Ireland - whole-country totals plus the 11 local council areas
    (Antrim and Newtownabbey, Ards and North Down, Armagh City, Banbridge and
    Craigavon, Belfast, Causeway Coast and Glens, Derry City and Strabane,
    Fermanagh and Omagh, Lisburn and Castlereagh, Mid and East Antrim,
    Mid Ulster, Newry, Mourne and Down).

Example:
    >>> from bolster.data_sources.nisra import planning_statistics
    >>> df = planning_statistics.get_latest_data()
    >>> 'applications_received' in df.columns
    True
"""

from __future__ import annotations

import logging

import pandas as pd

from ._base import NISRAValidationError
from .pxstat import read_dataset

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_LGD = "PALGD"
_MATRIX_APPROVED_LGD = "PAPLGD"
_MATRIX_ASSEMBLY_AREA = "PADAA"

# Application status codes in PALGD
_STATUS_RECEIVED = "Applications received"
_STATUS_DECIDED = "Applications decided"
_STATUS_APPROVED = "Applications approved"
_STATUS_WITHDRAWN = "Applications withdrawn"

# Metric codes in PADAA (API returns integers after pivot on STATISTIC column)
_STAT_RECEIVED = 1
_STAT_DECIDED = 2
_STAT_APPROVED = 3
_STAT_APPROVAL_RATE = 4
_STAT_WITHDRAWN = 5

# NI-wide aggregate code — exclude from council/area outputs
_NI_CODE = "N92000002"

_VALID_QUARTERS = {"Q1", "Q2", "Q3", "Q4"}


def _parse_financial_year_to_date(financial_year: str) -> pd.Timestamp:
    """Convert a financial year string like '2024/25' to a Timestamp.

    Returns the first day of the financial year (April 1).

    Args:
        financial_year: Financial year string like '2024/25'.

    Returns:
        Timestamp for April 1 of the start year.

    Example:
        >>> _parse_financial_year_to_date("2024/25")
        Timestamp('2024-04-01 00:00:00')
    """
    start_year = int(financial_year.split("/")[0])
    return pd.Timestamp(year=start_year, month=4, day=1)


def parse_planning_by_lgd(force_refresh: bool = False) -> pd.DataFrame:
    """Parse annual planning applications by Local Government District (PALGD).

    Args:
        force_refresh: Accepted for API compatibility but ignored.

    Returns:
        DataFrame with columns: financial_year, date, year, council,
        applications_received, applications_decided, applications_approved,
        applications_withdrawn, approval_rate.
        The NI-wide aggregate row (council='Northern Ireland') is included.
    """
    raw = read_dataset(_MATRIX_LGD)

    lgd_col = "Local Government District"
    fy_col = "Financial year"
    status_col = "Application status"

    pivot = raw.pivot_table(
        index=[fy_col, lgd_col],
        columns=status_col,
        values="VALUE",
        aggfunc="first",
    ).reset_index()
    pivot.columns.name = None

    pivot = pivot.rename(
        columns={
            fy_col: "financial_year",
            lgd_col: "council",
            _STATUS_RECEIVED: "applications_received",
            _STATUS_DECIDED: "applications_decided",
            _STATUS_APPROVED: "applications_approved",
            _STATUS_WITHDRAWN: "applications_withdrawn",
        }
    )

    for col in ("applications_received", "applications_decided", "applications_approved", "applications_withdrawn"):
        if col in pivot.columns:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

    pivot["date"] = pivot["financial_year"].apply(_parse_financial_year_to_date)
    pivot["year"] = pivot["date"].dt.year

    # Compute approval rate from available columns
    if "applications_decided" in pivot.columns and "applications_approved" in pivot.columns:
        decided = pivot["applications_decided"].replace(0, float("nan"))
        pivot["approval_rate"] = (pivot["applications_approved"] / decided).round(4)
    else:
        pivot["approval_rate"] = float("nan")

    col_order = [
        "financial_year",
        "date",
        "year",
        "council",
        "applications_received",
        "applications_decided",
        "applications_approved",
        "applications_withdrawn",
        "approval_rate",
    ]
    return (
        pivot[[c for c in col_order if c in pivot.columns]]
        .sort_values(["financial_year", "council"])
        .reset_index(drop=True)
    )


def parse_planning_by_assembly_area(force_refresh: bool = False) -> pd.DataFrame:
    """Parse annual planning applications by Assembly Area (PADAA).

    Args:
        force_refresh: Accepted for API compatibility but ignored.

    Returns:
        DataFrame with columns: financial_year, date, year, assembly_area,
        applications_received, applications_decided, applications_approved,
        applications_withdrawn, approval_rate.
        The NI-wide aggregate row is included.
    """
    raw = read_dataset(_MATRIX_ASSEMBLY_AREA)

    aa_col = "Assembly Area"
    fy_col = "Financial year"
    stat_col = "STATISTIC"

    pivot = raw.pivot_table(
        index=[fy_col, aa_col],
        columns=stat_col,
        values="VALUE",
        aggfunc="first",
    ).reset_index()
    pivot.columns.name = None

    rename_map = {
        fy_col: "financial_year",
        aa_col: "assembly_area",
        _STAT_RECEIVED: "applications_received",
        _STAT_DECIDED: "applications_decided",
        _STAT_APPROVED: "applications_approved",
        _STAT_APPROVAL_RATE: "approval_rate_pct",
        _STAT_WITHDRAWN: "applications_withdrawn",
    }
    pivot = pivot.rename(columns={k: v for k, v in rename_map.items() if k in pivot.columns})

    for col in ("applications_received", "applications_decided", "applications_approved", "applications_withdrawn"):
        if col in pivot.columns:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

    pivot["date"] = pivot["financial_year"].apply(_parse_financial_year_to_date)
    pivot["year"] = pivot["date"].dt.year

    if "approval_rate_pct" in pivot.columns:
        pivot["approval_rate"] = pd.to_numeric(pivot["approval_rate_pct"], errors="coerce") / 100
    else:
        pivot["approval_rate"] = float("nan")

    col_order = [
        "financial_year",
        "date",
        "year",
        "assembly_area",
        "applications_received",
        "applications_decided",
        "applications_approved",
        "applications_withdrawn",
        "approval_rate",
    ]
    return (
        pivot[[c for c in col_order if c in pivot.columns]]
        .sort_values(["financial_year", "assembly_area"])
        .reset_index(drop=True)
    )


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and return NI-wide annual planning applications (all LGDs).

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame from :func:`parse_planning_by_lgd` with all councils
        and NI-wide totals.

    Example:
        >>> df = get_latest_data()
        >>> 'applications_received' in df.columns
        True
    """
    return parse_planning_by_lgd()


def get_latest_council_data(force_refresh: bool = False) -> pd.DataFrame:
    """Return council-area planning applications (excludes NI aggregate).

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with one row per (financial_year, council), excluding the
        NI-wide total row.

    Example:
        >>> df = get_latest_council_data()
        >>> 'council' in df.columns
        True
    """
    df = parse_planning_by_lgd()
    return df[df["council"] != "Northern Ireland"].reset_index(drop=True)


def get_latest_planning_statistics(
    dimension: str = "ni",
    financial_year: str | None = None,
    summary: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get planning application statistics for a given dimension.

    Args:
        dimension: Breakdown dimension — 'ni' for NI-wide total, 'council'
            for LGD breakdown, or 'assembly' for Assembly Area breakdown.
        financial_year: Optional financial year filter (e.g. '2024/25').
            If None, all available years are returned.
        summary: If True, return a summary aggregated across all financial
            years for each area.
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with planning application counts and approval rate.

    Raises:
        ValueError: If an unsupported dimension is given.
    """
    if dimension == "ni":
        df = parse_planning_by_lgd()
        df = df[df["council"] == "Northern Ireland"].reset_index(drop=True)
    elif dimension == "council":
        df = get_latest_council_data()
    elif dimension == "assembly":
        df = parse_planning_by_assembly_area()
        df = df[df["assembly_area"] != "Northern Ireland"].reset_index(drop=True)
    else:
        raise ValueError(f"Unsupported dimension: {dimension!r}. Use 'ni', 'council', or 'assembly'.")

    if financial_year is not None:
        df = df[df["financial_year"] == financial_year].reset_index(drop=True)

    if summary:
        df = get_council_summary(df)

    return df


def validate_data(df: pd.DataFrame) -> bool:
    """Validate an annual planning applications DataFrame.

    Args:
        df: DataFrame from :func:`get_latest_data` or
            :func:`parse_planning_by_lgd`.

    Returns:
        True if all checks pass.

    Raises:
        NISRAValidationError: If the DataFrame is empty, missing required
            columns, has implausible values, or has too short a time series.

    Example:
        >>> df = get_latest_data()
        >>> validate_data(df)
        True
    """
    if df is None or df.empty:
        raise NISRAValidationError("Planning DataFrame is empty")

    required = {
        "financial_year",
        "applications_received",
        "applications_decided",
        "applications_approved",
        "applications_withdrawn",
        "approval_rate",
    }
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < 5:
        raise NISRAValidationError(f"Too few records ({len(df)}); expected 5+ annual records")

    for col in ("applications_received", "applications_decided", "applications_approved"):
        vals = df[col].dropna()
        if (vals < 0).any():
            raise NISRAValidationError(f"Negative values found in {col}")
        if (vals > 500_000).any():
            raise NISRAValidationError(f"Implausibly high values in {col} (>500,000)")

    rates = df["approval_rate"].dropna()
    if ((rates < 0) | (rates > 1.0001)).any():
        raise NISRAValidationError("approval_rate outside the [0, 1] range")

    return True


def get_annual_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a DataFrame to annual (financial-year) totals across all areas.

    Args:
        df: DataFrame from :func:`get_latest_data` (may include council breakdown).

    Returns:
        DataFrame with one row per financial year and columns:
        financial_year, applications_received, applications_decided,
        applications_approved, applications_withdrawn, approval_rate.

    Example:
        >>> df = get_latest_data()
        >>> annual = get_annual_totals(df)
        >>> 'applications_received' in annual.columns
        True
    """
    # If NI-wide row is present, use it directly to avoid double-counting
    if "council" in df.columns and "Northern Ireland" in df["council"].values:
        ni_df = df[df["council"] == "Northern Ireland"].copy()
        return ni_df[
            [
                "financial_year",
                "applications_received",
                "applications_decided",
                "applications_approved",
                "applications_withdrawn",
                "approval_rate",
            ]
        ].reset_index(drop=True)

    # Otherwise aggregate
    grouped = df.groupby("financial_year", sort=True).agg(
        applications_received=("applications_received", "sum"),
        applications_decided=("applications_decided", "sum"),
        applications_approved=("applications_approved", "sum"),
        applications_withdrawn=("applications_withdrawn", "sum"),
    )
    decided = grouped["applications_decided"].replace(0, float("nan"))
    grouped["approval_rate"] = (grouped["applications_approved"] / decided).round(4)
    return grouped.reset_index()[
        [
            "financial_year",
            "applications_received",
            "applications_decided",
            "applications_approved",
            "applications_withdrawn",
            "approval_rate",
        ]
    ]


def get_council_summary(council_df: pd.DataFrame, financial_year: str | None = None) -> pd.DataFrame:
    """Summarise council-area data by council across all (or one) financial year.

    Args:
        council_df: DataFrame from :func:`get_latest_council_data`.
        financial_year: Optional financial year to filter to
            (e.g. '2024/25'). If None, summarises across all available years.

    Returns:
        DataFrame with one row per council, sorted by
        applications_received descending.

    Example:
        >>> council_df = get_latest_council_data()
        >>> summary = get_council_summary(council_df, financial_year='2024/25')
        >>> 'council' in summary.columns
        True
    """
    df = council_df
    if financial_year is not None:
        df = df[df["financial_year"] == financial_year]

    if "council" not in df.columns:
        return df

    grouped = df.groupby("council", sort=False).agg(
        applications_received=("applications_received", "sum"),
        applications_decided=("applications_decided", "sum"),
        applications_approved=("applications_approved", "sum"),
        applications_withdrawn=("applications_withdrawn", "sum"),
    )
    decided = grouped["applications_decided"].replace(0, pd.NA)
    grouped["approval_rate"] = (grouped["applications_approved"] / decided).round(4)
    return grouped.reset_index().sort_values("applications_received", ascending=False).reset_index(drop=True)
