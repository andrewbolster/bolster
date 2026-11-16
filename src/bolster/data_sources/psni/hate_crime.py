"""PSNI Hate Motivated Incidents and Crimes Data Source.

Police recorded incidents and crimes with a sexual orientation, racist or
sectarian motivation, by financial year from 2004/05 and by area down to ward
level. Each geography is a separate PxStat cube; this module reads them through
:func:`bolster.data_sources.nisra.pxstat.read_dataset` and reshapes every one
into the same tidy long format.

Published as: Hate incidents and crimes in Northern Ireland.

Data Source:
    The NISRA PxStat API (https://data.nisra.gov.uk/), which carries the area
    tables of the PSNI and NISRA hate motivation statistics.

    PxStat matrices used (see :data:`GEOGRAPHIES` for the short name of each):
    ``HATEAA``, ``HATEHSCT``, ``HATEUR``, ``HATELGD``, ``HATEDEA``,
    ``HATEWARD``.

Update Frequency: Annual (financial year, refreshed after the May bulletin)

Geographic Coverage: Northern Ireland, by Assembly Area, Health and Social Care
    Trust, urban/rural, Local Government District, District Electoral Area and
    ward. The LGD, DEA and ward cubes use the 2014 boundaries.

Reference Period: Financial years 2004/05 to 2025/26 (see the ``period`` column).
    Incidents start in 2007/08 and sectarian crimes in 2005/06; earlier cells
    are ``NaN`` where the source publishes nothing.

Note:
    **Three motivations only.** The cubes hold sexual orientation, racist and
    sectarian motivations. The PSNI bulletin also covers other motivations (for
    example disability, faith/religion and transphobic) that are not in these
    cubes, so totals here are not "all hate crime".

    **Area cubes carry crimes only; incidents appear from LGD down.** The
    Assembly Area, Health Trust and urban/rural cubes publish crimes; the LGD,
    DEA and ward cubes publish incidents and crimes.

    **Every cube includes a Northern Ireland total row** (code
    ``N92000002``), so summing all rows double counts. Frames from
    :func:`get_latest_hate_crime` leave that row out unless asked for it, and
    :func:`get_hate_crime_ni_totals` returns the totals on their own.

    **Parts do not always add up to the total.** The LGD, DEA and ward cubes
    sum exactly to Northern Ireland. The Assembly Area, Health Trust and
    urban/rural cubes fall short by up to 9 crimes in a year, with the same gap
    in all three, so some crimes are recorded in Northern Ireland but not
    placed in an area; :func:`get_unallocated` returns that gap.

    Recorded counts move with reporting and recording practice, so a change
    over time is not a change in prevalence.

Example:
    >>> from bolster.data_sources.psni import hate_crime
    >>> df = hate_crime.get_latest_hate_crime("lgd", motivation="racist", measure="crimes")
    >>> sorted(df.columns.tolist())[:3]
    ['cube', 'geography', 'geography_code']
"""

import logging
import re
from typing import NamedTuple

import pandas as pd

from bolster.data_sources.nisra.pxstat import read_dataset

from ._base import PSNIDataNotFoundError, PSNIValidationError

logger = logging.getLogger(__name__)

#: ONS code of the Northern Ireland total row carried by every cube.
NI_CODE = "N92000002"

_PERIOD_COLUMN = "TLIST(A1)"
_STATISTIC_COLUMN = "STATISTIC"
_VALUE_COLUMN = "VALUE"
_PERIOD_PATTERN = re.compile(r"^(\d{4})/\d{2}$")

#: Columns of the tidy frame, in order.
OUTPUT_COLUMNS = [
    "geography_level",
    "cube",
    "geography_code",
    "geography",
    "is_ni_total",
    "motivation",
    "measure",
    "period",
    "year",
    "value",
]

MOTIVATIONS = ("sexual_orientation", "racist", "sectarian")
MEASURES = ("crimes", "incidents")

#: PxStat statistic code -> (motivation, measure).
STATISTICS: dict[str, tuple[str, str]] = {
    "allsocrm": ("sexual_orientation", "crimes"),
    "allsoinc": ("sexual_orientation", "incidents"),
    "allraccrm": ("racist", "crimes"),
    "allracinc": ("racist", "incidents"),
    "allsectcrm": ("sectarian", "crimes"),
    "allsectinc": ("sectarian", "incidents"),
}


