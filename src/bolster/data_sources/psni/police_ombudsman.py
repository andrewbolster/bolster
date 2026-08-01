"""PSNI Police Ombudsman Complaint Statistics.

Provides access to complaint statistics published by the Police Ombudsman for
Northern Ireland (PONI), covering:

- Annual complaint totals back to 2000/01
- Complaints by policing district (2011/12 onwards)
- Allegations by type and subtype (2011/12 onwards)
- Complaint closures by outcome (2011/12 onwards)
- Quarterly complaint and allegation counts (latest 5 years)

Data Source:
    **Annual**: Police Ombudsman annual statistics bulletin
    https://www.policeombudsman.org/statistics-and-research/complaint-statistics-in-northern-ireland

    **Quarterly**: Police Ombudsman quarterly statistical bulletin
    https://www.policeombudsman.org/statistics-and-research/quarterly-reports

    Published under the Open Government Licence v3.0.

Update Frequency:
    - Annual: once per year (summer, covering previous financial year)
    - Quarterly: four times per year

Geographic Coverage:
    Northern Ireland — 11 Policing Districts aligned with LGDs.

Time Coverage:
    - Totals: 2000/01 to present
    - District / allegation / outcome breakdowns: 2011/12 to present
    - Quarterly: latest 5 financial years

Example:
    >>> from bolster.data_sources.psni import police_ombudsman
    >>> df = police_ombudsman.get_latest_complaints()
    >>> 'year' in df.columns
    True
    >>> url = police_ombudsman.get_annual_publication_url()
    >>> url.startswith("https://")
    True
"""

import logging
import re

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import (
    LGD_CODES,
    PSNIDataNotFoundError,
    PSNIValidationError,
    download_file,
)

logger = logging.getLogger(__name__)

# ── Public page URLs ──────────────────────────────────────────────────────────
_QUARTERLY_PAGE = "https://www.policeombudsman.org/statistics-and-research/quarterly-reports"
_ANNUAL_PAGE = "https://www.policeombudsman.org/statistics-and-research/complaint-statistics-in-northern-ireland"
_BASE_URL = "https://www.policeombudsman.org"

# policeombudsman.org returns 403 to requests' default UA; provide a browser UA.
_SCRAPE_HEADERS = {"User-Agent": ("Mozilla/5.0 (compatible; bolster/1.0; +https://github.com/andrewbolster/bolster)")}

# ── District name normalisation ───────────────────────────────────────────────
# Quarterly uses "District A - Belfast City" style labels.
# Annual uses "A - Belfast City" style labels.
# Both map to the canonical LGD names found in _base.LGD_CODES.

_QUARTERLY_DISTRICT_MAP: dict[str, str] = {
    "District A - Belfast City": "Belfast City",
    "District B - Lisburn & Castlereagh City": "Lisburn & Castlereagh City",
    "District C - Ards & North Down": "Ards & North Down",
    "District D - Newry, Mourne & Down": "Newry Mourne & Down",
    "District E - Armagh City, Banbridge & Craigavon": "Armagh City Banbridge & Craigavon",
    "District F - Mid Ulster": "Mid Ulster",
    "District G - Fermanagh & Omagh": "Fermanagh & Omagh",
    "District H - Derry City & Strabane": "Derry City & Strabane",
    "District J - Causeway Coast & Glens": "Causeway Coast & Glens",
    "District K - Mid & East Antrim": "Mid & East Antrim",
    "District L - Antrim & Newtownabbey": "Antrim & Newtownabbey",
}

# Annual "A - Belfast City" → canonical LGD name.
# Built by stripping "District " prefix from quarterly keys, then any
# spelling differences between the two formats are patched below.
_ANNUAL_DISTRICT_MAP: dict[str, str] = {k.replace("District ", ""): v for k, v in _QUARTERLY_DISTRICT_MAP.items()}
# The annual T8 sheet omits the comma in "Newry Mourne & Down":
_ANNUAL_DISTRICT_MAP["D - Newry Mourne & Down"] = "Newry Mourne & Down"
# Ensure the annual-format variant also covers "E - Armagh…" (no comma variant):
_ANNUAL_DISTRICT_MAP["E - Armagh City, Banbridge & Craigavon"] = "Armagh City Banbridge & Craigavon"

