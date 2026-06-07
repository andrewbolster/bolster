"""NISRA Cancer Waiting Times Module.

Provides access to Northern Ireland's cancer waiting times statistics,
measuring performance against key cancer treatment targets.

Cancer Waiting Time Targets:
    - 14-day: Urgent breast cancer referrals seen within 14 days
    - 31-day: Treatment started within 31 days of decision to treat
    - 62-day: Treatment started within 62 days of urgent GP referral

Data Coverage:
    - 31-day and 62-day by HSC Trust: April 2008 - Present (monthly)
    - 31-day and 62-day by Tumour Site: December 2008 - Present (monthly)
    - 14-day Breast by HSC Trust: April 2008 - Present (monthly)
    - Breast Cancer Referrals: April 2016 - Present (monthly)

HSC Trusts:
    - Belfast, Northern, South Eastern, Southern, Western

Tumour Sites:
    - Brain/Central Nervous System, Breast Cancer, Gynaecological Cancers,
    - Haematological Cancers, Head/Neck Cancer, Lower Gastrointestinal Cancer,
    - Lung Cancer, Other, Sarcomas, Skin Cancers, Upper Gastrointestinal Cancer,
    - Urological Cancer

Original data source:
    https://www.health-ni.gov.uk/articles/cancer-waiting-times

Data is fetched from the NISRA PxStat API using the following matrices:
    - CWT31HSCT: 31-day waiting times by HSC Trust
    - CWT62HSCT: 62-day waiting times by HSC Trust
    - CWTBCHSCT: 14-day breast cancer waiting times by HSC Trust
    - BCREFHSCT: Breast cancer referrals by HSC Trust
    - CWT31TUMOUR: 31-day waiting times by tumour site
    - CWT62TUMOUR: 62-day waiting times by tumour site

Example:
    >>> from bolster.data_sources.nisra import cancer_waiting_times as cwt
    >>> df = cwt.get_latest_31_day_by_trust()
    >>> sorted(df.columns.tolist())
    ['date', 'month', 'over_target', 'performance_rate', 'total', 'trust', 'within_target', 'year']

    >>> df_tumour = cwt.get_latest_62_day_by_tumour()
    >>> 'tumour_site' in df_tumour.columns
    True
"""

import logging

import pandas as pd

from .pxstat import read_dataset

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_31_TRUST = "CWT31HSCT"
_MATRIX_62_TRUST = "CWT62HSCT"
_MATRIX_14_BREAST = "CWTBCHSCT"
_MATRIX_BREAST_REF = "BCREFHSCT"
_MATRIX_31_TUMOUR = "CWT31TUMOUR"
_MATRIX_62_TUMOUR = "CWT62TUMOUR"

# STATISTIC values in the API
_STAT_TOTAL = "ALL"
_STAT_WITHIN_31 = "WITHIN31DAYS"
_STAT_OVER_31 = "OVER31DAYS"
_STAT_WITHIN_62 = "WITHIN62DAYS"
_STAT_OVER_62 = "OVER62DAYS"
_STAT_WITHIN_14 = "WITHIN14DAYS"
_STAT_OVER_14 = "OVER14DAYS"
_STAT_ROUTINE = "ROUTINE"
_STAT_URGENT = "URGENT"

# NI-wide aggregate code — exclude from trust/tumour-level outputs
_NI_CODE = "N92000002"


def _parse_tlist_month(tlist: str) -> pd.Timestamp:
    """Parse a TLIST(M1) value like '2008M04' into a pandas Timestamp.

    Args:
        tlist: String in the format 'YYYYMmm' (e.g. '2008M04').

    Returns:
        pandas Timestamp for the first day of that month.
    """
    year, month = tlist.split("M")
    return pd.Timestamp(year=int(year), month=int(month), day=1)


