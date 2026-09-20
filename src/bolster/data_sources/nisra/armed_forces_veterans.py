"""Census 2021: UK Armed Forces Veterans for Northern Ireland.

A one-off Census 2021 topic report estimating the veteran population of
Northern Ireland, produced by linking the Ministry of Defence's Service
Leavers Database against Census 2021 records — unlike England, Wales and
Scotland, the NI Census questionnaire did not ask a direct "have you
served" question.

This is a **static snapshot**, not a recurring series: there is nothing to
refresh, and no "latest" framing applies. The underlying data will never
change, so downloads are cached indefinitely.

The publication provides 138 separate cross-tabulation tables (``AFV001``
through ``AFV138``ish, covering age, sex, health, housing, employment and
more), each published as its own workbook with up to three geography-level
sheets (Northern Ireland, Local Government District, Health and Social Care
Trust — not every table has all three). Rather than one accessor per table,
:func:`list_tables` surfaces the full catalogue and :func:`get_table` reads
any one of them by table number, mirroring
:func:`bolster.data_sources.nisra.pxstat.read_dataset`'s matrix-code
pattern.

Data Source:
    **Publication page**:
    https://www.nisra.gov.uk/publications/census-2021-uk-armed-forces-veterans-for-northern-ireland

    The page links a single "table listing" workbook cataloguing all 138
    tables; the tables themselves are not individually linked but follow a
    predictable filename pattern (``census-2021-afv001.xlsx``, etc.) in the
    same directory as the listing.

Update Frequency: None — a one-off Census Day 2021 (21 March 2021) snapshot.
Geographic Coverage: Northern Ireland, Local Government District, or Health
    and Social Care Trust (varies by table — see :func:`list_tables`).
Reference Period: Census Day 2021 (21 March 2021).

Note:
    Suppressed cells (small counts withheld for disclosure control) are
    marked ``*`` in the source and become ``NaN`` after parsing.

Example:
    >>> from bolster.data_sources.nisra import armed_forces_veterans as afv
    >>> tables = afv.list_tables()  # doctest: +SKIP
    >>> len(tables) > 100  # doctest: +SKIP
    True
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from bolster.utils.excel import find_marker_row
from bolster.utils.web import scrape_file_links

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

PUBLICATION_URL = "https://www.nisra.gov.uk/publications/census-2021-uk-armed-forces-veterans-for-northern-ireland"

# Static Census 2021 snapshot -- this data will never change, so cache for a year.
_CACHE_TTL_HOURS = 24 * 365

# Most table numbers are "AFV" + 3 digits, but some have a trailing letter
# for an alternative/supplementary cut of the same base table (e.g. "AFV038a").
_TABLE_NUMBER_RE = re.compile(r"^AFV\d{3}[a-z]?$", re.IGNORECASE)


def _find_listing_url() -> str:
    """Find the URL of the master table-listing workbook.

    Returns:
        Absolute URL of the ``.xlsx`` table listing.

    Raises:
        NISRADataNotFoundError: If the publication page can't be fetched or
            has no matching ``.xlsx`` link.
    """
    links = scrape_file_links(PUBLICATION_URL, ".xlsx")
    matches = [link["url"] for link in links if "table-listing" in link["url"].lower()]

    if not matches:
        raise NISRADataNotFoundError(f"No table listing workbook found on {PUBLICATION_URL}")

    return matches[0]


def list_tables(force_refresh: bool = False) -> pd.DataFrame:
    """Return the catalogue of all 138 tables in this publication.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``file_name``, ``table_number``,
        ``table_title``, ``geographies`` and ``suppression``.

    Example:
        >>> tables = list_tables()  # doctest: +SKIP
        >>> 'AFV001' in set(tables['table_number'])  # doctest: +SKIP
        True
    """
    url = _find_listing_url()
    path = download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    df = pd.read_excel(path, sheet_name="Table listing")
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _table_url(table_number: str, force_refresh: bool = False) -> str:
    """Construct a table's download URL from the listing workbook's own directory."""
    listing_url = _find_listing_url()
    base_dir = listing_url.rsplit("/", 1)[0]

    tables = list_tables(force_refresh=force_refresh)
    match = tables[tables["table_number"].str.upper() == table_number.upper()]
    if match.empty:
        raise NISRADataNotFoundError(f"Unknown table number {table_number!r}; see list_tables() for valid values")

    file_name = match["file_name"].iloc[0]
    return f"{base_dir}/{file_name}.xlsx"


def get_table(table_number: str, geography: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return one table from the publication, optionally filtered to one geography level.

    Args:
        table_number: Table identifier, e.g. ``"AFV001"`` (case-insensitive).
            See :func:`list_tables` for the full catalogue.
        geography: One of ``"NI"``, ``"LGD"`` or ``"HSCT"`` to return only
            that geography level's sheet. Defaults to all geography levels
            the table actually has (not every table publishes all three),
            combined with a ``geography_level`` column.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``geography``, ``geography_code``, one column
        per category in the table (suppressed cells as ``NaN``), and
        ``geography_level`` when ``geography`` is not specified.

    Raises:
        NISRADataNotFoundError: If ``table_number`` is not in the catalogue,
            or ``geography`` doesn't match any sheet in the table.

    Example:
        >>> df = get_table("AFV001", geography="NI")  # doctest: +SKIP
        >>> int(df['Veteran'].iloc[0])  # doctest: +SKIP
        37697
    """
    if not _TABLE_NUMBER_RE.match(table_number):
        raise NISRADataNotFoundError(f"{table_number!r} doesn't look like a table number, e.g. 'AFV001'")

    url = _table_url(table_number, force_refresh)
    path = download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    workbook = pd.ExcelFile(path)

    # Sheets are usually named "{TABLE_NUMBER}_{GEOGRAPHY}", e.g. "AFV001_NI";
    # not every table publishes all three geography levels. Some "a"-suffixed
    # supplementary tables (e.g. "AFV038a") instead publish bare geography
    # sheet names with no table-number prefix at all.
    geography_levels = {"NI", "LGD", "HSCT"}
    prefix = f"{table_number.upper()}_"
    available = {name[len(prefix) :]: name for name in workbook.sheet_names if name.startswith(prefix)}
    if not available:
        available = {name.upper(): name for name in workbook.sheet_names if name.upper() in geography_levels}

    if geography is not None:
        if geography.upper() not in available:
            raise NISRADataNotFoundError(
                f"{table_number} has no {geography!r} geography level; available: {sorted(available)}"
            )
        return _parse_sheet(workbook, available[geography.upper()])

    frames = []
    for level, sheet_name in available.items():
        frame = _parse_sheet(workbook, sheet_name)
        frame.insert(0, "geography_level", level)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _parse_sheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    """Parse one geography-level sheet: header row starts at "Geography", data follows to the end."""
    sheet = pd.read_excel(workbook, sheet_name=sheet_name, header=None)

    header_row = find_marker_row(sheet, lambda v: str(v).strip() == "Geography", max_rows=20)
    if header_row is None:
        raise NISRAValidationError(f"Could not find a 'Geography' header row in sheet {sheet_name!r}")

    raw_columns = sheet.iloc[header_row].tolist()
    columns = [str(c).strip() for c in raw_columns]
    columns[0], columns[1] = "geography", "geography_code"

    table = sheet.iloc[header_row + 1 :].copy()
    table.columns = columns
    table = table.dropna(how="all").reset_index(drop=True)

    for column in columns[2:]:
        table[column] = pd.to_numeric(table[column], errors="coerce")

    return table


