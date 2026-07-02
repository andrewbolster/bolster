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
    - By GP practice (Table 5, Excel): ~305–360 practices, 2009/10 to present

Disease Registers (17):
    Asthma, Atrial Fibrillation, Cancer, Chronic Kidney Disease,
    Chronic Obstructive Pulmonary Disease, Coronary Heart Disease,
    Dementia, Depression, Diabetes Mellitus, Heart Failure 1,
    Heart Failure 3, Hypertension, Mental Health,
    Non-Diabetic Hyperglycaemia, Osteoporosis, Rheumatoid Arthritis,
    Stroke & TIA

Data sources:
    PxStat (NI / LGD / HSCT levels):
        DISPREVNI, DISPREVLGD, DISPREVHSCT matrices
    Excel workbook (GP-practice level — not in PxStat):
        https://www.health-ni.gov.uk/topics/health-statistics/disease-prevalence

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

from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file
from .pxstat import read_dataset

logger = logging.getLogger(__name__)

# PxStat matrix codes
_MATRIX_NI = "DISPREVNI"
# GP-practice Excel scraping constants
DOH_BASE_URL = "https://www.health-ni.gov.uk"
DOH_LANDING_PAGE = "https://www.health-ni.gov.uk/topics/health-statistics/disease-prevalence"
_CACHE_TTL = 24 * 365  # hours — annual publication
_SHEET_TABLE4 = "Table 4 GP practice details"

# Register name normalisation for GP-practice Table 5 sheets.
_GP_REGISTER_NORMALISE: dict[str, str] = {
    "Chronic Kidney Disease": "Chronic Kidney Disease 18+",
    "Stroke": "Stroke/TIA",
    "Epilespsy 18+": "Epilepsy 18+",  # typo in source data
    "Epilepsy": "Epilepsy 18+",
}
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
            Local Government District breakdown, 'trust' for HSC Trust, or
            'gp' for GP-practice-level data (sourced from Excel, not PxStat).
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
    elif level == "gp":
        df = get_latest_gp_prevalence(force_refresh=force_refresh)
    else:
        raise ValueError(f"level must be 'ni', 'lgd', 'trust', or 'gp', got {level!r}")

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


# ── GP-practice-level (Excel scraping) ───────────────────────────────────────


