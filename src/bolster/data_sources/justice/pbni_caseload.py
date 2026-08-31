r"""Probation Board for Northern Ireland (PBNI) Caseload Statistics.

Provides access to PBNI's annual and quarterly caseload bulletins, covering the
people under probation supervision in Northern Ireland: how many there are, what
orders they are serving, their demographics, risk assessments, and the victims
registered with the Victim Information Scheme.

Two cadences are published:

- **Annual** - a financial-year snapshot at 31 March, with five years of history
  and the widest breakdowns (offence classification, gender, directorate).
- **Quarterly** - a snapshot at each quarter end, with roughly nine quarters of
  history and some extra flow measures (new caseload, reports completed).

Data Source:
    PBNI publishes through GOV.UK, but the statistics themselves live in NISRA
    interactive data-visualisation pages at ``datavis.nisra.gov.uk/pbni/``. Each
    figure on those pages embeds its underlying CSV as a base64 data URI, so the
    published numbers are recovered exactly rather than scraped from charts.

    Publication URLs are discovered at runtime through the GOV.UK Search and
    Content APIs, so new releases are picked up without a code change.

Update Frequency: Quarterly, with an additional annual bulletin each spring
Geographic Coverage: Northern Ireland
Reference Period: Annual 2022 - present; quarterly 2024 - present

Note:
    The published CSVs are UTF-16LE encoded but use bare single-byte ``\r\n``
    line terminators, which desynchronises any standard UTF-16 decoder after the
    first row. :func:`_decode_csv` works around this by stripping null bytes.

Example:
    >>> from bolster.data_sources.justice import pbni_caseload
    >>> df = pbni_caseload.get_annual_caseload()
    >>> {"date", "caseload", "service_users"}.issubset(df.columns)
    True
"""

import base64
import io
import logging
import re

import pandas as pd

from bolster.utils.cache import CachedDownloader
from bolster.utils.web import session

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://www.gov.uk/api/search.json"
CONTENT_API_URL = "https://www.gov.uk/api/content"
DATAVIS_HOST = "datavis.nisra.gov.uk"

FREQUENCIES = ("annual", "quarterly")

# Figure number -> (dimension name, column renames) for each publication cadence.
# The datavis pages number their figures, and the numbering differs between the
# annual and quarterly bulletins even where the underlying measure is the same.
_ANNUAL_FIGURES: dict[int, tuple[str, dict[str, str]]] = {
    1: ("caseload", {"Caseload": "caseload", "Service users": "service_users"}),
    2: ("order_type", {"Order/Licence type": "order_type", "% of caseload": "percentage"}),
    3: ("offence", {"Offence Classification": "offence", "Caseload": "caseload", "% of caseload": "percentage"}),
    4: ("gender", {}),
    5: ("age", {"Age band": "age_band", "% of service users": "percentage"}),
    6: ("directorate", {}),
    7: ("ace", {}),
    8: ("ppani", {}),
    9: ("srosh", {}),
    10: ("new_victims", {"Financial year": "financial_year", "New victims": "new_victims"}),
    11: ("victims_gender", {"Male victims": "male_victims", "Female victims": "female_victims"}),
}

_QUARTERLY_FIGURES: dict[int, tuple[str, dict[str, str]]] = {
    1: ("caseload", {"Caseload": "caseload", "Service users": "service_users"}),
    2: (
        "supervision",
        {"Community supervision": "community_supervision", "Custody supervision": "custody_supervision"},
    ),
    3: ("order_type", {"Type of Order/Licence": "order_type", "% of caseload": "percentage"}),
    4: ("age", {"Age group": "age_band", "% of service users": "percentage"}),
    5: ("ace", {}),
    6: (
        "ppani",
        {"Service users categorised under PPANI": "ppani_service_users", "% of total service users": "percentage"},
    ),
    7: ("ppani_category", {}),
    8: ("srosh", {"Service users assessed as SROSH": "srosh_service_users", "% of total service users": "percentage"}),
    9: ("new_caseload", {"New caseload": "new_caseload", "New service users": "new_service_users"}),
    10: ("reports", {"Reports (excluding letters)": "reports"}),
    11: ("victims", {"Total victims": "total_victims", "New victims": "new_victims"}),
}

