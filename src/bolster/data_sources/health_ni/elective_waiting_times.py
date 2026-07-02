"""NISRA Elective/Outpatient Waiting Times Module.

Provides access to Northern Ireland's elective and outpatient waiting times
statistics, covering inpatient/day case and outpatient referrals waiting by
weeks-waited band, specialty, and HSC Trust.

Data is published quarterly by the Department of Health NI and covers two
separate series:

- **Inpatient/Day Case Waiting Times** — patients waiting by management type
  (Day Case or Inpatient), weeks-waited band, specialty, and HSC Trust.
  Data from Q1 2007-08 (quarter ending June 2007) to present.

- **Outpatient Waiting Times** — referrals waiting by weeks-waited band,
  specialty, and HSC Trust. Data from Q1 2008-09 (quarter ending June 2008)
  to present.

Both series contain two sheets reflecting a system change:

- **Pre-encompass**: Legacy PAS data up to March 2025 (inpatient) / March 2025
  (outpatient). Inpatient pre-encompass includes additional derived aggregate
  columns (e.g. "> 26 weeks") that are excluded from the long-format output.
- **encompass**: Data from the new electronic patient record system, starting
  from South Eastern Trust in December 2023. Not directly comparable with
  pre-encompass data due to the system transition.

Waiting Bands (Inpatient/Day Case — weeks):
    0 - 6, >6 - 13, >13 - 21, >21 - 26, >26 - 52, >52 - 65, >65 - 78,
    >78 - 91, >91 - 104, >104

Waiting Bands (Outpatient — weeks):
    0 - 6, >6 - 9, >9 - 13 / >9 - 12*, >12 - 15, >15 - 18, >18 - 26,
    >26 - 39, >39 - 52, >52 - 65, >65 - 78, >78 - 91, >91 - 104, >104

    (*The >9-13 / >9-12 split is a historical artefact; both columns appear
    but only one is populated per row.)

HSC Trusts:
    Belfast, Northern, South Eastern, Southern, Western
    (DPC = Domiciliary/Primary Care, included in source data but typically
    excluded from trust-level analyses)

Data Sources:
    - Inpatient/Day Case: https://www.health-ni.gov.uk/articles/inpatient-waiting-times
    - Outpatient: https://www.health-ni.gov.uk/articles/outpatient-waiting-times

Update Frequency:
    Quarterly, published approximately 3-6 months after the quarter end.

Example:
    >>> from bolster.data_sources.nisra import elective_waiting_times as ewt
    >>> df = ewt.get_latest_elective_waiting_times()
    >>> sorted(df.columns.tolist())
    ['date', 'patients_waiting', 'programme_of_care', 'quarter_ending', 'specialty', 'trust', 'waiting_type', 'weeks_waited_band', 'year']

    >>> ewt.validate_elective_waiting_times(df)
    True

Publication Details:
    - Frequency: Quarterly (published ~3-6 months after quarter end)
    - Published by: Department of Health NI
    - Sources: https://www.health-ni.gov.uk/articles/inpatient-waiting-times
               https://www.health-ni.gov.uk/articles/outpatient-waiting-times
"""

import logging
from pathlib import Path

import pandas as pd

from ._base import (
    NISRAValidationError,
    download_file,
    find_latest_xlsx,
)

logger = logging.getLogger(__name__)

DOH_INPATIENT_PAGE = "https://www.health-ni.gov.uk/articles/inpatient-waiting-times"
DOH_OUTPATIENT_PAGE = "https://www.health-ni.gov.uk/articles/outpatient-waiting-times"

# Sheet names (same in both inpatient and outpatient files)
SHEET_PRE_ENCOMPASS = "Pre-encompass"
SHEET_ENCOMPASS = "encompass"

# Expected HSC Trusts (excluding DPC variants)
EXPECTED_TRUSTS = {"Belfast", "Northern", "South Eastern", "Southern", "Western"}

