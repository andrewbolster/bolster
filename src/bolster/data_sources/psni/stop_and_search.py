"""PSNI Stop and Search Statistics.

Provides access to Police Service of Northern Ireland stop and search data,
covering individual stop and search records from 2017/18 to the latest
available financial year.

Data includes:
- Financial year and quarter (quarterly breakdowns)
- Legislation used (Misuse of Drugs Act, PACE, Justice & Security Act, etc.)
- PACE-specific reasons for search (stolen articles, prohibited articles, blade/point, fireworks)
- Subject demographics: age group and gender
- Geographic level: Northern Ireland-wide (no district breakdown in this dataset)

Data Source:
    **Primary Source**: OpenDataNI — Stop and Search Statistics 2017/18–2024/25

    https://www.opendatani.gov.uk/dataset/stop-and-search

    Data is published by the PSNI under the Open Government Licence v3.0.

Update Frequency: Annual (full dataset refreshed with each release)
Geographic Coverage: Northern Ireland (NI-wide only — no district breakdown)
Time Coverage: 2017/18 financial year to present
Row count: ~199,000 individual stop and search records

Example:
    >>> from bolster.data_sources.psni import stop_and_search
    >>> df = stop_and_search.get_latest_stop_and_search()
    >>> 'financial_year' in df.columns
    True
    >>> stop_and_search.validate_stop_and_search(df)
    True
"""

import logging

import pandas as pd

from bolster.utils.web import session

from ._base import PSNIValidationError, download_file

logger = logging.getLogger(__name__)

# OpenDataNI CKAN API (admin endpoint — the public endpoint redirects to a Cloudflare page)
OPENDATANI_API = "https://admin.opendatani.gov.uk/api/3/action"

# Stable dataset identifier on OpenDataNI
DATASET_ID = "421d96c1-fa5b-43e7-914c-b9a13e163d33"

# Fallback URL confirmed working as of 2025 — used if CKAN API is unavailable
FALLBACK_CSV_URL = (
    "https://admin.opendatani.gov.uk/dataset/421d96c1-fa5b-43e7-914c-b9a13e163d33"
    "/resource/73fcba18-4616-4a60-91ea-873f69f6d063"
    "/download/stop-and-search-open-data-201718to202425.csv"
)

# Cache TTL: monthly updates, so refresh roughly monthly
CACHE_TTL_HOURS = 24 * 30

# Mapping from verbose raw column names to clean snake_case equivalents
COLUMN_RENAMES: dict[str, str] = {
    "Financial Year": "financial_year",
    "Geographical Level": "geographical_level",
    "Legislation": "legislation",
    "(PACE) Reason for search - Stolen Articles": "pace_reason_stolen_articles",
    "(PACE) Reason for search - Prohibited Articles": "pace_reason_prohibited_articles",
    "(PACE) Reason for search - Blade or Point": "pace_reason_blade_or_point",
    "(PACE) Reason for search - Fireworks": "pace_reason_fireworks",
    "Quarter": "quarter",
    "AgeGroup": "age_group",
    "Gender": "gender",
}

# Quarter ordering for categorical dtype (chronological order within a year)
QUARTER_ORDER = [
    "April to June",
    "July to September",
    "October to December",
    "January to March",
]

# Age group ordering for categorical dtype
AGE_GROUP_ORDER = [
    "Under 18",
    "18 to 25",
    "26 to 35",
    "36 to 45",
    "46 to 55",
    "56 to 65",
    "Over 65",
    "Not Specified",
]


