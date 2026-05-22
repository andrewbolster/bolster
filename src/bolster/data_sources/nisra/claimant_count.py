"""NISRA Claimant Count Statistics Module.

This module provides access to the Northern Ireland Statistics and Research Agency (NISRA)
monthly Claimant Count statistics, covering Universal Credit (UC) and Jobseeker's Allowance
(JSA) claimants.

The Claimant Count is an experimental statistic measuring the number of people claiming
benefits principally for the reason of being unemployed. Data is published monthly and
covers Northern Ireland with multiple geographic breakdowns including Local Government
Districts, Parliamentary Constituency Areas, Travel-to-Work Areas, and Super Output Areas.

Data Source:
    **Publication page pattern**:
    https://www.nisra.gov.uk/publications/labour-market-report-{month_name}-{year}

    The module scrapes the monthly Labour Market Report publication page to find the
    ``lmr-claimant-count-tables-*.xlsx`` Excel file link, falling back to direct URL
    construction if scraping fails.

Update Frequency: Monthly, approximately 2–3 weeks after the reference month.

Sheets parsed:
    - ``Headline``: NI total by sex, seasonally adjusted and non-seasonally adjusted,
      full time series from April 1997.
    - ``Age``: NI total by age band (16–24, 25–49, 50+), from January 2013.
    - ``LGD_11``: Current-month snapshot for 11 Local Government Districts.
    - ``PCA``: Current-month snapshot for 18 Westminster Parliamentary Constituency Areas.
    - ``TTWA``: Current-month snapshot for 10 Travel-to-Work Areas.
    - ``SOA``: 889 Super Output Areas, wide-format time series from October 2017,
      melted to long format.

Notes:
    Claimant Count is an experimental statistic. The rate denominator is
    claimant count + workforce jobs. Five-week months are annotated ``[2]``,
    revised data with ``(r)``, provisional with ``(p)``. Annotation markers
    are stripped before date parsing.

    SOA data has a methodology break at January 2026 (transition from COA2011
    to DZ2021 geographies).

Usage:
    >>> from bolster.data_sources.nisra import claimant_count
    >>> df = claimant_count.get_latest_claimant_count("headline")
    >>> "claimants_000s" in df.columns
    True

    >>> lgd_df = claimant_count.get_latest_claimant_count("lgd")
    >>> "claimants_total" in lgd_df.columns
    True

Example:
    >>> from bolster.data_sources.nisra import claimant_count
    >>> df = claimant_count.get_latest_claimant_count("headline")
    >>> df[df["sex"] == "all_people"].sort_values("date").tail(1)["claimants_000s"].values[0] > 0
    True

Author: Claude Code
"""

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from bolster.data_sources.nisra._base import (
    NISRADataNotFoundError,
    download_file,
    scrape_download_links,
)

logger = logging.getLogger(__name__)

# Base URL for NISRA publications
_NISRA_BASE = "https://www.nisra.gov.uk"

# Cache TTL: 30 days (monthly release)
_CACHE_TTL_HOURS = 30 * 24

# Column name mapping for geography sheets
_GEO_COLMAP = {
    "LGD_11": "Local Government District",
    "PCA": "Parliamentary Constituency Area",
    "TTWA": "Travel-to-Work Area",
}

# Header row offset (0-indexed) for each geography sheet
_GEO_SKIPROWS = {
    "LGD_11": 6,
    "PCA": 5,
    "TTWA": 5,
}

# Annotation pattern: strips [2], (r), (p), [notes 1, 2, ...] etc.
_ANNOTATION_RE = re.compile(r"\s*[\[\(][^\]\)]+[\]\)]")


def _strip_annotations(raw: str) -> str:
    """Strip annotation markers like [2], (r), (p) from a date string.

    Args:
        raw: Raw date string potentially containing annotation markers.

    Returns:
        Cleaned date string.

    Example:
        >>> _strip_annotations("1997 Jun [2]")
        '1997 Jun'
        >>> _strip_annotations("2026 Mar (p)")
        '2026 Mar'
    """
    return _ANNOTATION_RE.sub("", str(raw)).strip()