# ---- Inpatient/Day Case column definitions ----
# Core identifier columns present in both pre-encompass and encompass sheets
IP_ID_COLS = ["Management", "Quarter Ending", "HSC Trust", "Specialty", "Programme Of Care"]

# Granular waiting-band columns present in BOTH inpatient sheets
# (pre-encompass has additional derived columns like "> 26 weeks" which we ignore)
IP_BAND_COLS = [
    "0 - 6 weeks",
    "> 6 - 13 weeks",
    "> 13 - 21 weeks",
    "> 21 - 26 weeks",
    "> 26-52 weeks",
    "> 52 - 65 weeks",
    "> 65 - 78 weeks",
    "> 78 - 91 weeks",
    "> 91 - 104 weeks",
    "> 104 weeks",
]

# ---- Outpatient column definitions ----
OP_ID_COLS = ["Quarter Ending", "HSC Trust", "Specialty", "Programme of Care"]

# Granular waiting-band columns (both pre-encompass and encompass have the same cols)
# The ">9 - 13 Wks" / ">9 - 12 Wks" split is a historical artefact — both present,
# only one populated per row. We include both and let the melt capture them.
OP_BAND_COLS = [
    "0 - 6 Wks",
    ">6 - 9 Wks",
    ">9 - 13 Wks",
    ">9 - 12 Wks",
    ">12 - 15 Wks",
    ">15 - 18 Wks",
    ">18 - 26 Wks",
    ">26 - 39 Wks",
    ">39 - 52 Wks",
    ">52 - 65 Wks",
    ">65 - 78 Wks",
    ">78 - 91 Wks",
    ">91 - 104 Wks",
    ">104 Wks",
]

# Required columns in the final validated output
REQUIRED_COLUMNS = {
    "date",
    "year",
    "quarter_ending",
    "trust",
    "specialty",
    "programme_of_care",
    "weeks_waited_band",
    "patients_waiting",
    "waiting_type",
}


def get_elective_waiting_times_url() -> dict[str, str]:
    """Scrape the Department of Health pages to find the latest Excel file URLs.

    Returns:
        Dictionary with keys ``"inpatient"`` and ``"outpatient"``, each mapping
        to the absolute URL of the most recent quarterly Excel file.

    Raises:
        NISRADataNotFoundError: If either URL cannot be located.
    """
    return {
        "inpatient": find_latest_xlsx(DOH_INPATIENT_PAGE, keyword="inpatient-and-day-case"),
        "outpatient": find_latest_xlsx(DOH_OUTPATIENT_PAGE, keyword="outpatient"),
    }


