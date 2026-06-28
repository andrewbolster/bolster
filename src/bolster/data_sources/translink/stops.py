"""Translink stop metadata — lookup table from Open Data NI ATCO-CIF timetable zips.

Parses QL (stop name) and QB (stop location) records from the three Translink
ATCO-CIF zip archives published on Open Data NI:

    - Metro & Glider   (metro-glider-*.zip)
    - Ulsterbus/GoldLine (ulb-gle-*.zip)

Each zip contains one or more ``.cif`` files in Irish National Grid (ING) / OSGB
coordinate system (Airy 1830 Modified ellipsoid, Transverse Mercator).  Coordinates
are converted to WGS84 (EPSG:4326) using the standard ING reverse projection.

The resulting lookup table maps NaPTAN ATCOCode (``700000xxxxxx``) to:

    - ``name``      : stop name as published in the CIF
    - ``easting``   : ING easting (integer metres)
    - ``northing``  : ING northing (integer metres)
    - ``latitude``  : WGS84 latitude (degrees)
    - ``longitude`` : WGS84 longitude (degrees)

The table is cached in memory after the first call.  Pass ``force_refresh=True``
to re-download the source zips.

Example:
    >>> lookup = get_stop_lookup()
    >>> lookup["700000001661"]["name"]
    'Victoria Square Victoria Street'
    >>> abs(lookup["700000001661"]["latitude"] - 54.595) < 0.01
    True
"""

import io
import logging
import math
import zipfile
from typing import Any

import pandas as pd

from bolster.utils.web import session

from ._base import (
    OPENDATANI_METRO_GLIDER_URL,
    OPENDATANI_ULSTERBUS_URL,
    TRANSLINK_BASE_URL,
    TranslinkDataNotFoundError,
    TranslinkValidationError,
    download_file,
)

logger = logging.getLogger(__name__)

# Cached in-process stop lookup: atco_code -> dict
_STOP_CACHE: dict[str, dict[str, Any]] | None = None

# ── Irish National Grid reverse projection ────────────────────────────────────
# Airy 1830 Modified ellipsoid, false origin lat=53.5°N lon=8°W,
# false easting=200000m, false northing=250000m, scale=1.000035
_ING_A = 6_377_340.189
_ING_B = 6_356_034.447
_ING_F0 = 1.000035
_ING_LAT0 = math.radians(53.5)
_ING_LON0 = math.radians(-8.0)
_ING_E0 = 200_000.0
_ING_N0 = 250_000.0
_ING_E2 = 1 - (_ING_B / _ING_A) ** 2
_ING_N = (_ING_A - _ING_B) / (_ING_A + _ING_B)