def get_latest_publication_url() -> str:
    """Return the URL of the most recent disease prevalence Excel workbook.

    Searches the Department of Health publications index for disease prevalence,
    follows the first (most recent) result, and returns the .xlsx download URL.

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

    search_url = f"{DOH_BASE_URL}/publications?keywords=disease+prevalence"
    try:
        resp = session.get(search_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch disease prevalence publications index: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")
    pub_url: str | None = None
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "/publications/" in href and "disease-prevalence" in href:
            pub_url = href if href.startswith("http") else f"{DOH_BASE_URL}{href}"
            break

    if pub_url is None:
        raise NISRADataNotFoundError(f"Could not find a disease prevalence publication on {search_url}")

    try:
        pub_resp = session.get(pub_url, timeout=30)
        pub_resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch publication page {pub_url}: {exc}") from exc

    pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
    for a in pub_soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".xlsx"):
            return href if href.startswith("http") else f"{DOH_BASE_URL}{href}"

    raise NISRADataNotFoundError(f"Could not find an .xlsx link on {pub_url}")


def _normalise_gp_register(name: str) -> str:
    return _GP_REGISTER_NORMALISE.get(name, name)


def _sheet_to_financial_year(sheet_name: str) -> tuple[str, int]:
    """Derive (financial_year, start_year) from a Table 5 sheet name.

    Args:
        sheet_name: e.g. ``"Table 5a Prevalence 2026"``

    Returns:
        ``("2025/26", 2025)``

    Raises:
        ValueError: If the year cannot be parsed.
    """
    parts = sheet_name.strip().split()
    if not parts:
        raise ValueError(f"Cannot parse year from sheet name: {sheet_name!r}")
    try:
        end_year = int(parts[-1])
    except ValueError as exc:
        raise ValueError(f"Cannot parse year from sheet name: {sheet_name!r}") from exc
    start_year = end_year - 1
    return f"{start_year}/{str(end_year)[-2:]}", start_year


def _parse_table5_sheet(raw: pd.DataFrame, financial_year: str, year: int) -> pd.DataFrame:
    """Parse a single Table 5 sheet into long-format GP practice records.

    The sheet has a compound 2-row header at rows 4–5 (0-indexed). Row 4
    contains block section labels; row 5 contains register names. Data rows
    start at row 6; practice codes always begin with "Z".

    Args:
        raw: Raw DataFrame read with ``header=None``.
        financial_year: e.g. ``"2025/26"``
        year: Start year integer, e.g. ``2025``

    Returns:
        Long-format DataFrame with columns: practice_code, practice_name,
        lcg, federation, financial_year, year, register,
        registered_patients, prevalence_per_1000.
    """
    row4 = raw.iloc[4]
    row5 = raw.iloc[5]

    block_starts: dict[int, str] = {
        col_idx: str(val).strip() for col_idx, val in enumerate(row4) if pd.notna(val) and str(val).strip()
    }
    sorted_blocks = sorted(block_starts.items())

    count_start = count_end = prev_start = prev_end = None
    for i, (col, label) in enumerate(sorted_blocks):
        label_lower = label.lower()
        next_col = sorted_blocks[i + 1][0] if i + 1 < len(sorted_blocks) else raw.shape[1]
        if "number of patients" in label_lower:
            count_start, count_end = col, next_col
        elif "prevalence per 1000 patients using full list" in label_lower:
            prev_start, prev_end = col, next_col

    if count_start is None or prev_start is None:
        raise NISRADataNotFoundError(
            f"Could not locate register blocks in sheet (financial_year={financial_year!r}). "
            f"Block labels found: {list(block_starts.values())}"
        )

    def _block_registers(start: int, end: int) -> list[tuple[int, str]]:
        result = []
        for ci in range(start, end):
            if ci >= len(row5):
                break
            v = row5.iloc[ci]
            if pd.notna(v) and str(v).strip():
                name = str(v).strip()
                if not name.replace("+", "").isdigit():
                    result.append((ci, _normalise_gp_register(name)))
        return result

    count_col: dict[str, int] = {reg: ci for ci, reg in _block_registers(count_start, count_end)}
    prev_col: dict[str, int] = {reg: ci for ci, reg in _block_registers(prev_start, prev_end)}
    all_registers = sorted(set(count_col) | set(prev_col))

    col3_label = str(row4.iloc[3]).strip() if pd.notna(row4.iloc[3]) else ""
    has_federation = "ederation" in col3_label
    lcg_col = 2
    fed_col = 3 if has_federation else None

    def _safe_float(row_idx: int, col: int | None) -> float:
        if col is None or col >= raw.shape[1]:
            return float("nan")
        val = raw.iloc[row_idx, col]
        try:
            return float(val) if pd.notna(val) else float("nan")
        except (TypeError, ValueError):
            return float("nan")

    records: list[dict] = []
    for row_idx in range(6, len(raw)):
        practice_code_raw = raw.iloc[row_idx, 1]
        if pd.isna(practice_code_raw):
            break
        pcode = str(practice_code_raw).strip()
        if not pcode.startswith("Z"):
            break

        lcg = str(raw.iloc[row_idx, lcg_col]).strip() if pd.notna(raw.iloc[row_idx, lcg_col]) else None
        federation: str | None = None
        if fed_col is not None:
            fed_raw = raw.iloc[row_idx, fed_col]
            federation = str(fed_raw).strip() if pd.notna(fed_raw) else None

        for reg in all_registers:
            records.append(
                {
                    "practice_code": pcode,
                    "practice_name": None,
                    "lcg": lcg,
                    "federation": federation,
                    "financial_year": financial_year,
                    "year": year,
                    "register": reg,
                    "registered_patients": _safe_float(row_idx, count_col.get(reg)),
                    "prevalence_per_1000": _safe_float(row_idx, prev_col.get(reg)),
                }
            )

    return pd.DataFrame(records)


def parse_gp_practice_lookup(file_path: str, sheet_name: str | None = None) -> pd.DataFrame:
    """Parse Table 4 (GP practice details) into a lookup DataFrame.

    Args:
        file_path: Path to the downloaded .xlsx workbook.
        sheet_name: Sheet name override; defaults to ``"Table 4 GP practice details"``.

    Returns:
        DataFrame with columns: practice_code, practice_name, address, postcode.

    Raises:
        NISRADataNotFoundError: If the sheet cannot be found.

    Example:
        >>> lkp = parse_gp_practice_lookup("/tmp/rdptd-tables-2026.xlsx")
        >>> "practice_code" in lkp.columns
        True
        >>> lkp["practice_code"].str.startswith("Z").all()
        True
    """
    target = sheet_name or _SHEET_TABLE4
    try:
        raw = pd.read_excel(file_path, sheet_name=target, header=None, engine="openpyxl")
    except ValueError as exc:
        raise NISRADataNotFoundError(f"Sheet {target!r} not found in {file_path}: {exc}") from exc

    records: list[dict] = []
    for row_idx in range(8, len(raw)):
        pid_raw = raw.iloc[row_idx, 1]
        if pd.isna(pid_raw):
            continue
        pcode = str(pid_raw).strip()
        if not pcode.startswith("Z"):
            continue
        name_raw = raw.iloc[row_idx, 2]
        practice_name = str(name_raw).strip() if pd.notna(name_raw) else None
        addr_parts = [
            str(raw.iloc[row_idx, c]).strip()
            for c in (3, 4, 5)
            if pd.notna(raw.iloc[row_idx, c]) and str(raw.iloc[row_idx, c]).strip()
        ]
        postcode_raw = raw.iloc[row_idx, 6]
        records.append(
            {
                "practice_code": pcode,
                "practice_name": practice_name,
                "address": ", ".join(addr_parts) if addr_parts else None,
                "postcode": str(postcode_raw).strip() if pd.notna(postcode_raw) else None,
            }
        )
    return pd.DataFrame(records)


def parse_all_gp_practices(file_path: str) -> pd.DataFrame:
    """Parse all Table 5 sheets and return a concatenated long-format DataFrame.

    Args:
        file_path: Path to the downloaded .xlsx workbook.

    Returns:
        Long-format DataFrame with columns: practice_code, practice_name,
        lcg, federation, financial_year, year, register,
        registered_patients, prevalence_per_1000.

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
        raise NISRADataNotFoundError(f"No Table 5 sheets found in {file_path}")

    frames: list[pd.DataFrame] = []
    for sheet_name in table5_sheets:
        try:
            raw = xl.parse(sheet_name, header=None)
            financial_year, year = _sheet_to_financial_year(sheet_name)
            df_sheet = _parse_table5_sheet(raw, financial_year, year)
            if not df_sheet.empty:
                frames.append(df_sheet)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping sheet %r: %s", sheet_name, exc)

    if not frames:
        raise NISRADataNotFoundError(f"All Table 5 sheets failed to parse in {file_path}")

    combined = pd.concat(frames, ignore_index=True)

    try:
        lookup = parse_gp_practice_lookup(file_path)
        if not lookup.empty:
            name_map = lookup.set_index("practice_code")["practice_name"]
            combined["practice_name"] = combined["practice_code"].map(name_map)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load Table 4 practice lookup: %s; practice_name will be None", exc)

    return combined.sort_values(["year", "practice_code", "register"]).reset_index(drop=True)


