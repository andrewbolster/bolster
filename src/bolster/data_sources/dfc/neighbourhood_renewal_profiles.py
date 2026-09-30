"""Neighbourhood Renewal Area (NRA) Profiles (Department for Communities).

Annual statistical profiles of the 36 Neighbourhood Renewal Areas in Northern Ireland, published by the
Department for Communities (DfC) as one interactive NISRA "datavis" page per area. Unlike most datavis
reports these pages embed no downloadable files: every chart's data is only in the page as Plotly JSON,
which this module reads without running any JavaScript (see :mod:`bolster.utils.htmlwidgets`).

Each profile covers about 60 charts across Population, Employment, Health, Education, Crime and Census
sections, comparing the area with Northern Ireland as a whole.

Update Frequency: Annual
Geographic Coverage: 36 Neighbourhood Renewal Areas, with Northern Ireland as the comparator

Data Source:
    **Hub**: https://www.communities-ni.gov.uk/articles/neighbourhood-renewal-area-profiles-2026

    The hub links every area's page; page URLs are irregular (``Falls_Clonard_...``,
    ``Upper_Ardoyne_Ballysillan_...``) so they are taken from the hub, never constructed.

Performance:
    Each page is about 5 MB. :func:`get_area_profile` fetches one; :func:`get_all_area_profiles` fetches all 36
    (roughly 200 MB, a few minutes on a cold cache). Pages are cached by the shared session.

Example:
    >>> from bolster.data_sources.dfc import neighbourhood_renewal_profiles as nra
    >>> df = nra.get_area_profile("Andersonstown")  # doctest: +SKIP
    >>> sorted(df["section"].unique())[:2]  # doctest: +SKIP
    ['Census data 2001, 2011 & 2021.', 'Census data 2021 only']
"""

import logging
import re
from datetime import date

import pandas as pd
from bs4 import BeautifulSoup, Tag

from bolster.utils.htmlwidgets import extract_widgets, plotly_frame
from bolster.utils.web import is_url_host, session

logger = logging.getLogger(__name__)

