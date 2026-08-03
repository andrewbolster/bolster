"""PSNI Motoring Offences Statistics.

Enforcement outcomes for motoring offences in Northern Ireland: fixed penalty
notices, discretionary disposals, awareness/driver courses and referrals for
prosecution.

This complements :mod:`bolster.data_sources.psni.road_traffic_collisions`.
Collisions data covers injury *events*; this module covers enforcement
*actions*, whether or not a collision occurred.

Data available:
    - Annual totals by disposal type, 1998 to present
    - Offence group breakdowns by month, age, gender and disposal type
    - Policing district breakdowns with population-adjusted rates
    - Dedicated series for speeding, mobile phone, careless driving and
      drink/drug driving offences, each back to 2011
    - Top speeds detected by PSNI within each speed limit

Data Source:
    **Primary Source**: PSNI Motoring Offences Statistics annual publication

    https://www.psni.police.uk/about-us/our-publications-and-reports/official-statistics/motoring-offence-statistics

    Published under the Open Government Licence v3.0.

Update Frequency: Annual (March), with rolling 12-month tables published monthly.
    Only the annual workbook is wired up here — the rolling file's URL embeds the
    month it covers, so it would break the module every four weeks.

Note:
    The PSNI website returns HTTP 403 to automated requests for HTML pages, so
    the workbook URL cannot be discovered by scraping. Known URLs are pinned in
    :data:`ANNUAL_URLS`; add a new entry each March.

Example:
    >>> from bolster.data_sources.psni import motoring_offences
    >>> trends = motoring_offences.get_annual_trends()
    >>> int(trends['year'].min())
    1998
    >>> motoring_offences.validate_data(trends)
    True
"""

import logging
import re
from pathlib import Path

import pandas as pd

from ._base import (
    PSNIDataNotFoundError,
    PSNIValidationError,
    download_file,
    get_lgd_code,
)

logger = logging.getLogger(__name__)

# Known annual workbook URLs, keyed by the calendar year the edition covers.
#
# IMPORTANT: add a new entry each March when PSNI publishes the next edition.
# The URLs are not predictable (the ``sites/default/files/YYYY-MM/`` prefix
# tracks the publication month, not the reference year).
ANNUAL_URLS: dict[int, str] = {
    2025: ("https://www.psni.police.uk/sites/default/files/2026-03/Accompanying%20spreadsheet_2025.xlsx"),
}

# Cache TTL: annual publication, so refresh roughly annually
CACHE_TTL_HOURS = 24 * 365

# Sheet names in the annual workbook
_SHEET_TRENDS = "Trends"
_SHEET_DISPOSAL = "Disposal Type"
_SHEET_MONTH = "Offence by month"
_SHEET_AGE_GENDER = "Age & Gender"
_SHEET_DISTRICT = "District number and rates"
_SHEET_OFFENCE_DISPOSAL = "Offence by disposal"

# Offence-specific sheets that carry their own annual series back to 2011
_OFFENCE_SHEETS = {
    "speeding": "Speeding",
    "mobile-phone": "Mobile Phone",
    "careless-driving": "Careless Driving",
    "drink-drug-driving": "Drink drug driving",
}

# Gender and age column labels in the Age & Gender sheet, by position.
# Both breakdowns contain an "Unknown" column, so positional lookup avoids
# the ambiguity of matching on header text alone.
_GENDER_COLUMNS = ["Male", "Female", "Unknown"]
_AGE_COLUMNS = ["Under 18", "18 - 29", "30 - 49", "50 - 69", "70+", "Unknown"]

# Column names for the district breakdown, in sheet order
_DISTRICT_COLUMNS = [
    "district",
    "endorsable_fpn",
    "non_endorsable_fpn",
    "referred_for_prosecution",
    "speed_awareness_course",
    "safer_driver_course",
    "total",
    "population_16_plus",
    "rate_per_10000",
]

# PSNI writes some district names with commas that the shared LGD_CODES
# mapping omits, e.g. "Newry, Mourne & Down".
_DISTRICT_ALIASES = {
    "Newry, Mourne & Down": "Newry Mourne & Down",
    "Armagh City, Banbridge & Craigavon": "Armagh City Banbridge & Craigavon",
}

# The workbook abbreviates September as "Sept", which ``%b`` does not accept.
_MONTH_FIXES = {"Sept": "Sep"}


