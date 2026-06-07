"""NISRA Disease Prevalence Module.

Provides access to Northern Ireland's disease prevalence statistics from
GP clinical disease registers (Quality & Outcomes Framework, QOF).
Data are released annually after National Prevalence Day.

Data Coverage:
    - Financial years 2017/18 to present (extended annually)
    - NI-level: registered patients per disease register and prevalence
      per 1,000 patients
    - By Local Government District (LGD): same metrics per council
    - By HSC Trust: same metrics per Trust

Disease Registers (17):
    Asthma, Atrial Fibrillation, Cancer, Chronic Kidney Disease,
    Chronic Obstructive Pulmonary Disease, Coronary Heart Disease,
    Dementia, Depression, Diabetes Mellitus, Heart Failure 1,
    Heart Failure 3, Hypertension, Mental Health,
    Non-Diabetic Hyperglycaemia, Osteoporosis, Rheumatoid Arthritis,
    Stroke & TIA

Original data sources:
    https://www.opendatani.gov.uk/dataset/gp-practice-reference-file
    https://www.health-ni.gov.uk/topics/health-statistics/disease-prevalence

Data is fetched from the NISRA PxStat API using the following matrices:
    - DISPREVNI: NI-wide annual prevalence by disease
    - DISPREVLGD: Annual prevalence by LGD and disease
    - DISPREVHSCT: Annual prevalence by HSC Trust and disease

Update Frequency:
    Annual, approximately May of the following calendar year.

Example:
    >>> from bolster.data_sources.nisra import disease_prevalence as dp
    >>> df = dp.get_latest_disease_prevalence()
    >>> 'registered_patients' in df.columns
    True
    >>> 'prevalence_per_1000' in df.columns
    True
"""

import logging

import pandas as pd

from ._base import NISRAValidationError
from .pxstat import read_dataset

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_NI = "DISPREVNI"
_MATRIX_LGD = "DISPREVLGD"
_MATRIX_HSCT = "DISPREVHSCT"

# STATISTIC values
_STAT_NUMREG = "Numreg"
_STAT_PREV = "Rawprevalence1000"


def _pivot_prevalence(raw: pd.DataFrame, group_col: str, output_col: str) -> pd.DataFrame:
    """Pivot a disease prevalence matrix to wide format.

    Args:
        raw: Raw DataFrame from read_dataset().
        group_col: Column name for the geographic dimension (e.g. 'Disease').
        output_col: Name for the geographic dimension in the output.

    Returns:
        DataFrame with columns: financial_year, year, {output_col}, disease,
        registered_patients, prevalence_per_1000.
    """
    fy_col = "Financial Year"
    disease_col = "Disease"

    pivot = raw.pivot_table(
        index=[fy_col, group_col, disease_col],
        columns="STATISTIC",
        values="VALUE",
        aggfunc="first",
    ).reset_index()
    pivot.columns.name = None

    pivot = pivot.rename(
        columns={
            fy_col: "financial_year",
            group_col: output_col,
            disease_col: "disease",
            _STAT_NUMREG: "registered_patients",
            _STAT_PREV: "prevalence_per_1000",
        }
    )

    for col in ("registered_patients", "prevalence_per_1000"):
        if col in pivot.columns:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

    pivot["year"] = pivot["financial_year"].apply(lambda fy: int(str(fy).split("/")[0]))

    col_order = ["financial_year", "year", output_col, "disease", "registered_patients", "prevalence_per_1000"]
    return (
        pivot[[c for c in col_order if c in pivot.columns]]
        .sort_values(["financial_year", output_col, "disease"])
        .reset_index(drop=True)
    )


def get_ni_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Get NI-wide annual disease prevalence (DISPREVNI).

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: financial_year, year, disease,
        registered_patients, prevalence_per_1000.
    """
    raw = read_dataset(_MATRIX_NI)
    # DISPREVNI has no geographic dimension — pivot directly
    fy_col = "Financial Year"
    disease_col = "Disease"

    pivot = raw.pivot_table(
        index=[fy_col, disease_col],
        columns="STATISTIC",
        values="VALUE",
        aggfunc="first",
    ).reset_index()
    pivot.columns.name = None

    pivot = pivot.rename(
        columns={
            fy_col: "financial_year",
            disease_col: "disease",
            _STAT_NUMREG: "registered_patients",
            _STAT_PREV: "prevalence_per_1000",
        }
    )

    for col in ("registered_patients", "prevalence_per_1000"):
        if col in pivot.columns:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

    pivot["year"] = pivot["financial_year"].apply(lambda fy: int(str(fy).split("/")[0]))

    col_order = ["financial_year", "year", "disease", "registered_patients", "prevalence_per_1000"]
    return (
        pivot[[c for c in col_order if c in pivot.columns]]
        .sort_values(["financial_year", "disease"])
        .reset_index(drop=True)
    )


def get_lgd_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Get annual disease prevalence by Local Government District (DISPREVLGD).

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: financial_year, year, lgd, disease,
        registered_patients, prevalence_per_1000.
    """
    raw = read_dataset(_MATRIX_LGD)
    return _pivot_prevalence(raw, "Local Government District", "lgd")


