"""NISRA Raw Disease Prevalence Module.

Provides access to Northern Ireland's raw disease prevalence statistics
published annually by the Department of Health.  The data originate from
General Practice clinical disease registers (Quality & Outcomes Framework,
QOF) and are released once per year after National Prevalence Day.

Data Coverage:
    - Financial years 2004/05 to 2025/26 (22 years, extended annually)
    - NI-level summary: registered patients per disease register (Table 1)
      and prevalence per 1,000 patients (Table 2a)
    - GP practice-level: same metrics per practice (Table 5a–5q), 2009/10–2025/26
    - 26 named disease registers; 14 are active as of 2025/26
    - ~305–360 GP practices per year

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
_SHEET_TABLE4 = "Table 4 GP practice details"

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


def validate_disease_prevalence(df: pd.DataFrame, level: str = "ni") -> bool:
    """Validate the disease prevalence DataFrame for internal consistency.

    Checks that required columns are present, the DataFrame is non-empty,
    has sufficient temporal coverage, and that key numeric fields are within
    plausible bounds.

    Args:
        df: DataFrame as returned by :func:`parse_ni_summary`,
            :func:`get_latest_disease_prevalence`, :func:`parse_all_gp_practices`,
            or :func:`get_latest_gp_prevalence`.
        level: Validation mode — ``"ni"`` (default) for NI-level summary DataFrames
            or ``"gp"`` for GP-practice-level DataFrames.  ``"ni"`` is the
            backward-compatible default.

    Returns:
        True if all checks pass.

    Raises:
        NISRAValidationError: Describing the first failing check.
        ValueError: If *level* is not ``"ni"`` or ``"gp"``.

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
    if level not in ("ni", "gp"):
        raise ValueError(f"level must be 'ni' or 'gp', got {level!r}")

    if level == "ni":
        required = {"year", "financial_year", "register", "registered_patients", "prevalence_per_1000"}
    else:
        required = {
            "practice_code",
            "lcg",
            "financial_year",
            "year",
            "register",
            "registered_patients",
            "prevalence_per_1000",
        }

    missing = required - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if df["register"].nunique() < 5:
        raise NISRAValidationError(f"Too few disease registers: expected ≥ 5, got {df['register'].nunique()}")

    if level == "ni":
        if df["financial_year"].nunique() < 10:
            raise NISRAValidationError(f"Too few financial years: expected ≥ 10, got {df['financial_year'].nunique()}")
    else:
        if df["practice_code"].nunique() < 100:
            raise NISRAValidationError(f"Too few GP practices: expected ≥ 100, got {df['practice_code'].nunique()}")
        if df["financial_year"].nunique() < 3:
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


# ── GP practice lookup (Table 4) ─────────────────────────────────────────────