def _parse_inpatient_sheet(file_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """Parse one sheet from an inpatient/day case Excel file into long format.

    Reads the given sheet, selects only the core identifier and granular band
    columns (ignoring derived aggregate columns), melts the band columns, and
    returns a tidy DataFrame.

    Args:
        file_path: Path to the inpatient Excel file.
        sheet_name: Name of the sheet (``"Pre-encompass"`` or ``"encompass"``).

    Returns:
        Long-format DataFrame with columns: management, quarter_ending, trust,
        specialty, programme_of_care, weeks_waited_band, patients_waiting.
    """
    df = pd.read_excel(file_path, sheet_name=sheet_name)

    # Select only columns that exist (band cols may differ between sheets)
    available_band_cols = [c for c in IP_BAND_COLS if c in df.columns]
    select_cols = IP_ID_COLS + available_band_cols + ["Total"]
    df = df[[c for c in select_cols if c in df.columns]].copy()

    # Rename for consistency
    df = df.rename(
        columns={
            "Management": "management",
            "Quarter Ending": "quarter_ending",
            "HSC Trust": "trust",
            "Specialty": "specialty",
            "Programme Of Care": "programme_of_care",
            "Total": "total",
        }
    )

    # Melt band columns to long format
    id_cols = ["management", "quarter_ending", "trust", "specialty", "programme_of_care"]
    if "total" in df.columns:
        id_cols.append("total")

    return df.melt(
        id_vars=id_cols,
        value_vars=list(available_band_cols),
        var_name="weeks_waited_band",
        value_name="patients_waiting",
    )


def _parse_outpatient_sheet(file_path: str | Path, sheet_name: str) -> pd.DataFrame:
    """Parse one sheet from an outpatient Excel file into long format.

    Args:
        file_path: Path to the outpatient Excel file.
        sheet_name: Name of the sheet (``"Pre-encompass"`` or ``"encompass"``).

    Returns:
        Long-format DataFrame with columns: quarter_ending, trust, specialty,
        programme_of_care, weeks_waited_band, patients_waiting.
    """
    df = pd.read_excel(file_path, sheet_name=sheet_name)

    available_band_cols = [c for c in OP_BAND_COLS if c in df.columns]
    select_cols = OP_ID_COLS + available_band_cols + ["Total Waiting"]
    df = df[[c for c in select_cols if c in df.columns]].copy()

    df = df.rename(
        columns={
            "Quarter Ending": "quarter_ending",
            "HSC Trust": "trust",
            "Specialty": "specialty",
            "Programme of Care": "programme_of_care",
            "Total Waiting": "total",
        }
    )

    id_cols = ["quarter_ending", "trust", "specialty", "programme_of_care"]
    if "total" in df.columns:
        id_cols.append("total")

    return df.melt(
        id_vars=id_cols,
        value_vars=list(available_band_cols),
        var_name="weeks_waited_band",
        value_name="patients_waiting",
    )


def _parse_file(file_path: str | Path, waiting_type: str) -> pd.DataFrame:
    """Parse both sheets of an elective waiting times Excel file.

    Reads the ``Pre-encompass`` and ``encompass`` sheets, concatenates them,
    adds a ``waiting_type`` label, converts the quarter_ending column to a
    proper date, and derives ``date`` and ``year`` columns.

    Args:
        file_path: Path to the downloaded Excel file.
        waiting_type: Label to populate the ``waiting_type`` column.
            Use ``"inpatient_day_case"`` for inpatient files and
            ``"outpatient"`` for outpatient files.

    Returns:
        Long-format DataFrame.
    """
    with pd.ExcelFile(file_path) as xl:
        sheet_names = xl.sheet_names

    parts = []
    for sheet in [SHEET_PRE_ENCOMPASS, SHEET_ENCOMPASS]:
        if sheet not in sheet_names:
            logger.warning(f"Sheet '{sheet}' not found in {file_path} — skipping")
            continue

        if waiting_type == "inpatient_day_case":
            chunk = _parse_inpatient_sheet(file_path, sheet)
        else:
            chunk = _parse_outpatient_sheet(file_path, sheet)

        chunk["data_source"] = sheet  # Pre-encompass vs encompass label
        parts.append(chunk)

    if not parts:
        raise NISRAValidationError(f"No data sheets found in {file_path}")

    df = pd.concat(parts, ignore_index=True)
    df["waiting_type"] = waiting_type

    # Normalise quarter_ending to datetime (mixed formats: datetime objects from
    # openpyxl for inpatient pre-encompass, string dates like "30-Jun-08" for
    # outpatient pre-encompass, and ISO-ish strings from the encompass sheet)
    df["quarter_ending"] = pd.to_datetime(df["quarter_ending"], errors="coerce", format="mixed")
    df = df.dropna(subset=["quarter_ending"])

    # Add date (= quarter_ending) and year
    df["date"] = df["quarter_ending"]
    df["year"] = df["date"].dt.year.astype(int)

    # Coerce patients_waiting to numeric
    df["patients_waiting"] = pd.to_numeric(df["patients_waiting"], errors="coerce")

    return df


def parse_elective_waiting_times_file(file_path: str | Path) -> pd.DataFrame:
    """Parse a combined elective waiting times Excel file (inpatient or outpatient).

    Reads both ``Pre-encompass`` and ``encompass`` sheets from the file, melts
    the weekly waiting-band columns into long format, and returns a unified
    DataFrame.

    The parser auto-detects the file type (inpatient vs outpatient) by checking
    whether a ``Management`` column (present only in inpatient files) exists in
    the first data sheet.

    Args:
        file_path: Path to an Excel file downloaded from the Department of
            Health inpatient or outpatient waiting times publication pages.

    Returns:
        Long-format DataFrame with columns:

        - ``date`` (datetime): Quarter-end date (e.g. 2025-12-31)
        - ``year`` (int): Calendar year of the quarter end
        - ``quarter_ending`` (datetime): Same as ``date``
        - ``trust`` (str): HSC Trust name
        - ``specialty`` (str): Medical specialty
        - ``programme_of_care`` (str): Programme of care grouping
        - ``weeks_waited_band`` (str): Waiting band label (e.g. "0 - 6 weeks")
        - ``patients_waiting`` (float): Number of patients/referrals in that band
        - ``waiting_type`` (str): ``"inpatient_day_case"`` or ``"outpatient"``

        For inpatient files, ``management`` (``"Day Case"`` or ``"Inpatient"``)
        is also present.

    Raises:
        NISRAValidationError: If neither expected sheet is found in the file.
    """
    with pd.ExcelFile(file_path) as xl:
        sheet_names = xl.sheet_names

    target_sheet = SHEET_PRE_ENCOMPASS if SHEET_PRE_ENCOMPASS in sheet_names else SHEET_ENCOMPASS
    probe = pd.read_excel(file_path, sheet_name=target_sheet, nrows=0)

    waiting_type = "inpatient_day_case" if "Management" in probe.columns else "outpatient"
    return _parse_file(file_path, waiting_type)


def get_latest_elective_waiting_times(force_refresh: bool = False) -> pd.DataFrame:
    """Download and return the latest elective waiting times data (both series).

    Fetches the most recent quarterly publication for both the inpatient/day
    case and outpatient series, parses each into long format, and returns a
    combined DataFrame.

    Args:
        force_refresh: If ``True``, bypass the on-disk cache and re-download
            the Excel files.

    Returns:
        Combined long-format DataFrame covering both inpatient/day case and
        outpatient waiting times.  See :func:`parse_elective_waiting_times_file`
        for the column schema.

    Raises:
        NISRADataNotFoundError: If either publication page or Excel file cannot
            be located.
        NISRAValidationError: If the downloaded data fails schema validation.
    """
    urls = get_elective_waiting_times_url()

    parts = []
    for key, url in urls.items():
        logger.info(f"Downloading {key} waiting times from {url}")
        file_path = download_file(url, force_refresh=force_refresh)
        # Determine waiting_type from key so we don't need to re-probe
        waiting_type = "inpatient_day_case" if key == "inpatient" else "outpatient"
        parts.append(_parse_file(file_path, waiting_type))

    df = pd.concat(parts, ignore_index=True)
    validate_elective_waiting_times(df)
    return df


def validate_elective_waiting_times(df: pd.DataFrame) -> bool:
    """Validate that an elective waiting times DataFrame meets quality requirements.

    Checks that the DataFrame is non-empty, contains all required columns, and
    has no negative patient counts.

    Args:
        df: DataFrame as returned by :func:`get_latest_elective_waiting_times`
            or :func:`parse_elective_waiting_times_file`.

    Returns:
        ``True`` if all checks pass.

    Raises:
        NISRAValidationError: If the DataFrame is empty, missing required
            columns, or contains negative ``patients_waiting`` values.
    """
    if df is None or len(df) == 0:
        raise NISRAValidationError("Elective waiting times DataFrame is empty")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {missing}")

    valid = df["patients_waiting"].dropna()
    if len(valid) > 0 and (valid < 0).any():
        n_neg = (valid < 0).sum()
        raise NISRAValidationError(f"patients_waiting contains {n_neg} negative value(s); min = {valid.min()}")

    return True
