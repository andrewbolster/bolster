"""NISRA Raw Disease Prevalence Module.

Provides access to Northern Ireland's raw disease prevalence statistics
published annually by the Department of Health.  The data originate from
General Practice clinical disease registers (Quality & Outcomes Framework,
QOF) and are released once per year after National Prevalence Day.

Data Coverage:
    - Financial years 2004/05 to 2025/26 (22 years, extended annually)
    - NI-level summary: registered patients per disease register (Table 1)
      and prevalence per 1,000 patients (Table 2a)
    - 26 named disease registers; 14 are active as of 2025/26

Data Source:
    Department of Health Northern Ireland publishes an Excel workbook via
    https://www.health-ni.gov.uk/articles/prevalence-statistics.  The
    landing page links to a publications page which hosts the Excel file.

Update Frequency:
    Annual, approximately May of the following calendar year.

Example:
    >>> from bolster.data_sources.nisra import disease_prevalence as dp
    >>> df = dp.get_latest_disease_prevalence()
    >>> 'registered_patients' in df.columns
    True
    >>> 'prevalence_per_1000' in df.columns
    True

Publication Details:
    - Frequency: Annual
    - Published by: Department of Health / NISRA
    - Source: https://www.health-ni.gov.uk/articles/prevalence-statistics
"""

import logging

import pandas as pd

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

# ── URLs ──────────────────────────────────────────────────────────────────────
DOH_LANDING_PAGE = "https://www.health-ni.gov.uk/articles/prevalence-statistics"
DOH_BASE_URL = "https://www.health-ni.gov.uk"

# ── Sheet names ───────────────────────────────────────────────────────────────
_SHEET_TABLE1 = "Table 1 Prevalence Registers"
_SHEET_TABLE2 = "Table 2 Prevalence per 1000 pts"

# Cache TTL: annual publication → 24*365 hours
_CACHE_TTL = 24 * 365

# ── Register name normalisation ───────────────────────────────────────────────
# Maps raw Excel names → canonical names used in the output DataFrame.
# Only applied where names clearly differ from the canonical set.
_REGISTER_NORMALISE: dict[str, str] = {
    "Diabetes 17+": "Diabetes",
    "Stroke & TIA": "Stroke/TIA",
    "Mental Health": "Mental Health (Serious)",
    "Chronic Kidney Disease 18+": "Chronic Kidney Disease (CKD 18+)",
}


def _normalise_register(name: str) -> str:
    """Apply canonical register name mapping if available, else return as-is.

    Args:
        name: Raw register name from Excel workbook.

    Returns:
        Canonical register name, or the original string if no mapping exists.
    """
    return _REGISTER_NORMALISE.get(name, name)


def get_latest_publication_url() -> str:
    """Return the URL of the most recent disease prevalence Excel workbook.

    Scrapes the Department of Health landing page, follows the first link
    to a publications page, and returns the .xlsx download URL found there.

    Returns:
        Absolute URL of the latest Excel workbook.

    Raises:
        NISRADataNotFoundError: If the Excel link cannot be located.

    Example:
        >>> url = get_latest_publication_url()
        >>> url.endswith(".xlsx")
        True
    """
    from bs4 import BeautifulSoup

    logger.info("Fetching disease prevalence landing page: %s", DOH_LANDING_PAGE)
    try:
        resp = session.get(DOH_LANDING_PAGE, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch disease prevalence landing page: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")

    # The landing page lists publication links – we want the latest year link
    pub_url: str | None = None
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # Look for a publications link that mentions raw disease prevalence
        if "publications" in href and "disease-prevalence" in href:
            pub_url = href if href.startswith("http") else f"{DOH_BASE_URL}{href}"
            break

    if pub_url is None:
        raise NISRADataNotFoundError(f"Could not find a publications link for disease prevalence on {DOH_LANDING_PAGE}")

    logger.info("Fetching publications page: %s", pub_url)
    try:
        pub_resp = session.get(pub_url, timeout=30)
        pub_resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch disease prevalence publications page {pub_url}: {exc}") from exc

    pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
    for a in pub_soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".xlsx"):
            return href if href.startswith("http") else f"{DOH_BASE_URL}{href}"

    raise NISRADataNotFoundError(f"Could not find an .xlsx link on disease prevalence publications page {pub_url}")


