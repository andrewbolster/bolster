"""Northern Ireland Greenhouse Gas Inventory (DAERA).

Annual greenhouse gas emissions statistics for Northern Ireland, derived from
the National Atmospheric Emissions Inventory (NAEI) and published by the
Department of Agriculture, Environment and Rural Affairs (DAERA).

The published workbook contains nine data tables covering NI emissions by
sector, by gas, by gas-within-sector, inventory revisions, progress against
the Programme for Government measure, the equivalent UK figures, and two
alternative sector classifications (National Communication and Territorial
Emissions Statistics).

Data Source:
    **Discovery page**:
    https://www.daera-ni.gov.uk/articles/northern-ireland-greenhouse-gas-inventory

    That article links to one statistical bulletin page per edition
    (``1990-2008`` through ``1990-2024``).  This module scrapes the article to
    find the most recent bulletin, then scrapes that bulletin for the data
    workbook, so it keeps working when a new edition is published.

Update Frequency:
    Annual, published in June.  The reporting period runs from 1990 to two
    calendar years before publication.  Note that 1991-1994 and 1996-1997 are
    not published in the time series.

Geographic Coverage:
    Northern Ireland, with United Kingdom totals provided for comparison.

Units:
    Tables reported as full time series (sector, National Communication and
    Territorial Emissions Statistics breakdowns) are in **ktCO2e**.  Summary
    and change tables are in **MtCO2e**.  Column names carry the unit suffix.

    LULUCF (Land Use, Land Use Change and Forestry) and some categories can
    legitimately be **negative** where removals exceed emissions, so
    validation does not reject negative values.

Example:
    >>> from bolster.data_sources import daera_greenhouse_gas
    >>> df = daera_greenhouse_gas.get_emissions_by_sector()
    >>> 'sector' in df.columns and 'emissions_ktco2e' in df.columns
    True

"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import cast

import pandas as pd
from bs4 import Tag  # noqa: TC002 (used inside `cast(...)`, evaluated at runtime)

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import fetch_soup, scrape_file_links

logger = logging.getLogger(__name__)

# ── Public pages to scrape for the current workbook URL ──────────────────────
DAERA_ARTICLE_PAGE = "https://www.daera-ni.gov.uk/articles/northern-ireland-greenhouse-gas-inventory"
DAERA_BASE_URL = "https://www.daera-ni.gov.uk"

# Bulletin pages are named ".../northern-ireland-greenhouse-gas-inventory-1990-YYYY-statistical-bulletin"
_BULLETIN_RE = re.compile(r"greenhouse-gas-inventory-1990-(\d{4})-statistical-bulletin")
_YEAR_RE = re.compile(r"\d{4}")

# ── Cached downloader (namespace = "daera", shared with daera_waste) ─────────
_downloader = CachedDownloader("daera", timeout=60)

# Editions change once a year, so a long TTL is appropriate.
_CACHE_TTL_HOURS = 24 * 30

# Unicode subscripts appear in the "by gas" tables but not the others.
_GAS_ALIASES = {"CO₂": "CO2", "CH₄": "CH4", "N₂O": "N2O"}

# Rows that sit inside a data block but are not observations.
_NON_DATA_LABELS = {"% of all gases"}


class DAERADataNotFoundError(Exception):
    """DAERA greenhouse gas workbook or publication page could not be located."""


class DAERAValidationError(Exception):
    """DAERA DataFrame failed validation checks."""


# ── Source discovery ─────────────────────────────────────────────────────────


def _absolute(href: str) -> str:
    """Resolve a possibly-relative DAERA href to an absolute URL.

    Example:
        >>> _absolute("/publications/foo")
        'https://www.daera-ni.gov.uk/publications/foo'
        >>> _absolute("https://example.com/bar")
        'https://example.com/bar'
    """
    return f"{DAERA_BASE_URL}{href}" if href.startswith("/") else href


def get_bulletin_pages() -> dict[int, str]:
    """Return every published bulletin page keyed by its final inventory year.

    Returns:
        Mapping of inventory end year (e.g. ``2024``) to bulletin page URL,
        sorted with the most recent edition last.

    Raises:
        DAERADataNotFoundError: If the article page lists no bulletin pages.
    """
    soup = fetch_soup(DAERA_ARTICLE_PAGE)

    pages: dict[int, str] = {}
    for anchor in cast("list[Tag]", soup.find_all("a", href=True)):
        href = cast("str", anchor["href"])
        match = _BULLETIN_RE.search(href)
        if match:
            pages[int(match.group(1))] = _absolute(href)

    if not pages:
        raise DAERADataNotFoundError(f"No greenhouse gas bulletin pages found on {DAERA_ARTICLE_PAGE}")

    logger.info(f"Found {len(pages)} greenhouse gas bulletin editions")
    return dict(sorted(pages.items()))


def get_workbook_url(year: int | None = None) -> str:
    """Return the data-workbook URL for an inventory edition.

    Args:
        year: Final inventory year of the desired edition (e.g. ``2024``).
            Defaults to the most recent published edition.

    Returns:
        Absolute URL of the ``.xlsx`` data tables workbook.

    Raises:
        DAERADataNotFoundError: If the edition or its workbook cannot be found.
    """
    pages = get_bulletin_pages()
    if year is None:
        year = max(pages)
    if year not in pages:
        raise DAERADataNotFoundError(f"No greenhouse gas bulletin published for 1990-{year}; have {sorted(pages)}")

    # Suffix casing varies between editions (".XLSX" in 2024, ".xlsx" earlier).
    links = scrape_file_links(pages[year], ".xlsx", base_url=DAERA_BASE_URL)
    if not links:
        raise DAERADataNotFoundError(f"No .xlsx workbook linked from {pages[year]}")

    return links[0]["url"]


@lru_cache(maxsize=4)
def _load_workbook(year: int | None = None, force_refresh: bool = False) -> pd.ExcelFile:
    """Download and open the inventory workbook, using the on-disk cache.

    Args:
        year: Final inventory year; defaults to the most recent edition.
        force_refresh: Bypass the download cache.

    Returns:
        An open :class:`pandas.ExcelFile` for the workbook.

    Raises:
        DAERADataNotFoundError: If the workbook cannot be downloaded.
    """
    url = get_workbook_url(year)
    try:
        path = _downloader.download(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    except DownloadError as exc:
        raise DAERADataNotFoundError(str(exc)) from exc
    return pd.ExcelFile(path)


def _sheet(name: str, year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Read one workbook sheet as a header-less DataFrame."""
    workbook = _load_workbook(year, force_refresh)
    if name not in workbook.sheet_names:
        raise DAERADataNotFoundError(f"Sheet {name!r} missing from workbook; have {workbook.sheet_names}")
    return pd.read_excel(workbook, sheet_name=name, header=None)