def _ing_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert Irish National Grid (ING) easting/northing to WGS84 lat/lon.

    Args:
        easting: ING easting in metres.
        northing: ING northing in metres.

    Returns:
        (latitude, longitude) in decimal degrees (WGS84).
    """
    Et = easting - _ING_E0
    n, a, b, F0 = _ING_N, _ING_A, _ING_B, _ING_F0
    e2, lat0 = _ING_E2, _ING_LAT0

    lat = (northing - _ING_N0) / (a * F0) + lat0

    for _ in range(100):
        M = (
            b
            * F0
            * (
                (1 + n + 5 / 4 * n**2 + 5 / 4 * n**3) * (lat - lat0)
                - (3 * n + 3 * n**2 + 21 / 8 * n**3) * math.sin(lat - lat0) * math.cos(lat + lat0)
                + (15 / 8 * n**2 + 15 / 8 * n**3) * math.sin(2 * (lat - lat0)) * math.cos(2 * (lat + lat0))
                - 35 / 24 * n**3 * math.sin(3 * (lat - lat0)) * math.cos(3 * (lat + lat0))
            )
        )
        delta = northing - _ING_N0 - M
        if abs(delta) < 1e-6:
            break
        lat += delta / (a * F0)

    nu = a * F0 / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    rho = a * F0 * (1 - e2) / (1 - e2 * math.sin(lat) ** 2) ** 1.5
    eta2 = nu / rho - 1
    t = math.tan(lat)
    s = 1 / math.cos(lat)

    lat_r = (
        lat
        - t / (2 * rho * nu) * Et**2
        + t / (24 * rho * nu**3) * (5 + 3 * t**2 + eta2 - 9 * t**2 * eta2) * Et**4
        - t / (720 * rho * nu**5) * (61 + 90 * t**2 + 45 * t**4) * Et**6
    )
    lon_r = (
        _ING_LON0
        + s / nu * Et
        - s / (6 * nu**3) * (nu / rho + 2 * t**2) * Et**3
        + s / (120 * nu**5) * (5 + 28 * t**2 + 24 * t**4) * Et**5
        - s / (5040 * nu**7) * (61 + 662 * t**2 + 1320 * t**4 + 720 * t**6) * Et**7
    )
    return math.degrees(lat_r), math.degrees(lon_r)


# ── CIF parsing ───────────────────────────────────────────────────────────────


def _parse_cif_zip(zip_bytes: bytes) -> dict[str, dict[str, Any]]:
    """Extract stop records from an ATCO-CIF zip archive.

    Args:
        zip_bytes: Raw bytes of the zip file.

    Returns:
        Dict mapping ATCOCode to ``{name, easting, northing}``.
    """
    stops: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for fname in zf.namelist():
            if not fname.lower().endswith(".cif"):
                continue
            content = zf.read(fname).decode("utf-8", errors="replace")
            for line in content.splitlines():
                if line.startswith("QL"):
                    # QLN<atco:12><name:48>...
                    atco = line[3:15].strip()
                    name = line[15:63].strip()
                    stops.setdefault(atco, {})["name"] = name
                elif line.startswith("QB"):
                    # QBN<atco:12><easting:8><northing:8>...
                    atco = line[3:15].strip()
                    try:
                        easting = int(line[15:23].strip())
                        northing = int(line[23:31].strip())
                    except ValueError:
                        continue
                    stops.setdefault(atco, {})["easting"] = easting
                    stops.setdefault(atco, {})["northing"] = northing
    return stops


def _build_stop_lookup(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Download CIF zips and build the full stop lookup table.

    Downloads the Metro/Glider and Ulsterbus/GoldLine ATCO-CIF zip archives
    from Open Data NI, parses QL/QB records, converts ING coordinates to
    WGS84, and returns the combined lookup dict.

    Args:
        force_refresh: Re-download even if cached files exist.

    Returns:
        Dict mapping ``ATCOCode`` → ``{name, easting, northing, latitude, longitude}``.

    Raises:
        TranslinkDataNotFoundError: If a zip cannot be downloaded.
        TranslinkValidationError: If the combined table has fewer than 5000 stops.
    """
    stops: dict[str, dict[str, Any]] = {}

    for label, url in [
        ("Metro/Glider", OPENDATANI_METRO_GLIDER_URL),
        ("Ulsterbus/GoldLine", OPENDATANI_ULSTERBUS_URL),
    ]:
        logger.info("Downloading %s CIF zip", label)
        path = download_file(url, cache_ttl_hours=168, force_refresh=force_refresh)  # 1-week TTL
        zip_bytes = path.read_bytes()
        new_stops = _parse_cif_zip(zip_bytes)
        logger.info("%s: parsed %d stops", label, len(new_stops))
        stops.update(new_stops)

    # Add WGS84 coordinates
    for _atco, info in stops.items():
        if "easting" in info and "northing" in info:
            try:
                lat, lon = _ing_to_wgs84(info["easting"], info["northing"])
                info["latitude"] = round(lat, 6)
                info["longitude"] = round(lon, 6)
            except (ValueError, ZeroDivisionError):
                pass

    if len(stops) < 5000:
        raise TranslinkValidationError(f"Stop lookup suspiciously small: only {len(stops)} stops parsed")

    logger.info("Stop lookup built: %d stops total", len(stops))
    return stops


