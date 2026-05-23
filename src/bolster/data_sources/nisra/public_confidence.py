"""NISRA Public Confidence in Official Statistics Module.

This module provides access to Northern Ireland's Public Awareness of and Trust
(Confidence) in Official Statistics (PCOS) data published annually by NISRA.

The report covers public awareness of and trust in official statistics,
measuring public confidence across multiple dimensions:
- Awareness of NISRA
- Trust in NISRA, Civil Service, NI Assembly, Media, and NISRA Statistics
- Value placed on NISRA statistics
- Belief in freedom from political interference
- Belief in confidentiality of personal information

Data Source: Northern Ireland Statistics and Research Agency (NISRA) publishes
annual Public Awareness of and Trust in Official Statistics (PCOS) reports.
The data is drawn from the Northern Ireland Continuous Household Survey (CHS,
2018 to present) and the Northern Ireland Omnibus Survey (2009 to 2016).

Update Frequency: Annual publications, typically in the first half of the
following calendar year (e.g., 2025 data published May 2026).

Data Coverage:
    - Awareness of NISRA: 2009 to present (back-filled in latest file)
    - Trust measures: 2014 to present (back-filled in latest file)
    - Value/Political Interference/Confidentiality: 2014/2016 to present

Examples:
    >>> from bolster.data_sources.nisra import public_confidence
    >>> df = public_confidence.get_latest_public_confidence(breakdown="awareness")
    >>> "year" in df.columns
    True
    >>> df_trust = public_confidence.get_latest_public_confidence(breakdown="trust_nisra")
    >>> "topic" in df_trust.columns
    True

Publication Details:
    - Frequency: Annual
    - Published by: NISRA
    - Survey: Northern Ireland Continuous Household Survey (CHS)
    - Topic page: https://www.nisra.gov.uk/statistics/people-and-communities/public-awareness-and-trust-confidence-official-statistics-pcos
"""

import logging
import re
from pathlib import Path

import pandas as pd

from ._base import NISRADataNotFoundError, download_file

logger = logging.getLogger(__name__)

TOPIC_URL = "https://www.nisra.gov.uk/statistics/people-and-communities/public-awareness-and-trust-confidence-official-statistics-pcos"
NISRA_BASE_URL = "https://www.nisra.gov.uk"

# Map topic keys to ODS sheet names
_TRUST_SHEET_MAP = {
    "nisra": "Trust_NISRA",
    "civil_service": "Trust_Civil_Service",
    "ni_assembly": "Trust_NI_Assembly",
    "media": "Trust_Media",
    "nisra_statistics": "Trust_NISRA_Statistics",
}