def get_latest_gp_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch and return the latest GP-practice-level disease prevalence data.

    Downloads the current Excel workbook from the Department of Health website
    (cached for one year), parses all Table 5 sheets, and returns a clean
    long-format DataFrame covering 2009/10 to the latest published year.

    Args:
        force_refresh: If True, bypass the local file cache and re-download.

    Returns:
        Long-format DataFrame with columns:

        - ``practice_code`` (str): GP practice identifier (e.g. ``"Z00001"``)
        - ``practice_name`` (str or None): Practice name from Table 4
        - ``lcg`` (str or None): Local Commissioning Group
        - ``federation`` (str or None): Federation name (None pre-2017/18)
        - ``financial_year`` (str): e.g. ``"2025/26"``
        - ``year`` (int): Start year of the financial year
        - ``register`` (str): Disease register name (normalised)
        - ``registered_patients`` (float): Patients on register at NPD
        - ``prevalence_per_1000`` (float): Prevalence per 1,000 registered pts

    Raises:
        NISRADataNotFoundError: If the workbook cannot be located or downloaded.
        NISRAValidationError: If the parsed data fails validation.

    Example:
        >>> df = get_latest_gp_prevalence()
        >>> df["practice_code"].str.startswith("Z").all()
        True
        >>> df["financial_year"].nunique() >= 3
        True
    """
    url = get_latest_publication_url()
    logger.info("Downloading disease prevalence workbook from %s", url)
    file_path = download_file(url, cache_ttl_hours=_CACHE_TTL, force_refresh=force_refresh)
    df = parse_all_gp_practices(file_path)
    validate_disease_prevalence(df, level="gp")
    return df