def parse_gp_practice_lookup(file_path, sheet_name: str | None = None) -> pd.DataFrame:
    """Parse Table 4 (GP practice details) into a lookup DataFrame.

    Table 4 is a single sheet in the workbook that provides the canonical
    practice name, address, and postcode for every GP practice code.  It
    is used to populate the ``practice_name`` column that is absent from
    the Table 5 prevalence sheets.

    The sheet header row is at row index 7 (0-based).  Data rows start
    immediately below and continue until the last row; all ``Practice ID``
    values start with ``"Z"``.

    Args:
        file_path: Path to the downloaded ``.xlsx`` workbook.
        sheet_name: Sheet name override.  If ``None`` (default), uses the
            constant ``_SHEET_TABLE4`` (``"Table 4 GP practice details"``).

    Returns:
        DataFrame with columns:
            - ``practice_code`` (str): Practice identifier (e.g. ``"Z00001"``)
            - ``practice_name`` (str): Practice name (e.g. ``"Dr. IRWIN"``)
            - ``address`` (str or None): Full formatted address (Address1 /
              Address2 / Address3 joined, NaN parts dropped)
            - ``postcode`` (str or None): Postcode (e.g. ``"BT4 1NS"``)

    Raises:
        NISRADataNotFoundError: If the sheet cannot be found in the workbook.

    Example:
        >>> lkp = parse_gp_practice_lookup("/tmp/rdptd-tables-2026.xlsx")
        >>> "practice_code" in lkp.columns
        True
        >>> lkp["practice_code"].str.startswith("Z").all()
        True
    """
    target_sheet = sheet_name if sheet_name is not None else _SHEET_TABLE4
    try:
        raw = pd.read_excel(file_path, sheet_name=target_sheet, header=None, engine="openpyxl")
    except ValueError as exc:
        raise NISRADataNotFoundError(f"Sheet {target_sheet!r} not found in workbook {file_path}: {exc}") from exc

    # Row 7 (0-indexed) contains column headers; data starts at row 8.
    # Columns: 0=Practice number, 1=Practice ID, 2=PracticeName,
    #          3=Address1, 4=Address2, 5=Address3, 6=Postcode, 7=Comments
    records: list[dict] = []
    for row_idx in range(8, len(raw)):
        practice_id_raw = raw.iloc[row_idx, 1]
        if pd.isna(practice_id_raw):
            continue
        pcode = str(practice_id_raw).strip()
        if not pcode.startswith("Z"):
            continue  # skip any footer / summary rows

        name_raw = raw.iloc[row_idx, 2]
        practice_name: str | None = str(name_raw).strip() if pd.notna(name_raw) else None

        # Build a tidy address by joining non-null address parts
        addr_parts = []
        for addr_col in (3, 4, 5):
            v = raw.iloc[row_idx, addr_col]
            if pd.notna(v) and str(v).strip():
                addr_parts.append(str(v).strip())
        address: str | None = ", ".join(addr_parts) if addr_parts else None

        postcode_raw = raw.iloc[row_idx, 6]
        postcode: str | None = str(postcode_raw).strip() if pd.notna(postcode_raw) else None

        records.append(
            {
                "practice_code": pcode,
                "practice_name": practice_name,
                "address": address,
                "postcode": postcode,
            }
        )

    return pd.DataFrame(records)


# ── GP-practice-level parsing ─────────────────────────────────────────────────

# Table 5 sheet names contain the calendar year of the end of the financial year.
# e.g. "Table 5a Prevalence 2026" → financial year 2025/26.
# We derive the financial year from the year suffix in the sheet name.

# Register name normalisation for GP-practice tables (Table 5 sheets).
# These map raw Table 5 names to canonical forms used in the output.
_GP_REGISTER_NORMALISE: dict[str, str] = {
    "Chronic Kidney Disease": "Chronic Kidney Disease 18+",
    "Stroke": "Stroke/TIA",
    "Epilespsy 18+": "Epilepsy 18+",  # typo in source data fixed
    "Epilepsy": "Epilepsy 18+",
}


def _normalise_gp_register(name: str) -> str:
    """Apply canonical GP register name mapping if available, else return as-is.

    Args:
        name: Raw register name from a Table 5 Excel sheet.

    Returns:
        Canonical register name, or the original string if no mapping exists.
    """
    return _GP_REGISTER_NORMALISE.get(name, name)


def _sheet_to_financial_year(sheet_name: str) -> tuple[str, int]:
    """Derive (financial_year, year) from a Table 5 sheet name.

    The sheet names follow the pattern ``"Table 5X Prevalence YYYY"`` where
    ``YYYY`` is the end calendar year of the financial year (e.g. 2026 →
    financial year 2025/26).

    Args:
        sheet_name: Full Excel sheet name, e.g. ``"Table 5a Prevalence 2026"``.

    Returns:
        Tuple of (financial_year string, start year int),
        e.g. ``("2025/26", 2025)``.

    Raises:
        ValueError: If the year cannot be parsed from the sheet name.
    """
    parts = sheet_name.strip().split()
    if not parts:
        raise ValueError(f"Cannot parse year from sheet name: {sheet_name!r}")
    try:
        end_year = int(parts[-1])
    except ValueError as exc:
        raise ValueError(f"Cannot parse year from sheet name: {sheet_name!r}") from exc
    start_year = end_year - 1
    fin_year = f"{start_year}/{str(end_year)[-2:]}"
    return fin_year, start_year


