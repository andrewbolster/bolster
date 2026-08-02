"""Northern Ireland Road Safety Partnership (RSP) Statistics.

Record-level detections issued by the Northern Ireland Road Safety Partnership's
safety camera programme — fixed, mobile and average-speed cameras plus red-light
running cameras.

Data includes:
- One row per detection with date, time, camera type and posted speed limit
- Banded detected speed (exact speeds are not published)
- Enforcement outcome (fixed penalty, speed awareness course, prosecution)
- Geographic breakdown by the 11 Local Government Districts
- Banded offender age and gender
- Historical coverage from 2011 onwards

Data Source:
    **Primary Source**: OpenDataNI - Northern Ireland Road Safety Partnership

    https://www.opendatani.gov.uk/dataset?q=road+safety+partnership

    The Road Safety Partnership brings together the PSNI, the Department for
    Infrastructure and the Northern Ireland Courts and Tribunals Service to
    operate the safety camera programme. Published under the Open Government
    Licence v3.0.

Update Frequency: Periodic (published in multi-year batches)
Geographic Coverage: Northern Ireland (11 Local Government Districts)
Reference Date: Date of detected offence
Time Coverage: 2011 to present

Note:
    This is the RSP *enforcement* dataset. It is distinct from the Northern
    Ireland Road Safety Strategy to 2030 progress reports, which cover casualty
    reduction targets rather than camera detections.

    Detection reference numbers restart at 1 in each published batch, so they
    are unique within a batch but not across the full series.

Example:
    >>> from bolster.data_sources.psni import road_safety_partnership as rsp
    >>> df = rsp.get_detections(year=2024)
    >>> 'camera_type' in df.columns
    True
    >>> summary = rsp.get_annual_summary()
    >>> 'detections' in summary.columns
    True
"""

import logging
import re

import pandas as pd

from bolster.utils.web import session

from ._base import (
    PSNIDataNotFoundError,
    PSNIValidationError,
    download_file,
    get_lgd_code,
    get_nuts3_code,
)

logger = logging.getLogger(__name__)

# OpenDataNI API endpoint
OPENDATANI_API = "https://admin.opendatani.gov.uk/api/3/action"

# Search term used to locate the RSP packages on OpenDataNI
DATASET_QUERY = "road safety partnership"

# Column names differ between published batches; map both to a common schema.
COLUMN_ALIASES = {
    "id": "reference",
    "refno": "reference",
    "offencedate": "offence_date",
    "offencetime": "offence_time",
    "cameratype": "camera_type",
    "speedlimit(mph)": "speed_limit_mph",
    "speedlimitmph": "speed_limit_mph",
    "speeddetected(grouped)": "speed_band",
    "speed_grouped": "speed_band",
    "outcome": "outcome",
    "localgovernmentdistrict": "district",
    "offenderage(grouped)": "age_band",
    "age": "age_band",
    "offendergender": "gender",
    "offender_sex": "gender",
}

# Speed bands in ascending order. The published labels are inconsistently
# spaced, and the 2011-2019 batch contains a single "110-120mph" record that is
# a typo for the 111-120 band.
SPEED_BANDS = [
    "31-40 mph",
    "41-50 mph",
    "51-60 mph",
    "61-70 mph",
    "71-80 mph",
    "81-90 mph",
    "91-100 mph",
    "101-110 mph",
    "111-120 mph",
    "121-130 mph",
]

SPEED_BAND_FIXES = {"110-120 mph": "111-120 mph"}

# Age bands in ascending order ("Unknown" sorts last).
AGE_BANDS = ["Under 17", "17 - 24", "25 - 39", "40 - 54", "55 - 69", "70+", "Unknown"]

CAMERA_TYPES = [
    "Average Speed Camera",
    "Fixed Speed Camera",
    "Mobile Speed Camera",
    "Red Light Running Camera",
]

OUTCOMES = [
    "Fixed Penalty Notice Issued",
    "Referred for Prosecution",
    "Speed Awareness Course Completed",
]

# Red light cameras record no speed, so speed columns are legitimately null.
NO_SPEED_CAMERA_TYPE = "Red Light Running Camera"

REQUIRED_COLUMNS = [
    "reference",
    "offence_date",
    "camera_type",
    "outcome",
    "district",
    "year",
]