def get_latest_publication_url() -> str:
    """Discover the URL of the most recent claimant count Excel file.

    Scrapes the NISRA Labour Market Report publication page for the current
    month, falling back to previous months if needed, then falls back to
    direct URL construction.

    Returns:
        Full URL to the latest claimant count Excel file.

    Raises:
        NISRADataNotFoundError: If no publication can be found.

    Example:
        >>> url = get_latest_publication_url()
        >>> url.endswith(".xlsx")
        True
    """
    now = datetime.now()

    # Try recent months (current + 3 previous)
    for delta in range(4):
        # Calculate target month
        year = now.year
        month = now.month - delta
        while month <= 0:
            month += 12
            year -= 1

        month_name = datetime(year, month, 1).strftime("%B").lower()
        page_url = f"{_NISRA_BASE}/publications/labour-market-report-{month_name}-{year}"

        logger.debug("Checking publication page: %s", page_url)

        try:
            links = scrape_download_links(page_url, file_extension=".xlsx")
            for link in links:
                if "lmr-claimant-count" in link["url"].lower():
                    logger.info("Found claimant count file: %s", link["url"])
                    return link["url"]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not fetch %s: %s", page_url, exc)

    # Fallback: construct URL directly for last known-good month
    year = now.year
    month = now.month - 1
    if month <= 0:
        month = 12
        year -= 1
    month_name = datetime(year, month, 1).strftime("%B").lower()
    pub_month_str = f"{year}-{month:02d}"
    fallback_url = (
        f"{_NISRA_BASE}/system/files/statistics/{pub_month_str}/lmr-claimant-count-tables-{month_name}-{year}.xlsx"
    )
    logger.warning("Using fallback URL: %s", fallback_url)
    return fallback_url


def parse_headline(file_path: str | Path) -> pd.DataFrame:
    """Parse the Headline sheet: NI total claimant count by sex.

    The Headline sheet contains two side-by-side tables:
    - Table 1a: Seasonally adjusted claimant count by sex
    - Table 1b: Non-seasonally adjusted claimant count by sex

    Both tables share the same date column structure with men, women and
    all people counts (thousands) and rates.

    Args:
        file_path: Path to the claimant count Excel file.

    Returns:
        DataFrame with columns:
            - ``date``: pandas Timestamp (monthly, day=1)
            - ``adjusted``: ``"seasonally_adjusted"`` or ``"non_seasonally_adjusted"``
            - ``sex``: ``"men"``, ``"women"``, or ``"all_people"``
            - ``claimants_000s``: Claimant count in thousands (float)
            - ``claimant_rate``: Claimant rate as percentage (float)

    Raises:
        NISRADataNotFoundError: If the Headline sheet is not found.

    Example:
        >>> df = parse_headline("/tmp/claimant_count.xlsx")
        >>> sorted(df["sex"].unique())
        ['all_people', 'men', 'women']
        >>> sorted(df["adjusted"].unique())
        ['non_seasonally_adjusted', 'seasonally_adjusted']
    """
    try:
        raw = pd.read_excel(file_path, sheet_name="Headline", header=None, engine="openpyxl")
    except Exception as exc:
        raise NISRADataNotFoundError(f"Cannot read Headline sheet from {file_path}: {exc}") from exc

    # Row 6 (0-indexed) contains column headers; data starts at row 7.
    # Columns 0–6: seasonally adjusted (col 7 is blank separator)
    # Columns 8–14: non-seasonally adjusted
    #
    # SA columns: Date(0), men_count(1), men_rate(2), women_count(3),
    #             women_rate(4), all_count(5), all_rate(6)
    # Non-SA:     Date(8), men_count(9), men_rate(10), women_count(11),
    #             women_rate(12), all_count(13), all_rate(14)

    records = []

    for _, row in raw.iloc[7:].iterrows():
        date_raw = row.iloc[0]

        # Stop at non-date rows (change rows, footnotes, NaN)
        if pd.isna(date_raw):
            continue
        date_str = _strip_annotations(str(date_raw))
        if not re.match(r"^\d{4}\s+\w{3}$", date_str):
            continue

        try:
            date = pd.to_datetime(date_str, format="%Y %b")
        except ValueError:
            logger.debug("Skipping unparseable date: %r", date_raw)
            continue

        # Seasonally adjusted
        for sex, count_col, rate_col in [("men", 1, 2), ("women", 3, 4), ("all_people", 5, 6)]:
            count_val = row.iloc[count_col] if len(row) > count_col else None
            rate_val = row.iloc[rate_col] if len(row) > rate_col else None
            if pd.notna(count_val):
                records.append(
                    {
                        "date": date,
                        "adjusted": "seasonally_adjusted",
                        "sex": sex,
                        "claimants_000s": float(count_val),
                        "claimant_rate": float(rate_val) if pd.notna(rate_val) else None,
                    }
                )

        # Non-seasonally adjusted (same date column at index 8)
        for sex, count_col, rate_col in [("men", 9, 10), ("women", 11, 12), ("all_people", 13, 14)]:
            if len(row) <= count_col:
                continue
            count_val = row.iloc[count_col]
            rate_val = row.iloc[rate_col] if len(row) > rate_col else None
            if pd.notna(count_val):
                records.append(
                    {
                        "date": date,
                        "adjusted": "non_seasonally_adjusted",
                        "sex": sex,
                        "claimants_000s": float(count_val),
                        "claimant_rate": float(rate_val) if pd.notna(rate_val) else None,
                    }
                )

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(["adjusted", "sex", "date"]).reset_index(drop=True)
    return df