def _pivot_hsct(matrix: str, stat_within: str, stat_over: str) -> pd.DataFrame:
    """Fetch an HSCT wait-time matrix and pivot STATISTIC rows to columns.

    Args:
        matrix: PxStat matrix code.
        stat_within: STATISTIC value for the within-target count.
        stat_over: STATISTIC value for the over-target count.

    Returns:
        DataFrame with columns: date, year, month, trust, within_target,
        over_target, total, performance_rate.  Northern Ireland aggregate
        rows are excluded.
    """
    raw = read_dataset(matrix)

    # Exclude NI-wide aggregate; keep individual trusts only
    raw = raw[raw["HSCT"] != _NI_CODE].copy()

    trust_col = "Health and Social Care Trust"
    month_col = "TLIST(M1)"

    pivot = raw.pivot_table(
        index=[month_col, trust_col],
        columns="STATISTIC",
        values="VALUE",
        aggfunc="first",
    ).reset_index()

    pivot.columns.name = None
    pivot = pivot.rename(
        columns={
            month_col: "tlist",
            trust_col: "trust",
            _STAT_TOTAL: "total",
            stat_within: "within_target",
            stat_over: "over_target",
        }
    )

    pivot["date"] = pivot["tlist"].apply(_parse_tlist_month)
    pivot["year"] = pivot["date"].dt.year
    pivot["month"] = pivot["date"].dt.strftime("%B")
    pivot["within_target"] = pd.to_numeric(pivot["within_target"], errors="coerce")
    pivot["over_target"] = pd.to_numeric(pivot["over_target"], errors="coerce")
    pivot["total"] = pd.to_numeric(pivot["total"], errors="coerce")
    pivot["performance_rate"] = pivot["within_target"] / pivot["total"]

    return (
        pivot[["date", "year", "month", "trust", "within_target", "over_target", "total", "performance_rate"]]
        .sort_values(["date", "trust"])
        .reset_index(drop=True)
    )


