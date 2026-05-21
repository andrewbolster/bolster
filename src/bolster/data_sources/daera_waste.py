"""DAERA NI Local Authority Collected (LAC) Municipal Waste Statistics.

Quarterly time-series data on local-authority-collected municipal waste
management across Northern Ireland, published by the Department of
Agriculture, Environment and Rural Affairs (DAERA).

Data Source:
    **Discovery page**:
    https://www.daera-ni.gov.uk/publications/northern-ireland-local-authority-collected-municipal-waste-management-statistics-time-series-data

    The module scrapes the DAERA publications page to auto-discover the
    current CSV URL (which changes with each release, e.g. ``2026-04/...``).
    It then downloads the time-series CSV and returns a tidy long-format
    DataFrame.

Update Frequency:
    Quarterly (provisional) with finalised annual revisions.  The current
    series runs from Q1 2006/07 to the most recent available quarter.

Geographic Coverage:
    All NI council areas including both pre- and post-2015 boundaries, plus
    a Northern Ireland aggregate row.  The 11 post-2015 LGD councils are:
    Antrim & Newtownabbey, Ards & North Down, Armagh City Banbridge &
    Craigavon, Belfast, Causeway Coast & Glens, Derry City & Strabane,
    Fermanagh & Omagh, Lisburn & Castlereagh, Mid & East Antrim, Mid Ulster,
    Newry Mourne & Down.

Example:
    >>> from bolster.data_sources import daera_waste
    >>> df = daera_waste.get_latest_waste_statistics()
    >>> 'council_area' in df.columns
    True
    >>> 'tonnes' in df.columns
    True

"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import session

logger = logging.getLogger(__name__)

# ── Public page to scrape for the current file URL ──────────────────────────
DAERA_PUBLICATION_PAGE = (
    "https://www.daera-ni.gov.uk/publications/"
    "northern-ireland-local-authority-collected-municipal-waste-"
    "management-statistics-time-series-data"
)
DAERA_BASE_URL = "https://www.daera-ni.gov.uk"

# ── Cached downloader (namespace = "daera") ──────────────────────────────────
_downloader = CachedDownloader("daera", timeout=60)

# ── Canonical column renames from wide CSV to internal names ─────────────────
# Each entry maps a substring of the raw CSV column header to a clean name.
# Order matters: more-specific patterns must come before broader ones.
_WASTE_COLUMN_MAP: dict[str, str] = {
    # LAC arisings
    "local authority collected municipal waste arisings": "lac_waste_arisings_tonnes",
    # LAC recycling / composting
    "local authority collected municipal waste preparing for reuse, dry recycling and composting (tonnes)": "lac_reuse_recycling_composting_tonnes",
    "local authority collected municipal waste dry recycling and composting (tonnes)": "lac_dry_recycling_composting_tonnes",
    "local authority collected municipal waste preparing for reuse (tonnes)": "lac_preparing_for_reuse_tonnes",
    "local authority collected municipal waste dry recycling (tonnes)": "lac_dry_recycling_tonnes",
    "local authority collected municipal waste composting (tonnes)": "lac_composting_tonnes",
    # LAC rates
    "local authority collected municipal waste preparing for reuse, dry recycling and composting rate": "lac_reuse_recycling_composting_rate_pct",
    "local authority collected municipal waste dry recycling and composting rate": "lac_dry_recycling_composting_rate_pct",
    # LAC energy recovery
    "local authority collected municipal waste energy recovery for specific streams": "lac_energy_recovery_specific_streams_tonnes",
    "local authority collected municipal waste energy recovery for mixed residual": "lac_energy_recovery_mixed_residual_tonnes",
    "local authority collected municipal waste energy recovery rate": "lac_energy_recovery_rate_pct",
    # LAC landfill
    "local authority collected municipal waste landfilled (tonnes)": "lac_landfilled_tonnes",
    "local authority collected municipal waste landfill rate": "lac_landfill_rate_pct",
    # NILAS
    "biodegradable local authority collected municipal waste to landfill": "lac_biodegradable_to_landfill_tonnes",
    "nilas financial year allocation before transfers": "nilas_allocation_before_transfers_tonnes",
    "nilas financial year allocation after transfers": "nilas_allocation_after_transfers_tonnes",
    # Household arisings
    "household waste arisings (tonnes)": "hh_waste_arisings_tonnes",
    # Household recycling / composting
    "household waste preparing for reuse, dry recycling and composting (tonnes)": "hh_reuse_recycling_composting_tonnes",
    "household waste dry recycling and composting (tonnes)": "hh_dry_recycling_composting_tonnes",
    "household waste preparing for reuse (tonnes)": "hh_preparing_for_reuse_tonnes",
    "household waste dry recycling (tonnes)": "hh_dry_recycling_tonnes",
    "household waste composting (tonnes)": "hh_composting_tonnes",
    # Household rates
    "household waste preparing for reuse, dry recycling and composting rate": "hh_reuse_recycling_composting_rate_pct",
    "household waste dry recycling and composting rate": "hh_dry_recycling_composting_rate_pct",
    # Household landfill
    "household waste landfilled (tonnes)": "hh_landfilled_tonnes",
    "household waste landfill rate": "hh_landfill_rate_pct",
    # Household per-household / per-capita
    "number of households": "num_households",
    "household waste arisings per household": "hh_waste_per_household_kg",
    "population": "population",
    "household waste arisings per capita": "hh_waste_per_capita_kg",
    # Waste from households (statutory definition)
    "waste from households recycling rate": "wfh_recycling_rate_pct",
    "waste from households recycling": "wfh_recycling_tonnes",
    "waste from households arisings": "wfh_arisings_tonnes",
}

# ── Required columns for validation ─────────────────────────────────────────
_REQUIRED_COLUMNS = {
    "financial_year",
    "quarter_code",
    "quarter_name",
    "area_code",
    "council_area",
    "waste_management_group",
    "data_status",
    "lac_waste_arisings_tonnes",
    "hh_waste_arisings_tonnes",
}

# ── 11 post-2015 LGD councils expected in the data ───────────────────────────
NI_COUNCILS_POST_2015 = {
    "Antrim & Newtownabbey",
    "Ards & North Down",
    "Armagh City, Banbridge & Craigavon",
    "Belfast",
    "Causeway Coast & Glens",
    "Derry City & Strabane",
    "Fermanagh & Omagh",
    "Lisburn & Castlereagh",
    "Mid & East Antrim",
    "Mid Ulster",
    "Newry, Mourne & Down",
}


# ── Custom exceptions ────────────────────────────────────────────────────────


class DAERADataNotFoundError(Exception):
    """DAERA data file or publication page could not be located."""


class DAERAValidationError(Exception):
    """DAERA DataFrame failed validation checks."""


# ── URL discovery ────────────────────────────────────────────────────────────


def get_waste_publication_url(prefer: str = "csv") -> str:
    """Scrape the DAERA publications page for the latest LAC waste CSV/Excel URL.

    The URL contains a date component (e.g. ``2026-04/``) that changes with
    each release, so this function fetches the page and finds the current link.

    Args:
        prefer: Preferred file type — ``"csv"`` (default) or ``"xlsx"``.

    Returns:
        Absolute URL of the latest time-series file.

    Raises:
        DAERADataNotFoundError: If the publication page cannot be fetched or
            no matching link is found.

    Example:
        >>> url = get_waste_publication_url()
        >>> url.endswith(".csv") or url.endswith(".xlsx")
        True
        >>> "daera-ni.gov.uk" in url
        True
    """
    try:
        response = session.get(DAERA_PUBLICATION_PAGE, timeout=30)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network errors
        raise DAERADataNotFoundError(f"Failed to fetch DAERA publication page: {exc}") from exc

    soup = BeautifulSoup(response.content, "html.parser")

    ext_order = (".csv", ".xlsx") if prefer == "csv" else (".xlsx", ".csv")

    candidates: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        href_lower = href.lower()
        if "lac-municipal-waste" not in href_lower:
            continue
        for ext in ext_order:
            if href_lower.endswith(ext):
                if href.startswith("/"):
                    href = f"{DAERA_BASE_URL}{href}"
                candidates[ext] = href
                break

    for ext in ext_order:
        if ext in candidates:
            logger.info("Discovered DAERA waste URL: %s", candidates[ext])
            return candidates[ext]

    raise DAERADataNotFoundError(f"No LAC municipal waste CSV or Excel link found on {DAERA_PUBLICATION_PAGE}")


# ── Parsing ──────────────────────────────────────────────────────────────────


def _rename_waste_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename verbose CSV column headers to clean internal names.

    Applies a longest-match strategy: for each raw column, the *first*
    pattern in ``_WASTE_COLUMN_MAP`` whose text is contained in the
    lower-cased column header wins.

    Args:
        df: DataFrame with raw column names straight from the CSV.

    Returns:
        DataFrame with renamed columns (unmapped columns are kept as-is).
    """
    rename_map: dict[str, str] = {}
    for raw_col in df.columns:
        raw_lower = raw_col.lower()
        for pattern, clean_name in _WASTE_COLUMN_MAP.items():
            if pattern in raw_lower:
                rename_map[raw_col] = clean_name
                break
    return df.rename(columns=rename_map)


