"""NISRA Highest Qualification and Participation in Education and Training.

Annual Labour Force Survey (LFS) release covering two related headline
measures for the working-age population (16 to 64):

- The **highest qualification level held** (No qualifications through
  Level 6+), for NI and the UK, 2015 to present.
- The **lifelong learning indicator**: participation in education or
  training among 25 to 64 year olds, NI and the UK, 2016 to present.

A companion workbook breaks the Level 2+ and Level 3+ attainment thresholds
down further by Local Government District, sex, age band, disability and
deprivation quintile.

Both workbooks are published with the same recurring layout: each worksheet
stacks one or more sub-tables vertically, each introduced by a
``"Table X.Yz: <description>"`` row with its own header immediately below.
:func:`_read_blocks` parses this generically rather than hard-coding a
function per sub-table.

Data Source:
    **Hub page**: https://www.nisra.gov.uk/statistics/work-pay-and-benefits/labour-force-survey

    The current edition is discovered by scraping the hub page for the
    "Highest qualification level held and participation" publication link,
    then scraping that publication page for its two workbooks. Filenames
    change every year (e.g. ``highest-qualification-2025.xlsx``), so URLs
    are always discovered, never constructed.

Update Frequency: Annual, typically published in August/September.
Geographic Coverage: Northern Ireland and UK (headline tables); Local
    Government District (Level 2/3 attainment breakdown).
Reference Period: Calendar year, January to December (rolling series from
    2015/2016 to the latest year).

Note:
    Because LFS estimates come from a household sample survey, cells based
    on small samples are flagged in a dedicated "Small sample size cells"
    column rather than being suppressed outright.

Example:
    >>> from bolster.data_sources.nisra import highest_qualification as hq
    >>> df = hq.get_qualification_levels()  # doctest: +SKIP
    >>> sorted(df['geography'].unique())  # doctest: +SKIP
    ['NI', 'UK']
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from bolster.utils.text import clean_column_name

from ._base import NISRADataNotFoundError, NISRAValidationError, download_file, find_publication_link

logger = logging.getLogger(__name__)

HUB_URL = "https://www.nisra.gov.uk/statistics/work-pay-and-benefits/labour-force-survey"
_PUB_TEXT = "Highest qualification level held and participation"

# Annual publication -- re-check monthly for a new edition, matching the
# convention used by other annual NISRA releases (business_register, deprivation).
_CACHE_TTL_HOURS = 24 * 30

#: Breakdown sheets in the Level 2/3 companion workbook.
LEVEL_2_3_BREAKDOWNS = [
    "NI",
    "Male",
    "Female",
    "Aged_16_to_24",
    "Aged_25_to_34",
    "Aged_35_to_49",
    "Aged_50_to_64",
    "Disabled",
    "Not_disabled",
    "Deprivation",
]

_NOTE_RE = re.compile(r"\s*\[[Nn]ote \d+\]")
# Non-greedy but allows embedded commas in the captured area (e.g. "Armagh
# City, Banbridge and Craigavon") -- anchored on "aged <digit>" rather than
# a bare comma boundary, since some area names contain commas of their own.
_AREA_RE = re.compile(r",\s*(.+?),\s*aged \d", re.IGNORECASE)
_QUINTILE_RE = re.compile(r"quintile \d[^,]*", re.IGNORECASE)


def _clean_column(name: object) -> str:
    """Normalise a published column header into snake_case.

    Strips embedded newlines and ``[note N]`` references, expands
    ``(Number)``/``(%)``/``(Percentage)`` suffixes, then lowercases and
    collapses everything else to underscores.
    """
    text = str(name).replace("\n", " ")
    text = _NOTE_RE.sub("", text)
    text = re.sub(r"\(number\)", " number", text, flags=re.IGNORECASE)
    text = re.sub(r"\(percentage\)", " pct", text, flags=re.IGNORECASE)
    text = re.sub(r"\(%\)", " pct", text)
    return clean_column_name(text)


def _extract_area(title: str, sheet_name: str) -> str:
    """Extract the geography/breakdown label embedded in a block's title row."""
    if sheet_name == "Deprivation":
        match = _QUINTILE_RE.search(title)
        if match:
            return match.group(0).strip()
    match = _AREA_RE.search(title)
    if match:
        return match.group(1).strip()
    raise NISRADataNotFoundError(f"Could not extract an area/geography label from table title: {title!r}")


def _read_blocks(path, sheet_name: str) -> list[tuple[str, pd.DataFrame]]:
    """Split a worksheet into its vertically-stacked sub-tables.

    Args:
        path: Path to the downloaded workbook.
        sheet_name: Sheet to parse.

    Returns:
        List of ``(title, DataFrame)`` tuples in sheet order.

    Raises:
        NISRADataNotFoundError: If no ``"Table ..."`` title row is found.
    """
    sheet = pd.read_excel(path, sheet_name=sheet_name, header=None)
    title_rows = [
        index
        for index in range(len(sheet))
        if isinstance(sheet.iat[index, 0], str) and sheet.iat[index, 0].startswith("Table ")
    ]
    if not title_rows:
        raise NISRADataNotFoundError(f"No 'Table ...' blocks found in sheet {sheet_name!r}")

    blocks = []
    for position, title_row in enumerate(title_rows):
        title = sheet.iat[title_row, 0]
        header_row = title_row + 1
        end_row = title_rows[position + 1] - 1 if position + 1 < len(title_rows) else len(sheet)
        while end_row > header_row and sheet.iloc[end_row - 1].isna().all():
            end_row -= 1

        columns = [_clean_column(c) for c in sheet.iloc[header_row]]
        table = sheet.iloc[header_row + 1 : end_row].copy()
        table.columns = columns
        table = table.dropna(how="all").reset_index(drop=True)
        for column in columns:
            table[column] = pd.to_numeric(table[column], errors="coerce")
        blocks.append((title, table))
    return blocks