def _parse_table1(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse the wide-format Table 1 (registered patients) into long format.

    Args:
        raw: Raw DataFrame from pd.read_excel with header=None.

    Returns:
        Long-format DataFrame with columns: financial_year, year, register,
        registered_patients.
    """
    # Year headers are in row 3, starting from column 2
    year_labels: list[str] = [str(v) for v in raw.iloc[3, 2:] if pd.notna(v) and str(v).strip()]

    # Register rows: col 1 contains the name, data starts at col 2
    # Rows 4–29 cover the register data; stop at any row where col 1 looks like
    # a footnote (contains "Data Source", "Note", "Shaded", "Hashed").
    _STOP_WORDS = ("data source", "note", "shaded", "hashed")
    records: list[dict] = []
    for row_idx in range(4, len(raw)):
        register_raw = raw.iloc[row_idx, 1]
        if pd.isna(register_raw) or not str(register_raw).strip():
            continue
        register_str = str(register_raw).strip()
        if any(sw in register_str.lower() for sw in _STOP_WORDS):
            break  # Footer rows reached – we're done

        # Extract values for each year column
        for col_offset, fin_year in enumerate(year_labels):
            col_idx = 2 + col_offset
            val = raw.iloc[row_idx, col_idx] if col_idx < raw.shape[1] else None
            try:
                float_val = float(val) if pd.notna(val) else float("nan")
            except (TypeError, ValueError):
                float_val = float("nan")

            records.append(
                {
                    "financial_year": fin_year,
                    "year": int(fin_year.split("/")[0]),
                    "register": _normalise_register(register_str),
                    "registered_patients": float_val,
                }
            )

    return pd.DataFrame(records)


def _parse_table2(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse the wide-format Table 2a (prevalence per 1,000) into long format.

    Only Table 2a (full registered list, all ages) is extracted; Table 2b
    (age-specific denominators) is intentionally omitted.

    Args:
        raw: Raw DataFrame from pd.read_excel with header=None.

    Returns:
        Long-format DataFrame with columns: financial_year, year, register,
        prevalence_per_1000.
    """
    # Table 2a years are in row 5, starting from column 2
    year_labels: list[str] = [str(v) for v in raw.iloc[5, 2:] if pd.notna(v) and str(v).strip()]

    _STOP_WORDS = ("shaded", "hashed", "data source", "note", "table 2b", "denominator")
    records: list[dict] = []
    for row_idx in range(6, len(raw)):
        register_raw = raw.iloc[row_idx, 1]
        if pd.isna(register_raw) or not str(register_raw).strip():
            continue
        register_str = str(register_raw).strip()
        if any(sw in register_str.lower() for sw in _STOP_WORDS):
            break

        for col_offset, fin_year in enumerate(year_labels):
            col_idx = 2 + col_offset
            val = raw.iloc[row_idx, col_idx] if col_idx < raw.shape[1] else None
            try:
                float_val = float(val) if pd.notna(val) else float("nan")
            except (TypeError, ValueError):
                float_val = float("nan")

            records.append(
                {
                    "financial_year": fin_year,
                    "year": int(fin_year.split("/")[0]),
                    "register": _normalise_register(register_str),
                    "prevalence_per_1000": float_val,
                }
            )

    return pd.DataFrame(records)


def parse_ni_summary(file_path) -> pd.DataFrame:
    """Parse Table 1 and Table 2 from the disease prevalence Excel workbook.

    Reads both NI-level summary sheets and returns a single merged long-format
    DataFrame with one row per (financial_year, register) combination.

    Args:
        file_path: Path-like object or string pointing to the downloaded .xlsx
            workbook.

    Returns:
        DataFrame with columns:
            - year (int): Start year of the financial year (e.g. 2004 for "2004/05")
            - financial_year (str): Financial year label (e.g. "2004/05")
            - register (str): Normalised disease register name
            - registered_patients (float): Number of patients on the register
              at National Prevalence Day (NaN if not available for that year)
            - prevalence_per_1000 (float): Prevalence per 1,000 registered
              patients (NaN if not available for that year)

        Rows are sorted by register, then year.

    Raises:
        NISRADataNotFoundError: If the expected sheets are not found.
        NISRAValidationError: If the parsed data fails basic sanity checks.

    Example:
        >>> df = parse_ni_summary("/tmp/rdptd-tables-2026.xlsx")
        >>> set(df.columns) >= {"year", "financial_year", "register",
        ...                     "registered_patients", "prevalence_per_1000"}
        True
    """
    try:
        raw1 = pd.read_excel(file_path, sheet_name=_SHEET_TABLE1, header=None)
        raw2 = pd.read_excel(file_path, sheet_name=_SHEET_TABLE2, header=None)
    except ValueError as exc:
        raise NISRADataNotFoundError(f"Expected sheets not found in workbook {file_path}: {exc}") from exc

    t1 = _parse_table1(raw1)
    t2 = _parse_table2(raw2)

    if t1.empty:
        raise NISRAValidationError("Table 1 (registered patients) parsed to empty DataFrame")
    if t2.empty:
        raise NISRAValidationError("Table 2 (prevalence per 1,000) parsed to empty DataFrame")

    merged = pd.merge(
        t1,
        t2[["financial_year", "register", "prevalence_per_1000"]],
        on=["financial_year", "register"],
        how="outer",
    )

    return (
        merged[["year", "financial_year", "register", "registered_patients", "prevalence_per_1000"]]
        .sort_values(["register", "year"])
        .reset_index(drop=True)
    )


def get_latest_disease_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch and return the latest NI disease prevalence data.

    Downloads the current Excel workbook from the Department of Health
    website (with a 24×365-hour cache), parses both NI-level summary
    tables, validates the result, and returns a clean long-format DataFrame.

    Args:
        force_refresh: If True, bypass the local file cache and re-download
            the workbook.  Default: False.

    Returns:
        DataFrame with columns:
            - year (int): Start year of the financial year
            - financial_year (str): Label such as "2004/05"
            - register (str): Disease register name (normalised)
            - registered_patients (float): Patients on register at NPD
            - prevalence_per_1000 (float): Prevalence per 1,000 registered pts

        Data spans 2004/05 to the latest published year.

    Raises:
        NISRADataNotFoundError: If the workbook cannot be located or downloaded.
        NISRAValidationError: If the parsed data fails validation.

    Example:
        >>> df = get_latest_disease_prevalence()
        >>> df["register"].nunique() >= 14
        True
        >>> df["year"].min() <= 2004
        True
    """
    url = get_latest_publication_url()
    logger.info("Downloading disease prevalence workbook from %s", url)
    file_path = download_file(url, cache_ttl_hours=_CACHE_TTL, force_refresh=force_refresh)
    df = parse_ni_summary(file_path)
    validate_disease_prevalence(df)
    return df


def validate_disease_prevalence(df: pd.DataFrame) -> bool:
    """Validate the disease prevalence DataFrame for internal consistency.

    Checks that required columns are present, the DataFrame is non-empty,
    has sufficient temporal coverage, and that key numeric fields are within
    plausible bounds.

    Args:
        df: DataFrame as returned by :func:`parse_ni_summary` or
            :func:`get_latest_disease_prevalence`.

    Returns:
        True if all checks pass.

    Raises:
        NISRAValidationError: Describing the first failing check.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     "year": [2004], "financial_year": ["2004/05"],
        ...     "register": ["Hypertension"],
        ...     "registered_patients": [184824.0],
        ...     "prevalence_per_1000": [102.9],
        ... })
        >>> validate_disease_prevalence(df)
        True
    """
    required = {"year", "financial_year", "register", "registered_patients", "prevalence_per_1000"}
    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if df["register"].nunique() < 5:
        raise NISRAValidationError(f"Too few disease registers: expected ≥ 5, got {df['register'].nunique()}")

    if df["financial_year"].nunique() < 10:
        raise NISRAValidationError(f"Too few financial years: expected ≥ 10, got {df['financial_year'].nunique()}")

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