def get_latest_publication_url() -> str:
    """Return the download URL for the most recent known annual workbook.

    Returns:
        Direct download URL for the latest PSNI motoring offences workbook.

    Example:
        >>> get_latest_publication_url().endswith('.xlsx')
        True
    """
    return ANNUAL_URLS[max(ANNUAL_URLS)]


def _download(force_refresh: bool = False) -> Path:
    """Download (or reuse a cached copy of) the latest annual workbook."""
    return download_file(
        get_latest_publication_url(),
        cache_ttl_hours=CACHE_TTL_HOURS,
        force_refresh=force_refresh,
    )


def _split_blocks(sheet: pd.DataFrame) -> list[pd.DataFrame]:
    """Split a sheet into contiguous non-blank row blocks.

    Every sheet in the workbook stacks several sub-tables separated by blank
    rows, each preceded by a one-row title. Splitting on blank rows yields
    single-row title blocks and multi-row table blocks.

    Args:
        sheet: Raw sheet read with ``header=None``.

    Returns:
        Blocks of consecutive non-blank rows, with all-empty columns dropped.
    """
    blocks: list[pd.DataFrame] = []
    current: list[int] = []

    for index, row in sheet.iterrows():
        if row.isna().all():
            if current:
                blocks.append(sheet.loc[current])
                current = []
        else:
            current.append(index)

    if current:
        blocks.append(sheet.loc[current])

    return [block.dropna(axis=1, how="all").reset_index(drop=True) for block in blocks]


def _find_block(blocks: list[pd.DataFrame], first_header: str) -> pd.DataFrame:
    """Return the first table block whose top-left header cell matches.

    Args:
        blocks: Blocks from :func:`_split_blocks`.
        first_header: Expected value of the block's first header cell.

    Returns:
        The matching block, header row included.

    Raises:
        PSNIDataNotFoundError: If no block has that header.
    """
    for block in blocks:
        if len(block) > 1 and str(block.iloc[0, 0]).strip() == first_header:
            return block

    raise PSNIDataNotFoundError(f"No table block with header {first_header!r} in sheet")


def _to_count(values: pd.Series) -> pd.Series:
    """Coerce a column of offence counts to numbers.

    PSNI writes ``-`` where a disposal type did not exist or recorded nothing;
    the published totals treat those as zero, so this does too.
    """
    return pd.to_numeric(values.replace("-", 0), errors="coerce")


def _year_rows(block: pd.DataFrame) -> pd.DataFrame:
    """Drop footnote and total rows, keeping only four-digit year rows."""
    body = block.iloc[1:].copy()
    is_year = body.iloc[:, 0].astype(str).str.fullmatch(r"(?:19|20)\d{2}(?:\.0)?")
    return body[is_year.fillna(False)]


def _melt_counts(
    body: pd.DataFrame,
    id_column: str,
    labels: list[str],
    value_name: str,
    variable_name: str,
) -> pd.DataFrame:
    """Reshape a wide count table into long form.

    Args:
        body: Data rows (no header), first column holding the identifier.
        id_column: Name for the first column in the output.
        labels: Column labels for positions 1..len(labels).
        value_name: Name for the count column.
        variable_name: Name for the label column.

    Returns:
        Long-format frame with three columns.
    """
    records = []
    for _, row in body.iterrows():
        identifier = str(row.iloc[0]).strip()
        for offset, label in enumerate(labels, start=1):
            records.append(
                {
                    id_column: identifier,
                    variable_name: label,
                    value_name: _to_count(pd.Series([row.iloc[offset]])).iloc[0],
                }
            )

    return pd.DataFrame(records)


def _normalise_district(name: str) -> str:
    """Map a PSNI district label onto the shared ``LGD_CODES`` spelling."""
    cleaned = re.sub(r"\s+", " ", str(name)).strip()
    return _DISTRICT_ALIASES.get(cleaned, cleaned)


def _parse_month(label: str) -> pd.Timestamp | None:
    """Parse a ``"Jan 2025"``-style column header into a Timestamp."""
    text = re.sub(r"\s+", " ", str(label)).strip()
    match = re.fullmatch(r"([A-Za-z]+) ((?:19|20)\d{2})", text)
    if match is None:
        return None

    month = _MONTH_FIXES.get(match.group(1), match.group(1))
    try:
        return pd.Timestamp(f"{month} {match.group(2)}")
    except ValueError:
        return None