class Geography(NamedTuple):
    """How one PxStat cube maps onto the tidy frame.

    ``parts_sum_to_ni`` is ``True`` where the cube's areas add up exactly to the
    Northern Ireland row, and ``False`` where some crimes are not placed in an
    area.
    """

    cube: str
    title: str
    code_column: str
    label_column: str
    parts_sum_to_ni: bool


#: Short geography name -> cube definition.
GEOGRAPHIES: dict[str, Geography] = {
    "assembly_area": Geography("HATEAA", "Assembly Area", "AA", "Assembly Area", False),
    "health_trust": Geography(
        "HATEHSCT", "Health and Social Care Trust", "HSCT", "Health and Social Care Trust", False
    ),
    "urban_rural": Geography("HATEUR", "Urban/Rural", "UR2015", "Urban Rural", False),
    "lgd": Geography("HATELGD", "Local Government District (2014)", "LGD2014", "Local Government District", True),
    "dea": Geography("HATEDEA", "District Electoral Area (2014)", "DEA2014", "District Electoral Area", True),
    "ward": Geography("HATEWARD", "Ward (2014)", "Ward2014", "Ward", True),
}

_NI_LEVEL = "northern_ireland"


def _check_geography(geography: str) -> Geography:
    if geography not in GEOGRAPHIES:
        raise ValueError(f"geography must be one of {sorted(GEOGRAPHIES)}, got {geography!r}")
    return GEOGRAPHIES[geography]


def _check_choice(value: str | None, allowed: tuple[str, ...], name: str) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"{name} must be one of {list(allowed)}, got {value!r}")


