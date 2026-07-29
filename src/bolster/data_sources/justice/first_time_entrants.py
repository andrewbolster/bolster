"""First Time Entrants to the Criminal Justice System in Northern Ireland.

How many of the people dealt with by the NI criminal justice system in a given
year were there for the first time. The Department of Justice publishes this
annually as a set of percentages: of everyone convicted at court or given a
formal diversionary disposal, what share had no previous conviction or diversion
on record.

Four measures are published side by side, and the distinction matters:

- ``all`` - first offences as a percentage of all convictions **and** diversions.
  This is the headline measure.
- ``convictions`` - first *convictions* as a percentage of all convictions.
  Someone previously cautioned but never convicted counts as a first conviction.
- ``court`` - first *offences* as a percentage of all convictions. Stricter than
  ``convictions``: a prior diversion disqualifies you.
- ``diversions`` - first offences as a percentage of all diversions.

Each measure is broken down by age band, gender, offence classification and
disposal category, with the prior financial year alongside for comparison. A
separate ten-year series tracks the headline percentage over time.

Data Source:
    The Department of Justice publishes through GOV.UK, but the statistical
    tables themselves live on ``justice-ni.gov.uk`` as a single multi-sheet ODS
    workbook. Publication URLs are discovered at runtime through the GOV.UK
    Search and Content APIs, so new annual releases are picked up without a code
    change.

Update Frequency: Annual, typically each June
Geographic Coverage: Northern Ireland
Reference Period: 2015-16 - present (headline series); latest two years (breakdowns)

Note:
    The published workbook suppresses small counts with markers such as
    ``[low]``, ``[c]`` and ``[d]``. These become ``NaN`` rather than zero, so a
    suppressed cell is never mistaken for an absence of offending.

Example:
    >>> from bolster.data_sources.justice import first_time_entrants
    >>> df = first_time_entrants.get_annual_series()
    >>> {"financial_year", "first_time_offender_pct"}.issubset(df.columns)
    True
"""

import logging
import re

import pandas as pd

from bolster.utils.cache import CachedDownloader
from bolster.utils.web import session

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://www.gov.uk/api/search.json"
CONTENT_API_URL = "https://www.gov.uk/api/content"
LINK_PREFIX = "/government/statistics/first-time-entrants-to-the-criminal-justice-system-in-northern-ireland"
JUSTICE_HOST = "justice-ni.gov.uk"

#: Measure key -> (table letter within each worksheet, published description).
MEASURES: dict[str, tuple[str, str]] = {
    "all": ("a", "First offences as a percentage of all convictions and diversions"),
    "convictions": ("b", "First convictions as a percentage of all convictions"),
    "court": ("c", "First offences as a percentage of all convictions"),
    "diversions": ("d", "First offences as a percentage of all diversions"),
}

#: Breakdown key -> (worksheet name, table number used within that worksheet).
#: The worksheet names and the table numbers printed on them do not line up:
#: disposal breakdowns live on sheet "5" but are labelled "Table 4a" onwards.
DIMENSIONS: dict[str, tuple[str, int]] = {
    "age": ("1", 1),
    "gender": ("2", 2),
    "offence": ("3", 3),
    "disposal": ("5", 4),
}

_SHEET_OFFENCE_DISPOSAL = "4"
_SHEET_ANNUAL = "6"

_TABLE_RE = re.compile(r"^Table\s+(\d+)([a-e])\s*:", re.IGNORECASE)
_YEAR_RE = re.compile(r"(\d{4})-(\d{2})")
_NOTE_RE = re.compile(r"\s*\[note\s*\d+\]", re.IGNORECASE)

_downloader = CachedDownloader("justice_fte", timeout=120)


class FirstTimeEntrantsError(Exception):
    """Base exception for first time entrants data errors."""


class FirstTimeEntrantsDataNotFoundError(FirstTimeEntrantsError):
    """Raised when a publication, worksheet or table cannot be located."""