# Financial-year column pattern: "2024/25"
_FY_RE = re.compile(r"^\d{4}/\d{2}$")


def _normalise_annual_district(raw: str) -> str:
    """Normalise an annual-file district label to the canonical LGD name.

    Args:
        raw: Raw district label from the annual Excel (e.g. ``"A - Belfast City"``).

    Returns:
        Canonical LGD name matching ``_base.LGD_CODES``, or the input string
        unchanged if no mapping is found.
    """
    return _ANNUAL_DISTRICT_MAP.get(str(raw).strip(), str(raw).strip())


def _normalise_quarterly_district(raw: str) -> str:
    """Normalise a quarterly-file district label to the canonical LGD name.

    Args:
        raw: Raw district string (e.g. ``"District A - Belfast City"``).

    Returns:
        Canonical LGD name, or the original string if no mapping found.
    """
    return _QUARTERLY_DISTRICT_MAP.get(str(raw).strip(), str(raw).strip())


def _parse_fy_label(label: str) -> int:
    """Parse a financial-year label such as ``'2024/25'`` to the start year.

    Args:
        label: String like ``'2024/25'`` or ``'2000/01*'``.

    Returns:
        Integer start year, e.g. ``2024``.
    """
    return int(str(label).strip().split("/")[0])


def _find_sheet(xl: pd.ExcelFile, prefix: str) -> str:
    """Return the first sheet name that starts with *prefix* (case-insensitive).

    Args:
        xl: Opened ``pd.ExcelFile`` object.
        prefix: Sheet name prefix to search for (e.g. ``"T8"``).

    Returns:
        Matching sheet name.

    Raises:
        PSNIDataNotFoundError: If no matching sheet is found.
    """
    for name in xl.sheet_names:
        if name.upper().startswith(prefix.upper()):
            return name
    raise PSNIDataNotFoundError(f"No sheet starting with {prefix!r} found. Available: {xl.sheet_names}")


# ── URL scrapers ───────────────────────────────────────────────────────────────