def get_annual_trends(force_refresh: bool = False) -> pd.DataFrame:
    """Return motoring offences by year and disposal type since 1998.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Long-format frame with ``year``, ``disposal_type`` and ``offences``.

    Example:
        >>> df = get_annual_trends()
        >>> sorted(df.columns.tolist())
        ['disposal_type', 'offences', 'year']
        >>> int(df['year'].min())
        1998
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_SHEET_TRENDS, header=None)
    block = _find_block(_split_blocks(sheet), "Year")
    labels = [str(x).strip() for x in block.iloc[0, 1:].tolist()]

    frame = _melt_counts(
        _year_rows(block),
        id_column="year",
        labels=labels,
        value_name="offences",
        variable_name="disposal_type",
    )
    frame["year"] = frame["year"].astype(float).astype(int)

    # "Total" is a derived column, not a disposal type.
    return frame[frame["disposal_type"] != "Total"].reset_index(drop=True)


def get_offences_by_disposal_type(force_refresh: bool = False) -> pd.DataFrame:
    """Return the latest two years of offences by disposal type.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with ``disposal_type``, ``year`` and ``offences``.

    Example:
        >>> df = get_offences_by_disposal_type()
        >>> 'disposal_type' in df.columns
        True
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_SHEET_DISPOSAL, header=None)
    block = _find_block(_split_blocks(sheet), "Disposal Type")

    years = [
        int(float(value))
        for value in block.iloc[0, 1:].tolist()
        if re.fullmatch(r"(?:19|20)\d{2}(?:\.0)?", str(value).strip())
    ]
    body = block.iloc[1:]
    body = body[body.iloc[:, 0].astype(str).str.strip() != "Total"]

    return _melt_counts(
        body,
        id_column="disposal_type",
        labels=[str(year) for year in years],
        value_name="offences",
        variable_name="year",
    ).astype({"year": int})


def get_offences_by_month(force_refresh: bool = False) -> pd.DataFrame:
    """Return offence group counts for each month of the latest year.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with ``offence_group``, ``month`` (Timestamp) and ``offences``.

    Example:
        >>> df = get_offences_by_month()
        >>> len(df['month'].unique())
        12
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_SHEET_MONTH, header=None)
    block = _find_block(_split_blocks(sheet), "Offence group")

    months = {
        position: parsed
        for position, label in enumerate(block.iloc[0].tolist())
        if position > 0 and (parsed := _parse_month(label)) is not None
    }

    body = block.iloc[1:]
    body = body[body.iloc[:, 0].astype(str).str.strip() != "Total"]

    records = []
    for _, row in body.iterrows():
        for position, month in months.items():
            records.append(
                {
                    "offence_group": str(row.iloc[0]).strip(),
                    "month": month,
                    "offences": _to_count(pd.Series([row.iloc[position]])).iloc[0],
                }
            )

    return pd.DataFrame(records)


def get_offences_by_age_gender(force_refresh: bool = False) -> pd.DataFrame:
    """Return offence group counts broken down by gender and by age band.

    The workbook publishes both breakdowns side by side, each summing to the
    same total. They are stacked here with a ``breakdown`` column so the two
    can be filtered apart.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with ``offence_group``, ``breakdown``, ``category`` and ``offences``.

    Example:
        >>> df = get_offences_by_age_gender()
        >>> sorted(df['breakdown'].unique().tolist())
        ['age', 'gender']
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_SHEET_AGE_GENDER, header=None)
    block = _find_block(_split_blocks(sheet), "Offence group")

    body = block.iloc[1:]
    body = body[body.iloc[:, 0].astype(str).str.strip() != "Total"]

    frames = []
    for breakdown, labels, start in (
        ("gender", _GENDER_COLUMNS, 1),
        ("age", _AGE_COLUMNS, 1 + len(_GENDER_COLUMNS)),
    ):
        slice_ = pd.concat([body.iloc[:, [0]], body.iloc[:, start : start + len(labels)]], axis=1)
        melted = _melt_counts(
            slice_,
            id_column="offence_group",
            labels=labels,
            value_name="offences",
            variable_name="category",
        )
        melted.insert(1, "breakdown", breakdown)
        frames.append(melted)

    return pd.concat(frames, ignore_index=True)


