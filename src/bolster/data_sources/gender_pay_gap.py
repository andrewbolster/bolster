"""UK Gender Pay Gap Reporting Data Source.

Provides access to UK Gender Pay Gap (GPG) reporting data published annually by
the UK Government. All employers with 250+ employees are legally required to
report their gender pay gap figures each year.

Data Source:
    **Download page**: https://gender-pay-gap.service.gov.uk/viewing/download

    Annual CSV files are published for each reporting year, covering all UK employers
    with 250+ employees. Data is available from 2017 to present. Northern Ireland
    employers (identifiable by BT postcodes) are included in the UK-wide dataset.

    The reporting deadline is 4 April each year (for the 12-month snapshot period
    ending 5 April the previous year), so data for year Y covers the snapshot date
    of 5 April Y.

Update Frequency: Annual (April each year)
Geographic Coverage: UK-wide. NI employers identifiable via BT postcode prefix.
Licence: Open Government Licence v3.0

Metrics Provided:
    - Mean and median hourly pay gap (%) between male and female employees
    - Mean and median bonus pay gap (%)
    - Proportion of male/female employees receiving a bonus
    - Pay quartile gender composition (lower, lower-middle, upper-middle, upper)
    - Employer metadata (size band, SIC code, Companies House number)

Example:
    >>> from bolster.data_sources import gender_pay_gap
    >>> # Get all UK employers for 2024 reporting year
    >>> df = gender_pay_gap.get_data(year=2024)
    >>> print(df.head())

    >>> # Get NI employers only (BT postcode prefix)
    >>> ni_df = gender_pay_gap.get_data(year=2024, postcode_prefix="BT")
    >>> print(f"NI employers reporting: {len(ni_df)}")

    >>> # Get all available years combined, filtered to NI
    >>> all_df = gender_pay_gap.get_all_years(postcode_prefix="BT")
    >>> print(all_df.groupby('reporting_year')['diff_mean_hourly_percent'].median())
"""

import logging
from io import StringIO

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Base URL for gender pay gap CSV downloads
GPG_BASE_URL = "https://gender-pay-gap.service.gov.uk/viewing/download-data/{year}"

# First year data is available
FIRST_YEAR = 2017

# Column name mapping from raw CSV to snake_case
COLUMN_MAPPING = {
    "EmployerName": "employer_name",
    "EmployerId": "employer_id",
    "Address": "address",
    "PostCode": "postcode",
    "CompanyNumber": "company_number",
    "SicCodes": "sic_codes",
    "DiffMeanHourlyPercent": "diff_mean_hourly_percent",
    "DiffMedianHourlyPercent": "diff_median_hourly_percent",
    "DiffMeanBonusPercent": "diff_mean_bonus_percent",
    "DiffMedianBonusPercent": "diff_median_bonus_percent",
    "MaleBonusPercent": "male_bonus_percent",
    "FemaleBonusPercent": "female_bonus_percent",
    "MaleLowerQuartile": "male_lower_quartile",
    "FemaleLowerQuartile": "female_lower_quartile",
    "MaleLowerMiddleQuartile": "male_lower_middle_quartile",
    "FemaleLowerMiddleQuartile": "female_lower_middle_quartile",
    "MaleUpperMiddleQuartile": "male_upper_middle_quartile",
    "FemaleUpperMiddleQuartile": "female_upper_middle_quartile",
    "MaleTopQuartile": "male_top_quartile",
    "FemaleTopQuartile": "female_top_quartile",
    "CompanyLinkToGPGInfo": "company_link_to_gpg_info",
    "ResponsiblePerson": "responsible_person",
    "EmployerSize": "employer_size",
    "CurrentName": "current_name",
    "SubmittedAfterTheDeadline": "submitted_after_deadline",
    "DueDate": "due_date",
    "DateSubmitted": "date_submitted",
}

# Numeric columns to coerce (some cells contain empty strings)
NUMERIC_COLUMNS = [
    "diff_mean_hourly_percent",
    "diff_median_hourly_percent",
    "diff_mean_bonus_percent",
    "diff_median_bonus_percent",
    "male_bonus_percent",
    "female_bonus_percent",
    "male_lower_quartile",
    "female_lower_quartile",
    "male_lower_middle_quartile",
    "female_lower_middle_quartile",
    "male_upper_middle_quartile",
    "female_upper_middle_quartile",
    "male_top_quartile",
    "female_top_quartile",
]


