"""Qualifications gained at UK Higher Education Institutions: NI Analysis.

Annual Department for the Economy (DfE) statistical bulletin, sourced from
HESA (the Higher Education Statistics Agency), and the direct companion
publication to :mod:`~bolster.data_sources.dfe.higher_education_enrolments`
(qualifications gained rather than enrolments, same student populations,
same academic year). Covers two related populations:

- **NI-domiciled students gaining qualifications at any UK HEI** (Table 1)
  -- by level of qualification, mode of study and location of institution
  (NI / GB / Open University).
- **All students gaining qualifications at NI's own HEIs** (Table 6),
  regardless of domicile -- by level of qualification, mode of study and
  country of domicile (NI / GB / RoI / other EU / non-EU).

The publication has 12 tables in total (with dozens of lettered
percentage-change and demographic sub-tables); this module covers the two
headline cross-tabulations, mirroring the scope of the enrolments module.
Both share the same layout as their enrolments counterparts: a title row, a
three-row nested column header (level of qualification -> location/domicile
-> NI/GB/.../Total), then repeating mode marker rows (Full-time, Part-time,
Total) each followed by one data row per academic year. One quirk: Table 1's
row-axis header cell reads "Mode and Year" but Table 6's reads "Level and
Year" -- the same structure under a differently-worded label.

Data Source:
    **Hub page**: https://www.economy-ni.gov.uk/articles/higher-education-qualifications

    The current edition is discovered by scraping the hub page for the
    "Qualifications gained at UK Higher Education Institutions" publication
    link, then scraping that publication page for its workbook. Filenames
    change every year (e.g.
    ``Qualifications  2024_25 Tables.xlsx``), so the URL is always
    discovered, never constructed.

Update Frequency: Annual, typically published in September.
Geographic Coverage: Northern Ireland, GB, Republic of Ireland, EU and
    non-EU (by domicile/location, not sub-NI geography).
Reference Period: Academic year (e.g. 2024/25), 2015/16 to present.

Note:
    Counts are rounded to the nearest 5 (0, 1, 2 round to 0) to prevent
    identification of individuals, so components will not always sum
    exactly to their published totals.

Example:
    >>> from bolster.data_sources.dfe import higher_education_qualifications as qualifications
    >>> df = qualifications.get_ni_domiciled_qualifications()  # doctest: +SKIP
    >>> sorted(df['mode'].unique())  # doctest: +SKIP
    ['full_time', 'part_time', 'total']
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from bolster.utils.cache import CachedDownloader, bind_download_file
from bolster.utils.excel import find_marker_row
from bolster.utils.text import clean_column_name as _clean_column
from bolster.utils.web import find_publication_link

from ._base import DfEDataNotFoundError, DfEValidationError

logger = logging.getLogger(__name__)

HUB_URL = "https://www.economy-ni.gov.uk/articles/higher-education-qualifications"
_PUB_TEXT = "Qualifications gained at UK Higher Education Institutions"

# Annual publication -- re-check monthly for a new edition.
_CACHE_TTL_HOURS = 24 * 30

_downloader = CachedDownloader("dfe_higher_education_qualifications", timeout=60)
download_file = bind_download_file(_downloader, DfEDataNotFoundError, _CACHE_TTL_HOURS)

_MODE_LABELS = {"Full-time", "Part-time", "Total"}
_YEAR_RE = re.compile(r"^\d{4}/\d{2}$")


def get_workbook_url(force_refresh: bool = False) -> str:
    """Find the URL of the latest Qualifications workbook.

    Args:
        force_refresh: Bypass the page-discovery cache.

    Returns:
        Absolute URL of the Excel workbook.

    Raises:
        DfEDataNotFoundError: If the publication or file link can't be found.

    Example:
        >>> url = get_workbook_url()  # doctest: +SKIP
        >>> url.endswith('.xlsx')  # doctest: +SKIP
        True
    """
    try:
        return find_publication_link(
            hub_url=HUB_URL,
            pub_text_contains=_PUB_TEXT,
            file_href_contains="Qualifications",
            force_refresh=force_refresh,
        )
    except Exception as e:
        raise DfEDataNotFoundError(f"Could not find the Qualifications workbook: {e}") from e


def _parse_wide_table(path, sheet_name: str) -> pd.DataFrame:
    """Parse a "Mode/Level and Year" cross-tabulation sheet (Table 1 / Table 6 shape).

    Args:
        path: Path to the downloaded workbook.
        sheet_name: Sheet to parse.

    Returns:
        DataFrame with columns ``mode``, ``year``, and one numeric column per
        (level of qualification x location/domicile) combination.

    Raises:
        DfEDataNotFoundError: If the sheet has no row-axis header row.
    """
    sheet = pd.read_excel(path, sheet_name=sheet_name, header=None)

    # Table 1 labels this "Mode and Year"; Table 6 labels the identically
    # shaped row axis "Level and Year" instead -- accept either.
    header_row = find_marker_row(sheet, lambda v: isinstance(v, str) and v.strip().lower().endswith("and year"))
    if header_row is None:
        raise DfEDataNotFoundError(f"Could not find a '... and Year' header row in sheet {sheet_name!r}")

    group_row = sheet.iloc[header_row - 2]
    sub_row = sheet.iloc[header_row]

    columns = ["mode", "year"]
    data_columns = []
    current_group = None
    for col in range(1, sheet.shape[1]):
        sub_label = sub_row[col]
        if pd.isna(sub_label):
            current_group = None
            continue
        if pd.notna(group_row[col]):
            current_group = group_row[col]
        name = f"{current_group} {sub_label}" if current_group is not None else str(sub_label)
        columns.append(_clean_column(name))
        data_columns.append(col)

    rows = []
    mode = None
    for index in range(header_row + 1, len(sheet)):
        label = sheet.iat[index, 0]
        if pd.isna(label):
            continue
        label = str(label).strip()
        if label in _MODE_LABELS:
            mode = label
            continue
        if _YEAR_RE.match(label):
            rows.append([mode, label] + [sheet.iat[index, col] for col in data_columns])
            continue
        break  # Footer text ("Source: ...", "Notes", ...) reached.

    table = pd.DataFrame(rows, columns=columns)
    table["mode"] = table["mode"].str.lower().str.replace("-", "_", regex=False)
    for column in columns[2:]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


def get_ni_domiciled_qualifications(force_refresh: bool = False) -> pd.DataFrame:
    """Return NI-domiciled students gaining qualifications at any UK HEI (Table 1).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``mode`` (``full_time``/``part_time``/
        ``total``), ``year`` (e.g. ``"2024/25"``), and one number column per
        (level of qualification x location) combination -- e.g.
        ``first_degree_ni``, ``postgraduate_total``.

    Example:
        >>> df = get_ni_domiciled_qualifications()  # doctest: +SKIP
        >>> total_row = df[(df['mode'] == 'total') & (df['year'] == '2024/25')]  # doctest: +SKIP
        >>> int(total_row['total_total'].iloc[0]) > 0  # doctest: +SKIP
        True
    """
    path = download_file(get_workbook_url(force_refresh=force_refresh), force_refresh=force_refresh)
    return _parse_wide_table(path, "Table1")


def get_ni_hei_qualifications(force_refresh: bool = False) -> pd.DataFrame:
    """Return all students gaining qualifications at NI's own HEIs, by domicile (Table 6).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``mode``, ``year``, and one number column per
        (level of qualification x country of domicile) combination -- e.g.
        ``first_degree_ni``, ``total_non_eu``.

    Example:
        >>> df = get_ni_hei_qualifications()  # doctest: +SKIP
        >>> sorted(df['mode'].unique())  # doctest: +SKIP
        ['full_time', 'part_time', 'total']
    """
    path = download_file(get_workbook_url(force_refresh=force_refresh), force_refresh=force_refresh)
    return _parse_wide_table(path, "Table6")


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a parsed DataFrame is structurally sound.

    Args:
        df: DataFrame returned by :func:`get_ni_domiciled_qualifications` or
            :func:`get_ni_hei_qualifications`.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        DfEValidationError: If the frame is empty, missing ``mode``/``year``
            columns, or has no non-null numeric data.

    Example:
        >>> validate_data(get_ni_domiciled_qualifications())  # doctest: +SKIP
        True
    """
    if df.empty:
        raise DfEValidationError("DataFrame is empty")

    if not {"mode", "year"}.issubset(df.columns):
        raise DfEValidationError(f"Missing expected 'mode'/'year' columns in {list(df.columns)}")

    data_columns = [c for c in df.columns if c not in {"mode", "year"}]
    if not data_columns:
        raise DfEValidationError("No data columns found")

    if df[data_columns].notna().sum().sum() == 0:
        raise DfEValidationError("All data columns are entirely null")

    return True