def parse_waste_file(file_path: str | Path) -> pd.DataFrame:
    """Parse a DAERA LAC municipal waste time-series CSV file.

    Reads the CSV (which uses commas as thousands separators in numeric
    columns), renames columns to clean internal names, and returns a tidy
    long-format DataFrame.

    Metadata columns (``QuarterCode``, ``QuarterName``, ``FinancialYear``,
    ``AreaCode``, ``AreaName``, ``WasteManagementGroup``, ``DataStatus``) are
    retained alongside all numeric waste metric columns.

    Args:
        file_path: Path to a downloaded ``.csv`` waste time-series file.

    Returns:
        DataFrame with one row per (quarter, council area) and columns
        including ``financial_year``, ``quarter_code``, ``quarter_name``,
        ``area_code``, ``council_area``, ``waste_management_group``,
        ``data_status``, plus numeric waste metrics.

    Raises:
        DAERAValidationError: If the file cannot be read or lacks the
            expected structure.

    Example:
        >>> import tempfile, pathlib
        >>> # In practice, use get_latest_waste_statistics() instead
        >>> # parse_waste_file(pathlib.Path("/path/to/download.csv"))
    """
    file_path = Path(file_path)
    # The CSV is published with Windows-1252 encoding (a `\x80` byte appears
    # in the header row as part of a KPI footnote marker). Using latin-1 (which
    # is a superset of the byte range) avoids a UnicodeDecodeError while still
    # decoding all printable characters correctly.
    try:
        raw = pd.read_csv(
            file_path,
            thousands=",",
            na_values=["-", ""],
            encoding="latin-1",
        )
    except Exception as exc:
        raise DAERAValidationError(f"Failed to read waste CSV {file_path}: {exc}") from exc

    if raw.empty:
        raise DAERAValidationError(f"Waste CSV {file_path} is empty")

    # Rename raw columns to internal names
    df = _rename_waste_columns(raw)

    # Rename the metadata columns too
    meta_renames = {
        "QuarterCode": "quarter_code",
        "QuarterName": "quarter_name",
        "FinancialYear": "financial_year",
        "AreaCode": "area_code",
        "AreaName": "council_area",
        "WasteManagementGroup": "waste_management_group",
        "DataStatus": "data_status",
    }
    df = df.rename(columns=meta_renames)

    # Parse financial year start year (e.g. "2006/07" -> 2006)
    df["financial_year_start"] = df["financial_year"].str.extract(r"^(\d{4})/", expand=False).astype("Int64")

    # Quarter ordinal (Q1=1 … Q4=4) for sorting
    _quarter_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
    df["quarter_number"] = df["quarter_code"].map(_quarter_order)

    df = df.sort_values(["financial_year_start", "quarter_number", "council_area"]).reset_index(drop=True)

    logger.info(
        "Parsed DAERA waste CSV: %d rows, %d columns, FY %s–%s",
        len(df),
        len(df.columns),
        df["financial_year"].iloc[0] if len(df) else "?",
        df["financial_year"].iloc[-1] if len(df) else "?",
    )
    return df