_FIGURES = {"annual": _ANNUAL_FIGURES, "quarterly": _QUARTERLY_FIGURES}

# Matches the per-figure download links, whose base64 payloads are line-wrapped.
_DATA_URI_RE = re.compile(r'href="data:[^,]*base64,([A-Za-z0-9+/=\s]+?)"\s*download="([^"]+?figure-(\d+)[^"]*\.csv)"')

_downloader = CachedDownloader("pbni", timeout=120)


class PBNIDataError(Exception):
    """Base exception for PBNI caseload data errors."""


class PBNIDataNotFoundError(PBNIDataError):
    """Raised when a publication or figure cannot be located."""


def _check_frequency(frequency: str) -> None:
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of {FREQUENCIES}, got {frequency!r}")


def find_latest_publication(frequency: str = "annual") -> str:
    """Find the datavis URL of the most recent PBNI caseload bulletin.

    Args:
        frequency: Either ``"annual"`` or ``"quarterly"``.

    Returns:
        Absolute URL of the NISRA data-visualisation page holding the data.

    Raises:
        ValueError: If ``frequency`` is not a recognised cadence.
        PBNIDataNotFoundError: If no matching publication is found on GOV.UK.

    Example:
        >>> find_latest_publication("annual").startswith("https://datavis.nisra.gov.uk/pbni/")
        True
    """
    _check_frequency(frequency)

    response = session.get(
        SEARCH_API_URL,
        params={
            "q": f"probation board ni {frequency} caseload",
            "count": 50,
            "fields": "title,link,public_timestamp",
        },
        timeout=30,
    )
    response.raise_for_status()

    prefix = f"/government/statistics/probation-board-ni-{frequency}-caseload"
    matches = [r for r in response.json().get("results", []) if r.get("link", "").startswith(prefix)]
    if not matches:
        raise PBNIDataNotFoundError(f"No {frequency} PBNI caseload publications found on GOV.UK")
    matches.sort(key=lambda r: r.get("public_timestamp", ""), reverse=True)

    for match in matches:
        content = session.get(f"{CONTENT_API_URL}{match['link']}", timeout=30)
        content.raise_for_status()
        for attachment in content.json().get("details", {}).get("attachments", []):
            url = attachment.get("url", "")
            if DATAVIS_HOST in url:
                logger.info("Resolved %s PBNI bulletin to %s", frequency, url)
                return url

    raise PBNIDataNotFoundError(f"No {frequency} PBNI publication links to a {DATAVIS_HOST} data page")


def _decode_csv(payload: bytes) -> str:
    r"""Decode an embedded figure CSV.

    NISRA exports these as UTF-16LE but terminates lines with a bare single-byte
    ``\r\n``, so every row after the first is byte-misaligned for a real UTF-16
    decoder. The content is pure ASCII, so dropping null bytes recovers it.
    """
    return payload.replace(b"\x00", b"").decode("utf-8-sig")


def _extract_figures(html: str, frequency: str) -> dict[str, pd.DataFrame]:
    """Pull every embedded figure CSV out of a datavis page, keyed by dimension."""
    registry = _FIGURES[frequency]
    frames: dict[str, pd.DataFrame] = {}

    for match in _DATA_URI_RE.finditer(html):
        figure_number = int(match.group(3))
        if figure_number not in registry:
            continue
        dimension, renames = registry[figure_number]

        payload = base64.b64decode(re.sub(r"\s+", "", match.group(1)))
        frame = pd.read_csv(io.StringIO(_decode_csv(payload)))
        frame = frame.rename(columns={**renames, "Date": "date", "Quarter": "quarter"})
        frame.columns = [_snake_case(c) for c in frame.columns]
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frames[dimension] = frame

    missing = {d for d, _ in registry.values()} - set(frames)
    if missing:
        raise PBNIDataNotFoundError(f"Missing {frequency} figures for dimensions: {sorted(missing)}")
    return frames


