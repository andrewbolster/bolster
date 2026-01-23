"""NISRA Individual Wellbeing Module.

This module provides access to Northern Ireland's individual wellbeing statistics,
measuring subjective wellbeing across the population aged 16 and over.

The report covers four main areas of individual wellbeing:
- Personal Wellbeing (ONS4 measures): Life Satisfaction, Worthwhile, Happiness, Anxiety
- Loneliness: Frequency of feeling lonely
- Self-efficacy: Belief in one's capabilities
- Locus of Control: Perceived control over life events

Data Coverage:
    - Personal Wellbeing (ONS4): 2014/15 - Present (annual, mean scores 0-10)
    - Loneliness: 2017/18 - Present (annual, proportions)
    - Self-efficacy: 2014/15 - Present (annual, mean scores 5-25)
    - Locus of Control: Available in recent years

Demographics available:
    - Sex, Age Group, Marital Status, Sexual Orientation
    - Religion, Dependant status, Health status, Employment status

Examples:
    >>> from bolster.data_sources.nisra import wellbeing
    >>> # Get latest personal wellbeing timeseries (ONS4 measures)
    >>> df = wellbeing.get_latest_personal_wellbeing()
    >>> print(df.tail())

    >>> # Get loneliness data
    >>> df_lonely = wellbeing.get_latest_loneliness()
    >>> print(df_lonely[df_lonely['year'] == '2024/25'])

    >>> # Get summary across all measures
    >>> summary = wellbeing.get_wellbeing_summary()
    >>> print(summary)

Publication Details:
    - Frequency: Annual (January publication)
    - Reference period: Financial year (April - March)
    - Published by: NISRA / The Executive Office
    - Contact: pfganalytics@executiveoffice-ni.gov.uk
    - Population: Adults aged 16+ in Northern Ireland
"""

import logging
import re
from pathlib import Path
from typing import Optional, Tuple, Union

import pandas as pd

from ._base import NISRADataNotFoundError, download_file

logger = logging.getLogger(__name__)

# Base URL for wellbeing publications (hosted on Executive Office site)
WELLBEING_BASE_URL = "https://www.nisra.gov.uk/statistics/wellbeing/individual-wellbeing-northern-ireland"
EXEC_OFFICE_TOPIC_URL = "https://www.executiveoffice-ni.gov.uk/topics/individual-wellbeing-northern-ireland"
EXEC_OFFICE_BASE_URL = "https://www.executiveoffice-ni.gov.uk"