def get_qualification_levels_url(force_refresh: bool = False) -> str:
    """Find the URL of the latest highest-qualification-level workbook.

    Args:
        force_refresh: Bypass the page-discovery cache.

    Returns:
        Absolute URL of the Excel workbook.

    Raises:
        NISRADataNotFoundError: If the publication or file link can't be found.

    Example:
        >>> url = get_qualification_levels_url()  # doctest: +SKIP
        >>> url.endswith('.xlsx')  # doctest: +SKIP
        True
    """
    return find_publication_link(
        hub_url=HUB_URL,
        pub_text_contains=_PUB_TEXT,
        file_href_contains="highest-qualification",
        force_refresh=force_refresh,
    )


def get_level_2_3_url(force_refresh: bool = False) -> str:
    """Find the URL of the latest Level 2/3 attainment breakdown workbook.

    Args:
        force_refresh: Bypass the page-discovery cache.

    Returns:
        Absolute URL of the Excel workbook.

    Raises:
        NISRADataNotFoundError: If the publication or file link can't be found.

    Example:
        >>> url = get_level_2_3_url()  # doctest: +SKIP
        >>> url.endswith('.xlsx')  # doctest: +SKIP
        True
    """
    return find_publication_link(
        hub_url=HUB_URL,
        pub_text_contains=_PUB_TEXT,
        file_href_contains="Level-2-Level_3",
        force_refresh=force_refresh,
    )


def get_qualification_levels(force_refresh: bool = False) -> pd.DataFrame:
    """Return highest qualification level held, NI and UK, 2015 to present.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``geography``, ``year``, one
        number/percentage column pair per qualification band (no
        qualifications, below level 2, level 2, level 3, level 4 to 5,
        level 6), ``total_number`` and ``small_sample_size_cells``.

    Example:
        >>> df = get_qualification_levels()  # doctest: +SKIP
        >>> sorted(df['geography'].unique())  # doctest: +SKIP
        ['NI', 'UK']
    """
    path = download_file(
        get_qualification_levels_url(force_refresh=force_refresh),
        cache_ttl_hours=_CACHE_TTL_HOURS,
        force_refresh=force_refresh,
    )
    frames = []
    for title, table in _read_blocks(path, "Table_1"):
        table.insert(0, "geography", _extract_area(title, "Table_1"))
        frames.append(table)
    return pd.concat(frames, ignore_index=True)


def get_participation(force_refresh: bool = False) -> pd.DataFrame:
    """Return the lifelong learning participation headline series, NI and UK.

    Participation in education or training among 25 to 64 year olds, 2016
    to present. NI and UK figures are published side by side in a single
    table, so (unlike :func:`get_qualification_levels`) no ``geography``
    column is needed.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year``, number/percentage participating
        for NI and UK, and ``small_sample_size_cells``.

    Example:
        >>> df = get_participation()  # doctest: +SKIP
        >>> df['year'].min()  # doctest: +SKIP
        2016
    """
    path = download_file(
        get_qualification_levels_url(force_refresh=force_refresh),
        cache_ttl_hours=_CACHE_TTL_HOURS,
        force_refresh=force_refresh,
    )
    _, table = _read_blocks(path, "Table_2")[0]
    return table


def get_qualified_level_2_3(breakdown: str = "NI", force_refresh: bool = False) -> pd.DataFrame:
    """Return Level 2+ and Level 3+ attainment for one demographic/geographic breakdown.

    Args:
        breakdown: One of :data:`LEVEL_2_3_BREAKDOWNS`. ``"NI"``, ``"Male"``,
            ``"Female"``, the four age-band sheets and the disability sheets
            each split into NI plus its 11 Local Government Districts;
            ``"Deprivation"`` splits into the most- and least-deprived
            quintiles only.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``area``, ``year``, ``level_2_and_above_number``,
        ``level_2_and_above_pct``, ``level_3_and_above_number``,
        ``level_3_and_above_pct`` and ``small_sample_size_cells``.

    Raises:
        NISRADataNotFoundError: If ``breakdown`` is not a valid sheet name.

    Example:
        >>> df = get_qualified_level_2_3("Deprivation")  # doctest: +SKIP
        >>> sorted(df['area'].unique())  # doctest: +SKIP
        ['quintile 1 (most deprived)', 'quintile 5 (least deprived)']
    """
    if breakdown not in LEVEL_2_3_BREAKDOWNS:
        raise NISRADataNotFoundError(f"{breakdown!r} is not a valid breakdown; see LEVEL_2_3_BREAKDOWNS")

    path = download_file(
        get_level_2_3_url(force_refresh=force_refresh),
        cache_ttl_hours=_CACHE_TTL_HOURS,
        force_refresh=force_refresh,
    )
    frames = []
    for title, table in _read_blocks(path, breakdown):
        table.insert(0, "area", _extract_area(title, breakdown))
        frames.append(table)
    return pd.concat(frames, ignore_index=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a parsed DataFrame is structurally sound.

    Args:
        df: DataFrame returned by any ``get_*`` function in this module.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        NISRAValidationError: If the frame is empty, missing a ``year``
            column, or has no non-null numeric data columns.

    Example:
        >>> validate_data(get_participation())  # doctest: +SKIP
        True
    """
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    if "year" not in df.columns:
        raise NISRAValidationError(f"Missing expected 'year' column in {list(df.columns)}")

    label_columns = {"geography", "area", "year"}
    data_columns = [c for c in df.columns if c not in label_columns]
    if not data_columns:
        raise NISRAValidationError("No data columns found")

    if df[data_columns].notna().sum().sum() == 0:
        raise NISRAValidationError("All data columns are entirely null")

    return True