# ── Download + cache ─────────────────────────────────────────────────────────


def get_latest_waste_statistics(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the latest DAERA LAC municipal waste statistics.

    Scrapes the DAERA publications page for the current CSV URL (handling
    date-stamped paths that change with each release), downloads the file
    with 30-day caching, and returns a parsed DataFrame.

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        DataFrame from :func:`parse_waste_file`.

    Raises:
        DAERADataNotFoundError: If the publication page or file cannot be
            fetched.
        DAERAValidationError: If the downloaded file cannot be parsed.

    Example:
        >>> df = get_latest_waste_statistics()
        >>> 'council_area' in df.columns
        True
        >>> (df['lac_waste_arisings_tonnes'] >= 0).all()
        True
    """
    csv_url = get_waste_publication_url(prefer="csv")
    logger.info("Downloading DAERA waste statistics from %s", csv_url)
    try:
        file_path = _downloader.download(csv_url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)
    except DownloadError as exc:
        raise DAERADataNotFoundError(str(exc)) from exc
    return parse_waste_file(file_path)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_waste_data(df: pd.DataFrame) -> bool:
    """Validate a DAERA LAC municipal waste DataFrame.

    Args:
        df: DataFrame from :func:`get_latest_waste_statistics` or
            :func:`parse_waste_file`.

    Returns:
        ``True`` if all checks pass.

    Raises:
        DAERAValidationError: If the DataFrame is empty, missing required
            columns, has negative tonnage values, lacks expected NI councils,
            or covers an implausibly short time span.

    Example:
        >>> df = get_latest_waste_statistics()
        >>> validate_waste_data(df)
        True
    """
    if df is None or df.empty:
        raise DAERAValidationError("Waste DataFrame is empty")

    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise DAERAValidationError(f"Missing required columns: {sorted(missing)}")

    # No negative tonnes in the two headline series
    for col in ("lac_waste_arisings_tonnes", "hh_waste_arisings_tonnes"):
        vals = df[col].dropna()
        if (vals < 0).any():
            raise DAERAValidationError(f"Negative values found in {col}")

    # At least the 11 post-2015 LGD councils should appear
    councils_in_data = set(df["council_area"].unique())
    missing_councils = NI_COUNCILS_POST_2015 - councils_in_data
    if missing_councils:
        raise DAERAValidationError(f"Missing expected NI councils: {sorted(missing_councils)}")

    # Series must span at least 5 financial years (data starts 2006/07)
    if "financial_year_start" in df.columns:
        years = df["financial_year_start"].dropna()
        if years.nunique() < 5:
            raise DAERAValidationError(f"Too few financial years ({years.nunique()}); expected 5+")

    return True
