"""Inpatient and Day Case Activity in Northern Ireland.

Annual Department of Health (DoH) / NISRA Hospital Activity Information
Branch (HAIB) publication covering hospital bed activity -- available and
occupied beds, admissions, and length-of-stay proxies -- distinct from
:mod:`~bolster.data_sources.health_ni.elective_waiting_times` (which covers
patients queued *for* treatment, not activity once admitted).

Published as five separate workbooks rather than sheets of one file:

- **Pre-encompass** (:func:`get_bed_activity_by_specialty`) -- the long-run
  series (2016/17 to present) by HSC Trust, Hospital, Programme of Care and
  legacy Specialty classification. Since November 2023, each HSC Trust has
  moved onto a new electronic patient record system ("encompass") in turn
  (South Eastern first, Western/Southern last in 2025/26); this file only
  ever reflects the *legacy*-system portion of a quarter, so trust-level
  totals become a partial quarter once that trust has transitioned. See the
  workbook's own "Data Warning" sheet for the exact transition dates.
- **TFC** (:func:`get_bed_activity_by_treatment_function`) -- the
  encompass-system replacement for the above (2023/24 to present), using
  the NHS-wide Treatment Function Code standard rather than the legacy
  specialty classification. Not a like-for-like continuation of the
  pre-encompass series: different classification system, and only covers
  the post-transition portion of each trust's data.
- **POC** -- a coarser Programme-of-Care-only rollup of the same
  encompass-era data as TFC. Not covered by this module: it carries no
  information not already present (more coarsely aggregated) in
  :func:`get_bed_activity_by_treatment_function`.
- **Independent sector** (:func:`get_independent_sector_activity`) -- NI
  HSC-funded inpatient/day case activity delivered in independent
  (private) hospitals, by HSC Trust and specialty, 2016/17 to present.
- **Theatres** (:func:`get_theatre_usage`) -- operating theatre case
  throughput by hospital and admission urgency (Immediate/Urgent/
  Expedited/Elective), 2016/17 to present.

Data Source:
    **Hub page**: https://www.health-ni.gov.uk/articles/inpatient-and-day-case-activity

    The current edition is discovered by scraping the hub page for its
    first publication link (the current year's bulletin is always listed
    first, ahead of the explanatory notes, quality report and historical
    archive links), then scraping that publication page for all five
    workbook links. Filenames are year-stamped (e.g. ``...-25-26.xlsx``),
    so URLs are always discovered, never constructed.

Update Frequency: Annual, typically published in August.
Geographic Coverage: Northern Ireland, by HSC Trust and Hospital.
Reference Period: Financial year (e.g. 2025/26), by quarter; 2016/17 to
    present (2023/24 to present for the TFC series).

Example:
    >>> from bolster.data_sources.health_ni import hospital_activity
    >>> df = hospital_activity.get_bed_activity_by_specialty()  # doctest: +SKIP
    >>> "hsc_trust" in df.columns  # doctest: +SKIP
    True
"""

from __future__ import annotations

import logging
import re
from typing import cast

import bs4
import pandas as pd

from bolster.utils.excel import find_marker_row
from bolster.utils.text import clean_column_name
from bolster.utils.web import session

from ._base import (
    HEALTH_NI_BASE_URL,
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    make_absolute_url,
)

logger = logging.getLogger(__name__)

DOH_HUB_URL = "https://www.health-ni.gov.uk/articles/inpatient-and-day-case-activity"

# Substrings distinguishing each of the five workbook filenames, e.g.
# "hs-inpatient-pre-encompass-hts-tables-25-26.xlsx". Matched in this order
# to make sure "pre-encompass" (a superstring-safe match) is checked before
# any shorter, more general keyword could confuse the two encompass-era files.
_FILE_KEYWORDS = {
    "specialty": "pre-encompass",
    "treatment_function": "-tfc-",
    "independent": "independent",
    "theatres": "theatres",
}

_FOOTNOTE_RE = re.compile(r"\*+$")


def _clean_column(name: object) -> str:
    """Normalise a column header to snake_case, stripping trailing footnote markers."""
    return clean_column_name(_FOOTNOTE_RE.sub("", str(name).strip()))