def find_latest_publication() -> str:
    """Find the ``justice-ni.gov.uk`` page for the most recent annual bulletin.

    Returns:
        Absolute URL of the Department of Justice publication page.

    Raises:
        FirstTimeEntrantsDataNotFoundError: If no matching publication is found.

    Example:
        >>> find_latest_publication().startswith("https://www.justice-ni.gov.uk/")
        True
    """
    response = session.get(
        SEARCH_API_URL,
        params={
            "q": "first time entrants criminal justice northern ireland",
            "count": 50,
            "fields": "title,link,public_timestamp",
        },
        timeout=30,
    )
    response.raise_for_status()

    matches = [r for r in response.json().get("results", []) if r.get("link", "").startswith(LINK_PREFIX)]
    if not matches:
        raise FirstTimeEntrantsDataNotFoundError("No first time entrants publications found on GOV.UK")
    matches.sort(key=lambda r: r.get("public_timestamp", ""), reverse=True)

    for match in matches:
        content = session.get(f"{CONTENT_API_URL}{match['link']}", timeout=30)
        content.raise_for_status()
        for attachment in content.json().get("details", {}).get("attachments", []):
            url = attachment.get("url", "")
            if JUSTICE_HOST in url:
                logger.info("Resolved first time entrants bulletin to %s", url)
                return url

    raise FirstTimeEntrantsDataNotFoundError(f"No first time entrants publication links to {JUSTICE_HOST}")


def find_data_url(publication_url: str | None = None) -> str:
    """Find the ODS workbook linked from a publication page.

    Args:
        publication_url: Publication page to scrape. Defaults to the latest.

    Returns:
        Absolute URL of the ``.ods`` statistical tables.

    Raises:
        FirstTimeEntrantsDataNotFoundError: If the page links to no ODS file.

    Example:
        >>> find_data_url().endswith(".ods")
        True
    """
    publication_url = publication_url or find_latest_publication()
    response = session.get(publication_url, timeout=60)
    response.raise_for_status()

    links = re.findall(r'href="([^"]+\.ods)"', response.text)
    if not links:
        raise FirstTimeEntrantsDataNotFoundError(f"No ODS workbook linked from {publication_url}")
    return links[0]