def get_stop_lookup(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return the NaPTAN ATCOCode → stop metadata lookup table.

    The table is built on first call and cached in memory for the lifetime
    of the process.  The underlying zip files are cached on disk for one week.

    Args:
        force_refresh: Re-download source zips and rebuild the lookup.

    Returns:
        Dict mapping ``ATCOCode`` (e.g. ``"700000001661"``) to a dict with keys:

        - ``name`` (str): Stop name from the CIF
        - ``easting`` (int): ING easting in metres
        - ``northing`` (int): ING northing in metres
        - ``latitude`` (float): WGS84 latitude
        - ``longitude`` (float): WGS84 longitude

    Raises:
        TranslinkDataNotFoundError: If the source zips cannot be downloaded.
        TranslinkValidationError: If the resulting table is implausibly small.
    """
    global _STOP_CACHE
    if _STOP_CACHE is None or force_refresh:
        _STOP_CACHE = _build_stop_lookup(force_refresh=force_refresh)
    return _STOP_CACHE


def resolve_stop_name(atco_code: str, fallback: bool = True) -> str | None:
    """Return a human-readable name for a NaPTAN ATCOCode.

    Looks up the code in the CIF-derived table first.  If not found and
    ``fallback`` is True, queries the Translink locationApi live.

    Args:
        atco_code: NaPTAN ATCOCode, e.g. ``"700000014482"``.
        fallback: If True, attempt a live API lookup for unknown codes.

    Returns:
        Stop name string, or None if not resolvable.
    """
    lookup = get_stop_lookup()
    info = lookup.get(atco_code)
    if info:
        return info.get("name")

    if not fallback:
        return None

    # Live fallback: Translink locationApi accepts ATCOCode as a search string
    try:
        resp = session.get(
            f"{TRANSLINK_BASE_URL}/locationApi/find",
            params={"SearchString": atco_code, "StopsOnly": "true"},
            timeout=8,
        )
        resp.raise_for_status()
        locs = resp.json().get("Locations", [])
        if locs:
            name = locs[0].get("Name")
            # Cache the result so we don't hit the API again
            lookup[atco_code] = {"name": name}
            return name
    except Exception as e:
        logger.debug("Live stop lookup failed for %s: %s", atco_code, e)

    return None


def find_stop(query: str) -> list[dict[str, Any]]:
    """Search for stops by name using the Translink locationApi.

    Args:
        query: Partial or full stop name, e.g. ``"Cambria Street"``.

    Returns:
        List of dicts, each with keys:
        ``id`` (Translink internal StopId), ``name``, ``location_type``.

    Raises:
        TranslinkDataNotFoundError: If the API request fails.
    """
    try:
        resp = session.get(
            f"{TRANSLINK_BASE_URL}/locationApi/find",
            params={"SearchString": query, "StopsOnly": "true"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        raise TranslinkDataNotFoundError(f"Stop search failed for '{query}': {e}") from e

    locs = resp.json().get("Locations", [])
    return [
        {
            "id": loc["Id"],
            "name": loc["Name"],
            "location_type": loc.get("LocationType", ""),
        }
        for loc in locs
    ]


def get_stop_dataframe(force_refresh: bool = False) -> pd.DataFrame:
    """Return the full stop lookup as a DataFrame.

    Columns: ``atco_code``, ``name``, ``easting``, ``northing``,
    ``latitude``, ``longitude``.

    Args:
        force_refresh: Re-download and rebuild the stop table.

    Returns:
        DataFrame with one row per stop, indexed by ``atco_code``.
    """
    lookup = get_stop_lookup(force_refresh=force_refresh)
    rows = [{"atco_code": k, **v} for k, v in lookup.items()]
    df = pd.DataFrame(rows)
    for col in ("easting", "northing"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("latitude", "longitude"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.set_index("atco_code")