def get_workbook_urls() -> dict[str, str]:
    """Find the URLs of the five current workbooks.

    Returns:
        Dictionary with keys ``"specialty"``, ``"treatment_function"``,
        ``"independent"`` and ``"theatres"``, each mapping to an absolute
        ``.xlsx`` URL.

    Raises:
        NISRADataNotFoundError: If the hub page, publication page, or any
            expected workbook link can't be found.

    Example:
        >>> urls = get_workbook_urls()  # doctest: +SKIP
        >>> set(urls) == {"specialty", "treatment_function", "independent", "theatres"}  # doctest: +SKIP
        True
    """
    try:
        response = session.get(DOH_HUB_URL, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch {DOH_HUB_URL}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, "html.parser")
    pub_url = None
    for a_tag in cast("list[bs4.Tag]", soup.find_all("a", href=True)):
        href = cast("str", a_tag["href"])
        if "/publications/" in href:
            pub_url = make_absolute_url(href, HEALTH_NI_BASE_URL)
            break
    if pub_url is None:
        raise NISRADataNotFoundError(f"No publications link found on {DOH_HUB_URL}")

    try:
        pub_response = session.get(pub_url, timeout=30)
        pub_response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch {pub_url}: {e}") from e

    pub_soup = bs4.BeautifulSoup(pub_response.content, "html.parser")
    xlsx_hrefs = [
        cast("str", a_tag["href"])
        for a_tag in cast("list[bs4.Tag]", pub_soup.find_all("a", href=True))
        if cast("str", a_tag["href"]).lower().endswith(".xlsx")
    ]

    urls = {}
    for key, keyword in _FILE_KEYWORDS.items():
        match = next((href for href in xlsx_hrefs if keyword in href.lower()), None)
        if match is None:
            raise NISRADataNotFoundError(f"No .xlsx link containing {keyword!r} found on {pub_url}")
        urls[key] = make_absolute_url(match, HEALTH_NI_BASE_URL)
    return urls


def _data_sheet_name(path) -> str:
    """Return the first sheet name that isn't the workbook's "Data Warning" cover sheet."""
    with pd.ExcelFile(path) as workbook:
        names = [name for name in workbook.sheet_names if name.strip().lower() != "data warning"]
    if not names:
        raise NISRADataNotFoundError(f"No data sheet found in {path}")
    return names[0]


def _parse_flat_sheet(path) -> pd.DataFrame:
    """Parse a tidy, single-header-row sheet (the specialty/TFC file shape)."""
    sheet_name = _data_sheet_name(path)
    table = pd.read_excel(path, sheet_name=sheet_name)
    table.columns = [_clean_column(c) for c in table.columns]
    return table


def _parse_single_table_sheet(path) -> pd.DataFrame:
    """Parse a "this worksheet contains one table" sheet (the theatres/independent shape).

    Layout: a title row, a "This worksheet contains one table." descriptor
    row, one or more blank rows, then the header row and data.
    """
    sheet_name = _data_sheet_name(path)
    sheet = pd.read_excel(path, sheet_name=sheet_name, header=None)

    marker_row = find_marker_row(sheet, lambda v: isinstance(v, str) and "worksheet contains" in v.lower())
    if marker_row is None:
        raise NISRADataNotFoundError(f"Could not find a 'worksheet contains' marker row in {sheet_name!r}")

    header_row = marker_row + 1
    while header_row < len(sheet) and sheet.iloc[header_row].isna().all():
        header_row += 1
    if header_row >= len(sheet):
        raise NISRADataNotFoundError(f"Could not find a header row after the marker in {sheet_name!r}")

    header = sheet.iloc[header_row]
    keep_columns = [i for i, value in enumerate(header) if pd.notna(value) and str(value).strip()]

    table = sheet.iloc[header_row + 1 :, keep_columns].copy()
    table.columns = [_clean_column(header.iloc[i]) for i in keep_columns]
    table = table.dropna(how="all").reset_index(drop=True)

    non_numeric_columns = table.columns.difference(table.select_dtypes(include="number").columns)
    for column in non_numeric_columns:
        converted = pd.to_numeric(table[column], errors="coerce")
        if converted.notna().any():
            table[column] = converted
    return table