# ── Sheet parsing helpers ────────────────────────────────────────────────────


def _clean_header(value: object, position: int) -> str:
    """Normalise a raw header cell into a usable column name.

    Year headers arrive inconsistently as floats (``1990.0``) or strings
    (``'2024'``) depending on how the sheet was authored, so both are coerced
    to a plain four-digit string.

    Example:
        >>> _clean_header(1990.0, 2)
        '1990'
        >>> _clean_header('Base year', 1)
        'BaseYear'
        >>> _clean_header(float('nan'), 7)
        '_unnamed_7'
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return f"_unnamed_{position}"
    if isinstance(value, int | float):
        return str(int(value))
    text = str(value).strip()
    if text.replace(" ", "").lower() == "baseyear":
        return "BaseYear"
    return text or f"_unnamed_{position}"


def _find_header_rows(sheet: pd.DataFrame, label: str) -> list[int]:
    """Return the row indices whose first cell equals ``label``.

    Several sheets stack two or three tables vertically; each repeats the same
    first-column label, so the caller selects by position.
    """
    first_column = sheet.iloc[:, 0].astype(str).str.strip()
    rows = first_column[first_column == label].index.tolist()
    if not rows:
        raise DAERAValidationError(f"No header row labelled {label!r} found in sheet")
    return rows


def _read_block(sheet: pd.DataFrame, header_row: int, n_label_cols: int = 1) -> pd.DataFrame:
    """Slice a single table out of a sheet that may hold several.

    Reads forward from ``header_row`` until the label column runs out or the
    first value column stops being numeric, which is what separates a data
    block from the source notes and footnotes underneath it.

    Args:
        sheet: Header-less sheet DataFrame.
        header_row: Index of the row holding column names.
        n_label_cols: Number of leading identifier columns; everything to the
            right of these is expected to be numeric.

    Returns:
        DataFrame with cleaned column names and only the data rows.
    """
    columns = [_clean_header(value, position) for position, value in enumerate(sheet.iloc[header_row])]

    rows: list[int] = []
    for index in range(header_row + 1, len(sheet)):
        label = sheet.iat[index, 0]
        if label is None or (isinstance(label, float) and pd.isna(label)):
            break
        # Footnote and source rows carry text in column 0 and nothing numeric
        # beside it.  Genuine data rows may still have individual gaps, so the
        # whole row is checked rather than a single probe cell.
        values = sheet.iloc[index, n_label_cols:]
        if not any(isinstance(value, int | float) and not pd.isna(value) for value in values):
            break
        if str(label).strip() in _NON_DATA_LABELS:
            continue
        rows.append(index)

    if not rows:
        raise DAERAValidationError(f"No data rows found below header row {header_row}")

    block = sheet.loc[rows].copy()
    block.columns = columns
    block = block.loc[:, [column for column in block.columns if not column.startswith("_unnamed_")]]
    return block.reset_index(drop=True)


def _year_columns(block: pd.DataFrame) -> list[str]:
    """Return the four-digit year column names of a block, in order."""
    return [column for column in block.columns if _YEAR_RE.fullmatch(str(column))]


def _melt_years(block: pd.DataFrame, id_columns: list[str], value_name: str) -> pd.DataFrame:
    """Reshape a wide year-per-column block into tidy long format.

    The ``BaseYear`` column is deliberately dropped: it is a near-duplicate of
    1990 and is exposed instead through the dedicated change tables.
    """
    years = _year_columns(block)
    if not years:
        raise DAERAValidationError("Block contains no year columns")

    long = block.melt(id_vars=id_columns, value_vars=years, var_name="year", value_name=value_name)
    long["year"] = long["year"].astype(int)
    long[value_name] = pd.to_numeric(long[value_name], errors="coerce")
    for column in id_columns:
        long[column] = long[column].astype(str).str.strip()
    return long.sort_values([*id_columns, "year"]).reset_index(drop=True)


def _normalise_gases(series: pd.Series) -> pd.Series:
    """Map Unicode-subscript gas names onto their ASCII equivalents."""
    return series.astype(str).str.strip().replace(_GAS_ALIASES)


def _melt_gases(block: pd.DataFrame, value_name: str) -> pd.DataFrame:
    """Reshape a sector x gas matrix into tidy long format."""
    gases = [column for column in block.columns if column not in {"Sector", "Total", "All gases"}]
    long = block.melt(id_vars=["Sector"], value_vars=gases, var_name="gas", value_name=value_name)
    long = long.rename(columns={"Sector": "sector"})
    long["sector"] = long["sector"].astype(str).str.strip()
    long["gas"] = _normalise_gases(long["gas"])
    long[value_name] = pd.to_numeric(long[value_name], errors="coerce")
    return long.sort_values(["sector", "gas"]).reset_index(drop=True)


# ── Northern Ireland: emissions by sector ────────────────────────────────────


def get_emissions_by_sector(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return the full NI emissions time series by sector (Table 1c).

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame with columns ``sector``, ``year`` and
        ``emissions_ktco2e``.  Includes a ``Total`` sector row per year.

    Example:
        >>> df = get_emissions_by_sector()
        >>> bool((df['year'] >= 1990).all())
        True
    """
    sheet = _sheet("Table_1", year, force_refresh)
    # Table_1 stacks 1a, 1b and 1c; the third "Sector" header starts the
    # underlying NAEI time series.
    header_rows = _find_header_rows(sheet, "Sector")
    block = _read_block(sheet, header_rows[2])
    return _melt_years(block, ["Sector"], "emissions_ktco2e").rename(columns={"Sector": "sector"})