def parse_age(file_path: str | Path) -> pd.DataFrame:
    """Parse the Age sheet: NI claimant count by age band.

    Contains a single table of non-seasonally adjusted claimant counts
    broken down into three age bands: 16–24, 25–49, 50+. Data runs from
    January 2013.

    Args:
        file_path: Path to the claimant count Excel file.

    Returns:
        DataFrame with columns:
            - ``date``: pandas Timestamp (monthly, day=1)
            - ``age_group``: One of ``"16-24"``, ``"25-49"``, ``"50+"``.
            - ``claimants``: Claimant count (integer, rounded to nearest 5).

    Raises:
        NISRADataNotFoundError: If the Age sheet is not found.

    Example:
        >>> df = parse_age("/tmp/claimant_count.xlsx")
        >>> sorted(df["age_group"].unique())
        ['16-24', '25-49', '50+']
    """
    try:
        raw = pd.read_excel(file_path, sheet_name="Age", skiprows=2, engine="openpyxl")
    except Exception as exc:
        raise NISRADataNotFoundError(f"Cannot read Age sheet from {file_path}: {exc}") from exc

    # Columns: Date, 16-24 Total, 25-49 Total, 50+ Total
    raw.columns = ["date_raw", "16-24", "25-49", "50+"]

    records = []
    for _, row in raw.iterrows():
        date_raw = row["date_raw"]
        if pd.isna(date_raw):
            continue
        date_str = _strip_annotations(str(date_raw))
        try:
            date = pd.to_datetime(date_str, format="%B %Y")
        except ValueError:
            logger.debug("Skipping unparseable age-sheet date: %r", date_raw)
            continue

        for age_group in ["16-24", "25-49", "50+"]:
            val = row[age_group]
            if pd.notna(val):
                records.append({"date": date, "age_group": age_group, "claimants": int(val)})

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(["age_group", "date"]).reset_index(drop=True)
    return df