def _parse_table5_sheet(raw: pd.DataFrame, financial_year: str, year: int) -> pd.DataFrame:
    """Parse a single Table 5 sheet (raw) into long-format GP practice records.

    Internal helper used by :func:`parse_gp_practice`.

    The sheet has a compound 2-row header at rows 4–5 (0-indexed).  Row 4
    contains block section labels; row 5 contains register names and
    demographic size labels.  Data rows start at row 6 and continue until
    the first row where col 1 does not start with ``"Z"`` (practice codes
    always begin with Z).

    Args:
        raw: Raw DataFrame read with ``header=None``.
        financial_year: Financial year label, e.g. ``"2025/26"``.
        year: Start year integer, e.g. ``2025``.

    Returns:
        Long-format DataFrame with columns:
        ``practice_code``, ``practice_name``, ``lcg``, ``federation``,
        ``financial_year``, ``year``, ``register``,
        ``registered_patients``, ``prevalence_per_1000``.
    """
    row4 = raw.iloc[4]
    row5 = raw.iloc[5]

    # ── Locate block boundaries from row 4 ─────────────────────────────────
    # Block labels of interest (matched as substrings, case-insensitive):
    #   "Number of patients on register"   → count block
    #   "Prevalence per 1000 patients using full list"  → prevalence block
    # Other blocks (Practice Id repetitions, age-specific prevalence) are skipped.

    block_starts: dict[int, str] = {}
    for col_idx, val in enumerate(row4):
        if pd.notna(val) and str(val).strip():
            block_starts[col_idx] = str(val).strip()

    sorted_blocks = sorted(block_starts.items())  # [(col_idx, label), ...]

    count_start: int | None = None
    count_end: int | None = None
    prev_start: int | None = None
    prev_end: int | None = None

    for i, (col, label) in enumerate(sorted_blocks):
        label_lower = label.lower()
        if "number of patients" in label_lower:
            count_start = col
            # End is the start of the next block
            count_end = sorted_blocks[i + 1][0] if i + 1 < len(sorted_blocks) else raw.shape[1]
        elif "prevalence per 1000 patients using full list" in label_lower:
            prev_start = col
            prev_end = sorted_blocks[i + 1][0] if i + 1 < len(sorted_blocks) else raw.shape[1]

    if count_start is None or prev_start is None:
        raise NISRADataNotFoundError(
            f"Could not locate register count / prevalence blocks in sheet "
            f"(financial_year={financial_year!r}). "
            f"Block labels found: {list(block_starts.values())}"
        )

    # ── Extract register names for each block ──────────────────────────────
    def _block_registers(start: int, end: int) -> list[tuple[int, str]]:
        """Return [(col_idx, register_name)] for register columns in a block."""
        result = []
        for ci in range(start, end):
            if ci >= len(row5):
                break
            v = row5.iloc[ci]
            if pd.notna(v) and str(v).strip():
                name = str(v).strip()
                # Skip demographic size labels (e.g. "16+", "17+", "18+", "50+")
                if not name.replace("+", "").isdigit():
                    result.append((ci, _normalise_gp_register(name)))
        return result

    count_registers = _block_registers(count_start, count_end)
    prev_registers = _block_registers(prev_start, prev_end)

    # Build dicts: register → col index for quick lookup
    count_col: dict[str, int] = {reg: ci for ci, reg in count_registers}
    prev_col: dict[str, int] = {reg: ci for ci, reg in prev_registers}

    # Union of all register names across both blocks
    all_registers = sorted(set(count_col) | set(prev_col))

    # ── Detect metadata columns ─────────────────────────────────────────────
    # Row 4 first non-null label at col 1 is "Practice Id" / "Practice ID".
    # LCG is always the next non-empty col in row 4 after Practice Id.
    # Federation appears in row 4 as the next label; absent in early years.

    # col 1 = practice code, col 2 = LCG; check if col 3 has "Federation"
    col3_label = str(row4.iloc[3]).strip() if pd.notna(row4.iloc[3]) else ""
    has_federation = "ederation" in col3_label  # matches "Federation" and "Federation1"

    lcg_col = 2
    fed_col = 3 if has_federation else None

    # ── Parse data rows ─────────────────────────────────────────────────────
    records: list[dict] = []
    data_start_row = 6
    for row_idx in range(data_start_row, len(raw)):
        practice_code_raw = raw.iloc[row_idx, 1]
        # Practice codes start with "Z"; stop on NI summary / empty rows
        if pd.isna(practice_code_raw):
            break
        pcode = str(practice_code_raw).strip()
        if not pcode.startswith("Z"):
            break  # "Northern Ireland" summary row or footer

        lcg = str(raw.iloc[row_idx, lcg_col]).strip() if pd.notna(raw.iloc[row_idx, lcg_col]) else None
        federation: str | None = None
        if fed_col is not None:
            fed_raw = raw.iloc[row_idx, fed_col]
            federation = str(fed_raw).strip() if pd.notna(fed_raw) else None

        for reg in all_registers:
            cnt_ci = count_col.get(reg)
            prv_ci = prev_col.get(reg)

            def _safe_float(df_row: int, col: int | None) -> float:
                if col is None or col >= raw.shape[1]:
                    return float("nan")
                val = raw.iloc[df_row, col]
                try:
                    return float(val) if pd.notna(val) else float("nan")
                except (TypeError, ValueError):
                    return float("nan")

            records.append(
                {
                    "practice_code": pcode,
                    "practice_name": None,  # not present in Table 5
                    "lcg": lcg,
                    "federation": federation,
                    "financial_year": financial_year,
                    "year": year,
                    "register": reg,
                    "registered_patients": _safe_float(row_idx, cnt_ci),
                    "prevalence_per_1000": _safe_float(row_idx, prv_ci),
                }
            )

    return pd.DataFrame(records)