def get_sector_changes(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return base-year and year-on-year change by sector (Tables 1a and 1b).

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with one row per sector and columns ``sector``,
        ``base_year_mtco2e``, ``previous_year_mtco2e``, ``latest_year_mtco2e``,
        ``change_from_base_mtco2e``, ``change_from_previous_mtco2e``,
        ``pct_change_from_base`` and ``pct_change_from_previous``.

        ``pct_change_from_base`` is null for Fuel supply, whose base-year
        tonnage is zero.
    """
    sheet = _sheet("Table_1", year, force_refresh)
    header_rows = _find_header_rows(sheet, "Sector")
    absolute = _read_block(sheet, header_rows[0])
    percentage = _read_block(sheet, header_rows[1])
    return _combine_change_tables(absolute, percentage, "Sector", "sector")


def _combine_change_tables(
    absolute: pd.DataFrame, percentage: pd.DataFrame, label_column: str, output_label: str
) -> pd.DataFrame:
    """Merge the absolute-change and percentage-change halves of a sheet.

    Tables 1a/1b, 2a/2b and 7a/7b repeat the same level columns and differ only
    in their final two change columns, so the level columns are taken from the
    absolute table and only the change columns are pulled from each half.
    """
    years = _year_columns(absolute)
    if len(years) < 2:
        raise DAERAValidationError("Change table does not expose both comparison years")
    previous_year, latest_year = years[-2], years[-1]

    absolute_changes = [column for column in absolute.columns if column.startswith("Change ")]
    percentage_changes = [column for column in percentage.columns if column.lower().startswith("% change")]
    if len(absolute_changes) != 2 or len(percentage_changes) != 2:
        raise DAERAValidationError("Change table is missing its base-year and previous-year change columns")

    combined = pd.DataFrame(
        {
            output_label: absolute[label_column].astype(str).str.strip(),
            "base_year_mtco2e": absolute["BaseYear"],
            "previous_year_mtco2e": absolute[previous_year],
            "latest_year_mtco2e": absolute[latest_year],
            "change_from_base_mtco2e": absolute[absolute_changes[0]],
            "change_from_previous_mtco2e": absolute[absolute_changes[1]],
            "pct_change_from_base": percentage[percentage_changes[0]],
            "pct_change_from_previous": percentage[percentage_changes[1]],
        }
    )
    for column in combined.columns.drop(output_label):
        combined[column] = pd.to_numeric(combined[column], errors="coerce")
    combined.attrs["previous_year"] = int(previous_year)
    combined.attrs["latest_year"] = int(latest_year)
    return combined.reset_index(drop=True)


# ── Northern Ireland: emissions by gas ───────────────────────────────────────


def get_gas_changes(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return base-year and year-on-year change by gas (Tables 2a and 2b).

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with one row per gas (``CO2``, ``CH4``, ``N2O``,
        ``F-gases``, ``Total``) and the same change columns as
        :func:`get_sector_changes`, keyed by ``gas``.
    """
    sheet = _sheet("Table_2", year, force_refresh)
    header_rows = _find_header_rows(sheet, "Gas")
    absolute = _read_block(sheet, header_rows[0])
    percentage = _read_block(sheet, header_rows[1])
    combined = _combine_change_tables(absolute, percentage, "Gas", "gas")
    combined["gas"] = _normalise_gases(combined["gas"])
    return combined


def get_emissions_by_gas_and_sector(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return latest-year NI emissions split by gas within sector (Table 3).

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame with columns ``sector``, ``gas`` and
        ``emissions_mtco2e``, covering the seven reported gases.
    """
    sheet = _sheet("Table_3", year, force_refresh)
    block = _read_block(sheet, _find_header_rows(sheet, "Sector")[0])
    return _melt_gases(block, "emissions_mtco2e")


# ── Northern Ireland: revisions and Programme for Government ─────────────────


def get_inventory_revisions(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return revisions between consecutive inventory editions (Table 4).

    Each annual inventory restates prior years as methodologies improve.  This
    table quantifies that restatement for the base year and the previous year.

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``sector``, ``period``, ``previous_edition_mtco2e``,
        ``current_edition_mtco2e`` and ``revision_mtco2e``.  ``period`` is either
        ``"Base Year"`` or the calendar year that was restated.
    """
    sheet = _sheet("Table_4", year, force_refresh)
    block = _read_block(sheet, _find_header_rows(sheet, "Sector")[0])
    block = block.rename(columns={"Sector": "sector"})
    block["sector"] = block["sector"].astype(str).str.strip()

    value_columns = [column for column in block.columns if column != "sector"]
    if len(value_columns) % 3:
        raise DAERAValidationError(f"Table 4 expected groups of three revision columns, found {value_columns}")

    frames = []
    for offset in range(0, len(value_columns), 3):
        previous, current, change = value_columns[offset : offset + 3]
        frames.append(
            pd.DataFrame(
                {
                    "sector": block["sector"],
                    "period": previous.split("(")[0].strip(),
                    "previous_edition_mtco2e": pd.to_numeric(block[previous], errors="coerce"),
                    "current_edition_mtco2e": pd.to_numeric(block[current], errors="coerce"),
                    "revision_mtco2e": pd.to_numeric(block[change], errors="coerce"),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def get_pfg_progress(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return progress against the Programme for Government measure (Table 5).

    Reports the 1990 baseline, the 2019 comparison year and the two most recent
    inventory years used to track the Executive's climate commitment.

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year`` and ``emissions_mtco2e``.
    """
    sheet = _sheet("Table_5", year, force_refresh)
    block = _read_block(sheet, _find_header_rows(sheet, "Year")[0])
    value_column = block.columns[1]
    progress = pd.DataFrame(
        {
            "year": pd.to_numeric(block["Year"], errors="coerce").astype(int),
            "emissions_mtco2e": pd.to_numeric(block[value_column], errors="coerce"),
        }
    )
    return progress.sort_values("year").reset_index(drop=True)


# ── United Kingdom comparison tables ─────────────────────────────────────────


def get_uk_emissions_by_gas_and_sector(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return latest-year UK emissions split by gas within sector (Table 6).

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame with columns ``sector``, ``gas`` and
        ``emissions_ktco2e``.
    """
    sheet = _sheet("Table_6", year, force_refresh)
    block = _read_block(sheet, _find_header_rows(sheet, "Sector")[0])
    return _melt_gases(block, "emissions_ktco2e")


def get_uk_emissions_by_sector(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return the full UK emissions time series by sector (Table 7b).

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame with columns ``sector``, ``year`` and
        ``emissions_ktco2e``, directly comparable with
        :func:`get_emissions_by_sector`.
    """
    sheet = _sheet("Table_7", year, force_refresh)
    header_rows = _find_header_rows(sheet, "Sector")
    block = _read_block(sheet, header_rows[1])
    return _melt_years(block, ["Sector"], "emissions_ktco2e").rename(columns={"Sector": "sector"})


# ── Alternative sector classifications ───────────────────────────────────────


def get_national_communication_sectors(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return NI emissions under the National Communication classification (Table 8).

    This is the classification used for international reporting under the
    UNFCCC, and splits differently from the headline sector table — for example
    it separates ``Residential``, ``Public`` and ``Business`` where Table 1
    reports a single ``Buildings and product uses`` sector.

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame with columns ``sector``, ``year`` and
        ``emissions_ktco2e``.
    """
    sheet = _sheet("Table_8", year, force_refresh)
    block = _read_block(sheet, _find_header_rows(sheet, "National Communication sector")[0])
    block = block.rename(columns={"National Communication sector": "sector"})
    return _melt_years(block, ["sector"], "emissions_ktco2e")


def get_tes_categories(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return NI emissions by Territorial Emissions Statistics category (Table 9).

    The most granular breakdown available, with roughly 140 categories nested
    under subsectors and sectors.  Sector subtotals appear as rows labelled
    ``"<Sector> - Total"`` with an empty subsector and category, and the
    overall total as ``"Grand Total"``; filter these out before aggregating.

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Long-format DataFrame with columns ``sector``, ``subsector``,
        ``category``, ``year`` and ``emissions_ktco2e``.
    """
    sheet = _sheet("Table_9", year, force_refresh)
    block = _read_block(sheet, _find_header_rows(sheet, "TES Sector")[0], n_label_cols=3)
    block = block.rename(columns={"TES Sector": "sector", "TES Subsector": "subsector", "TES Category": "category"})
    long = _melt_years(block, ["sector", "subsector", "category"], "emissions_ktco2e")
    # Subtotal rows carry NaN identifiers, which str-casting turns into "nan".
    for column in ("subsector", "category"):
        long[column] = long[column].replace("nan", "")
    return long


# ── Convenience accessors ────────────────────────────────────────────────────


def get_available_years(year: int | None = None, force_refresh: bool = False) -> list[int]:
    """Return the reporting years present in the NI sector time series.

    The inventory omits 1991-1994 and 1996-1997, so this is not a contiguous
    range.

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        Sorted list of reporting years.

    Example:
        >>> years = get_available_years()
        >>> 1990 in years and 2020 in years
        True
    """
    return sorted(get_emissions_by_sector(year, force_refresh)["year"].unique().tolist())


def get_latest_year(year: int | None = None, force_refresh: bool = False) -> int:
    """Return the most recent reporting year in the NI sector time series."""
    return max(get_available_years(year, force_refresh))


def get_annual_totals(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Return NI total emissions per year, extracted from Table 1c.

    Args:
        year: Inventory edition to read; defaults to the most recent.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with columns ``year`` and ``emissions_ktco2e``.
    """
    sectors = get_emissions_by_sector(year, force_refresh)
    totals = sectors[sectors["sector"] == "Total"][["year", "emissions_ktco2e"]]
    return totals.sort_values("year").reset_index(drop=True)


# ── Validation ───────────────────────────────────────────────────────────────


def validate_data(df: pd.DataFrame, value_column: str | None = None) -> bool:
    """Check that a parsed greenhouse gas DataFrame is structurally sound.

    Negative values are accepted: LULUCF removals and some TES categories are
    legitimately negative.

    Args:
        df: DataFrame returned by any of this module's accessors.
        value_column: Emissions column to check; inferred from the frame when
            omitted.

    Returns:
        ``True`` if the frame passes all checks.

    Raises:
        DAERAValidationError: If the frame is empty, missing its emissions
            column, or has no non-null emissions values.

    Example:
        >>> validate_data(get_annual_totals())
        True
    """
    if df.empty:
        raise DAERAValidationError("DataFrame is empty")

    if value_column is None:
        candidates = [column for column in df.columns if column.startswith("emissions_")]
        if not candidates:
            raise DAERAValidationError(f"No emissions column found in {list(df.columns)}")
        value_column = candidates[0]

    if value_column not in df.columns:
        raise DAERAValidationError(f"Missing expected column {value_column!r}")

    if df[value_column].notna().sum() == 0:
        raise DAERAValidationError(f"Column {value_column!r} contains no values")

    if "year" in df.columns and not df["year"].between(1990, 2100).all():
        raise DAERAValidationError("Year column contains implausible values")

    return True