def get_population(force_refresh: bool = False) -> pd.DataFrame:
    """Return the headline veteran/non-veteran population table (AFV001).

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``geography_level``, ``geography``,
        ``geography_code``, ``Non-veteran`` and ``Veteran``.

    Example:
        >>> df = get_population()  # doctest: +SKIP
        >>> ni_row = df[df['geography'] == 'Northern Ireland']  # doctest: +SKIP
        >>> int(ni_row['Veteran'].iloc[0])  # doctest: +SKIP
        37697
    """
    return get_table("AFV001", force_refresh=force_refresh)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a parsed table DataFrame is structurally sound.

    Args:
        df: DataFrame returned by :func:`get_table` or :func:`get_population`.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        NISRAValidationError: If the frame is empty, missing the geography
            columns, or has no non-null category values.

    Example:
        >>> validate_data(get_population())  # doctest: +SKIP
        True
    """
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if not {"geography", "geography_code"}.issubset(df.columns):
        raise NISRAValidationError(f"Missing expected geography columns in {list(df.columns)}")

    category_columns = [c for c in df.columns if c not in {"geography_level", "geography", "geography_code"}]
    if not category_columns:
        raise NISRAValidationError("No category columns found")

    if df[category_columns].notna().sum().sum() == 0:
        raise NISRAValidationError("All category columns are entirely null")

    return True