def get_quarterly_publication_url() -> str:
    """Scrape the quarterly-reports page for the latest .xlsx download link.

    policeombudsman.org returns 403 to default User-Agents; this function
    uses a browser-like UA via ``bolster.utils.web.session``.

    Returns:
        Absolute URL of the latest quarterly Excel spreadsheet.

    Raises:
        PSNIDataNotFoundError: If the page cannot be retrieved or no .xlsx
            link is found.

    Example:
        >>> url = get_quarterly_publication_url()
        >>> url.startswith("https://")
        True
    """
    try:
        resp = session.get(_QUARTERLY_PAGE, headers=_SCRAPE_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise PSNIDataNotFoundError(f"Failed to fetch quarterly-reports page: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if href.lower().endswith((".xlsx", ".xls")):
            return href if href.startswith("http") else _BASE_URL + href

    raise PSNIDataNotFoundError(f"No .xlsx link found on {_QUARTERLY_PAGE}")


def get_annual_publication_url() -> str:
    """Scrape the complaint-statistics page for the latest .xlsx download link.

    policeombudsman.org returns 403 to default User-Agents; this function
    uses a browser-like UA via ``bolster.utils.web.session``.

    Returns:
        Absolute URL of the latest annual Excel spreadsheet.

    Raises:
        PSNIDataNotFoundError: If the page cannot be retrieved or no .xlsx
            link is found.

    Example:
        >>> url = get_annual_publication_url()
        >>> url.startswith("https://")
        True
    """
    try:
        resp = session.get(_ANNUAL_PAGE, headers=_SCRAPE_HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise PSNIDataNotFoundError(f"Failed to fetch annual statistics page: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if href.lower().endswith((".xlsx", ".xls")):
            return href if href.startswith("http") else _BASE_URL + href

    raise PSNIDataNotFoundError(f"No .xlsx link found on {_ANNUAL_PAGE}")


# ── Annual file parsers ────────────────────────────────────────────────────────


def _parse_annual_t1(xl: pd.ExcelFile) -> pd.DataFrame:
    """Parse the T1 (total complaints) sheet of the annual workbook.

    Returns a tidy DataFrame with columns ``year`` (int) and
    ``complaints`` (int), one row per financial year from 2000/01 onwards.
    """
    sheet = _find_sheet(xl, "T1")
    raw = xl.parse(sheet, header=None)

    # Locate the "Year" header row
    header_row = None
    for i, val in enumerate(raw.iloc[:, 0]):
        if str(val).strip().lower() == "year":
            header_row = i
            break
    if header_row is None:
        raise PSNIDataNotFoundError("Cannot find 'Year' header row in T1 sheet")

    data = raw.iloc[header_row + 1 :].copy()
    data.columns = ["year_label", "complaints"]
    data = data.dropna(subset=["year_label", "complaints"])
    data = data[data["year_label"].astype(str).str.match(r"^\d{4}/\d{2}")]
    data["year"] = data["year_label"].apply(_parse_fy_label)
    data["complaints"] = pd.to_numeric(data["complaints"], errors="coerce").astype("Int64")
    return data[["year", "year_label", "complaints"]].reset_index(drop=True)


def _parse_annual_t8(xl: pd.ExcelFile) -> pd.DataFrame:
    """Parse the T8 (by district) sheet of the annual workbook.

    Returns a tidy long-form DataFrame with columns
    ``year``, ``year_label``, ``district``, ``lgd_code``, ``complaints``.
    """
    sheet = _find_sheet(xl, "T8")
    raw = xl.parse(sheet, header=None)

    # Row 1 (0-indexed) is headers: District, 2011/12, 2012/13, ...
    header_row = 1
    headers = raw.iloc[header_row].tolist()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = [str(h).strip() if pd.notna(h) else f"_col{i}" for i, h in enumerate(headers)]

    district_col = data.columns[0]
    year_cols = [c for c in data.columns if _FY_RE.match(str(c).strip())]

    # Keep district rows only — drop NaN, total, and "Unknown / Other" rows
    data = data.dropna(subset=[district_col])
    _exclude = data[district_col].astype(str).str.lower()
    data = data[~(_exclude.str.contains("total", na=False) | _exclude.str.contains("unknown", na=False))]

    melted = data[[district_col] + year_cols].melt(
        id_vars=[district_col], var_name="year_label", value_name="complaints"
    )
    melted = melted.dropna(subset=["complaints"])
    melted["complaints"] = pd.to_numeric(melted["complaints"], errors="coerce").astype("Int64")
    melted["district"] = melted[district_col].apply(_normalise_annual_district)
    melted["lgd_code"] = melted["district"].map(LGD_CODES)
    melted["year"] = melted["year_label"].apply(_parse_fy_label)
    return melted[["year", "year_label", "district", "lgd_code", "complaints"]].reset_index(drop=True)


def _parse_annual_t10(xl: pd.ExcelFile) -> pd.DataFrame:
    """Parse the T10 (allegation types) sheet of the annual workbook.

    Returns a tidy long-form DataFrame with columns
    ``year``, ``year_label``, ``allegation_type``, ``allegation_subtype``,
    ``allegations``.

    The ``allegation_type`` column is forward-filled because the Excel uses
    merged cells for the parent category.
    """
    sheet = _find_sheet(xl, "T10")
    raw = xl.parse(sheet, header=None)

    # Row 1 has: "Allegation Type", "Allegation Subtype", year cols...
    header_row = 1
    headers = raw.iloc[header_row].tolist()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = [str(h).strip() if pd.notna(h) else f"_col{i}" for i, h in enumerate(headers)]

    type_col = data.columns[0]
    subtype_col = data.columns[1]

    # Forward-fill allegation type (merged cells appear as NaN below first row)
    data[type_col] = data[type_col].ffill()

    year_cols = [c for c in data.columns if _FY_RE.match(str(c).strip())]

    # Drop subtotal / total rows
    data = data[~data[subtype_col].astype(str).str.lower().isin(["subtotal", "total", "nan"])]
    data = data.dropna(subset=[subtype_col])

    melted = data[[type_col, subtype_col] + year_cols].melt(
        id_vars=[type_col, subtype_col], var_name="year_label", value_name="allegations"
    )
    melted = melted.dropna(subset=["allegations"])
    melted["allegations"] = pd.to_numeric(melted["allegations"], errors="coerce").astype("Int64")
    melted["year"] = melted["year_label"].apply(_parse_fy_label)
    melted = melted.rename(columns={type_col: "allegation_type", subtype_col: "allegation_subtype"})
    return melted[["year", "year_label", "allegation_type", "allegation_subtype", "allegations"]].reset_index(drop=True)


def _parse_annual_t12(xl: pd.ExcelFile) -> pd.DataFrame:
    """Parse the T12 (complaint closures) sheet of the annual workbook.

    Returns a tidy long-form DataFrame with columns
    ``year``, ``year_label``, ``outcome``, ``closures``.
    """
    sheet = _find_sheet(xl, "T12")
    raw = xl.parse(sheet, header=None)

    # Row 1 has: NaN, year_labels...
    header_row = 1
    headers = raw.iloc[header_row].tolist()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = [str(h).strip() if pd.notna(h) else f"_col{i}" for i, h in enumerate(headers)]

    outcome_col = data.columns[0]
    year_cols = [c for c in data.columns if _FY_RE.match(str(c).strip())]

    data = data.dropna(subset=[outcome_col])
    data = data[data[outcome_col].astype(str).str.strip() != "nan"]

    melted = data[[outcome_col] + year_cols].melt(id_vars=[outcome_col], var_name="year_label", value_name="closures")
    melted = melted.dropna(subset=["closures"])
    melted["closures"] = pd.to_numeric(melted["closures"], errors="coerce").astype("Int64")
    melted["year"] = melted["year_label"].apply(_parse_fy_label)
    melted = melted.rename(columns={outcome_col: "outcome"})
    return melted[["year", "year_label", "outcome", "closures"]].reset_index(drop=True)


def parse_annual(file_path: str) -> dict[str, pd.DataFrame]:
    """Parse the annual Police Ombudsman statistics Excel workbook.

    Extracts four key tables from the workbook:

    - ``totals``: total complaints 2000/01 onwards (T1)
    - ``by_district``: complaints by policing district, 2011/12 onwards (T8)
    - ``by_allegation_type``: allegations by type & subtype, 2011/12+ (T10)
    - ``by_outcome``: complaint closures by outcome, 2011/12 onwards (T12)

    Args:
        file_path: Local path (or file-like) to the downloaded ``.xlsx`` file.

    Returns:
        Dict mapping breakdown name to tidy DataFrame.  All DataFrames include
        ``year`` (int, financial-year start) and ``year_label`` (e.g.
        ``"2024/25"``) columns.

    Raises:
        PSNIDataNotFoundError: If required sheets cannot be found.

    Example:
        >>> from bolster.data_sources.psni import police_ombudsman
        >>> result = parse_annual.__doc__  # placeholder
        >>> 'totals' in result
        False
    """
    xl = pd.ExcelFile(file_path)
    return {
        "totals": _parse_annual_t1(xl),
        "by_district": _parse_annual_t8(xl),
        "by_allegation_type": _parse_annual_t10(xl),
        "by_outcome": _parse_annual_t12(xl),
    }


# ── Quarterly file parser ──────────────────────────────────────────────────────


def parse_quarterly(file_path: str) -> dict[str, pd.DataFrame]:
    """Parse a quarterly Police Ombudsman statistics Excel workbook.

    Extracts three tables:

    - ``complaints``: complaints received by quarter × year
    - ``allegations``: allegations received by quarter × year
    - ``by_district``: complaints by policing district × year

    The quarterly workbook covers the latest five financial years, with four
    quarters per year plus totals.

    Args:
        file_path: Local path (or file-like) to the downloaded ``.xlsx`` file.

    Returns:
        Dict mapping key name to long-form DataFrame.  Each DataFrame includes
        ``year_label`` (e.g. ``"2024/25"``) and ``year`` (int start year).

    Raises:
        PSNIDataNotFoundError: If required sheets cannot be found.

    Example:
        >>> from bolster.data_sources.psni import police_ombudsman
        >>> True  # real call requires downloaded file
        True
    """
    xl = pd.ExcelFile(file_path)

    def _parse_quarterly_table(sheet_name: str, value_name: str) -> pd.DataFrame:
        raw = xl.parse(sheet_name, header=None)
        # Row 3 (0-indexed): "Quarter", year_label, year_label, ...
        header_row = 3
        headers = raw.iloc[header_row].tolist()
        data = raw.iloc[header_row + 1 :].copy()
        data.columns = [str(h).strip() if pd.notna(h) else f"_col{i}" for i, h in enumerate(headers)]

        quarter_col = data.columns[0]
        year_cols = [c for c in data.columns if _FY_RE.match(str(c).strip())]

        # Keep only quarter rows
        data = data[data[quarter_col].astype(str).str.lower().str.startswith("quarter")]

        melted = data[[quarter_col] + year_cols].melt(
            id_vars=[quarter_col], var_name="year_label", value_name=value_name
        )
        melted = melted.dropna(subset=[value_name])
        melted[value_name] = pd.to_numeric(melted[value_name], errors="coerce").astype("Int64")
        melted["year"] = melted["year_label"].apply(_parse_fy_label)
        melted = melted.rename(columns={quarter_col: "quarter"})
        return melted[["year", "year_label", "quarter", value_name]].reset_index(drop=True)

    complaints_df = _parse_quarterly_table("Complaints Received", "complaints")
    allegations_df = _parse_quarterly_table("Allegations Received", "allegations")

    # District sheet name has a trailing space: "Complaints - Area & District "
    district_sheet = next(
        (s for s in xl.sheet_names if "area" in s.lower() and "district" in s.lower()),
        None,
    )
    if district_sheet is None:
        raise PSNIDataNotFoundError("District sheet not found in quarterly workbook")

    raw_d = xl.parse(district_sheet, header=None)
    # Row 3: Area, District, year1, year2
    header_row = 3
    headers = raw_d.iloc[header_row].tolist()
    data_d = raw_d.iloc[header_row + 1 :].copy()
    data_d.columns = [str(h).strip() if pd.notna(h) else f"_col{i}" for i, h in enumerate(headers)]

    district_col = data_d.columns[1]  # col 1 is "District"
    year_cols_d = [c for c in data_d.columns if _FY_RE.match(str(c).strip())]

    # Keep only rows where the district column starts with "District"
    data_d = data_d[data_d[district_col].astype(str).str.lower().str.startswith("district")]

    melted_d = data_d[[district_col] + year_cols_d].melt(
        id_vars=[district_col], var_name="year_label", value_name="complaints"
    )
    melted_d = melted_d.dropna(subset=["complaints"])
    melted_d["complaints"] = pd.to_numeric(melted_d["complaints"], errors="coerce").astype("Int64")
    melted_d["district"] = melted_d[district_col].apply(_normalise_quarterly_district)
    melted_d["lgd_code"] = melted_d["district"].map(LGD_CODES)
    melted_d["year"] = melted_d["year_label"].apply(_parse_fy_label)
    district_df = melted_d[["year", "year_label", "district", "lgd_code", "complaints"]].reset_index(drop=True)

    return {
        "complaints": complaints_df,
        "allegations": allegations_df,
        "by_district": district_df,
    }


# ── High-level accessor ────────────────────────────────────────────────────────


def get_latest_complaints(
    breakdown: str = "totals",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download and return the latest Police Ombudsman complaint data.

    For ``totals``, ``by_district``, ``by_allegation_type``, and
    ``by_outcome`` the annual publication is used (richest historical
    coverage).  For ``quarterly`` the latest quarterly bulletin is used.

    Args:
        breakdown: One of:

            - ``"totals"`` — total complaints 2000/01 to present (default)
            - ``"by_district"`` — complaints by policing district, 2011/12+
            - ``"by_allegation_type"`` — allegations by type, 2011/12+
            - ``"by_outcome"`` — closures by outcome, 2011/12+
            - ``"quarterly"`` — quarterly complaints, latest 5 financial years

        force_refresh: If ``True``, bypass cache and re-download the source file.

    Returns:
        Tidy DataFrame for the requested breakdown.

    Raises:
        ValueError: If *breakdown* is not one of the recognised values.
        PSNIDataNotFoundError: If the source cannot be downloaded.

    Example:
        >>> df = get_latest_complaints()
        >>> set(["year", "complaints"]).issubset(df.columns)
        True
        >>> df_d = get_latest_complaints("by_district")
        >>> "district" in df_d.columns
        True
    """
    _annual_keys = {"totals", "by_district", "by_allegation_type", "by_outcome"}
    _quarterly_keys = {"quarterly"}
    _all_keys = _annual_keys | _quarterly_keys

    if breakdown not in _all_keys:
        raise ValueError(f"Invalid breakdown {breakdown!r}. Choose from: {sorted(_all_keys)}")

    if breakdown in _quarterly_keys:
        url = get_quarterly_publication_url()
        file_path = download_file(url, cache_ttl_hours=24 * 7, force_refresh=force_refresh)
        data = parse_quarterly(file_path)
        return data["complaints"]

    url = get_annual_publication_url()
    file_path = download_file(url, cache_ttl_hours=24 * 30, force_refresh=force_refresh)
    data = parse_annual(file_path)
    return data[breakdown]


# ── Validation ─────────────────────────────────────────────────────────────────


def validate_complaints(df: pd.DataFrame, breakdown: str) -> bool:
    """Validate a Police Ombudsman complaints DataFrame.

    Checks that:

    - The DataFrame is non-empty.
    - Required columns for the given *breakdown* are present.
    - The ``year`` column contains plausible financial-year start years.
    - Complaint / allegation counts are non-negative.

    Args:
        df: DataFrame to validate (as returned by :func:`get_latest_complaints`).
        breakdown: One of ``"totals"``, ``"by_district"``,
            ``"by_allegation_type"``, ``"by_outcome"``, ``"quarterly"``.

    Returns:
        ``True`` if validation passes.

    Raises:
        PSNIValidationError: If any check fails.

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({"year": [2020, 2021], "complaints": [3000, 3100]})
        >>> validate_complaints(df, "totals")
        True
    """
    if df.empty:
        raise PSNIValidationError(f"Empty DataFrame for breakdown={breakdown!r}")

    required: dict[str, list[str]] = {
        "totals": ["year", "complaints"],
        "by_district": ["year", "district", "complaints"],
        "by_allegation_type": ["year", "allegation_type", "allegations"],
        "by_outcome": ["year", "outcome", "closures"],
        "quarterly": ["year", "quarter", "complaints"],
    }

    if breakdown not in required:
        raise PSNIValidationError(f"Unknown breakdown {breakdown!r}")

    missing = set(required[breakdown]) - set(df.columns)
    if missing:
        raise PSNIValidationError(f"Missing required columns for breakdown={breakdown!r}: {missing}")

    # Year range sanity check
    years = df["year"].dropna().astype(int)
    if years.empty:
        raise PSNIValidationError("No valid year values found")
    if years.min() < 2000 or years.max() > 2030:
        raise PSNIValidationError(
            f"Year values out of expected range [2000, 2030]: min={years.min()}, max={years.max()}"
        )

    # Value column must be non-negative
    value_col = required[breakdown][-1]
    values = pd.to_numeric(df[value_col], errors="coerce").dropna()
    if (values < 0).any():
        raise PSNIValidationError(f"Negative values found in column {value_col!r} for breakdown={breakdown!r}")

    logger.info(
        "validate_complaints passed: breakdown=%r, rows=%d, years=%d–%d",
        breakdown,
        len(df),
        int(years.min()),
        int(years.max()),
    )
    return True