def tidy_cube(geography: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Reshape one raw PxStat cube into the tidy long format.

    Args:
        geography: Short geography name, a key of :data:`GEOGRAPHIES`.
        raw: Raw frame from :func:`bolster.data_sources.nisra.pxstat.read_dataset`
            for that geography's cube.

    Returns:
        DataFrame with the columns in :data:`OUTPUT_COLUMNS`. The Northern
        Ireland total row is kept and flagged ``is_ni_total``.

    Raises:
        ValueError: If ``geography`` is not a known geography.
        PSNIDataNotFoundError: If the cube lacks an expected column.
        PSNIValidationError: If the cube holds a statistic or period label the
            module does not know, rather than dropping those rows silently.

    Example:
        >>> raw = pd.DataFrame(
        ...     {
        ...         "STATISTIC": ["allraccrm", "allraccrm"],
        ...         "TLIST(A1)": ["2025/26", "2025/26"],
        ...         "LGD2014": ["N09000003", "N92000002"],
        ...         "Local Government District": ["Belfast", "Northern Ireland"],
        ...         "UNIT": ["number", "number"],
        ...         "VALUE": [300.0, 1507.0],
        ...     }
        ... )
        >>> tidy_cube("lgd", raw)[["geography", "is_ni_total", "year", "value"]].values.tolist()
        [['Belfast', False, 2025, 300.0], ['Northern Ireland', True, 2025, 1507.0]]
    """
    spec = _check_geography(geography)
    required = [_PERIOD_COLUMN, _STATISTIC_COLUMN, _VALUE_COLUMN, spec.code_column, spec.label_column]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise PSNIDataNotFoundError(
            f"PxStat cube {spec.cube} lacks expected column(s) {missing}; its columns are {list(raw.columns)}"
        )

    unknown_stats = sorted(set(raw[_STATISTIC_COLUMN]) - set(STATISTICS))
    if unknown_stats:
        raise PSNIValidationError(
            f"PxStat cube {spec.cube} has statistic code(s) {unknown_stats} this module does not map; "
            f"known codes are {sorted(STATISTICS)}"
        )
    periods = raw[_PERIOD_COLUMN].astype(str)
    bad_periods = sorted(set(periods[~periods.str.match(_PERIOD_PATTERN.pattern)]))
    if bad_periods:
        raise PSNIValidationError(
            f"PxStat cube {spec.cube} has period label(s) {bad_periods} that are not financial years (YYYY/YY)"
        )

    mapped = raw[_STATISTIC_COLUMN].map(STATISTICS)
    code = raw[spec.code_column].astype(str)
    tidy = pd.DataFrame(
        {
            "geography_level": geography,
            "cube": spec.cube,
            "geography_code": code,
            "geography": raw[spec.label_column].astype(str).str.replace(r"\s+", " ", regex=True).str.strip(),
            "is_ni_total": code == NI_CODE,
            "motivation": mapped.str[0],
            "measure": mapped.str[1],
            "period": periods,
            "year": periods.str.extract(_PERIOD_PATTERN.pattern, expand=False).astype("Int64"),
            "value": pd.to_numeric(raw[_VALUE_COLUMN], errors="coerce"),
        }
    )
    return tidy[OUTPUT_COLUMNS].reset_index(drop=True)


def list_geographies() -> pd.DataFrame:
    """List the available geographies.

    Returns:
        DataFrame with columns ``geography``, ``cube``, ``title`` and
        ``parts_sum_to_ni``.

    Example:
        >>> "ward" in set(list_geographies()["geography"])
        True
    """
    return pd.DataFrame(
        [
            {"geography": name, "cube": spec.cube, "title": spec.title, "parts_sum_to_ni": spec.parts_sum_to_ni}
            for name, spec in GEOGRAPHIES.items()
        ]
    )


def _select(df: pd.DataFrame, motivation: str | None, measure: str | None) -> pd.DataFrame:
    if motivation is not None:
        df = df[df["motivation"] == motivation]
    if measure is not None:
        df = df[df["measure"] == measure]
    return df.reset_index(drop=True)


def get_latest_hate_crime(
    geography: str = "lgd",
    motivation: str | None = None,
    measure: str | None = None,
    include_ni_total: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Get police recorded hate motivated incidents and crimes by area.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored: the
        PxStat API is called directly with no local cache layer.

    Args:
        geography: Short geography name (see :func:`list_geographies`).
        motivation: ``sexual_orientation``, ``racist`` or ``sectarian``;
            ``None`` returns all three.
        measure: ``crimes`` or ``incidents``; ``None`` returns both. The
            Assembly Area, Health Trust and urban/rural cubes publish crimes only.
        include_ni_total: Keep the Northern Ireland total row. Off by default so
            that summing the frame cannot double count; with it on, select
            ``is_ni_total`` before aggregating.
        force_refresh: Ignored. Retained for API compatibility.

    Returns:
        Tidy DataFrame with the columns in :data:`OUTPUT_COLUMNS`:

        - ``geography_level`` / ``cube``: short geography name and PxStat matrix
        - ``geography_code`` / ``geography``: the area's code and name
        - ``is_ni_total``: ``True`` on the Northern Ireland total row
        - ``motivation`` / ``measure``: what was recorded
        - ``period`` / ``year``: the financial year label and its starting year
        - ``value``: the count, ``NaN`` where the source publishes nothing

    Raises:
        ValueError: If ``geography``, ``motivation`` or ``measure`` is not recognised.
        PSNIDataNotFoundError: If the cube lacks an expected column.
        PSNIValidationError: If the cube holds an unknown statistic or period.
        bolster.data_sources.nisra.pxstat.PxStatError: If PxStat returns an error.

    Example:
        >>> df = get_latest_hate_crime("health_trust", motivation="racist")
        >>> sorted(df["measure"].unique())
        ['crimes']
    """
    spec = _check_geography(geography)
    _check_choice(motivation, MOTIVATIONS, "motivation")
    _check_choice(measure, MEASURES, "measure")
    tidy = tidy_cube(geography, read_dataset(spec.cube))
    if not include_ni_total:
        tidy = tidy[~tidy["is_ni_total"]]
    return _select(tidy, motivation, measure)


def get_hate_crime_ni_totals(motivation: str | None = None, measure: str | None = None) -> pd.DataFrame:
    """Get the Northern Ireland totals on their own.

    Read from the Local Government District cube, which carries all six
    statistics (incidents and crimes for each motivation); every cube's
    Northern Ireland row holds the same figures.

    Args:
        motivation: ``sexual_orientation``, ``racist`` or ``sectarian``; ``None``
            returns all three.
        measure: ``crimes`` or ``incidents``; ``None`` returns both.

    Returns:
        Tidy DataFrame with the columns in :data:`OUTPUT_COLUMNS`, one row per
        motivation, measure and financial year, with ``geography_level`` of
        ``northern_ireland``.

    Raises:
        ValueError: If ``motivation`` or ``measure`` is not recognised.
        PSNIDataNotFoundError: If the cube lacks an expected column.
        PSNIValidationError: If the cube holds an unknown statistic or period.

    Example:
        >>> ni = get_hate_crime_ni_totals(motivation="racist", measure="crimes")
        >>> int(ni.loc[ni["period"] == "2025/26", "value"].iloc[0])
        1507
    """
    _check_choice(motivation, MOTIVATIONS, "motivation")
    _check_choice(measure, MEASURES, "measure")
    tidy = tidy_cube("lgd", read_dataset(GEOGRAPHIES["lgd"].cube))
    totals = tidy[tidy["is_ni_total"]].copy()
    totals["geography_level"] = _NI_LEVEL
    return _select(totals, motivation, measure)


def get_unallocated(geography: str = "assembly_area") -> pd.DataFrame:
    """Get the crimes recorded in Northern Ireland but not placed in an area.

    For each motivation, measure and year this is the Northern Ireland total
    minus the sum of the areas. It is zero for the LGD, DEA and ward cubes and
    up to 9 crimes a year for the Assembly Area, Health Trust and urban/rural
    cubes.

    Args:
        geography: Short geography name (see :func:`list_geographies`).

    Returns:
        DataFrame with columns ``motivation``, ``measure``, ``period``,
        ``year``, ``ni_total``, ``allocated`` and ``unallocated``. Rows where
        the source has no count are left out.

    Raises:
        ValueError: If ``geography`` is not recognised.
        PSNIValidationError: If the areas add up to more than the total, which
            would mean the frame double counts.

    Example:
        >>> gap = get_unallocated("lgd")
        >>> int(gap["unallocated"].abs().max())
        0
    """
    spec = _check_geography(geography)
    tidy = tidy_cube(geography, read_dataset(spec.cube))
    key = ["motivation", "measure", "period", "year"]
    total = tidy[tidy["is_ni_total"]].set_index(key)["value"].rename("ni_total")
    allocated = tidy[~tidy["is_ni_total"]].groupby(key)["value"].sum(min_count=1).rename("allocated")
    gap = pd.concat([total, allocated], axis=1).dropna().reset_index()
    gap["unallocated"] = gap["ni_total"] - gap["allocated"]
    over = gap[gap["unallocated"] < 0]
    if not over.empty:
        raise PSNIValidationError(
            f"PxStat cube {spec.cube}: areas sum to more than Northern Ireland in {len(over)} row(s), "
            f"first {over.iloc[0][key].to_dict()}"
        )
    return gap.sort_values(key).reset_index(drop=True)


def validate_hate_crime(df: pd.DataFrame) -> bool:
    """Validate a frame returned by this module.

    Args:
        df: Frame from :func:`get_latest_hate_crime`,
            :func:`get_hate_crime_ni_totals` or :func:`tidy_cube`.

    Returns:
        ``True`` when the frame passes.

    Raises:
        PSNIValidationError: If the frame is empty, lacks a column, has a
            negative count, an unknown motivation or measure, a duplicated
            ``(geography, motivation, measure, period)`` row, or only ``NaN``
            counts.

    Example:
        >>> raw = pd.DataFrame(
        ...     {
        ...         "STATISTIC": ["allraccrm"],
        ...         "TLIST(A1)": ["2025/26"],
        ...         "LGD2014": ["N09000003"],
        ...         "Local Government District": ["Belfast"],
        ...         "VALUE": [300.0],
        ...     }
        ... )
        >>> validate_hate_crime(tidy_cube("lgd", raw))
        True
    """
    if df.empty:
        raise PSNIValidationError("Hate crime frame is empty")
    missing = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing:
        raise PSNIValidationError(f"Hate crime frame lacks column(s) {missing}")
    if (df["value"].dropna() < 0).any():
        raise PSNIValidationError("Hate crime frame has negative counts")
    if df["value"].isna().all():
        raise PSNIValidationError("Hate crime frame has no counts")
    bad_motivation = sorted(set(df["motivation"]) - set(MOTIVATIONS))
    bad_measure = sorted(set(df["measure"]) - set(MEASURES))
    if bad_motivation or bad_measure:
        raise PSNIValidationError(f"Unknown motivation(s) {bad_motivation} or measure(s) {bad_measure}")
    key = ["geography_level", "geography_code", "motivation", "measure", "period"]
    if df.duplicated(key).any():
        raise PSNIValidationError("Hate crime frame has duplicated (geography, motivation, measure, period) rows")
    return True