def get_latest_publication_url() -> str:
    """Scrape the PCOS topic page to find the latest ODS data file URL.

    Navigates the NISRA topic page to find the most recent publication,
    then fetches that publication's page to locate the ODS download link.

    Returns:
        URL string for the latest ODS data tables file.

    Raises:
        NISRADataNotFoundError: If unable to find the publication or ODS file.

    Example:
        >>> url = get_latest_publication_url()
        >>> url.startswith("https://")
        True
    """
    from bs4 import BeautifulSoup

    from bolster.utils.web import session

    logger.info("Fetching PCOS topic page: %s", TOPIC_URL)

    try:
        response = session.get(TOPIC_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch PCOS topic page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    # Find all links to annual publication pages
    pub_links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        m = re.search(r"public-awareness-and-trust-official-statistics-(\d{4})$", href)
        if m:
            year = int(m.group(1))
            pub_url = href if href.startswith("http") else f"{NISRA_BASE_URL}{href}"
            pub_links.append((year, pub_url))

    if not pub_links:
        raise NISRADataNotFoundError("Could not find any PCOS publication links on topic page")

    # Sort descending and take the latest
    pub_links.sort(key=lambda x: x[0], reverse=True)
    latest_year, latest_pub_url = pub_links[0]

    logger.info("Found latest PCOS publication: %d at %s", latest_year, latest_pub_url)

    # Fetch the publication page to find the ODS link
    try:
        r2 = session.get(latest_pub_url, timeout=30)
        r2.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch publication page {latest_pub_url}: {e}") from e

    soup2 = BeautifulSoup(r2.content, "html.parser")

    for a_tag in soup2.find_all("a", href=True):
        href = a_tag["href"]
        if ".ods" in href.lower():
            ods_url = href if href.startswith("http") else f"{NISRA_BASE_URL}{href}"
            logger.info("Found ODS file: %s", ods_url)
            return ods_url

    raise NISRADataNotFoundError(f"Could not find ODS file on publication page {latest_pub_url}")


def _parse_time_series_sheet(file_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """Parse a wide-format time-series sheet from the ODS file.

    Each sheet has 2–4 pre-data text rows, then a header row with
    ``Response (%)`` in column 0 and year values in subsequent columns,
    followed by data rows. Multiple tables may appear vertically separated
    by blank rows; only the first (main time-series) table is extracted.

    Args:
        file_path: Path to the ODS data tables file.
        sheet_name: Name of the sheet to parse.

    Returns:
        DataFrame with columns: ``year`` (int), ``response`` (str),
        ``percentage`` (float). Rows where ``response`` is
        ``Number of Respondents`` are excluded.

    Raises:
        NISRADataNotFoundError: If the header row cannot be found.
    """
    df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine="odf")

    # Find the header row: first row where col 0 contains "Response (%)"
    header_row_idx = None
    for idx, row in df_raw.iterrows():
        cell = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
        if "response (%)" in cell.lower():
            header_row_idx = idx
            break

    if header_row_idx is None:
        raise NISRADataNotFoundError(f"Could not find header row in sheet {sheet_name!r}")

    header_row = df_raw.iloc[header_row_idx]

    # Extract year columns: skip col 0 (Response label); take columns where header
    # looks like a year (numeric or starts with a 4-digit year)
    year_cols = {}
    for col_idx in range(1, len(header_row)):
        raw_val = header_row.iloc[col_idx]
        if pd.isna(raw_val):
            break
        # Parse year from cell — handle "2009 [Note 1]", 2012.0, "2012", etc.
        year_str = str(raw_val).strip()
        m = re.match(r"(\d{4})", year_str)
        if m:
            year_int = int(m.group(1))
            year_cols[col_idx] = year_int
        else:
            # Non-year header (e.g. "NISRA", "ONS") — stop at the first table boundary
            break

    if not year_cols:
        raise NISRADataNotFoundError(f"No year columns found in sheet {sheet_name!r}")

    # Extract data rows immediately after the header until a blank/non-data row
    records = []
    for row_idx in range(header_row_idx + 1, len(df_raw)):
        row = df_raw.iloc[row_idx]
        response = row.iloc[0]

        # Stop at blank row or when we hit a second table header
        if pd.isna(response) or str(response).strip() == "":
            break
        response_str = str(response).strip()

        # Skip the respondent count row
        if "number of respondents" in response_str.lower():
            continue

        for col_idx, year in year_cols.items():
            raw_pct = row.iloc[col_idx]
            # Skip "No data" placeholders
            if pd.isna(raw_pct) or str(raw_pct).strip().lower() in ("no data", ""):
                continue
            try:
                pct = float(raw_pct)
            except (ValueError, TypeError):
                continue
            records.append({"year": year, "response": response_str, "percentage": round(pct, 4)})

    return pd.DataFrame(records, columns=["year", "response", "percentage"])


def parse_awareness(file_path: str | Path) -> pd.DataFrame:
    """Parse NISRA awareness time-series data from the ODS file.

    Extracts the ``Awareness_of_NISRA`` sheet (Table 1a: time series 2009–present),
    converting the wide-format table to a tidy long-format DataFrame.

    Args:
        file_path: Path to the downloaded ODS data tables file.

    Returns:
        DataFrame with columns:
            - year: int (survey year, e.g. 2025)
            - response: str (e.g. ``"Yes"``, ``"No"``, ``"Don't Know"``)
            - percentage: float (rounded to 4 decimal places)

    Example:
        >>> url = get_latest_publication_url()
        >>> path = download_file(url, cache_ttl_hours=24 * 365)
        >>> df = parse_awareness(path)
        >>> set(df.columns) == {"year", "response", "percentage"}
        True
    """
    logger.info("Parsing awareness data from %s", file_path)
    df = _parse_time_series_sheet(file_path, "Awareness_of_NISRA")
    df = df.sort_values(["year", "response"]).reset_index(drop=True)
    logger.info("Parsed %d awareness records", len(df))
    return df


def parse_trust(file_path: str | Path, topic: str) -> pd.DataFrame:
    """Parse trust time-series data for a specific institution from the ODS file.

    Args:
        file_path: Path to the downloaded ODS data tables file.
        topic: Institution to parse. One of:
            ``"nisra"``, ``"civil_service"``, ``"ni_assembly"``,
            ``"media"``, ``"nisra_statistics"``.

    Returns:
        DataFrame with columns:
            - year: int (survey year)
            - response: str (e.g. ``"Tend to trust/trust a great deal"``)
            - percentage: float
            - topic: str (the ``topic`` argument)

    Raises:
        ValueError: If ``topic`` is not a valid key.
        NISRADataNotFoundError: If the sheet cannot be parsed.

    Example:
        >>> url = get_latest_publication_url()
        >>> path = download_file(url, cache_ttl_hours=24 * 365)
        >>> df = parse_trust(path, "nisra")
        >>> "topic" in df.columns
        True
    """
    if topic not in _TRUST_SHEET_MAP:
        valid = ", ".join(sorted(_TRUST_SHEET_MAP.keys()))
        raise ValueError(f"Unknown topic {topic!r}. Valid options: {valid}")

    sheet_name = _TRUST_SHEET_MAP[topic]
    logger.info("Parsing trust data for topic=%r from sheet=%r", topic, sheet_name)

    df = _parse_time_series_sheet(file_path, sheet_name)
    df["topic"] = topic
    df = df[["year", "response", "percentage", "topic"]]
    df = df.sort_values(["year", "response"]).reset_index(drop=True)

    logger.info("Parsed %d trust records for topic=%r", len(df), topic)
    return df


def get_latest_public_confidence(
    breakdown: str = "awareness",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download and parse the latest PCOS data for a given breakdown.

    Downloads the latest ODS file (cached for one year — annual data) and
    returns a tidy DataFrame for the requested breakdown.

    Args:
        breakdown: Which breakdown to return. One of:
            ``"awareness"``           — awareness of NISRA (2009–present),
            ``"trust_nisra"``         — trust in NISRA (2014–present),
            ``"trust_civil_service"`` — trust in the Civil Service,
            ``"trust_ni_assembly"``   — trust in the NI Assembly,
            ``"trust_media"``         — trust in the Media,
            ``"trust_nisra_statistics"`` — trust in NISRA statistics,
            ``"all_trust"``           — all five trust topics combined
                                        (adds ``topic`` column).
        force_refresh: If ``True``, bypass cache and re-download the file.

    Returns:
        Tidy long-format DataFrame. For ``"awareness"``: columns
        ``year``, ``response``, ``percentage``. For trust breakdowns:
        ``year``, ``response``, ``percentage``, ``topic``.

    Raises:
        ValueError: If ``breakdown`` is not a valid option.
        NISRADataNotFoundError: If the data cannot be downloaded or parsed.

    Example:
        >>> df = get_latest_public_confidence(breakdown="awareness")
        >>> sorted(df.columns.tolist())
        ['percentage', 'response', 'year']
        >>> df_trust = get_latest_public_confidence(breakdown="all_trust")
        >>> "topic" in df_trust.columns
        True
    """
    valid_breakdowns = {
        "awareness",
        "trust_nisra",
        "trust_civil_service",
        "trust_ni_assembly",
        "trust_media",
        "trust_nisra_statistics",
        "all_trust",
    }
    if breakdown not in valid_breakdowns:
        raise ValueError(f"Unknown breakdown {breakdown!r}. Valid options: {sorted(valid_breakdowns)}")

    ods_url = get_latest_publication_url()
    file_path = download_file(ods_url, cache_ttl_hours=24 * 365, force_refresh=force_refresh)

    if breakdown == "awareness":
        return parse_awareness(file_path)

    if breakdown == "all_trust":
        frames = []
        for topic_key in _TRUST_SHEET_MAP:
            try:
                frames.append(parse_trust(file_path, topic_key))
            except NISRADataNotFoundError as e:
                logger.warning("Skipping topic %r: %s", topic_key, e)
        if not frames:
            raise NISRADataNotFoundError("Could not parse any trust topics")
        return pd.concat(frames, ignore_index=True).sort_values(["topic", "year", "response"]).reset_index(drop=True)

    # Single trust topic: strip "trust_" prefix
    topic_key = breakdown.removeprefix("trust_")
    return parse_trust(file_path, topic_key)


def validate_public_confidence(df: pd.DataFrame) -> bool:
    """Validate a public confidence DataFrame for required structure and value ranges.

    Checks that:
    - DataFrame is not empty.
    - Required columns are present (``year``, ``response``, ``percentage``).
    - All ``percentage`` values are in the range [0, 100].
    - The ``year`` column contains only integers.

    Args:
        df: DataFrame from :func:`get_latest_public_confidence` or the
            individual parse functions.

    Returns:
        ``True`` if all checks pass.

    Raises:
        ValueError: If any check fails, with a descriptive message.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({"year": [2025], "response": ["Yes"], "percentage": [48.1]})
        >>> validate_public_confidence(df)
        True
    """
    if df.empty:
        raise ValueError("DataFrame is empty")

    required = {"year", "response", "percentage"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    pct = df["percentage"]
    if (pct < 0).any() or (pct > 100).any():
        bad = df[(pct < 0) | (pct > 100)]["percentage"].tolist()
        raise ValueError(f"Percentage values out of range [0, 100]: {bad[:5]}")

    return True