def _snake_case(name: str) -> str:
    """Normalise a published column heading to snake_case."""
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name.replace("%", "pct")).strip("_")
    return cleaned.lower()


def list_dimensions(frequency: str = "annual") -> list[str]:
    """List the dimensions available for a publication cadence.

    Args:
        frequency: Either ``"annual"`` or ``"quarterly"``.

    Returns:
        Sorted dimension names accepted by :func:`get_latest_data`.

    Example:
        >>> "caseload" in list_dimensions("annual")
        True
    """
    _check_frequency(frequency)
    return sorted(dimension for dimension, _ in _FIGURES[frequency].values())


def get_latest_data(
    dimension: str = "caseload",
    frequency: str = "annual",
    force_refresh: bool = False,
) -> pd.DataFrame | dict[str, pd.DataFrame]:
    """Retrieve the latest PBNI caseload statistics.

    Args:
        dimension: Which breakdown to return, or ``"all"`` for every dimension.
            See :func:`list_dimensions` for the options.
        frequency: Either ``"annual"`` or ``"quarterly"``.
        force_refresh: Bypass the local cache and re-download the bulletin.

    Returns:
        A DataFrame for a single dimension, or a mapping of dimension name to
        DataFrame when ``dimension="all"``.

    Raises:
        ValueError: If ``frequency`` or ``dimension`` is not recognised.

    Example:
        >>> df = get_latest_data("order_type", frequency="annual")
        >>> "Probation Order" in set(df["order_type"])
        True
    """
    _check_frequency(frequency)
    available = list_dimensions(frequency)
    if dimension != "all" and dimension not in available:
        raise ValueError(f"dimension must be 'all' or one of {available}, got {dimension!r}")

    url = find_latest_publication(frequency)
    path = _downloader.download(url, cache_ttl_hours=24 * 7, force_refresh=force_refresh)
    frames = _extract_figures(path.read_bytes().decode("utf-8"), frequency)

    return frames if dimension == "all" else frames[dimension]


def get_annual_caseload(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the annual caseload and service-user totals at each 31 March.

    Args:
        force_refresh: Bypass the local cache and re-download the bulletin.

    Returns:
        DataFrame with ``date``, ``caseload`` and ``service_users`` columns.

    Example:
        >>> df = get_annual_caseload()
        >>> bool((df["caseload"] >= df["service_users"]).all())
        True
    """
    return get_latest_data("caseload", frequency="annual", force_refresh=force_refresh)


def get_quarterly_caseload(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the quarterly caseload and service-user totals at each quarter end.

    Args:
        force_refresh: Bypass the local cache and re-download the bulletin.

    Returns:
        DataFrame with ``date``, ``caseload`` and ``service_users`` columns.

    Example:
        >>> df = get_quarterly_caseload()
        >>> len(df) >= 8
        True
    """
    return get_latest_data("caseload", frequency="quarterly", force_refresh=force_refresh)


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a caseload frame is structurally sound.

    Args:
        df: A frame returned by :func:`get_annual_caseload` or
            :func:`get_quarterly_caseload`.

    Returns:
        True if the frame passes every check.

    Raises:
        PBNIDataError: If the frame is empty, missing columns, or holds
            non-positive counts.

    Example:
        >>> validate_data(get_annual_caseload())
        True
    """
    if df.empty:
        raise PBNIDataError("Caseload data is empty")

    required = {"date", "caseload", "service_users"}
    missing = required - set(df.columns)
    if missing:
        raise PBNIDataError(f"Caseload data missing columns: {sorted(missing)}")

    if df["date"].isna().any():
        raise PBNIDataError("Caseload data contains unparseable dates")

    if (df[["caseload", "service_users"]] <= 0).to_numpy().any():
        raise PBNIDataError("Caseload data contains non-positive counts")

    return True
