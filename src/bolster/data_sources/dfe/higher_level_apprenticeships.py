"""Higher Level Apprenticeships (HLA) in Higher Education Institutions NI.

Annual Department for the Economy (DfE) statistical bulletin covering HLA
programmes (Level 6/7 apprenticeships) delivered in Higher Education
Institutions (HEIs) in Northern Ireland since 2018/19. Published as 29
tables in a single workbook, one worksheet each, covering three stages of
the HLA lifecycle:

- **Starts** (``A`` tables) — new entrants, by provider, sex, age, level,
  subject area, STEM indicator, and (for NI-domiciled starts) deprivation
  quintile, Local Government District and Parliamentary Constituency.
- **Participants** (``B`` tables) — the live caseload, with similar
  breakdowns.
- **Qualifiers** (``C`` tables) — students who completed, with similar
  breakdowns.
- **Supplementary** (``S`` tables) — dependant status, disability,
  ethnicity, marital status and religion, for the latest academic year only.

Unlike :mod:`~bolster.data_sources.dfe.higher_education_enrolments`'s
nested-header cross-tabs, every sheet here holds exactly one flat table: a
title row, a "this worksheet contains one table" descriptor, a single
header row, and data rows ending in a ``Total``/``All Providers`` row.
:func:`list_tables` surfaces the full catalogue (from the workbook's own
"Contents" sheet) and :func:`get_table` reads any one of them generically,
mirroring :func:`bolster.data_sources.nisra.pxstat.read_dataset`'s
matrix-code pattern.

Data Source:
    **Hub page**: https://www.economy-ni.gov.uk/articles/higher-level-apprenticeships-northern-ireland-heis-statistical-fact-sheets

    The current edition is discovered by scraping the hub page for the
    "Higher Level Apprenticeships in HEIs" publication link, then scraping
    that publication page for its workbook. Filenames change every year
    (e.g. ``HLA HEI 2024_25.xlsx``), so the URL is always discovered, never
    constructed.

Update Frequency: Annual, typically published in August.
Geographic Coverage: Northern Ireland; NI-domiciled breakdowns additionally
    by Local Government District and Parliamentary Constituency.
Reference Period: Academic year (e.g. 2024/25); most tables cover 2020/21
    to present, ``S`` (supplementary) tables the latest year only.

Example:
    >>> from bolster.data_sources.dfe import higher_level_apprenticeships as hla
    >>> tables = hla.list_tables()  # doctest: +SKIP
    >>> "A1" in set(tables['table_id'])  # doctest: +SKIP
    True
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

HUB_URL = (
    "https://www.economy-ni.gov.uk/articles/higher-level-apprenticeships-northern-ireland-heis-statistical-fact-sheets"
)
_PUB_TEXT = "Higher Level Apprenticeships in HEIs"

# Annual publication -- re-check monthly for a new edition.
_CACHE_TTL_HOURS = 24 * 30

_downloader = CachedDownloader("dfe_higher_level_apprenticeships", timeout=60)
download_file = bind_download_file(_downloader, DfEDataNotFoundError, _CACHE_TTL_HOURS)

_NOTE_RE = re.compile(r"\s*\[notes? [\d, ]+\]", re.IGNORECASE)


def get_workbook_url(force_refresh: bool = False) -> str:
    """Find the URL of the latest HLA workbook.

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
            file_href_contains="HLA",
            force_refresh=force_refresh,
        )
    except Exception as e:
        raise DfEDataNotFoundError(f"Could not find the HLA workbook: {e}") from e


def list_tables(force_refresh: bool = False) -> pd.DataFrame:
    """Return the catalogue of all 29 tables in this publication.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``table_id`` (e.g. ``"A1"``), ``sheet_name``
        (e.g. ``"Table_A1"``) and ``title``.

    Example:
        >>> tables = list_tables()  # doctest: +SKIP
        >>> "A1" in set(tables['table_id'])  # doctest: +SKIP
        True
    """
    path = download_file(get_workbook_url(force_refresh=force_refresh), force_refresh=force_refresh)
    contents = pd.read_excel(path, sheet_name="Contents", header=1)
    contents = contents[contents["Worksheet name"] != "Notes"].copy()
    contents["table_id"] = contents["Worksheet name"].str.replace("Table ", "", regex=False)
    contents["sheet_name"] = "Table_" + contents["table_id"]
    contents["title"] = contents["Table name"].apply(lambda title: _NOTE_RE.sub("", str(title)).strip())
    return contents[["table_id", "sheet_name", "title"]].reset_index(drop=True)