def _pivot_tumour(matrix: str, stat_within: str, stat_over: str) -> pd.DataFrame:
    """Fetch a tumour-site wait-time matrix and pivot STATISTIC rows to columns.

    Args:
        matrix: PxStat matrix code.
        stat_within: STATISTIC value for the within-target count.
        stat_over: STATISTIC value for the over-target count.

    Returns:
        DataFrame with columns: date, year, month, tumour_site, within_target,
        over_target, total, performance_rate.  'All tumour sites' aggregate rows
        are excluded.
    """
    raw = read_dataset(matrix)

    site_col = "Site of Tumour"
    month_col = "TLIST(M1)"

    # Exclude the "All tumour sites" aggregate
    raw = raw[raw["TUMOURSITE"] != "ALL"].copy()

    pivot = raw.pivot_table(
        index=[month_col, site_col],
        columns="STATISTIC",
        values="VALUE",
        aggfunc="first",
    ).reset_index()

    pivot.columns.name = None
    pivot = pivot.rename(
        columns={
            month_col: "tlist",
            site_col: "tumour_site",
            _STAT_TOTAL: "total",
            stat_within: "within_target",
            stat_over: "over_target",
        }
    )

    pivot["date"] = pivot["tlist"].apply(_parse_tlist_month)
    pivot["year"] = pivot["date"].dt.year
    pivot["month"] = pivot["date"].dt.strftime("%B")
    pivot["within_target"] = pd.to_numeric(pivot["within_target"], errors="coerce")
    pivot["over_target"] = pd.to_numeric(pivot["over_target"], errors="coerce")
    pivot["total"] = pd.to_numeric(pivot["total"], errors="coerce")
    pivot["performance_rate"] = pivot["within_target"] / pivot["total"]

    return (
        pivot[["date", "year", "month", "tumour_site", "within_target", "over_target", "total", "performance_rate"]]
        .sort_values(["date", "tumour_site"])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Public data-fetching functions
# ---------------------------------------------------------------------------


def get_latest_31_day_by_trust(force_refresh: bool = False) -> pd.DataFrame:
    """Get 31-day waiting times by HSC Trust.

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: date, year, month, trust, within_target,
        over_target, total, performance_rate.
    """
    return _pivot_hsct(_MATRIX_31_TRUST, _STAT_WITHIN_31, _STAT_OVER_31)


def get_latest_31_day_by_tumour(force_refresh: bool = False) -> pd.DataFrame:
    """Get 31-day waiting times by Tumour Site.

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: date, year, month, tumour_site, within_target,
        over_target, total, performance_rate.
    """
    return _pivot_tumour(_MATRIX_31_TUMOUR, _STAT_WITHIN_31, _STAT_OVER_31)


def get_latest_62_day_by_trust(force_refresh: bool = False) -> pd.DataFrame:
    """Get 62-day waiting times by HSC Trust.

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: date, year, month, trust, within_target,
        over_target, total, performance_rate.

    Note:
        62-day data may contain fractional patient counts due to shared care
        arrangements between trusts.
    """
    return _pivot_hsct(_MATRIX_62_TRUST, _STAT_WITHIN_62, _STAT_OVER_62)


def get_latest_62_day_by_tumour(force_refresh: bool = False) -> pd.DataFrame:
    """Get 62-day waiting times by Tumour Site.

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: date, year, month, tumour_site, within_target,
        over_target, total, performance_rate.
    """
    return _pivot_tumour(_MATRIX_62_TUMOUR, _STAT_WITHIN_62, _STAT_OVER_62)


def get_latest_14_day_breast(force_refresh: bool = False) -> pd.DataFrame:
    """Get 14-day breast cancer waiting times by HSC Trust.

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: date, year, month, trust, within_target,
        over_target, total, performance_rate.
    """
    return _pivot_hsct(_MATRIX_14_BREAST, _STAT_WITHIN_14, _STAT_OVER_14)


def get_latest_breast_referrals(force_refresh: bool = False) -> pd.DataFrame:
    """Get breast cancer referrals by HSC Trust.

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: date, year, month, trust, total_referrals,
        urgent_referrals, urgent_rate.
    """
    raw = read_dataset(_MATRIX_BREAST_REF)

    # Exclude NI-wide aggregate
    raw = raw[raw["HSCT"] != _NI_CODE].copy()

    trust_col = "Health and Social Care Trust"
    month_col = "TLIST(M1)"

    pivot = raw.pivot_table(
        index=[month_col, trust_col],
        columns="STATISTIC",
        values="VALUE",
        aggfunc="first",
    ).reset_index()

    pivot.columns.name = None
    pivot = pivot.rename(
        columns={
            month_col: "tlist",
            trust_col: "trust",
            _STAT_TOTAL: "total_referrals",
            _STAT_URGENT: "urgent_referrals",
        }
    )

    pivot["date"] = pivot["tlist"].apply(_parse_tlist_month)
    pivot["year"] = pivot["date"].dt.year
    pivot["month"] = pivot["date"].dt.strftime("%B")
    pivot["total_referrals"] = pd.to_numeric(pivot["total_referrals"], errors="coerce")
    pivot["urgent_referrals"] = pd.to_numeric(pivot["urgent_referrals"], errors="coerce")
    pivot["urgent_rate"] = pivot["urgent_referrals"] / pivot["total_referrals"]

    return (
        pivot[["date", "year", "month", "trust", "total_referrals", "urgent_referrals", "urgent_rate"]]
        .sort_values(["date", "trust"])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Public combined function (named in the task brief)
# ---------------------------------------------------------------------------


def get_latest_cancer_waiting_times(
    target: str = "31-day",
    dimension: str = "trust",
    year: int | None = None,
    summary: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get cancer waiting times data for a given target and dimension.

    Args:
        target: Waiting time target — '31-day', '62-day', or '14-day'.
        dimension: Breakdown dimension — 'trust' or 'tumour' (tumour not
            available for 14-day).
        year: Optional year filter.  If None all years are returned.
        summary: If True return an annual performance summary aggregated
            across all groups instead of the full monthly series.
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with wait-time performance data.

    Raises:
        ValueError: If an unsupported target / dimension combination is given.
    """
    if target == "31-day" and dimension == "trust":
        df = get_latest_31_day_by_trust()
    elif target == "31-day" and dimension == "tumour":
        df = get_latest_31_day_by_tumour()
    elif target == "62-day" and dimension == "trust":
        df = get_latest_62_day_by_trust()
    elif target == "62-day" and dimension == "tumour":
        df = get_latest_62_day_by_tumour()
    elif target == "14-day" and dimension == "trust":
        df = get_latest_14_day_breast()
    else:
        raise ValueError(f"Unsupported combination: target={target!r}, dimension={dimension!r}")

    if year is not None:
        df = df[df["year"] == year].reset_index(drop=True)

    if summary:
        group_col = "trust" if "trust" in df.columns else "tumour_site"
        df = get_performance_summary_by_year(df, group_col)

    return df


# ---------------------------------------------------------------------------
# Helper / analysis functions (preserved from previous implementation)
# ---------------------------------------------------------------------------


def get_data_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Filter data for a specific year.

    Args:
        df: DataFrame with 'year' column.
        year: Year to filter for.

    Returns:
        Filtered DataFrame.
    """
    return df[df["year"] == year].reset_index(drop=True)


def get_performance_summary_by_year(df: pd.DataFrame, group_col: str = "trust") -> pd.DataFrame:
    """Calculate annual performance summary.

    Args:
        df: DataFrame with performance data.
        group_col: Column to group by ('trust' or 'tumour_site').

    Returns:
        DataFrame with annual summary statistics.
    """
    summary = (
        df.groupby(["year", group_col])
        .agg(
            total_patients=("total", "sum"),
            within_target=("within_target", "sum"),
            over_target=("over_target", "sum"),
            months_reported=("total", "count"),
        )
        .reset_index()
    )
    summary["performance_rate"] = summary["within_target"] / summary["total_patients"]
    return summary


def get_ni_wide_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate NI-wide performance (aggregated across all trusts/sites).

    Args:
        df: DataFrame with performance data.

    Returns:
        DataFrame with NI-wide monthly performance.
    """
    ni_wide = (
        df.groupby(["date", "year", "month"])
        .agg(
            within_target=("within_target", "sum"),
            over_target=("over_target", "sum"),
            total=("total", "sum"),
        )
        .reset_index()
    )
    ni_wide["performance_rate"] = ni_wide["within_target"] / ni_wide["total"]
    return ni_wide


def get_performance_trend(df: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    """Calculate rolling performance trend.

    Args:
        df: DataFrame with NI-wide performance data.
        window: Rolling window size in months (default: 12).

    Returns:
        DataFrame with rolling average performance.
    """
    df = df.sort_values("date").copy()
    df["rolling_performance"] = df["performance_rate"].rolling(window=window, min_periods=1).mean()
    return df


def get_tumour_site_ranking(df: pd.DataFrame, year: int = None) -> pd.DataFrame:
    """Rank tumour sites by performance.

    Args:
        df: DataFrame with tumour site data.
        year: Optional year to filter (default: all years).

    Returns:
        DataFrame ranked by performance (worst to best).
    """
    if year:
        df = df[df["year"] == year]

    ranking = (
        df.groupby("tumour_site")
        .agg(
            total_patients=("total", "sum"),
            within_target=("within_target", "sum"),
        )
        .reset_index()
    )
    ranking["performance_rate"] = ranking["within_target"] / ranking["total_patients"]
    ranking = ranking.sort_values("performance_rate", ascending=True)
    ranking["rank"] = range(1, len(ranking) + 1)
    return ranking


def validate_performance_data(df: pd.DataFrame) -> bool:  # pragma: no cover
    """Validate that performance data is internally consistent.

    Args:
        df: DataFrame with performance columns.

    Returns:
        True if validation passes.

    Raises:
        ValueError: If validation fails.

    Note:
        Rows with NaN values or zero totals are excluded from validation checks.
    """
    valid_df = df.dropna(subset=["within_target", "over_target", "total"])
    valid_df = valid_df[valid_df["total"] > 0]

    if len(valid_df) == 0:
        return True

    # Check within + over = total (with tolerance for fractional patients)
    total_check = abs(valid_df["within_target"] + valid_df["over_target"] - valid_df["total"]) < 1.0
    if not total_check.all():
        raise ValueError("within_target + over_target != total for some rows")

    # Check performance rate calculation
    expected_rate = valid_df["within_target"] / valid_df["total"]
    rate_check = abs(valid_df["performance_rate"] - expected_rate) < 0.001
    if not rate_check.all():
        raise ValueError("Performance rate calculation is incorrect")

    # Check performance rate is between 0 and 1
    valid_rates = valid_df["performance_rate"].replace([float("inf"), float("-inf")], float("nan")).dropna()
    if len(valid_rates) > 0 and not ((valid_rates >= 0) & (valid_rates <= 1)).all():
        raise ValueError("Performance rate outside 0-1 range")

    return True