HUB_URL = "https://www.communities-ni.gov.uk/articles/neighbourhood-renewal-area-profiles-{year}"
_LINK_NAME_RE = re.compile(r"^(.*?)\s+NRA Area Profile\b", re.IGNORECASE)
_URL_NAME_RE = re.compile(r"/([^/]+?)_NRA_Area_Profile", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_MIN_AREAS = 30


class NRADataError(Exception):
    """Base exception for Neighbourhood Renewal Area profile errors."""


class NRADataNotFoundError(NRADataError):
    """Raised when the hub, an area or its chart data cannot be found."""


class NRAValidationError(NRADataError):
    """Raised when a parsed profile fails validation."""


def _normalise(name: str) -> str:
    """``"Falls/Clonard"`` and ``"Falls_Clonard"`` both become ``"fallsclonard"``."""
    return _NON_ALNUM_RE.sub("", name.lower())


def _names(area: str, url: str) -> set[str]:
    """Normalised names an area goes by: the hub's name and the one in its page URL.

    They can differ: the hub lists "Greater Falls" but its page, and the series inside it, say ``Falls_Clonard``.
    """
    match = _URL_NAME_RE.search(url)
    return {_normalise(area)} | ({_normalise(match.group(1))} if match else set())


def list_areas(force_refresh: bool = False) -> dict[str, str]:
    """List the Neighbourhood Renewal Areas and their profile page URLs.

    Walks the yearly hub pages from the current year backwards until one lists profiles.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Mapping of area name (``"Andersonstown"``, ``"Upper Springfield/Whiterock"``) to page URL, in hub order.

    Raises:
        NRADataNotFoundError: If no recent hub page lists the profiles.
    """
    for year in range(date.today().year, date.today().year - 4, -1):
        response = session.get(HUB_URL.format(year=year), timeout=60, force_refresh=force_refresh)
        if response.status_code != 200:
            continue
        areas: dict[str, str] = {}
        for link in BeautifulSoup(response.text, "html.parser").find_all("a", href=True):
            href = str(link["href"]) if isinstance(link, Tag) else ""
            match = _LINK_NAME_RE.match(link.get_text(" ", strip=True))
            if match and is_url_host(href, "datavis.nisra.gov.uk"):
                areas[match.group(1)] = href
        if len(areas) >= _MIN_AREAS:
            return areas
    raise NRADataNotFoundError("Could not find the Neighbourhood Renewal Area profiles hub")


def _resolve_area(area: str, areas: dict[str, str]) -> str:
    wanted = _normalise(area)
    for name, url in areas.items():
        if wanted in _names(name, url):
            return name
    raise NRADataNotFoundError(f"Unknown Neighbourhood Renewal Area {area!r}; see list_areas() for valid names")


def get_area_profile(area: str, force_refresh: bool = False) -> pd.DataFrame:
    """Every chart value in one area's profile, in long form.

    Args:
        area: Area name as listed by :func:`list_areas`, or as it appears in the page URL; matching ignores case
            and punctuation (``"falls clonard"`` finds the area the hub lists as ``"Greater Falls"``).
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``nra``, ``section``, ``figure`` (chart title), ``unit``, ``series`` (the area, Northern
        Ireland, or a breakdown such as a sex or age band), ``category`` (usually a year) and ``value``, plus
        ``is_area`` (``True`` where the series is the area itself).

    Raises:
        NRADataNotFoundError: If the area is unknown or its page has no chart data.
        NRAValidationError: If the parsed profile fails :func:`validate_data`.
    """
    areas = list_areas(force_refresh=force_refresh)
    name = _resolve_area(area, areas)
    html = session.get(areas[name], timeout=90, force_refresh=force_refresh).text
    frame = plotly_frame(extract_widgets(html))
    if frame.empty:
        raise NRADataNotFoundError(f"No chart data found on {areas[name]}")
    frame.insert(0, "nra", name)
    frame["is_area"] = frame["series"].map(_normalise).isin(_names(name, areas[name]))
    validate_data(frame)
    return frame


def get_all_area_profiles(areas: list[str] | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Every chart value for several Neighbourhood Renewal Areas (all 36 by default), in long form.

    Fetches each area's page (about 5 MB each); see the module notes on cost.

    Args:
        areas: Area names to fetch, as accepted by :func:`get_area_profile`. ``None`` means every area.
        force_refresh: Bypass the page cache.

    Returns:
        The concatenation of :func:`get_area_profile` for each area, with the same columns.

    Raises:
        NRADataNotFoundError: If a requested area is unknown.
    """
    listed = list_areas(force_refresh=force_refresh)
    names = list(listed) if areas is None else [_resolve_area(area, listed) for area in areas]
    frames = []
    for index, name in enumerate(names, start=1):
        logger.info("Fetching NRA profile %d/%d: %s", index, len(names), name)
        frames.append(get_area_profile(name, force_refresh=force_refresh))
    return pd.concat(frames, ignore_index=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a :func:`get_area_profile` result.

    Args:
        df: Profile DataFrame.

    Returns:
        ``True`` if valid.

    Raises:
        NRAValidationError: If columns are missing, there are too few charts, the area's own series or the
            Northern Ireland comparator is absent, or there is no numeric data.
    """
    required = {"nra", "section", "figure", "unit", "series", "category", "value", "is_area"}
    missing = required - set(df.columns)
    if missing:
        raise NRAValidationError(f"Missing expected columns: {sorted(missing)}")
    if df["figure"].nunique() < 20:
        raise NRAValidationError(f"Too few charts: {df['figure'].nunique()}")
    if not df["is_area"].any():
        raise NRAValidationError("No series for the area itself")
    if not (df["series"] == "Northern Ireland").any():
        raise NRAValidationError("No Northern Ireland comparator series")
    if df["value"].notna().sum() == 0:
        raise NRAValidationError("No numeric values")
    return True