def _canonicalise_district(name: str) -> str:
    """Convert a published district name to the canonical PSNI form.

    The RSP data spells districts with "and" and includes a comma in
    "Armagh City, Banbridge and Craigavon", whereas the shared PSNI geographic
    lookups use "&" and no comma.

    Args:
        name: District name as published, e.g. "Mid and East Antrim"

    Returns:
        Canonical district name, e.g. "Mid & East Antrim"

    Example:
        >>> _canonicalise_district("Mid and East Antrim")
        'Mid & East Antrim'
        >>> _canonicalise_district("Armagh City, Banbridge and Craigavon")
        'Armagh City Banbridge & Craigavon'
    """
    return name.replace(",", "").replace(" and ", " & ").strip()


def _normalise_speed_band(band: str | float) -> str | None:
    """Normalise an inconsistently spaced speed band label.

    Args:
        band: Published band label, e.g. "61-70mph", or NaN

    Returns:
        Normalised label, e.g. "61-70 mph", or None if not a band

    Example:
        >>> _normalise_speed_band("61-70mph")
        '61-70 mph'
        >>> _normalise_speed_band("110-120mph")
        '111-120 mph'
        >>> _normalise_speed_band(None) is None
        True
    """
    if not isinstance(band, str):
        return None
    cleaned = re.sub(r"\s*mph\s*$", " mph", band.strip(), flags=re.IGNORECASE)
    return SPEED_BAND_FIXES.get(cleaned, cleaned)


def _normalise_column(name: str) -> str:
    """Map a published column header onto the common schema.

    Args:
        name: Raw column header from the CSV

    Returns:
        Canonical column name, or a lowercased fallback

    Example:
        >>> _normalise_column("SpeedLimit(mph)")
        'speed_limit_mph'
        >>> _normalise_column("Offender Age (grouped)")
        'age_band'
    """
    key = name.strip().lower().replace(" ", "")
    if key in COLUMN_ALIASES:
        return COLUMN_ALIASES[key]
    return name.strip().lower().replace(" ", "_")