def get_offences_by_district(force_refresh: bool = False) -> pd.DataFrame:
    """Return offences by policing district with population-adjusted rates.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with a row per district, disposal-type columns, ``lgd_code``,
        ``population_16_plus`` and ``rate_per_10000``.

    Example:
        >>> df = get_offences_by_district()
        >>> len(df)
        11
        >>> df.loc[df['district'] == 'Belfast City', 'lgd_code'].iloc[0]
        'N09000003'
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_SHEET_DISTRICT, header=None)
    block = _find_block(_split_blocks(sheet), "District")

    body = block.iloc[1:].copy()
    body.columns = _DISTRICT_COLUMNS
    body["district"] = body["district"].map(_normalise_district)
    # "Total" and "Unknown" are aggregates, not districts.
    body = body[~body["district"].isin(("Total", "Unknown"))]

    for column in _DISTRICT_COLUMNS[1:7]:
        body[column] = _to_count(body[column])
    for column in ("population_16_plus", "rate_per_10000"):
        body[column] = pd.to_numeric(body[column], errors="coerce")

    body.insert(1, "lgd_code", body["district"].map(get_lgd_code))
    return body.reset_index(drop=True)


def get_offences_by_offence_and_disposal(force_refresh: bool = False) -> pd.DataFrame:
    """Return offence group counts split by disposal type.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with ``offence_group``, ``disposal_type`` and ``offences``.

    Example:
        >>> df = get_offences_by_offence_and_disposal()
        >>> 'Speeding' in df['offence_group'].unique()
        True
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_SHEET_OFFENCE_DISPOSAL, header=None)
    block = _find_block(_split_blocks(sheet), "Offence group")
    labels = [str(x).strip() for x in block.iloc[0, 1:].tolist()]

    body = block.iloc[1:]
    body = body[body.iloc[:, 0].astype(str).str.strip() != "Total"]

    frame = _melt_counts(
        body,
        id_column="offence_group",
        labels=labels,
        value_name="offences",
        variable_name="disposal_type",
    )
    return frame[frame["disposal_type"] != "Total"].reset_index(drop=True)


def get_offence_trends(offence: str, force_refresh: bool = False) -> pd.DataFrame:
    """Return the annual series for a single offence type since 2011.

    Args:
        offence: One of the keys from :func:`list_offence_series`.
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with ``year``, ``disposal_type`` and ``offences``.

    Raises:
        PSNIDataNotFoundError: If the offence type has no dedicated sheet.

    Example:
        >>> df = get_offence_trends('speeding')
        >>> int(df['year'].min())
        2011
    """
    sheet_name = _OFFENCE_SHEETS.get(offence)
    if sheet_name is None:
        raise PSNIDataNotFoundError(f"Unknown offence series {offence!r}. Available: {list_offence_series()}")

    sheet = pd.read_excel(_download(force_refresh), sheet_name=sheet_name, header=None)
    block = _find_block(_split_blocks(sheet), "Year")
    labels = [str(x).strip() for x in block.iloc[0, 1:].tolist()]

    frame = _melt_counts(
        _year_rows(block),
        id_column="year",
        labels=labels,
        value_name="offences",
        variable_name="disposal_type",
    )
    frame["year"] = frame["year"].astype(float).astype(int)

    return frame[frame["disposal_type"] != "Total"].reset_index(drop=True)