def get_hsct_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Get annual disease prevalence by HSC Trust (DISPREVHSCT).

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.

    Returns:
        DataFrame with columns: financial_year, year, trust, disease,
        registered_patients, prevalence_per_1000.
    """
    raw = read_dataset(_MATRIX_HSCT)
    return _pivot_prevalence(raw, "Health and Social Care Trust", "trust")


def get_latest_disease_prevalence(
    force_refresh: bool = False,
    level: str = "ni",
    lcg: str | None = None,
) -> pd.DataFrame:
    """Get the latest NI disease prevalence data.

    Fetches data from the NISRA PxStat API.  The ``level`` parameter
    controls geographic granularity; ``lcg`` filters to a specific
    Local Government District (when level='lgd').

    Args:
        force_refresh: Accepted for API compatibility but ignored; the PxStat
            API always returns the latest data without caching.
        level: Geographic level — 'ni' for NI-wide (default), 'lgd' for
            Local Government District breakdown, or 'trust' for HSC Trust.
        lcg: Optional LGD name filter (used when level='lgd').  If provided,
            only rows for that LGD are returned.

    Returns:
        DataFrame with columns: financial_year, year, disease,
        registered_patients, prevalence_per_1000.
        When level='lgd', also includes an 'lgd' column.
        When level='trust', also includes a 'trust' column.

    Raises:
        ValueError: If level is not one of 'ni', 'lgd', or 'trust'.

    Example:
        >>> df = get_latest_disease_prevalence()
        >>> 'registered_patients' in df.columns
        True
        >>> 'prevalence_per_1000' in df.columns
        True
    """
    if level == "ni":
        df = get_ni_prevalence()
    elif level == "lgd":
        df = get_lgd_prevalence()
        if lcg is not None:
            df = df[df["lgd"] == lcg].reset_index(drop=True)
    elif level == "trust":
        df = get_hsct_prevalence()
    else:
        raise ValueError(f"level must be 'ni', 'lgd', or 'trust', got {level!r}")

    return df


def validate_disease_prevalence(df: pd.DataFrame, level: str = "ni") -> bool:
    """Validate the disease prevalence DataFrame for internal consistency.

    Args:
        df: DataFrame as returned by :func:`get_latest_disease_prevalence`.
        level: Validation mode — 'ni' (default) or 'lgd'/'trust' for
            geographic breakdowns.  Validates the 'gp' level alias for
            backward compatibility (treated same as 'lgd').

    Returns:
        True if all checks pass.

    Raises:
        NISRAValidationError: Describing the first failing check.
        ValueError: If level is not a recognised value.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     "year": [2017], "financial_year": ["2017/18"],
        ...     "disease": ["Hypertension"],
        ...     "registered_patients": [184824.0],
        ...     "prevalence_per_1000": [102.9],
        ... })
        >>> validate_disease_prevalence(df)
        True
    """
    if level not in ("ni", "lgd", "trust", "gp"):
        raise ValueError(f"level must be 'ni', 'lgd', 'trust', or 'gp', got {level!r}")

    required = {"financial_year", "year", "disease", "registered_patients", "prevalence_per_1000"}

    # Accept 'register' as alias for 'disease' (backward compat with old Excel-based module)
    if "register" in df.columns and "disease" not in df.columns:
        df = df.rename(columns={"register": "disease"})

    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if df["disease"].nunique() < 5:
        raise NISRAValidationError(f"Too few disease registers: expected ≥ 5, got {df['disease'].nunique()}")

    if level == "ni" and df["financial_year"].nunique() < 5:
        raise NISRAValidationError(f"Too few financial years: expected ≥ 5, got {df['financial_year'].nunique()}")
    if level == "gp" and df["financial_year"].nunique() < 3:
        # Backward-compat: treat gp level same as a geographic breakdown
        raise NISRAValidationError(f"Too few financial years: expected ≥ 3, got {df['financial_year'].nunique()}")

    prev = df["prevalence_per_1000"].dropna()
    if len(prev) > 0:
        if (prev < 0).any():
            bad = prev[prev < 0]
            raise NISRAValidationError(f"prevalence_per_1000 has {len(bad)} negative values: {bad.head().tolist()}")
        if (prev > 1000).any():
            bad = prev[prev > 1000]
            raise NISRAValidationError(f"prevalence_per_1000 has {len(bad)} values above 1000: {bad.head().tolist()}")

    patients = df["registered_patients"].dropna()
    if len(patients) > 0 and (patients < 0).any():
        bad = patients[patients < 0]
        raise NISRAValidationError(f"registered_patients has {len(bad)} negative values: {bad.head().tolist()}")

    return True