def _get_available_datasets() -> list[dict]:
    """Get the list of RSP detection datasets published on OpenDataNI.

    Dataset slugs and titles disagree about which years each batch covers
    (one batch is variously slugged ``...2011-2021`` and titled "2011-2019"),
    so the covered year range is taken from the resource filename, which
    matches the data itself.

    Returns:
        List of dataset dictionaries with keys:
            - name: str (package slug)
            - title: str
            - url: str (CSV download URL)
            - start_year: int
            - end_year: int

    Raises:
        PSNIDataNotFoundError: If the API request fails or returns nothing usable

    Example:
        >>> datasets = _get_available_datasets()
        >>> all('url' in d for d in datasets)
        True
    """
    try:
        resp = session.get(
            f"{OPENDATANI_API}/package_search",
            params={"q": DATASET_QUERY, "rows": 50},
            headers={"User-Agent": "bolster/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise PSNIDataNotFoundError(f"Failed to fetch RSP dataset list: {e}") from e

    if not data.get("success"):
        raise PSNIDataNotFoundError("OpenDataNI API returned unsuccessful response")

    datasets = []
    for pkg in data["result"]["results"]:
        title = pkg.get("title", "")
        if "road safety partnership" not in title.lower():
            continue

        for resource in pkg.get("resources", []):
            url = resource.get("url", "")
            if resource.get("format", "").upper() != "CSV":
                continue

            years = re.search(r"(\d{4})-(\d{4})", url.rsplit("/", 1)[-1]) or re.search(r"(\d{4})-(\d{4})", title)
            if not years:
                logger.debug("Skipping RSP resource with no year range: %s", url)
                continue

            datasets.append(
                {
                    "name": pkg.get("name", ""),
                    "title": title,
                    "url": url,
                    "start_year": int(years.group(1)),
                    "end_year": int(years.group(2)),
                }
            )

    if not datasets:
        raise PSNIDataNotFoundError("No Road Safety Partnership CSV resources found on OpenDataNI")

    datasets.sort(key=lambda d: d["start_year"])
    return datasets


def get_available_years() -> list[int]:
    """Get the years covered by published RSP detection data.

    Returns:
        Sorted list of years

    Example:
        >>> years = get_available_years()
        >>> 2011 in years
        True
    """
    years: set[int] = set()
    for dataset in _get_available_datasets():
        years.update(range(dataset["start_year"], dataset["end_year"] + 1))
    return sorted(years)


def _parse_detections(path) -> pd.DataFrame:
    """Parse a downloaded RSP CSV into the common schema.

    Args:
        path: Path to the downloaded CSV

    Returns:
        DataFrame with normalised columns and derived date parts
    """
    df = pd.read_csv(path, low_memory=False)
    df.columns = [_normalise_column(c) for c in df.columns]

    df["offence_date"] = pd.to_datetime(df["offence_date"], format="%d-%b-%y", errors="coerce")
    df["year"] = df["offence_date"].dt.year.astype("Int64")
    df["month"] = df["offence_date"].dt.month.astype("Int64")

    if "offence_time" in df.columns:
        df["hour"] = pd.to_datetime(df["offence_time"], format="%H:%M:%S", errors="coerce").dt.hour.astype("Int64")

    if "speed_band" in df.columns:
        df["speed_band"] = df["speed_band"].map(_normalise_speed_band)
    if "speed_limit_mph" in df.columns:
        df["speed_limit_mph"] = df["speed_limit_mph"].astype("Int64")

    df["district"] = df["district"].map(_canonicalise_district)
    df["lgd_code"] = df["district"].map(get_lgd_code)
    df["nuts3_code"] = df["district"].map(get_nuts3_code)

    return df


def get_detections(
    year: int | None = None,
    camera_type: str | None = None,
    district: str | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get record-level safety camera detections.

    Each row is a single detection. Detected speeds are published only as
    bands; red light camera rows carry no speed at all.

    Args:
        year: Restrict to a single year. If None, all published years are
            loaded and concatenated (around 700,000 rows).
        camera_type: Restrict to one of :data:`CAMERA_TYPES`
        district: Restrict to a district, in either the published
            ("Mid and East Antrim") or canonical ("Mid & East Antrim") form
        force_refresh: If True, bypass the download cache

    Returns:
        DataFrame with columns: reference, offence_date, offence_time,
        camera_type, speed_limit_mph, speed_band, outcome, district,
        age_band, gender, year, month, hour, lgd_code, nuts3_code

    Raises:
        PSNIDataNotFoundError: If no data is published for the requested year

    Example:
        >>> df = get_detections(year=2024)
        >>> bool((df['year'] == 2024).all())
        True
    """
    datasets = _get_available_datasets()

    if year is not None:
        datasets = [d for d in datasets if d["start_year"] <= year <= d["end_year"]]
        if not datasets:
            raise PSNIDataNotFoundError(
                f"No RSP data available for year {year}. Available years: {get_available_years()}"
            )

    frames = []
    for dataset in datasets:
        path = download_file(dataset["url"], cache_ttl_hours=24 * 30, force_refresh=force_refresh)
        frames.append(_parse_detections(path))

    df = pd.concat(frames, ignore_index=True)

    if year is not None:
        df = df[df["year"] == year]
    if camera_type is not None:
        df = df[df["camera_type"] == camera_type]
    if district is not None:
        df = df[df["district"] == _canonicalise_district(district)]

    return df.reset_index(drop=True)


def get_annual_summary(force_refresh: bool = False) -> pd.DataFrame:
    """Summarise detections by year.

    Args:
        force_refresh: If True, bypass the download cache

    Returns:
        DataFrame with columns: year, detections, fixed_penalties,
        awareness_courses, prosecutions, prosecution_rate_pct

    Example:
        >>> summary = get_annual_summary()
        >>> bool((summary['detections'] > 0).all())
        True
    """
    df = get_detections(force_refresh=force_refresh)

    counts = df.pivot_table(index="year", columns="outcome", values="reference", aggfunc="count", fill_value=0)
    summary = pd.DataFrame(
        {
            "year": counts.index,
            "detections": counts.sum(axis=1).to_numpy(),
            "fixed_penalties": counts.get("Fixed Penalty Notice Issued", 0),
            "awareness_courses": counts.get("Speed Awareness Course Completed", 0),
            "prosecutions": counts.get("Referred for Prosecution", 0),
        }
    ).reset_index(drop=True)

    summary["prosecution_rate_pct"] = (summary["prosecutions"] / summary["detections"] * 100).round(2)
    return summary


def get_detections_by_district(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Count detections by district.

    Args:
        year: Restrict to a single year, or None for all years
        force_refresh: If True, bypass the download cache

    Returns:
        DataFrame with columns: district, lgd_code, nuts3_code, detections,
        sorted by detections descending

    Example:
        >>> by_district = get_detections_by_district(year=2024)
        >>> len(by_district)
        11
    """
    df = get_detections(year=year, force_refresh=force_refresh)

    return (
        df.groupby(["district", "lgd_code", "nuts3_code"], dropna=False)
        .size()
        .reset_index(name="detections")
        .sort_values("detections", ascending=False)
        .reset_index(drop=True)
    )


def get_detections_by_camera_type(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Count detections by camera type and year.

    Args:
        year: Restrict to a single year, or None for all years
        force_refresh: If True, bypass the download cache

    Returns:
        DataFrame with columns: year, camera_type, detections

    Example:
        >>> by_camera = get_detections_by_camera_type(year=2024)
        >>> set(by_camera['camera_type']) <= set(CAMERA_TYPES)
        True
    """
    df = get_detections(year=year, force_refresh=force_refresh)

    return (
        df.groupby(["year", "camera_type"])
        .size()
        .reset_index(name="detections")
        .sort_values(["year", "detections"], ascending=[True, False])
        .reset_index(drop=True)
    )


def get_speed_distribution(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Cross-tabulate detected speed band against the posted speed limit.

    Red light camera detections are excluded because they record no speed.

    Args:
        year: Restrict to a single year, or None for all years
        force_refresh: If True, bypass the download cache

    Returns:
        DataFrame with columns: speed_limit_mph, speed_band, detections,
        ordered by limit then band severity

    Example:
        >>> dist = get_speed_distribution(year=2024)
        >>> bool((dist['detections'] > 0).all())
        True
    """
    df = get_detections(year=year, force_refresh=force_refresh)
    df = df[df["speed_band"].notna()]

    result = df.groupby(["speed_limit_mph", "speed_band"]).size().reset_index(name="detections")
    result["speed_band"] = pd.Categorical(result["speed_band"], categories=SPEED_BANDS, ordered=True)
    return result.sort_values(["speed_limit_mph", "speed_band"]).reset_index(drop=True)


def get_offender_demographics(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Cross-tabulate offender age band against gender.

    Args:
        year: Restrict to a single year, or None for all years
        force_refresh: If True, bypass the download cache

    Returns:
        DataFrame with columns: age_band, gender, detections

    Example:
        >>> demo = get_offender_demographics(year=2024)
        >>> 'age_band' in demo.columns
        True
    """
    df = get_detections(year=year, force_refresh=force_refresh)

    result = df.groupby(["age_band", "gender"]).size().reset_index(name="detections")
    result["age_band"] = pd.Categorical(result["age_band"], categories=AGE_BANDS, ordered=True)
    return result.sort_values(["age_band", "gender"]).reset_index(drop=True)


def get_hourly_profile(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Count detections by hour of day.

    Args:
        year: Restrict to a single year, or None for all years
        force_refresh: If True, bypass the download cache

    Returns:
        DataFrame with columns: hour, detections, sorted by hour

    Example:
        >>> profile = get_hourly_profile(year=2024)
        >>> bool(profile['hour'].between(0, 23).all())
        True
    """
    df = get_detections(year=year, force_refresh=force_refresh)
    df = df[df["hour"].notna()]

    return df.groupby("hour").size().reset_index(name="detections").sort_values("hour").reset_index(drop=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate an RSP detections DataFrame.

    Args:
        df: DataFrame returned by :func:`get_detections`

    Returns:
        True if the data passes all checks

    Raises:
        PSNIValidationError: If any check fails

    Example:
        >>> import pandas as pd
        >>> try:
        ...     validate_data(pd.DataFrame())
        ... except PSNIValidationError:
        ...     print("PSNIValidationError raised for empty frame")
        PSNIValidationError raised for empty frame
    """
    if df.empty:
        raise PSNIValidationError("Detections DataFrame is empty")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise PSNIValidationError(f"Missing required columns: {missing}")

    if df["offence_date"].isna().any():
        raise PSNIValidationError("Detections contain unparseable offence dates")

    unknown_cameras = set(df["camera_type"].dropna()) - set(CAMERA_TYPES)
    if unknown_cameras:
        raise PSNIValidationError(f"Unknown camera types: {sorted(unknown_cameras)}")

    unknown_outcomes = set(df["outcome"].dropna()) - set(OUTCOMES)
    if unknown_outcomes:
        raise PSNIValidationError(f"Unknown outcomes: {sorted(unknown_outcomes)}")

    if "speed_band" in df.columns:
        unknown_bands = set(df["speed_band"].dropna()) - set(SPEED_BANDS)
        if unknown_bands:
            raise PSNIValidationError(f"Unknown speed bands: {sorted(unknown_bands)}")

    if df["district"].isna().any():
        raise PSNIValidationError("Detections contain missing districts")

    return True