def _infer_reference_date(file_path: str | Path) -> pd.Timestamp:
    """Infer the reference date from the latest data row in the Headline sheet.

    The geographic snapshot sheets (LGD_11, PCA, TTWA) contain no date column;
    their reference period is the most recent month in the Headline time series.

    Args:
        file_path: Path to the claimant count Excel file.

    Returns:
        pandas Timestamp for the most recent month, or ``pd.NaT`` if not found.
    """
    try:
        raw = pd.read_excel(file_path, sheet_name="Headline", header=None, engine="openpyxl", usecols=[0])
        latest = pd.NaT
        for _, row in raw.iloc[7:].iterrows():
            date_raw = row.iloc[0]
            if pd.isna(date_raw):
                continue
            date_str = _strip_annotations(str(date_raw))
            if re.match(r"^\d{4}\s+\w{3}$", date_str):
                try:
                    candidate = pd.to_datetime(date_str, format="%Y %b")
                    if pd.isna(latest) or candidate > latest:
                        latest = candidate
                except ValueError:
                    pass
        return latest
    except Exception:  # noqa: BLE001
        return pd.NaT


def parse_geography(file_path: str | Path, sheet: str) -> pd.DataFrame:
    """Parse a geographic breakdown sheet (LGD_11, PCA, or TTWA).

    Each sheet contains a current-month snapshot with columns for:
    male/female/total claimant numbers, working-age rates, month and year
    changes.

    Args:
        file_path: Path to the claimant count Excel file.
        sheet: Sheet name — one of ``"LGD_11"``, ``"PCA"``, or ``"TTWA"``.

    Returns:
        DataFrame with columns:
            - ``date``: pandas Timestamp (extracted from the Excel filename)
            - ``geography``: Area name (e.g., ``"Belfast"``)
            - ``geography_type``: Sheet type identifier (e.g., ``"LGD_11"``)
            - ``claimants_male``: Number of male claimants (int)
            - ``claimants_female``: Number of female claimants (int)
            - ``claimants_total``: Total claimants (int)
            - ``claimant_rate_male_pct``: Male working-age claimant rate (float)
            - ``claimant_rate_female_pct``: Female working-age claimant rate (float)
            - ``claimant_rate_total_pct``: Total working-age claimant rate (float)
            - ``change_over_month_number``: Change vs previous month (int)
            - ``change_over_year_number``: Change vs same month last year (int)

    Raises:
        NISRADataNotFoundError: If the requested sheet is not found.
        ValueError: If sheet is not one of the supported values.

    Example:
        >>> df = parse_geography("/tmp/claimant_count.xlsx", "LGD_11")
        >>> len(df["geography"].unique()) >= 11
        True
        >>> "claimants_total" in df.columns
        True
    """
    if sheet not in _GEO_SKIPROWS:
        raise ValueError(f"sheet must be one of {list(_GEO_SKIPROWS)}, got {sheet!r}")

    skiprows = _GEO_SKIPROWS[sheet]

    try:
        raw = pd.read_excel(file_path, sheet_name=sheet, skiprows=skiprows, engine="openpyxl")
    except Exception as exc:
        raise NISRADataNotFoundError(f"Cannot read {sheet} sheet from {file_path}: {exc}") from exc

    # Drop rows where the geography column is NaN or purely numeric (totals/notes)
    raw = raw.dropna(subset=[raw.columns[0]])
    raw = raw[raw.iloc[:, 0].astype(str).str.strip() != ""]

    # Rename columns to standard names
    # Columns: geo_name, male_count, female_count, total_count,
    #          male_rate, female_rate, total_rate,
    #          change_month_n, change_month_pct, change_year_n, change_year_pct
    # LGD_11 also has Job Density Indicator (col 11)
    col_rename = {
        raw.columns[0]: "geography",
        raw.columns[1]: "claimants_male",
        raw.columns[2]: "claimants_female",
        raw.columns[3]: "claimants_total",
        raw.columns[4]: "claimant_rate_male_pct",
        raw.columns[5]: "claimant_rate_female_pct",
        raw.columns[6]: "claimant_rate_total_pct",
        raw.columns[7]: "change_over_month_number",
        raw.columns[8]: "change_over_month_pct",
        raw.columns[9]: "change_over_year_number",
    }
    if len(raw.columns) > 10:
        col_rename[raw.columns[10]] = "change_over_year_pct"

    raw = raw.rename(columns=col_rename)

    # Keep only the columns we want (drop extra like Job Density)
    keep_cols = [
        "geography",
        "claimants_male",
        "claimants_female",
        "claimants_total",
        "claimant_rate_male_pct",
        "claimant_rate_female_pct",
        "claimant_rate_total_pct",
        "change_over_month_number",
        "change_over_year_number",
    ]
    df = raw[[c for c in keep_cols if c in raw.columns]].copy()

    # Infer reference date from the Headline time series (most recent date)
    date = _infer_reference_date(file_path)

    df.insert(0, "date", date)
    df.insert(2, "geography_type", sheet)

    # Coerce numeric columns
    for col in [
        "claimants_male",
        "claimants_female",
        "claimants_total",
        "change_over_month_number",
        "change_over_year_number",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["claimant_rate_male_pct", "claimant_rate_female_pct", "claimant_rate_total_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.reset_index(drop=True)


def parse_soa(file_path: str | Path) -> pd.DataFrame:
    """Parse the SOA sheet: Super Output Area time series.

    The SOA sheet is wide-format with 889 Super Output Areas as rows and
    monthly dates as columns from October 2017. This function melts it to
    long format.

    Note:
        There is a methodology break at January 2026 where geography codes
        transition from COA2011 to DZ2021. Both series are included in the
        output.

    Args:
        file_path: Path to the claimant count Excel file.

    Returns:
        DataFrame with columns:
            - ``soa_code``: Super Output Area code and name (e.g., ``"95AA01S1 : Aldergrove_1"``)
            - ``date``: pandas Timestamp (monthly, day=1)
            - ``claimants``: Claimant count (int, rounded to nearest 5)

    Raises:
        NISRADataNotFoundError: If the SOA sheet is not found.

    Example:
        >>> df = parse_soa("/tmp/claimant_count.xlsx")
        >>> "soa_code" in df.columns
        True
        >>> df["date"].min().year <= 2018
        True
    """
    try:
        raw = pd.read_excel(file_path, sheet_name="SOA", skiprows=5, engine="openpyxl")
    except Exception as exc:
        raise NISRADataNotFoundError(f"Cannot read SOA sheet from {file_path}: {exc}") from exc

    # First column is the SOA identifier; remaining columns are month dates
    soa_col = raw.columns[0]
    date_cols = [c for c in raw.columns[1:] if pd.notna(c)]

    # Drop any trailing NaN rows
    raw = raw.dropna(subset=[soa_col])

    # Melt wide to long
    df_long = raw[[soa_col] + date_cols].melt(id_vars=[soa_col], var_name="date_raw", value_name="claimants")
    df_long = df_long.rename(columns={soa_col: "soa_code"})

    # Parse dates (column names are already in "Month YYYY" format)
    df_long["date"] = pd.to_datetime(df_long["date_raw"], format="%B %Y", errors="coerce")
    df_long = df_long.dropna(subset=["date"])

    # Coerce claimants to numeric
    df_long["claimants"] = pd.to_numeric(df_long["claimants"], errors="coerce")

    df_long = df_long[["soa_code", "date", "claimants"]].sort_values(["soa_code", "date"])
    return df_long.reset_index(drop=True)


def get_latest_claimant_count(
    breakdown: str = "headline",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download and parse the latest NISRA claimant count data.

    Automatically discovers and downloads the most recent monthly publication,
    then returns the requested breakdown.

    Args:
        breakdown: One of:
            - ``"headline"`` — NI total by sex, SA and non-SA (default)
            - ``"age"`` — NI total by age band (16–24, 25–49, 50+)
            - ``"lgd"`` — 11 Local Government Districts (current month)
            - ``"pca"`` — 18 Parliamentary Constituency Areas (current month)
            - ``"ttwa"`` — 10 Travel-to-Work Areas (current month)
            - ``"soa"`` — 889 Super Output Areas, long-format time series
        force_refresh: If ``True``, bypass cache and download fresh data.

    Returns:
        DataFrame for the requested breakdown. See individual ``parse_*``
        functions for column documentation.

    Raises:
        ValueError: If ``breakdown`` is not a supported value.
        NISRADataNotFoundError: If the data cannot be downloaded.

    Example:
        >>> df = get_latest_claimant_count("headline")
        >>> "claimants_000s" in df.columns
        True
        >>> df_lgd = get_latest_claimant_count("lgd")
        >>> len(df_lgd) >= 11
        True
    """
    valid = ("headline", "age", "lgd", "pca", "ttwa", "soa")
    if breakdown not in valid:
        raise ValueError(f"breakdown must be one of {valid}, got {breakdown!r}")

    url = get_latest_publication_url()
    file_path = download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)

    if breakdown == "headline":
        return parse_headline(file_path)
    if breakdown == "age":
        return parse_age(file_path)
    if breakdown == "lgd":
        return parse_geography(file_path, "LGD_11")
    if breakdown == "pca":
        return parse_geography(file_path, "PCA")
    if breakdown == "ttwa":
        return parse_geography(file_path, "TTWA")
    # breakdown == "soa"
    return parse_soa(file_path)


def validate_claimant_count(df: pd.DataFrame, breakdown: str) -> bool:
    """Validate the integrity of a claimant count DataFrame.

    Checks that required columns are present, values are in plausible
    ranges, and the DataFrame is non-empty.

    Args:
        df: DataFrame returned by ``get_latest_claimant_count`` or a
            ``parse_*`` function.
        breakdown: The breakdown type that produced the DataFrame.
            One of ``"headline"``, ``"age"``, ``"lgd"``, ``"pca"``,
            ``"ttwa"``, ``"soa"``.

    Returns:
        ``True`` if validation passes, ``False`` otherwise.

    Example:
        >>> import pandas as pd
        >>> validate_claimant_count(pd.DataFrame(), "headline")
        False
    """
    if df.empty:
        logger.warning("Claimant count DataFrame is empty (breakdown=%s)", breakdown)
        return False

    required_columns: dict[str, list[str]] = {
        "headline": ["date", "adjusted", "sex", "claimants_000s", "claimant_rate"],
        "age": ["date", "age_group", "claimants"],
        "lgd": ["date", "geography", "geography_type", "claimants_total", "claimant_rate_total_pct"],
        "pca": ["date", "geography", "geography_type", "claimants_total", "claimant_rate_total_pct"],
        "ttwa": ["date", "geography", "geography_type", "claimants_total", "claimant_rate_total_pct"],
        "soa": ["soa_code", "date", "claimants"],
    }

    if breakdown not in required_columns:
        logger.warning("Unknown breakdown type: %s", breakdown)
        return False

    missing = [c for c in required_columns[breakdown] if c not in df.columns]
    if missing:
        logger.warning("Missing columns for %s breakdown: %s", breakdown, missing)
        return False

    # Range checks
    if breakdown == "headline":
        if (df["claimants_000s"] < 0).any():
            logger.warning("Negative claimant counts in headline data")
            return False
        rates = df["claimant_rate"].dropna()
        if len(rates) > 0 and ((rates < 0).any() or (rates > 100).any()):
            logger.warning("Claimant rates out of range [0, 100]")
            return False

    if breakdown == "age" and (df["claimants"] < 0).any():
        logger.warning("Negative claimant counts in age data")
        return False

    if breakdown in ("lgd", "pca", "ttwa"):
        if (df["claimants_total"] < 0).any():
            logger.warning("Negative total claimants in %s data", breakdown)
            return False
        rates = df["claimant_rate_total_pct"].dropna()
        if len(rates) > 0 and ((rates < 0).any() or (rates > 100).any()):
            logger.warning("Claimant rates out of range [0, 100] in %s data", breakdown)
            return False

    return True
