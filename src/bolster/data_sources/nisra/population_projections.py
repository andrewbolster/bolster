"""NISRA Population Projections for Northern Ireland.

Provides access to official NISRA population projections with demographic breakdowns
by year, age, sex, and projection variant.

NI-level projections (2024-based, 2024-2074) are served via the PxStat API.
LGD sub-area projections are not yet available via PxStat and remain Excel-based.

Data Source:
    **PxStat API** (NI-level, used by this module):
        https://ws-data.nisra.gov.uk/public/api.restful/PxStat.Data.Cube_API.ReadDataset/{MATRIX}/CSV/1.0/en

    Matrix codes:
        - ``PPMY02T01``: NI projections by single year of age (0-90+) and sex — principal + variants
        - ``PPMY02T02``: NI projections by 5-year age bands and sex — principal only
        - ``PPMY02T03``: Variant projections (high/low fertility, life expectancy, migration)

    **Original publication pages** (for reference and LGD projections):
        - Principal: https://www.nisra.gov.uk/publications/2024-based-population-projections-northern-ireland
        - Variants: https://www.nisra.gov.uk/publications/2024-based-population-projections-northern-ireland-variant-projections
        - LGD sub-areas: https://www.nisra.gov.uk/publications/2022-based-population-projections-areas-within-northern-ireland

Update Frequency: Biennial (NI-level)
Geographic Coverage: Northern Ireland overall (LGD projections not yet in PxStat)
Projection Horizon: 2024-2074 (NI-level via API)

Example:
    >>> from bolster.data_sources.nisra import population_projections
    >>> df = population_projections.get_latest_projections()
    >>> 'population' in df.columns
    True
    >>> df_decade = population_projections.get_latest_projections(
    ...     start_year=2025,
    ...     end_year=2035
    ... )
    >>> len(df_decade) > 0
    True
"""

import logging

import pandas as pd

from ._base import NISRAValidationError
from .pxstat import PxStatError, read_dataset  # noqa: F401 — re-exported for callers

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_SYA = "PPMY02T01"  # single year of age, principal projection
_MATRIX_5YR = "PPMY02T02"  # 5-year age bands, principal projection
_MATRIX_VARIANTS = "PPMY02T03"  # variant projections


def get_latest_projections(
    start_year: int | None = None,
    end_year: int | None = None,
    age_groups: str = "5yr",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Retrieve NI population projections (principal projection).

    Args:
        start_year: First projection year to include (default: first available).
        end_year: Last projection year to include (default: last available).
        age_groups: Age breakdown format:
            - ``'5yr'``: 5-year age bands (default) — smaller result set
            - ``'single'``: Single year of age (0-90+) — larger result set
        force_refresh: Ignored — kept for API compatibility. The PxStat API
            always returns current data.

    Returns:
        DataFrame with columns:
            ``year``, ``age_group``, ``sex``, ``population``, ``base_year``

    Raises:
        NISRAValidationError: If the API returns empty or invalid data.
        PxStatError: If the API request fails.

    Example:
        >>> df = get_latest_projections()
        >>> 'population' in df.columns
        True
    """
    if force_refresh:
        logger.debug("force_refresh is ignored for PxStat-backed modules")

    matrix = _MATRIX_SYA if age_groups == "single" else _MATRIX_5YR
    age_col = "Single year of age" if age_groups == "single" else "Five year age bands"

    df = read_dataset(matrix)

    result = df[["Year", age_col, "Sex Label", "VALUE"]].rename(
        columns={"Year": "year", age_col: "age_group", "Sex Label": "sex", "VALUE": "population"}
    )
    result["base_year"] = 2024

    if start_year:
        result = result[result["year"] >= start_year]
    if end_year:
        result = result[result["year"] <= end_year]

    result = result.sort_values(["year", "age_group", "sex"]).reset_index(drop=True)

    if result.empty:
        raise NISRAValidationError("Population projections data is empty")

    return result


def get_variant_projections(
    variant: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Retrieve NI population projections including variant scenarios.

    Args:
        variant: Filter to a specific variant label (partial match, case-insensitive).
            E.g. ``'high fertility'``, ``'low fertility'``, ``'high life expectancy'``.
            If None, all variants are returned.
        start_year: First projection year to include.
        end_year: Last projection year to include.
        force_refresh: Ignored — kept for API compatibility.

    Returns:
        DataFrame with columns:
            ``year``, ``age_group``, ``sex``, ``variant``, ``population``
    """
    if force_refresh:
        logger.debug("force_refresh is ignored for PxStat-backed modules")

    df = read_dataset(_MATRIX_VARIANTS)

    result = df[["Year", "Single year of age", "Sex Label", "Variant Label", "VALUE"]].rename(
        columns={
            "Year": "year",
            "Single year of age": "age_group",
            "Sex Label": "sex",
            "Variant Label": "variant",
            "VALUE": "population",
        }
    )

    if variant:
        result = result[result["variant"].str.lower().str.contains(variant.lower())]
    if start_year:
        result = result[result["year"] >= start_year]
    if end_year:
        result = result[result["year"] <= end_year]

    return result.sort_values(["variant", "year", "age_group", "sex"]).reset_index(drop=True)


def validate_projections(df: pd.DataFrame) -> bool:
    """Validate a projections DataFrame for basic integrity.

    Args:
        df: DataFrame from :func:`get_latest_projections`.

    Returns:
        True if valid.

    Raises:
        NISRAValidationError: If validation fails.
    """
    required = {"year", "age_group", "sex", "population"}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")
    if (df["population"] < 0).any():
        raise NISRAValidationError("Negative population values found")
    return True