class GenderPayGapError(Exception):
    """Base exception for gender pay gap data errors."""


class GenderPayGapDataNotFoundError(GenderPayGapError):
    """Raised when data for the requested year is not available."""


def get_available_years() -> list[int]:
    """Return the list of reporting years with published data.

    Data is published annually. The first year is 2017; data for the current
    year is available once the April reporting deadline has passed.

    Returns:
        List of years (integers) for which data is available, e.g. [2017, ..., 2024].

    Example:
        >>> years = get_available_years()
        >>> print(f"Data available from {min(years)} to {max(years)}")
    """
    current_year = pd.Timestamp.now().year
    # Data for year Y is typically published in April of year Y+1
    # Be conservative: include up to the previous year
    return list(range(FIRST_YEAR, current_year))


def get_data(
    year: int,
    postcode_prefix: str | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download and parse gender pay gap data for a given reporting year.

    Returns UK-wide data by default. Use ``postcode_prefix`` to filter to a
    specific region — e.g. ``"BT"`` for Northern Ireland, ``"EH"`` for Edinburgh,
    ``"M"`` for Manchester. The full dataset is always downloaded first; filtering
    happens in-memory.

    Args:
        year: The reporting year (e.g. 2024 for the snapshot date of 5 April 2024).
              Must be between 2017 and the most recent available year.
        postcode_prefix: If given, only return employers whose postcode starts with
                         this prefix (case-insensitive). ``None`` (default) returns
                         all UK employers. Common values: ``"BT"`` (Northern Ireland),
                         ``"EH"`` (Edinburgh), ``"G"`` (Glasgow), ``"M"`` (Manchester).
        force_refresh: If True, bypass any cached response. Has no effect currently
                       as responses are streamed directly; reserved for future caching.

    Returns:
        DataFrame with one row per employer, columns:

        - employer_name: str
        - employer_id: str
        - address: str
        - postcode: str
        - company_number: str
        - sic_codes: str
        - diff_mean_hourly_percent: float — mean hourly pay gap (positive = men paid more)
        - diff_median_hourly_percent: float
        - diff_mean_bonus_percent: float
        - diff_median_bonus_percent: float
        - male_bonus_percent: float — % of male employees receiving a bonus
        - female_bonus_percent: float
        - male_lower_quartile: float — % of lower pay quartile who are male
        - female_lower_quartile: float
        - male_lower_middle_quartile: float
        - female_lower_middle_quartile: float
        - male_upper_middle_quartile: float
        - female_upper_middle_quartile: float
        - male_top_quartile: float
        - female_top_quartile: float
        - company_link_to_gpg_info: str
        - responsible_person: str
        - employer_size: str — e.g. "250 to 499", "500 to 999", "5000 to 19,999", "20,000 or more"
        - current_name: str
        - submitted_after_deadline: bool
        - due_date: datetime
        - date_submitted: datetime
        - reporting_year: int — the reporting year (same as ``year`` arg)

    Raises:
        GenderPayGapDataNotFoundError: If data for the requested year is not available.
        GenderPayGapError: If the download or parse fails.

    Example:
        >>> # All UK employers
        >>> df = get_data(year=2024)
        >>> print(f"Total UK employers: {len(df)}")

        >>> # Northern Ireland only
        >>> ni = get_data(year=2024, postcode_prefix="BT")
        >>> print(f"NI employers: {len(ni)}")

        >>> # Edinburgh employers
        >>> edinburgh = get_data(year=2024, postcode_prefix="EH")
    """
    available = get_available_years()
    if year not in available:
        raise GenderPayGapDataNotFoundError(
            f"Year {year} is not available. Available years: {min(available)}–{max(available)}"
        )

    url = GPG_BASE_URL.format(year=year)
    logger.info(f"Downloading GPG data for {year} from {url}")

    try:
        response = session.get(url, timeout=60)
        response.raise_for_status()
    except Exception as e:
        raise GenderPayGapError(f"Failed to download GPG data for {year}: {e}") from e

    try:
        df = pd.read_csv(StringIO(response.text))
    except Exception as e:
        raise GenderPayGapError(f"Failed to parse GPG CSV for {year}: {e}") from e

    # Rename columns to snake_case
    df = df.rename(columns=COLUMN_MAPPING)

    # Coerce numeric columns (empty strings → NaN)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Parse datetime columns
    for col in ("due_date", "date_submitted"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Boolean column
    if "submitted_after_deadline" in df.columns:
        df["submitted_after_deadline"] = df["submitted_after_deadline"].map(
            {"True": True, "False": False, True: True, False: False}
        )

    # Add derived columns
    df["reporting_year"] = year

    if postcode_prefix is not None:
        prefix = postcode_prefix.upper()
        mask = df["postcode"].str.upper().str.startswith(prefix, na=False)
        df = df[mask].copy()
        logger.info(f"Filtered to {len(df)} employers with postcode prefix '{prefix}' for {year}")

    logger.info(f"Loaded {len(df)} employers for reporting year {year}")
    return df


def get_all_years(postcode_prefix: str | None = None) -> pd.DataFrame:
    """Download and combine gender pay gap data for all available years.

    Useful for trend analysis across multiple reporting years.

    Args:
        postcode_prefix: If given, filter to employers whose postcode starts with
                         this prefix before combining. See :func:`get_data` for details.

    Returns:
        Combined DataFrame with all years, including a ``reporting_year`` column.
        See :func:`get_data` for full column documentation.

    Example:
        >>> # NI employer median pay gap trend
        >>> df = get_all_years(postcode_prefix="BT")
        >>> trend = df.groupby('reporting_year')['diff_median_hourly_percent'].median()
        >>> print(trend)

        >>> # All UK employers across all years
        >>> df = get_all_years()
    """
    frames = []
    for year in get_available_years():
        try:
            df = get_data(year=year, postcode_prefix=postcode_prefix)
            frames.append(df)
            logger.info(f"Loaded {year}: {len(df)} employers")
        except GenderPayGapError as e:
            logger.warning(f"Skipping year {year}: {e}")

    if not frames:
        raise GenderPayGapError("No data could be loaded for any year")

    return pd.concat(frames, ignore_index=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a gender pay gap DataFrame for internal consistency.

    Checks:
    - Required columns are present
    - Pay quartile columns sum to ~100% (male + female = 100 per quartile)
    - Hourly pay gap values are within plausible range (-100% to +100%)

    Args:
        df: DataFrame from :func:`get_data` or :func:`get_all_years`.

    Returns:
        True if validation passes.

    Raises:
        GenderPayGapError: If any validation check fails.

    Example:
        >>> df = get_data(year=2024)
        >>> validate_data(df)
        True
    """
    required_columns = {
        "employer_name",
        "postcode",
        "diff_mean_hourly_percent",
        "diff_median_hourly_percent",
        "employer_size",
        "reporting_year",
    }
    missing = required_columns - set(df.columns)
    if missing:
        raise GenderPayGapError(f"Missing required columns: {missing}")

    # Check quartile columns sum to ~100 (allow rounding tolerance)
    quartile_pairs = [
        ("male_lower_quartile", "female_lower_quartile"),
        ("male_lower_middle_quartile", "female_lower_middle_quartile"),
        ("male_upper_middle_quartile", "female_upper_middle_quartile"),
        ("male_top_quartile", "female_top_quartile"),
    ]
    for male_col, female_col in quartile_pairs:
        if male_col in df.columns and female_col in df.columns:
            totals = df[male_col].fillna(0) + df[female_col].fillna(0)
            # Only check rows where both are non-null
            mask = df[male_col].notna() & df[female_col].notna()
            if mask.any():
                bad = ((totals[mask] - 100).abs() > 1.5).sum()
                if bad > 0:
                    raise GenderPayGapError(f"Quartile columns {male_col}+{female_col} don't sum to 100 for {bad} rows")

    # Hourly pay gap within plausible range.
    # The service accepts extreme negatives (e.g. -757%) from employers with
    # heavily female-dominated lower pay bands; cap check at -1000/+100.
    for col in ("diff_mean_hourly_percent", "diff_median_hourly_percent"):
        if col in df.columns:
            valid = df[col].dropna()
            if len(valid) > 0 and ((valid < -1000) | (valid > 100)).any():
                raise GenderPayGapError(f"Column {col} contains implausible values outside [-1000, 100]")

    logger.info(f"Validation passed for {len(df)} employers")
    return True