def parse_gp_practice(file_path, sheet_name: str) -> pd.DataFrame:
    """Parse a single Table 5 sheet into a long-format GP practice DataFrame.

    Reads the compound 2-row header (rows 4–5) to identify register columns,
    then extracts one row per (practice, register) pair.  Practice codes are
    in column 1 and always start with "Z"; the "Northern Ireland" summary row
    at the foot of each sheet is excluded.

    The sheet names in the workbook follow the pattern
    ``"Table 5X Prevalence YYYY"`` (e.g. ``"Table 5a Prevalence 2026"``),
    from which the financial year is derived automatically.

    Args:
        file_path: Path to the downloaded ``.xlsx`` workbook (string or
            path-like).
        sheet_name: Exact name of the Table 5 sheet to parse, e.g.
            ``"Table 5a Prevalence 2026"``.

    Returns:
        Long-format DataFrame with columns:

        - ``practice_code`` (str): Practice identifier (e.g. ``"Z00001"``)
        - ``practice_name`` (object): ``None``; practice names are sourced
          from Table 4 and are joined in :func:`parse_all_gp_practices`
          rather than at the individual sheet level
        - ``lcg`` (str or None): Local Commissioning Group name
        - ``federation`` (str or None): Federation name; ``None`` for years
          before 2017/18 when the column was not present
        - ``financial_year`` (str): Label such as ``"2025/26"``
        - ``year`` (int): Start year of the financial year (e.g. ``2025``)
        - ``register`` (str): Normalised disease register name
        - ``registered_patients`` (float): Patients on register at NPD;
          ``NaN`` if not available for that register in that year
        - ``prevalence_per_1000`` (float): Prevalence per 1,000 registered
          patients; ``NaN`` if not available

    Raises:
        NISRADataNotFoundError: If the sheet is not found or the expected
            column blocks cannot be located.

    Example:
        >>> df = parse_gp_practice("/tmp/rdptd-tables-2026.xlsx",
        ...                        "Table 5a Prevalence 2026")
        >>> df["practice_code"].str.startswith("Z").all()
        True
        >>> "Hypertension" in df["register"].values
        True
    """
    try:
        raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, engine="openpyxl")
    except ValueError as exc:
        raise NISRADataNotFoundError(f"Sheet {sheet_name!r} not found in workbook {file_path}: {exc}") from exc

    financial_year, year = _sheet_to_financial_year(sheet_name)
    return _parse_table5_sheet(raw, financial_year, year)