def get_latest_dataset_url() -> str:
    """Query the OpenDataNI CKAN API to find the latest Stop and Search CSV URL.

    Fetches resource metadata for the stop-and-search dataset from the OpenDataNI
    CKAN API and returns the download URL for the CSV resource. Falls back to the
    known direct URL if the API request fails.

    Returns:
        Download URL for the latest stop and search CSV file.

    Example:
        >>> url = get_latest_dataset_url()
        >>> url.startswith("https://")
        True
        >>> url.endswith(".csv")
        True
    """
    try:
        resp = session.get(
            f"{OPENDATANI_API}/package_show",
            params={"id": DATASET_ID},
            headers={"User-Agent": "bolster/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            logger.warning("OpenDataNI CKAN API returned unsuccessful response; falling back to known URL")
            return FALLBACK_CSV_URL

        resources = data.get("result", {}).get("resources", [])
        for resource in resources:
            if resource.get("format", "").upper() == "CSV":
                url = resource.get("url", "")
                if url:
                    logger.info(f"Found CSV resource via CKAN API: {url}")
                    return url

        logger.warning("No CSV resource found via CKAN API; falling back to known URL")
        return FALLBACK_CSV_URL

    except Exception as e:
        logger.warning(f"CKAN API request failed ({e}); falling back to known URL")
        return FALLBACK_CSV_URL


def _parse_stop_and_search(file_path: str) -> pd.DataFrame:
    """Parse a downloaded Stop and Search CSV file into a clean DataFrame.

    Args:
        file_path: Local path to the downloaded CSV file.

    Returns:
        Cleaned DataFrame with snake_case column names and appropriate dtypes.

    Raises:
        PSNIValidationError: If the CSV does not contain the expected columns.
    """
    df = pd.read_csv(file_path)

    # Validate raw columns before renaming
    expected_raw = set(COLUMN_RENAMES.keys())
    missing = expected_raw - set(df.columns)
    if missing:
        raise PSNIValidationError(
            f"Stop and Search CSV missing expected columns: {missing}. Found columns: {df.columns.tolist()}"
        )

    # Rename to snake_case
    df = df.rename(columns=COLUMN_RENAMES)

    # Normalise age_group: harmonise 'over 65' -> 'Over 65' (case inconsistency in source)
    df["age_group"] = df["age_group"].str.strip()
    df["age_group"] = df["age_group"].replace({"over 65": "Over 65", "Specified": "Not Specified"})

    # Normalise legislation: strip trailing whitespace (source has trailing spaces in some rows)
    df["legislation"] = df["legislation"].str.strip()

    # Boolean columns for PACE reasons (Yes/No -> bool)
    pace_cols = [
        "pace_reason_stolen_articles",
        "pace_reason_prohibited_articles",
        "pace_reason_blade_or_point",
        "pace_reason_fireworks",
    ]
    for col in pace_cols:
        df[col] = df[col].str.strip().str.upper().map({"YES": True, "NO": False})

    # Ordered categoricals for dimensions with a natural order
    df["quarter"] = pd.Categorical(df["quarter"], categories=QUARTER_ORDER, ordered=True)
    df["age_group"] = pd.Categorical(df["age_group"], categories=AGE_GROUP_ORDER, ordered=True)

    # Unordered categoricals for nominal dimensions
    for col in ["financial_year", "geographical_level", "legislation", "gender"]:
        df[col] = df[col].astype("category")

    logger.info(f"Parsed {len(df):,} stop and search records")
    return df


def get_latest_stop_and_search(force_refresh: bool = False) -> pd.DataFrame:
    """Download and return the latest PSNI Stop and Search dataset.

    Fetches the current stop and search data from OpenDataNI, caches it
    locally for ~30 days, and returns a cleaned DataFrame with snake_case
    column names and appropriate dtypes.

    The dataset covers individual stop and search records for Northern Ireland
    from financial year 2017/18 to the most recently published year. Note that
    the dataset does **not** include a district-level geographic breakdown —
    all records are at Northern Ireland level.

    Args:
        force_refresh: If True, bypass the local cache and re-download the data.

    Returns:
        DataFrame with columns:
            - financial_year (category): e.g. ``"2023/24"``
            - geographical_level (category): always ``"Northern Ireland"``
            - legislation (category): legislation under which the search was conducted
            - pace_reason_stolen_articles (bool): PACE reason — stolen articles
            - pace_reason_prohibited_articles (bool): PACE reason — prohibited articles
            - pace_reason_blade_or_point (bool): PACE reason — blade or point
            - pace_reason_fireworks (bool): PACE reason — fireworks
            - quarter (Categorical[ordered]): quarter label, e.g. ``"April to June"``
            - age_group (Categorical[ordered]): age band of the subject
            - gender (category): subject gender

    Raises:
        PSNIDataNotFoundError: If the download fails.
        PSNIValidationError: If the downloaded file does not match the expected schema.

    Example:
        >>> df = get_latest_stop_and_search()
        >>> len(df) > 100_000
        True
        >>> sorted(df['financial_year'].cat.categories.tolist())  # doctest: +SKIP
        ['2017/18', '2018/19', '2019/20', '2020/21', '2021/22', '2022/23', '2023/24', '2024/25']
    """
    url = get_latest_dataset_url()
    file_path = download_file(url, cache_ttl_hours=CACHE_TTL_HOURS, force_refresh=force_refresh)
    return _parse_stop_and_search(str(file_path))


def validate_stop_and_search(df: pd.DataFrame) -> bool:
    """Validate the integrity of a Stop and Search DataFrame.

    Checks that the DataFrame has the expected shape, required columns,
    a sensible set of financial years, no unexpected null values in key
    fields, and that PACE boolean columns contain only booleans.

    Args:
        df: DataFrame to validate (e.g. from :func:`get_latest_stop_and_search`).

    Returns:
        ``True`` if all checks pass.

    Raises:
        PSNIValidationError: If any check fails, with a descriptive message.

    Example:
        >>> df = get_latest_stop_and_search()
        >>> validate_stop_and_search(df)
        True
    """
    if df.empty:
        raise PSNIValidationError("Stop and Search DataFrame is empty")

    required_columns = {
        "financial_year",
        "geographical_level",
        "legislation",
        "pace_reason_stolen_articles",
        "pace_reason_prohibited_articles",
        "pace_reason_blade_or_point",
        "pace_reason_fireworks",
        "quarter",
        "age_group",
        "gender",
    }
    missing = required_columns - set(df.columns)
    if missing:
        raise PSNIValidationError(f"Missing required columns: {missing}")

    # Must have records from at least 2017/18
    years = df["financial_year"].unique().tolist()
    str_years = [str(y) for y in years]
    if "2017/18" not in str_years:
        raise PSNIValidationError(f"Expected data from 2017/18 but found years: {sorted(str_years)}")

    # Must have records for multiple financial years
    if len(str_years) < 2:
        raise PSNIValidationError(f"Expected multiple financial years, found only: {str_years}")

    # PACE columns must be boolean (no nulls from failed mapping)
    pace_cols = [
        "pace_reason_stolen_articles",
        "pace_reason_prohibited_articles",
        "pace_reason_blade_or_point",
        "pace_reason_fireworks",
    ]
    for col in pace_cols:
        null_count = df[col].isna().sum()
        if null_count > 0:
            raise PSNIValidationError(f"Column '{col}' has {null_count} unexpected null values")

    # At least 50,000 records (significantly less than 199k would indicate truncation)
    if len(df) < 50_000:
        raise PSNIValidationError(f"Too few records: expected ≥50,000 but got {len(df):,}")

    logger.info(f"Validation passed: {len(df):,} records, years {sorted(str_years)}")
    return True