def _load_workbook(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Download and parse every worksheet of the statistical tables workbook."""
    path = _downloader.download(find_data_url(), cache_ttl_hours=24 * 7, force_refresh=force_refresh)
    return pd.read_excel(path, sheet_name=None, engine="odf", header=None)


def _sheet(workbook: dict[str, pd.DataFrame], name: str) -> pd.DataFrame:
    if name not in workbook:
        raise FirstTimeEntrantsDataNotFoundError(f"Worksheet {name!r} not found in workbook")
    return workbook[name]


def _clean_label(value: object) -> str:
    """Strip note markers and repair a published typo in the age bands."""
    label = _NOTE_RE.sub("", str(value)).strip()
    # The published workbook renders the 40-49 band as "40 t0 49" (zero for "o").
    return "40 to 49" if label == "40 t0 49" else label


def _to_number(value: object) -> float:
    """Coerce a published cell to a number, mapping suppression markers to NaN.

    Small counts are withheld as ``[low]``, ``[c]``, ``[d]`` or ``n.a.``, and at
    least one cell carries a typo (``[d}``), so anything non-numeric is treated
    as missing rather than matched against a fixed list of markers.
    """
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def _find_table(sheet: pd.DataFrame, number: int, letter: str) -> int:
    """Return the row index of the header for ``Table <number><letter>``."""
    for position, value in enumerate(sheet[0]):
        match = _TABLE_RE.match(str(value))
        if match and int(match.group(1)) == number and match.group(2).lower() == letter:
            return position + 1
    raise FirstTimeEntrantsDataNotFoundError(f"Table {number}{letter} not found in worksheet")


def _parse_table(sheet: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Parse one sub-table into tidy long form, one row per category and year.

    Each published sub-table carries the prior year as a lone percentage and the
    current year as a count, a denominator and a percentage. Both are emitted as
    rows so that a caller can filter on ``financial_year`` rather than having to
    know which columns belong to which year.
    """
    header = [str(v) for v in sheet.iloc[header_row]]
    years = [_YEAR_RE.search(h) for h in header]
    if not years[1] or not years[2]:
        raise FirstTimeEntrantsDataNotFoundError(f"Could not read financial years from header: {header}")
    prior_year, current_year = years[1].group(0), years[2].group(0)

    records = []
    for _, row in sheet.iloc[header_row + 1 :].iterrows():
        if pd.isna(row[0]):
            break
        category = _clean_label(row[0])
        records.append(
            {
                "category": category,
                "financial_year": prior_year,
                "count": float("nan"),
                "denominator": float("nan"),
                "percentage": _to_number(row[1]),
            }
        )
        records.append(
            {
                "category": category,
                "financial_year": current_year,
                "count": _to_number(row[2]),
                "denominator": _to_number(row[3]),
                "percentage": _to_number(row[4]),
            }
        )

    if not records:
        raise FirstTimeEntrantsDataNotFoundError(f"No data rows below header at row {header_row}")
    return pd.DataFrame(records)


def get_breakdown(
    dimension: str,
    measure: str | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get first time entrant rates broken down by a published dimension.

    Args:
        dimension: One of ``"age"``, ``"gender"``, ``"offence"`` or ``"disposal"``.
        measure: Restrict to a single measure from :data:`MEASURES`. All four are
            returned when omitted.
        force_refresh: Bypass the cached workbook and re-download.

    Returns:
        DataFrame with columns ``measure``, ``category``, ``financial_year``,
        ``count``, ``denominator`` and ``percentage``. Counts and denominators
        are only published for the most recent year.

    Raises:
        ValueError: If ``dimension`` or ``measure`` is not recognised.

    Example:
        >>> df = get_breakdown("gender", measure="all")
        >>> sorted(df["category"].unique())
        ['Female', 'Male', 'Total']
    """
    if dimension not in DIMENSIONS:
        raise ValueError(f"dimension must be one of {sorted(DIMENSIONS)}, got {dimension!r}")
    if measure is not None and measure not in MEASURES:
        raise ValueError(f"measure must be one of {sorted(MEASURES)}, got {measure!r}")

    sheet_name, table_number = DIMENSIONS[dimension]
    sheet = _sheet(_load_workbook(force_refresh), sheet_name)
    wanted = [measure] if measure else list(MEASURES)

    frames = []
    for key in wanted:
        letter, _ = MEASURES[key]
        frame = _parse_table(sheet, _find_table(sheet, table_number, letter))
        frame.insert(0, "measure", key)
        frames.append(frame)

    return pd.concat(frames, ignore_index=True)


def get_offence_disposal_split(force_refresh: bool = False) -> pd.DataFrame:
    """Get first offences split between court convictions and diversions, by offence.

    Where :func:`get_breakdown` reports each route as a share of its own
    denominator, this table puts both routes over the same denominator - every
    conviction and diversion for that offence - so the two percentages sum to the
    offence's overall first offence rate.

    Args:
        force_refresh: Bypass the cached workbook and re-download.

    Returns:
        DataFrame with columns ``offence``, ``first_offence_convictions``,
        ``first_offence_diversions``, ``all_convictions_and_diversions``,
        ``convictions_pct`` and ``diversions_pct``.

    Example:
        >>> df = get_offence_disposal_split()
        >>> "Motoring" in set(df["offence"])
        True
    """
    sheet = _sheet(_load_workbook(force_refresh), _SHEET_OFFENCE_DISPOSAL)

    header_row = next(
        (position for position, value in enumerate(sheet[0]) if str(value).startswith("Offence Classification")),
        None,
    )
    if header_row is None:
        raise FirstTimeEntrantsDataNotFoundError("Offence classification header not found on worksheet 4")

    records = []
    for _, row in sheet.iloc[header_row + 1 :].iterrows():
        if pd.isna(row[0]):
            break
        records.append(
            {
                "offence": _clean_label(row[0]),
                "first_offence_convictions": _to_number(row[1]),
                "first_offence_diversions": _to_number(row[2]),
                "all_convictions_and_diversions": _to_number(row[3]),
                "convictions_pct": _to_number(row[4]),
                "diversions_pct": _to_number(row[5]),
            }
        )

    return pd.DataFrame(records)


def get_annual_series(force_refresh: bool = False) -> pd.DataFrame:
    """Get the ten-year series of headline first time offender percentages.

    Args:
        force_refresh: Bypass the cached workbook and re-download.

    Returns:
        DataFrame with columns ``financial_year``, ``year`` (the starting
        calendar year) and ``first_time_offender_pct``, ordered oldest first.

    Example:
        >>> df = get_annual_series()
        >>> df["year"].is_monotonic_increasing
        True
    """
    sheet = _sheet(_load_workbook(force_refresh), _SHEET_ANNUAL)

    header_row = next((position for position, value in enumerate(sheet[0]) if str(value).strip() == "Year"), None)
    if header_row is None:
        raise FirstTimeEntrantsDataNotFoundError("Year header not found on worksheet 6")

    records = []
    for _, row in sheet.iloc[header_row + 1 :].iterrows():
        match = _YEAR_RE.match(str(row[0]).strip())
        if not match:
            break
        records.append(
            {
                "financial_year": match.group(0),
                "year": int(match.group(1)),
                "first_time_offender_pct": _to_number(row[1]),
            }
        )

    if not records:
        raise FirstTimeEntrantsDataNotFoundError("No annual series rows found on worksheet 6")
    return pd.DataFrame(records).sort_values("year", ignore_index=True)