def parse_all_gp_practices(file_path) -> pd.DataFrame:
    """Parse all Table 5 sheets and return a concatenated long-format DataFrame.

    Iterates every sheet whose name starts with ``"Table 5"`` in the workbook,
    calls :func:`parse_gp_practice` for each, and concatenates the results.
    Financial year and start year are derived from each sheet's name.

    Sheets that cannot be parsed (e.g. due to unexpected structure) are
    skipped with a warning rather than raising an exception, so a partial
    result is always returned.

    Args:
        file_path: Path to the downloaded ``.xlsx`` workbook (string or
            path-like).

    Returns:
        Long-format DataFrame with columns:
        ``practice_code``, ``practice_name``, ``lcg``, ``federation``,
        ``financial_year``, ``year``, ``register``,
        ``registered_patients``, ``prevalence_per_1000``.

        Rows are sorted by ``financial_year``, ``practice_code``,
        then ``register``.

    Raises:
        NISRADataNotFoundError: If no Table 5 sheets can be found or parsed.

    Example:
        >>> df = parse_all_gp_practices("/tmp/rdptd-tables-2026.xlsx")
        >>> df["financial_year"].nunique() >= 17
        True
        >>> df["practice_code"].nunique() >= 300
        True
    """
    try:
        xl = pd.ExcelFile(file_path, engine="openpyxl")
    except Exception as exc:
        raise NISRADataNotFoundError(f"Cannot open workbook {file_path}: {exc}") from exc

    table5_sheets = [s for s in xl.sheet_names if s.strip().startswith("Table 5")]
    if not table5_sheets:
        raise NISRADataNotFoundError(f"No Table 5 sheets found in workbook {file_path}")

    frames: list[pd.DataFrame] = []
    for sheet_name in table5_sheets:
        try:
            raw = xl.parse(sheet_name, header=None)
            financial_year, year = _sheet_to_financial_year(sheet_name)
            df_sheet = _parse_table5_sheet(raw, financial_year, year)
            if not df_sheet.empty:
                frames.append(df_sheet)
                logger.debug("Parsed %d rows from sheet %r", len(df_sheet), sheet_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping sheet %r: %s", sheet_name, exc)

    if not frames:
        raise NISRADataNotFoundError(f"All Table 5 sheets failed to parse in workbook {file_path}")

    combined = pd.concat(frames, ignore_index=True)

    # ── Join Table 4 practice names ────────────────────────────────────────────
    try:
        lookup = parse_gp_practice_lookup(file_path)
        if not lookup.empty:
            name_map = lookup.set_index("practice_code")["practice_name"]
            combined["practice_name"] = combined["practice_code"].map(name_map)
            logger.debug("Populated practice_name for %d practices from Table 4", name_map.shape[0])
        else:
            logger.warning("Table 4 lookup returned empty DataFrame; practice_name will be None")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load Table 4 practice lookup: %s; practice_name will be None", exc)

    return combined.sort_values(["year", "practice_code", "register"]).reset_index(drop=True)


def get_latest_gp_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch and return the latest GP-practice-level disease prevalence data.

    Downloads the current Excel workbook from the Department of Health
    website (with a 24×365-hour cache), parses all Table 5 sheets (one per
    financial year), validates the result, and returns a clean long-format
    DataFrame covering 2009/10 to the latest published year.

    Args:
        force_refresh: If True, bypass the local file cache and re-download
            the workbook.  Default: False.

    Returns:
        Long-format DataFrame with columns:

        - ``practice_code`` (str): GP practice identifier (e.g. ``"Z00001"``)
        - ``practice_name`` (str or None): Practice name from Table 4 lookup
          (e.g. ``"Dr. IRWIN"``); ``None`` if the practice code is not found
          in Table 4 (e.g. historical practices no longer listed)
        - ``lcg`` (str or None): Local Commissioning Group
        - ``federation`` (str or None): Federation name (``None`` pre-2017/18)
        - ``financial_year`` (str): Label such as ``"2025/26"``
        - ``year`` (int): Start year of the financial year
        - ``register`` (str): Disease register name (normalised)
        - ``registered_patients`` (float): Patients on register at NPD
        - ``prevalence_per_1000`` (float): Prevalence per 1,000 registered pts

        Data spans 2009/10 to the latest published year (~17 financial years)
        with ~305–360 GP practices per year.

    Raises:
        NISRADataNotFoundError: If the workbook cannot be located or downloaded.
        NISRAValidationError: If the parsed data fails validation.

    Example:
        >>> df = get_latest_gp_prevalence()
        >>> df["practice_code"].str.startswith("Z").all()
        True
        >>> df["financial_year"].nunique() >= 17
        True
    """
    url = get_latest_publication_url()
    logger.info("Downloading disease prevalence workbook from %s", url)
    file_path = download_file(url, cache_ttl_hours=_CACHE_TTL, force_refresh=force_refresh)
    df = parse_all_gp_practices(file_path)
    validate_disease_prevalence(df, level="gp")
    return df