def get_top_speeds(force_refresh: bool = False) -> pd.DataFrame:
    """Return the highest speed PSNI detected within each speed limit.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with ``speed_limit_mph``, ``highest_speed_mph`` and ``location``.

    Example:
        >>> df = get_top_speeds()
        >>> bool((df['highest_speed_mph'] > df['speed_limit_mph']).all())
        True
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_OFFENCE_SHEETS["speeding"], header=None)
    block = _find_block(_split_blocks(sheet), "Speed limit")

    body = block.iloc[1:].copy()
    body.columns = ["speed_limit_mph", "highest_speed_mph", "location"]
    body["speed_limit_mph"] = pd.to_numeric(
        body["speed_limit_mph"].astype(str).str.replace("mph", "", regex=False),
        errors="coerce",
    )
    body["highest_speed_mph"] = pd.to_numeric(body["highest_speed_mph"], errors="coerce")
    body["location"] = body["location"].astype(str).str.strip()

    return body.dropna(subset=["speed_limit_mph"]).reset_index(drop=True)


def get_speeding_by_district(force_refresh: bool = False) -> pd.DataFrame:
    """Return speeding offences by policing district with rates.

    Args:
        force_refresh: If True, bypass the download cache.

    Returns:
        Frame with ``district``, ``lgd_code``, ``offences``,
        ``population_16_plus`` and ``rate_per_10000``.

    Example:
        >>> df = get_speeding_by_district()
        >>> len(df)
        11
    """
    sheet = pd.read_excel(_download(force_refresh), sheet_name=_OFFENCE_SHEETS["speeding"], header=None)
    block = _find_block(_split_blocks(sheet), "District")

    body = block.iloc[1:].copy()
    body.columns = ["district", "offences", "population_16_plus", "rate_per_10000"]
    body["district"] = body["district"].map(_normalise_district)
    body = body[~body["district"].isin(("Total", "Unknown"))]

    body["offences"] = _to_count(body["offences"])
    for column in ("population_16_plus", "rate_per_10000"):
        body[column] = pd.to_numeric(body[column], errors="coerce")

    body.insert(1, "lgd_code", body["district"].map(get_lgd_code))
    return body.reset_index(drop=True)


def list_offence_series() -> list[str]:
    """Return the offence types that have a dedicated annual series.

    Example:
        >>> list_offence_series()
        ['careless-driving', 'drink-drug-driving', 'mobile-phone', 'speeding']
    """
    return sorted(_OFFENCE_SHEETS)


# Table dispatcher: maps a CLI-friendly name onto its accessor
_TABLES = {
    "trends": get_annual_trends,
    "disposal-type": get_offences_by_disposal_type,
    "by-month": get_offences_by_month,
    "age-gender": get_offences_by_age_gender,
    "district": get_offences_by_district,
    "offence-by-disposal": get_offences_by_offence_and_disposal,
    "speeding": lambda force_refresh=False: get_offence_trends("speeding", force_refresh),
    "mobile-phone": lambda force_refresh=False: get_offence_trends("mobile-phone", force_refresh),
    "careless-driving": lambda force_refresh=False: get_offence_trends("careless-driving", force_refresh),
    "drink-drug-driving": lambda force_refresh=False: get_offence_trends("drink-drug-driving", force_refresh),
    "top-speeds": get_top_speeds,
    "speeding-district": get_speeding_by_district,
}


def list_tables() -> list[str]:
    """Return the table names accepted by :func:`get_latest_data`.

    Example:
        >>> 'trends' in list_tables()
        True
    """
    return sorted(_TABLES)


def get_latest_data(table: str = "trends", force_refresh: bool = False) -> pd.DataFrame:
    """Return one of the published tables.

    Args:
        table: Table name — see :func:`list_tables`.
        force_refresh: If True, bypass the download cache.

    Returns:
        The requested table.

    Raises:
        PSNIDataNotFoundError: If ``table`` is not a known table name.

    Example:
        >>> df = get_latest_data('district')
        >>> len(df)
        11
    """
    accessor = _TABLES.get(table)
    if accessor is None:
        raise PSNIDataNotFoundError(f"Unknown table {table!r}. Available: {list_tables()}")

    return accessor(force_refresh=force_refresh)


def validate_data(df: pd.DataFrame, required_columns: list[str] | None = None) -> bool:
    """Validate a motoring offences frame.

    Args:
        df: Frame to check.
        required_columns: Columns that must be present. Defaults to no
            column requirement beyond the frame being non-empty.

    Returns:
        True if the frame passes all checks.

    Raises:
        PSNIValidationError: If the frame is empty, is missing a required
            column, or contains negative offence counts.

    Example:
        >>> import pandas as pd
        >>> validate_data(pd.DataFrame({'offences': [1, 2]}))
        True
    """
    if df.empty:
        raise PSNIValidationError("DataFrame is empty")

    missing = set(required_columns or []) - set(df.columns)
    if missing:
        raise PSNIValidationError(f"Missing required columns: {sorted(missing)}")

    if "offences" in df.columns and (df["offences"].dropna() < 0).any():
        raise PSNIValidationError("Offence counts cannot be negative")

    return True