def get_latest_wellbeing_publication_url() -> Tuple[str, str]:
    """Get the URL of the latest Individual Wellbeing publication and its year.

    Scrapes the Executive Office topic page to find the most recent publication.

    Returns:
        Tuple of (publication_url, year_string) e.g. ("https://...", "2024/25")

    Raises:
        NISRADataNotFoundError: If unable to find the latest publication

    Example:
        >>> url, year = get_latest_wellbeing_publication_url()
        >>> print(f"Latest Wellbeing: {year} at {url}")
    """
    from bs4 import BeautifulSoup

    from bolster.utils.web import session

    logger.info("Fetching latest Individual Wellbeing publication URL...")

    try:
        response = session.get(EXEC_OFFICE_TOPIC_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch wellbeing page: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Find links to publications - pattern: "Individual Wellbeing in Northern Ireland Report 2024/25"
    publication_links = soup.find_all("a", href=True)

    # Collect all matching publications and find the latest
    publications = []
    for link in publication_links:
        link_text = link.get_text(strip=True)
        href = link["href"]

        # Match "Report 2024/25" or similar year patterns
        match = re.search(r"(\d{4})/(\d{2})", link_text)
        if match and "Report" in link_text:
            year_str = f"{match.group(1)}/{match.group(2)}"
            start_year = int(match.group(1))

            pub_url = href
            if not pub_url.startswith("http"):
                pub_url = f"{EXEC_OFFICE_BASE_URL}{pub_url}"

            publications.append((start_year, year_str, pub_url))

    if not publications:
        raise NISRADataNotFoundError("Could not find latest Individual Wellbeing publication")

    # Sort by year and get the latest
    publications.sort(key=lambda x: x[0], reverse=True)
    _, year_str, pub_url = publications[0]

    logger.info(f"Found latest wellbeing publication: {year_str} at {pub_url}")
    return pub_url, year_str


def get_wellbeing_file_url(year_str: str) -> str:
    """Construct URL for the wellbeing data tables Excel file.

    Args:
        year_str: Financial year string (e.g., "2024/25")

    Returns:
        URL to the Excel data tables file

    Example:
        >>> url = get_wellbeing_file_url("2024/25")
        >>> print(url)
    """
    # Convert "2024/25" to "202425"
    year_code = year_str.replace("/", "")

    # Pattern: individual-wellbeing-ni-{yearcode}-data-tables.xlsx
    # Published in January of the following year
    # e.g., 2024/25 data published in January 2026
    start_year = int(year_str.split("/")[0])
    pub_year = start_year + 2  # Publication year is 2 years after start

    filename = f"individual-wellbeing-ni-{year_code}-data-tables.xlsx"
    url = f"https://www.executiveoffice-ni.gov.uk/sites/default/files/{pub_year}-01/{filename}"

    logger.info(f"Constructed wellbeing file URL: {url}")
    return url


def parse_personal_wellbeing(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse personal wellbeing (ONS4) measures from the Excel file.

    Extracts Life Satisfaction, Worthwhile, Happiness, and Anxiety mean scores
    from the time series data.

    Args:
        file_path: Path to the wellbeing data tables Excel file

    Returns:
        DataFrame with columns:
            - year: str (financial year, e.g., "2024/25")
            - life_satisfaction: float (mean score 0-10)
            - worthwhile: float (mean score 0-10)
            - happiness: float (mean score 0-10)
            - anxiety: float (mean score 0-10, lower is better)

    Example:
        >>> df = parse_personal_wellbeing("individual-wellbeing-ni-202425-data-tables.xlsx")
        >>> print(df.tail())
    """
    logger.info(f"Parsing personal wellbeing from {file_path}")

    # Sheet names for ONS4 measures
    sheet_configs = {
        "life_satisfaction": "Life_Satisfaction_Avg",
        "worthwhile": "Worthwhile_Avg",
        "happiness": "Happiness_Avg",
        "anxiety": "Anxiety_Avg ",  # Note: trailing space in sheet name
    }

    results = {}

    for metric, sheet_name in sheet_configs.items():
        try:
            # Read the sheet
            df_raw = pd.read_excel(
                file_path,
                sheet_name=sheet_name,
                header=None,
                skiprows=4,  # Skip to header row
                nrows=15,  # Enough rows for the time series
            )

            # Extract year and estimate columns (columns 1 and 2)
            data = []
            for _, row in df_raw.iterrows():
                year_val = row.iloc[1]
                estimate = row.iloc[2]

                # Check if this is a valid year row
                if isinstance(year_val, str) and "/" in year_val and pd.notna(estimate):
                    try:
                        data.append({"year": year_val, metric: float(estimate)})
                    except (ValueError, TypeError):
                        continue

            results[metric] = pd.DataFrame(data)

        except Exception as e:
            logger.warning(f"Failed to parse {metric} from {sheet_name}: {e}")
            continue

    # Merge all metrics on year
    if not results:
        raise NISRADataNotFoundError("Could not parse any personal wellbeing metrics")

    df = None
    for metric, df_metric in results.items():
        if df is None:
            df = df_metric
        else:
            df = df.merge(df_metric, on="year", how="outer")

    # Sort by year
    df = df.sort_values("year").reset_index(drop=True)

    logger.info(f"Parsed {len(df)} years of personal wellbeing data")
    return df


def parse_loneliness(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse loneliness data from the Excel file.

    Extracts the proportion of people who feel lonely at least some of the time.

    Args:
        file_path: Path to the wellbeing data tables Excel file

    Returns:
        DataFrame with columns:
            - year: str (financial year, e.g., "2024/25")
            - lonely_some_of_time: float (proportion, e.g., 0.179 = 17.9%)
            - confidence_interval: str (e.g., "+/- 1.1")

    Example:
        >>> df = parse_loneliness("individual-wellbeing-ni-202425-data-tables.xlsx")
        >>> print(df.tail())
    """
    logger.info(f"Parsing loneliness from {file_path}")

    df_raw = pd.read_excel(
        file_path,
        sheet_name="Loneliness - some of the time",
        header=None,
        skiprows=4,  # Skip to header row
        nrows=12,  # Time series rows
    )

    data = []
    for _, row in df_raw.iterrows():
        year_val = row.iloc[1]
        estimate = row.iloc[2]
        ci = row.iloc[3]

        if isinstance(year_val, str) and "/" in year_val and pd.notna(estimate):
            try:
                data.append({
                    "year": year_val,
                    "lonely_some_of_time": float(estimate),
                    "confidence_interval": str(ci) if pd.notna(ci) else None,
                })
            except (ValueError, TypeError):
                continue

    df = pd.DataFrame(data)
    df = df.sort_values("year").reset_index(drop=True)

    logger.info(f"Parsed {len(df)} years of loneliness data")
    return df


def parse_self_efficacy(file_path: Union[str, Path]) -> pd.DataFrame:
    """Parse self-efficacy data from the Excel file.

    Self-efficacy measures a person's belief in their capabilities to influence
    events in their lives. Scores range from 5 to 25.

    Args:
        file_path: Path to the wellbeing data tables Excel file

    Returns:
        DataFrame with columns:
            - year: str (financial year, e.g., "2024/25")
            - self_efficacy_mean: float (mean score 5-25)
            - confidence_interval: str (e.g., "+/- 0.1")

    Example:
        >>> df = parse_self_efficacy("individual-wellbeing-ni-202425-data-tables.xlsx")
        >>> print(df.tail())
    """
    logger.info(f"Parsing self-efficacy from {file_path}")

    df_raw = pd.read_excel(
        file_path,
        sheet_name="Self-efficacy_avg",
        header=None,
        skiprows=3,  # Skip to header row
        nrows=15,  # Time series rows
    )

    data = []
    for _, row in df_raw.iterrows():
        year_val = row.iloc[1]
        estimate = row.iloc[2]
        ci = row.iloc[3]

        if isinstance(year_val, str) and "/" in year_val and pd.notna(estimate):
            try:
                data.append({
                    "year": year_val,
                    "self_efficacy_mean": float(estimate),
                    "confidence_interval": str(ci) if pd.notna(ci) else None,
                })
            except (ValueError, TypeError):
                continue

    df = pd.DataFrame(data)
    df = df.sort_values("year").reset_index(drop=True)

    logger.info(f"Parsed {len(df)} years of self-efficacy data")
    return df


def get_latest_personal_wellbeing(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest personal wellbeing (ONS4) data.

    Downloads and parses the latest Individual Wellbeing publication to extract
    the four ONS personal wellbeing measures: Life Satisfaction, Worthwhile,
    Happiness, and Anxiety.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with columns:
            - year: str (financial year)
            - life_satisfaction: float (mean 0-10, higher is better)
            - worthwhile: float (mean 0-10, higher is better)
            - happiness: float (mean 0-10, higher is better)
            - anxiety: float (mean 0-10, lower is better)

    Example:
        >>> df = get_latest_personal_wellbeing()
        >>> latest = df.iloc[-1]
        >>> print(f"Life Satisfaction {latest['year']}: {latest['life_satisfaction']}")
    """
    _, year_str = get_latest_wellbeing_publication_url()
    file_url = get_wellbeing_file_url(year_str)

    # Cache for 90 days (quarterly publication)
    file_path = download_file(file_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    return parse_personal_wellbeing(file_path)


def get_latest_loneliness(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest loneliness data.

    Downloads and parses the latest Individual Wellbeing publication to extract
    loneliness statistics (proportion feeling lonely at least some of the time).

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with columns:
            - year: str (financial year)
            - lonely_some_of_time: float (proportion)
            - confidence_interval: str

    Example:
        >>> df = get_latest_loneliness()
        >>> latest = df.iloc[-1]
        >>> print(f"Loneliness {latest['year']}: {latest['lonely_some_of_time']:.1%}")
    """
    _, year_str = get_latest_wellbeing_publication_url()
    file_url = get_wellbeing_file_url(year_str)

    file_path = download_file(file_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    return parse_loneliness(file_path)


def get_latest_self_efficacy(force_refresh: bool = False) -> pd.DataFrame:
    """Get the latest self-efficacy data.

    Downloads and parses the latest Individual Wellbeing publication to extract
    self-efficacy statistics (mean scores 5-25).

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with columns:
            - year: str (financial year)
            - self_efficacy_mean: float (mean 5-25)
            - confidence_interval: str

    Example:
        >>> df = get_latest_self_efficacy()
        >>> latest = df.iloc[-1]
        >>> print(f"Self-efficacy {latest['year']}: {latest['self_efficacy_mean']}")
    """
    _, year_str = get_latest_wellbeing_publication_url()
    file_url = get_wellbeing_file_url(year_str)

    file_path = download_file(file_url, cache_ttl_hours=90 * 24, force_refresh=force_refresh)

    return parse_self_efficacy(file_path)


def get_wellbeing_summary(force_refresh: bool = False) -> pd.DataFrame:
    """Get a summary of all wellbeing measures for the latest year.

    Combines personal wellbeing (ONS4), loneliness, and self-efficacy data
    into a single summary for the most recent year.

    Args:
        force_refresh: Force re-download even if cached

    Returns:
        DataFrame with one row containing:
            - year: str
            - life_satisfaction: float
            - worthwhile: float
            - happiness: float
            - anxiety: float
            - lonely_some_of_time: float
            - self_efficacy_mean: float

    Example:
        >>> summary = get_wellbeing_summary()
        >>> print(summary.T)  # Transpose for readable output
    """
    # Get all data
    df_personal = get_latest_personal_wellbeing(force_refresh=force_refresh)
    df_loneliness = get_latest_loneliness(force_refresh=False)  # Already cached
    df_efficacy = get_latest_self_efficacy(force_refresh=False)  # Already cached

    # Get the latest year from personal wellbeing
    latest_year = df_personal["year"].iloc[-1]

    # Build summary
    summary = {"year": latest_year}

    # Add personal wellbeing
    latest_personal = df_personal[df_personal["year"] == latest_year].iloc[0]
    for col in ["life_satisfaction", "worthwhile", "happiness", "anxiety"]:
        if col in latest_personal:
            summary[col] = latest_personal[col]

    # Add loneliness
    if latest_year in df_loneliness["year"].values:
        latest_lonely = df_loneliness[df_loneliness["year"] == latest_year].iloc[0]
        summary["lonely_some_of_time"] = latest_lonely["lonely_some_of_time"]

    # Add self-efficacy
    if latest_year in df_efficacy["year"].values:
        latest_efficacy = df_efficacy[df_efficacy["year"] == latest_year].iloc[0]
        summary["self_efficacy_mean"] = latest_efficacy["self_efficacy_mean"]

    return pd.DataFrame([summary])


def get_personal_wellbeing_by_year(df: pd.DataFrame, year: str) -> pd.DataFrame:
    """Filter personal wellbeing data for a specific year.

    Args:
        df: DataFrame from get_latest_personal_wellbeing()
        year: Financial year string (e.g., "2024/25")

    Returns:
        DataFrame filtered to the specified year

    Example:
        >>> df = get_latest_personal_wellbeing()
        >>> df_2024 = get_personal_wellbeing_by_year(df, "2024/25")
    """
    return df[df["year"] == year].copy()


def validate_personal_wellbeing(df: pd.DataFrame) -> bool:
    """Validate personal wellbeing data for consistency.

    Checks that:
    - All ONS4 measures are present
    - Scores are within expected ranges
    - No duplicate years

    Args:
        df: DataFrame from get_latest_personal_wellbeing()

    Returns:
        True if validation passes

    Raises:
        ValueError: If validation fails
    """
    required_cols = {"year", "life_satisfaction", "worthwhile", "happiness", "anxiety"}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Missing columns: {required_cols - set(df.columns)}")

    # Check score ranges (0-10 for ONS4 measures)
    for col in ["life_satisfaction", "worthwhile", "happiness", "anxiety"]:
        if col in df.columns:
            if df[col].min() < 0 or df[col].max() > 10:
                raise ValueError(f"{col} scores outside valid range 0-10")

    # Check for duplicates
    if df["year"].duplicated().any():
        raise ValueError("Duplicate years found")

    return True