def get_bed_activity_by_specialty(force_refresh: bool = False) -> pd.DataFrame:
    """Return the long-run bed activity series by legacy specialty (pre-encompass file).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``financial_year``, ``quarter_ending``,
        ``hsc_trust``, ``hospital``, ``programme_of_care``, ``specialty``,
        and numeric columns ``total_available_beds``,
        ``average_available_beds``, ``total_occupied_beds``,
        ``average_occupied_beds``, ``total_inpatients``, ``total_day_case``,
        ``elective_inpatient``, ``non_elective_inpatient``, ``day_case``,
        ``regular_attenders``. Covers 2016/17 to present, but only the
        legacy-system portion of a quarter for any trust that has since
        transitioned to encompass -- see the module docstring.

    Example:
        >>> df = get_bed_activity_by_specialty()  # doctest: +SKIP
        >>> "2016-2017" in set(df['financial_year'])  # doctest: +SKIP
        True
    """
    urls = get_workbook_urls()
    path = download_file(urls["specialty"], force_refresh=force_refresh)
    return _parse_flat_sheet(path)


def get_bed_activity_by_treatment_function(force_refresh: bool = False) -> pd.DataFrame:
    """Return the encompass-era bed activity series by Treatment Function Code (TFC file).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``financial_year``, ``quarter_ending``,
        ``hsc_trust``, ``hospital``, ``programme_of_care``, ``specialty``
        (a Treatment Function Code category, not the legacy specialty
        classification used by :func:`get_bed_activity_by_specialty`), and
        numeric columns ``total_occupied_beds``, ``total_inpatients``,
        ``total_day_cases``, ``elective_inpatient``,
        ``non_elective_inpatient``, ``day_case``, ``regular_attenders``.
        Covers 2023/24 to present -- only the post-transition portion of
        each trust's data.

    Example:
        >>> df = get_bed_activity_by_treatment_function()  # doctest: +SKIP
        >>> "2023-2024" in set(df['financial_year'])  # doctest: +SKIP
        True
    """
    urls = get_workbook_urls()
    path = download_file(urls["treatment_function"], force_refresh=force_refresh)
    return _parse_flat_sheet(path)


def get_independent_sector_activity(force_refresh: bool = False) -> pd.DataFrame:
    """Return NI HSC-funded activity delivered in independent (private) hospitals.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``financial_year``, ``hsc_trust``,
        ``source`` (``"Legacy"`` or ``"encompass"``), ``programme_of_care``,
        ``specialty``, and numeric columns ``inpatient``, ``day_case``.
        Covers 2016/17 to present.

    Example:
        >>> df = get_independent_sector_activity()  # doctest: +SKIP
        >>> {"inpatient", "day_case"}.issubset(df.columns)  # doctest: +SKIP
        True
    """
    urls = get_workbook_urls()
    path = download_file(urls["independent"], force_refresh=force_refresh)
    return _parse_single_table_sheet(path)


def get_theatre_usage(force_refresh: bool = False) -> pd.DataFrame:
    """Return operating theatre case throughput by hospital and admission urgency.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``financial_year``, ``programme_of_care``,
        ``hsc_trust``, ``hospital``, ``source`` (``"Legacy"`` or
        ``"encompass"``), and numeric columns ``immediate``, ``urgent``,
        ``expedited``, ``elective``, ``total``. Covers 2016/17 to present.

    Example:
        >>> df = get_theatre_usage()  # doctest: +SKIP
        >>> (df["total"] >= df["elective"]).all()  # doctest: +SKIP
        True
    """
    urls = get_workbook_urls()
    path = download_file(urls["theatres"], force_refresh=force_refresh)
    return _parse_single_table_sheet(path)


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a parsed DataFrame is structurally sound.

    Args:
        df: DataFrame returned by any of this module's ``get_*`` functions.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        NISRAValidationError: If the frame is empty or has no numeric data
            columns with any non-null values.

    Example:
        >>> validate_data(get_bed_activity_by_specialty())  # doctest: +SKIP
        True
    """
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    numeric_columns = df.select_dtypes(include="number").columns
    if len(numeric_columns) == 0:
        raise NISRAValidationError("No numeric data columns found")

    if df[numeric_columns].notna().sum().sum() == 0:
        raise NISRAValidationError("All numeric data columns are entirely null")

    return True