def get_table(table_id: str, force_refresh: bool = False) -> pd.DataFrame:
    """Return one table from the publication by its ID.

    Args:
        table_id: Table identifier, e.g. ``"A1"``, ``"B3"``, ``"S2"``
            (case-insensitive). See :func:`list_tables` for the full
            catalogue.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with the first column renamed to ``category`` and every
        other column snake_cased from its published header.

    Raises:
        DfEDataNotFoundError: If ``table_id`` is not in the catalogue, or
            the sheet has no recognisable header row.

    Example:
        >>> df = get_table("C1")  # doctest: +SKIP
        >>> "category" in df.columns  # doctest: +SKIP
        True
    """
    tables = list_tables(force_refresh=force_refresh)
    match = tables[tables["table_id"].str.upper() == table_id.upper()]
    if match.empty:
        raise DfEDataNotFoundError(f"Unknown table id {table_id!r}; see list_tables() for valid values")
    sheet_name = match["sheet_name"].iloc[0]

    path = download_file(get_workbook_url(force_refresh=force_refresh), force_refresh=force_refresh)
    sheet = pd.read_excel(path, sheet_name=sheet_name, header=None)

    marker_row = find_marker_row(sheet, lambda v: isinstance(v, str) and "worksheet contains" in v.lower())
    if marker_row is None:
        raise DfEDataNotFoundError(f"Could not find a header row in sheet {sheet_name!r}")
    header_row = marker_row + 1

    columns = ["category"] + [_clean_column(c) for c in sheet.iloc[header_row, 1:]]
    table = sheet.iloc[header_row + 1 :].copy()
    table.columns = columns
    table = table.dropna(how="all").reset_index(drop=True)
    for column in columns[1:]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


def get_starts(force_refresh: bool = False) -> pd.DataFrame:
    """Return HLA starts (new entrants) by sex, Academic Years 2020/21 to present (Table A2).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``category`` (``Female``/``Male``/``Total``)
        and one number column per academic year.

    Example:
        >>> df = get_starts()  # doctest: +SKIP
        >>> "category" in df.columns  # doctest: +SKIP
        True
    """
    return get_table("A2", force_refresh=force_refresh)


def get_participants(force_refresh: bool = False) -> pd.DataFrame:
    """Return HLA participants by sex, Academic Years 2020/21 to present (Table B2).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``category`` (``Female``/``Male``/``Total``)
        and one number column per academic year.

    Example:
        >>> df = get_participants()  # doctest: +SKIP
        >>> "category" in df.columns  # doctest: +SKIP
        True
    """
    return get_table("B2", force_refresh=force_refresh)


def get_qualifiers(force_refresh: bool = False) -> pd.DataFrame:
    """Return HLA qualifiers by academic year, 2020/21 to present (Table C1).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``category`` (the academic year, e.g.
        ``"2024/25"``) and ``qualified_hla_students_no``.

    Example:
        >>> df = get_qualifiers()  # doctest: +SKIP
        >>> "category" in df.columns  # doctest: +SKIP
        True
    """
    return get_table("C1", force_refresh=force_refresh)


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a parsed table DataFrame is structurally sound.

    Args:
        df: DataFrame returned by :func:`get_table` or one of its
            convenience wrappers.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        DfEValidationError: If the frame is empty, missing a ``category``
            column, or has no non-null numeric data.

    Example:
        >>> validate_data(get_qualifiers())  # doctest: +SKIP
        True
    """
    if df.empty:
        raise DfEValidationError("DataFrame is empty")

    if "category" not in df.columns:
        raise DfEValidationError(f"Missing expected 'category' column in {list(df.columns)}")

    data_columns = [c for c in df.columns if c != "category"]
    if not data_columns:
        raise DfEValidationError("No data columns found")

    if df[data_columns].notna().sum().sum() == 0:
        raise DfEValidationError("All data columns are entirely null")

    return True
