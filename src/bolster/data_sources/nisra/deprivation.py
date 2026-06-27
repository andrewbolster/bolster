"""NISRA Multiple Deprivation Measure (NIMDM 2017) Module.

Provides access to the Northern Ireland Multiple Deprivation Measure 2017,
which ranks all 890 Super Output Areas (SOAs) on overall deprivation and
seven domain ranks. Rank 1 is the most deprived SOA in each domain.

Domains:
    - Income
    - Employment
    - Health Deprivation and Disability
    - Education, Skills and Training
    - Access to Services
    - Living Environment
    - Crime and Disorder

Data Source:
    Publication page: https://www.nisra.gov.uk/publications/nimdm17-soa-level-results
    Direct file: https://www.nisra.gov.uk/files/nisra/publications/NIMDM17_SOAresults.xls

Update Frequency:
    Infrequent. NIMDM2017 is the current release; NIMDM2021 is pending
    Census 2021 data integration. The download URL is stable and has no
    year in the path, so it will need to be updated when NIMDM2021 publishes.

Example:
    >>> from bolster.data_sources.nisra import deprivation
    >>> df = deprivation.get_latest_data()
    >>> 'mdm_rank' in df.columns
    True
    >>> df['soa_code'].nunique()
    890
"""

import logging

import pandas as pd

from ._base import NISRADataError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

NIMDM_SOA_URL = "https://www.nisra.gov.uk/files/nisra/publications/NIMDM17_SOAresults.xls"

_SHEET_NAME = "MDM"

_COLUMN_MAP = {
    "LGD2014NAME": "lgd",
    "2015 Default Urban/Rural ": "urban_rural",
    "SOA2001": "soa_code",
    "SOA2001_name": "soa_name",
    "Multiple Deprivation Measure Rank \n(where 1 is most deprived)": "mdm_rank",
    "Income Domain Rank \n(where 1 is most deprived)": "income_rank",
    "Employment Domain Rank (where 1 is most deprived)": "employment_rank",
    "Health Deprivation and Disability Domain Rank (where 1 is most deprived)": "health_disability_rank",
    "Education, Skills and Training Domain Rank (where 1 is most deprived)": "education_rank",
    "Access to Services Domain Rank (where 1 is most deprived)": "access_to_services_rank",
    "Living Environment Domain Rank (where 1 is most deprived)": "living_environment_rank",
    "Crime and Disorder Domain Rank (where 1 is most deprived)": "crime_disorder_rank",
}

_RANK_COLUMNS = [
    "mdm_rank",
    "income_rank",
    "employment_rank",
    "health_disability_rank",
    "education_rank",
    "access_to_services_rank",
    "living_environment_rank",
    "crime_disorder_rank",
]


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest NIMDM SOA-level deprivation ranks.

    Args:
        force_refresh: Force re-download even if cached.

    Returns:
        DataFrame with columns: lgd, urban_rural, soa_code, soa_name,
        mdm_rank, income_rank, employment_rank, health_disability_rank,
        education_rank, access_to_services_rank, living_environment_rank,
        crime_disorder_rank. Rank 1 is the most deprived SOA.

    Raises:
        NISRADataError: If the data file cannot be downloaded or parsed.

    Example:
        >>> df = get_latest_data()
        >>> 'mdm_rank' in df.columns
        True
    """
    path = download_file(NIMDM_SOA_URL, cache_ttl_hours=24 * 30, force_refresh=force_refresh)

    try:
        df = pd.read_excel(path, sheet_name=_SHEET_NAME, engine="xlrd")
    except Exception as e:
        raise NISRADataError(f"Failed to parse NIMDM SOA results: {e}") from e

    df = df.rename(columns=_COLUMN_MAP)
    df = df[[c for c in _COLUMN_MAP.values() if c in df.columns]]

    for col in _RANK_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    return df.reset_index(drop=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate the NIMDM DataFrame for internal consistency.

    Args:
        df: DataFrame as returned by :func:`get_latest_data`.

    Returns:
        True if all checks pass.

    Raises:
        NISRAValidationError: Describing the first failing check.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     "soa_code": ["95AA01S1"], "soa_name": ["Aldergrove_1"],
        ...     "lgd": ["Antrim and Newtownabbey"], "urban_rural": ["Rural"],
        ...     "mdm_rank": [516], "income_rank": [790],
        ...     "employment_rank": [888], "health_disability_rank": [890],
        ...     "education_rank": [254], "access_to_services_rank": [17],
        ...     "living_environment_rank": [75], "crime_disorder_rank": [874],
        ... })
        >>> validate_data(df)
        True
    """
    required = {"soa_code", "soa_name", "lgd", *_RANK_COLUMNS}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    n_soa = df["soa_code"].nunique()
    if n_soa < 800:
        raise NISRAValidationError(f"Expected ~890 SOAs, got {n_soa}")

    if df["soa_code"].duplicated().any():
        dupes = df.loc[df["soa_code"].duplicated(), "soa_code"].tolist()
        raise NISRAValidationError(f"Duplicate soa_code values found: {dupes[:5]}")

    n_rows = len(df)
    for col in _RANK_COLUMNS:
        ranks = df[col].dropna()
        if (ranks < 1).any() or (ranks > n_rows).any():
            raise NISRAValidationError(f"{col} has values outside the expected 1-{n_rows} range")
        if ranks.nunique() < n_rows * 0.95:
            raise NISRAValidationError(f"{col} should be (near-)unique ranks, got {ranks.nunique()} unique values")

    return True
