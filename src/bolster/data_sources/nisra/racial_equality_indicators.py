"""NISRA Racial Equality Indicators Data Source.

Annual indicators monitoring the Northern Ireland Racial Equality Strategy
2015-2025: attitudes to minority ethnic communities, belonging, school
outcomes by ethnic group, public appointments and police-recorded racist
incidents and crimes. Each indicator is a separate PxStat cube; this module
reads them through :func:`bolster.data_sources.nisra.pxstat.read_dataset` and
reshapes every one into the same tidy long format.

Published as: Northern Ireland Racial Equality Indicators Dashboard.

Data Source:
    The NISRA PxStat API (https://data.nisra.gov.uk/). The dashboard is
    published by The Executive Office and NISRA at
    https://www.executiveoffice-ni.gov.uk/articles/racial-equality-indicators.

    PxStat matrices used (see :data:`INDICATORS` for the short name of each):
    ``ACCMEPREI``, ``BELNGHREI``, ``BELNIREI``, ``CREDSEREI``, ``CULRICREI``,
    ``CULTIRTRREI``, ``DESTREI``, ``LEAVQUAREI``, ``MEGPALREI``,
    ``MEGPUBLIREI``, ``NOQUAREI``, ``ORGPUBLIREI``, ``PREJUDREI``,
    ``PUBAPPREI``, ``PUBBODREI``, ``RACEBULLREI``, ``RACEREI``,
    ``RACPREJREI``, ``SOCMEGREI``.

Update Frequency: Annual (the cubes are refreshed together, in October)

Geographic Coverage: Northern Ireland

Reference Period: Calendar years, academic years or financial years depending
    on the indicator (see the ``period`` column); each indicator's own
    coverage differs (for example public appointments cover three financial
    years, survey indicators twelve calendar years).

Note:
    The survey indicators (attitudes, belonging) are percentages from the
    Northern Ireland Life and Times and Young Life and Times surveys and carry
    sampling error that the cubes do not publish; the Life and Times survey
    moved from in-person to web and telephone interviewing in 2020, so
    comparisons spanning 2020 mix modes. ``value`` is ``NaN`` where the source
    suppresses a cell.

    Racist incidents and crimes (``racist_incidents_crimes``) are police
    recorded counts, a different kind of measure from the survey percentages;
    recorded counts move with reporting and recording practice, so the two
    should not be combined into one series. Hate-motivated crime more widely
    (all motivations, with area breakdowns) is held in the separate ``HATE*``
    PxStat cubes; their Northern Ireland racist-motivation rows equal the
    ``racist_incidents_crimes`` counts here.

Example:
    >>> from bolster.data_sources.nisra import racial_equality_indicators as rei
    >>> df = rei.get_latest_racial_equality_indicators("prejudice")
    >>> sorted(df.columns.tolist())[:4]
    ['category', 'category_code', 'cube', 'group']
"""

import logging
import re
from typing import NamedTuple

import pandas as pd

from ._base import NISRADataNotFoundError, NISRAValidationError
from .pxstat import read_dataset

logger = logging.getLogger(__name__)

_PERIOD_COLUMN = "TLIST(A1)"
_STATISTIC_COLUMN = "STATISTIC"
_UNIT_COLUMN = "UNIT"
_VALUE_COLUMN = "VALUE"
# The label column for the statistic is called either of these, by cube.
_MEASURE_COLUMNS = ("Statistic Label", "Statistics")

#: Columns of the tidy frame, in order.
OUTPUT_COLUMNS = [
    "indicator",
    "cube",
    "statistic",
    "measure",
    "period",
    "year",
    "group_code",
    "group",
    "category_code",
    "category",
    "unit",
    "value",
]


class Indicator(NamedTuple):
    """How one PxStat cube maps onto the tidy frame.

    ``group`` is the ``(code column, label column)`` of the dimension naming who
    a figure describes (an equality group, an ethnic group or a minority
    community); ``category`` is the other breakdown the cube carries (an
    acceptance setting, a school-leaver destination, a public-life role or an
    application type). Either is ``None`` when the cube has no such dimension.
    """

    cube: str
    title: str
    group: tuple[str, str] | None = None
    category: tuple[str, str] | None = None


_EQUALITY_GROUP = ("EQGRP", "Equality group")
_ETHNIC_GROUP = ("MEG", "Ethnic group")

#: Short indicator name -> cube definition.
INDICATORS: dict[str, Indicator] = {
    "prejudice": Indicator(
        "PREJUDREI", "Self-reported prejudice against minority ethnic communities", group=_EQUALITY_GROUP
    ),
    "prejudice_increase": Indicator(
        "RACPREJREI",
        "More racial prejudice against minority ethnic communities than 5 years ago",
        group=_EQUALITY_GROUP,
    ),
    "acceptance": Indicator(
        "ACCMEPREI",
        "Acceptance of minority ethnic people",
        group=("MEG", "Minority ethnic group"),
        category=("ACCEPT", "Acceptance"),
    ),
    "culture_richness": Indicator(
        "CULRICREI",
        "Minority ethnic culture adds to the richness and diversity of Northern Ireland",
        group=_EQUALITY_GROUP,
    ),
    "traveller_culture_respect": Indicator(
        "CULTIRTRREI", "The culture of Irish Travellers is more respected than it once was", group=_EQUALITY_GROUP
    ),
    "friends": Indicator(
        "MEGPALREI",
        "People who have friends from minority ethnic communities",
        group=("FRIEND", "Minority ethnic community"),
    ),
    "public_life_participation": Indicator(
        "MEGPUBLIREI",
        "People who think minority ethnic people participate in public life",
        category=("RIS", "Role in public life"),
    ),
    "public_life_encouragement": Indicator(
        "ORGPUBLIREI",
        "People who believe organisations and leaders should encourage minority ethnic participation in public life",
        group=_EQUALITY_GROUP,
    ),
    "public_bodies_needs": Indicator(
        "PUBBODREI",
        "Importance of public bodies taking into account the needs of minority ethnic communities",
        group=_EQUALITY_GROUP,
    ),
    "belonging_neighbourhood": Indicator(
        "BELNGHREI", "People who feel they belong to their neighbourhood", group=_EQUALITY_GROUP
    ),
    "belonging_ni": Indicator("BELNIREI", "People who feel they belong to Northern Ireland", group=_EQUALITY_GROUP),
    "school_diversity": Indicator(
        "CREDSEREI",
        "Young people (aged 16) indicating schools are covering issues of diversity",
        group=_EQUALITY_GROUP,
    ),
    "racist_bullying": Indicator(
        "RACEBULLREI",
        "Young people who have witnessed racist bullying or harassment in their school",
        group=_EQUALITY_GROUP,
    ),
    "socialising": Indicator(
        "SOCMEGREI",
        "Young people who socialise or play sport with people from a different ethnic background",
        group=_EQUALITY_GROUP,
    ),
    "school_destinations": Indicator(
        "DESTREI", "Destination of school leavers", group=_ETHNIC_GROUP, category=("DEST", "Destination")
    ),
    "school_leavers_gcse": Indicator("LEAVQUAREI", "School leavers with 5 GCSEs at grades A*-C", group=_ETHNIC_GROUP),
    "school_leavers_no_qualifications": Indicator(
        "NOQUAREI", "Pupils leaving school with no qualifications", group=_ETHNIC_GROUP
    ),
    "public_appointments": Indicator(
        "PUBAPPREI", "Applications for public appointments", category=("APPLICATION", "Applications")
    ),
    "racist_incidents_crimes": Indicator(
        "RACEREI", "Racist incidents and crimes recorded by the police", group=("NI", "Northern Ireland")
    ),
}


def _clean_label(value: object) -> str:
    """Collapse runs of whitespace in a source label."""
    return re.sub(r"\s+", " ", str(value)).strip()


def _dimension(df: pd.DataFrame, columns: tuple[str, str] | None, cube: str) -> tuple[pd.Series, pd.Series]:
    """Return ``(code, label)`` series for a dimension, or empty values when the cube has none."""
    if columns is None:
        empty = pd.Series([pd.NA] * len(df), index=df.index, dtype="object")
        return empty, empty
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise NISRADataNotFoundError(
            f"PxStat cube {cube} has no column(s) {missing}; its columns are {list(df.columns)}"
        )
    return df[columns[0]].astype(str), df[columns[1]].map(_clean_label)


def tidy_cube(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Reshape one raw PxStat cube into the tidy long format.

    Args:
        name: Short indicator name, a key of :data:`INDICATORS`.
        df: Raw frame from :func:`bolster.data_sources.nisra.pxstat.read_dataset`
            for that indicator's cube.

    Returns:
        DataFrame with the columns in :data:`OUTPUT_COLUMNS`.

    Raises:
        ValueError: If ``name`` is not an indicator.
        NISRADataNotFoundError: If the cube lacks a column the indicator needs.

    Example:
        >>> raw = pd.DataFrame(
        ...     {
        ...         "STATISTIC": ["RACEINREI"],
        ...         "Statistic Label": ["All incidents with a racist motivation"],
        ...         "TLIST(A1)": ["2013/14"],
        ...         "NI": ["N92000002"],
        ...         "Northern Ireland": ["Northern Ireland"],
        ...         "UNIT": ["Number"],
        ...         "VALUE": [1000],
        ...     }
        ... )
        >>> tidy_cube("racist_incidents_crimes", raw)["year"].tolist()
        [2013]
    """
    if name not in INDICATORS:
        raise ValueError(f"indicator must be one of {sorted(INDICATORS)}, got {name!r}")
    spec = INDICATORS[name]

    measure_column = next((c for c in _MEASURE_COLUMNS if c in df.columns), None)
    required = [_PERIOD_COLUMN, _STATISTIC_COLUMN, _UNIT_COLUMN, _VALUE_COLUMN]
    missing = [c for c in required if c not in df.columns]
    if missing or measure_column is None:
        raise NISRADataNotFoundError(
            f"PxStat cube {spec.cube} lacks expected column(s) {missing or list(_MEASURE_COLUMNS)}; "
            f"its columns are {list(df.columns)}"
        )

    group_code, group = _dimension(df, spec.group, spec.cube)
    category_code, category = _dimension(df, spec.category, spec.cube)
    period = df[_PERIOD_COLUMN].astype(str)

    tidy = pd.DataFrame(
        {
            "indicator": name,
            "cube": spec.cube,
            "statistic": df[_STATISTIC_COLUMN],
            "measure": df[measure_column].map(_clean_label),
            "period": period,
            "year": period.str.extract(r"^(\d{4})", expand=False).astype("Int64"),
            "group_code": group_code,
            "group": group,
            "category_code": category_code,
            "category": category,
            "unit": df[_UNIT_COLUMN],
            "value": pd.to_numeric(df[_VALUE_COLUMN], errors="coerce"),
        }
    )
    return tidy[OUTPUT_COLUMNS].reset_index(drop=True)


def list_indicators() -> pd.DataFrame:
    """List the available indicators.

    Returns:
        DataFrame with columns ``indicator``, ``cube`` and ``title``.

    Example:
        >>> "prejudice" in set(list_indicators()["indicator"])
        True
    """
    return pd.DataFrame(
        [{"indicator": name, "cube": spec.cube, "title": spec.title} for name, spec in INDICATORS.items()]
    )


def get_latest_racial_equality_indicators(indicator: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get racial equality indicators for Northern Ireland.

    Note:
        ``force_refresh`` is accepted for API compatibility but is ignored: the
        PxStat API is called directly with no local cache layer.

    Args:
        indicator: Short indicator name (see :func:`list_indicators`). ``None``
            returns every indicator, which makes one PxStat request per cube.
        force_refresh: Ignored. Retained for API compatibility.

    Returns:
        Tidy DataFrame with the columns in :data:`OUTPUT_COLUMNS`:

        - ``indicator`` / ``cube``: short name and PxStat matrix code
        - ``statistic`` / ``measure``: statistic code and its label (a cube may
          carry both a count and a percentage)
        - ``period`` / ``year``: the period label and its starting year
        - ``group_code`` / ``group``: who the figure describes (equality group,
          ethnic group or minority community); ``NaN`` if the cube has none
        - ``category_code`` / ``category``: the other breakdown; ``NaN`` if none
        - ``unit`` / ``value``: ``%`` or ``Number``, and the figure

    Raises:
        ValueError: If ``indicator`` is not a known indicator.
        NISRADataNotFoundError: If a cube's columns are not the expected ones.
        bolster.data_sources.nisra.pxstat.PxStatError: If PxStat returns an error.

    Example:
        >>> df = get_latest_racial_equality_indicators("racist_incidents_crimes")
        >>> sorted(df["statistic"].unique())
        ['RACECRREI', 'RACEINREI']
    """
    names = list(INDICATORS) if indicator is None else [indicator]
    for name in names:
        if name not in INDICATORS:
            raise ValueError(f"indicator must be one of {sorted(INDICATORS)}, got {name!r}")

    frames = [tidy_cube(name, read_dataset(INDICATORS[name].cube)) for name in names]
    return pd.concat(frames, ignore_index=True)


_SERIES_KEY = ["indicator", "statistic", "group_code", "category_code"]


def validate_racial_equality_data(df: pd.DataFrame) -> bool:
    """Validate a frame from :func:`get_latest_racial_equality_indicators`.

    Checks that required columns are present, the frame is not empty, no value
    is negative, percentages do not exceed 100, no observation appears twice,
    every series of an indicator has an observation for every period of that
    indicator, and each indicator's years are consecutive.

    Args:
        df: DataFrame from :func:`get_latest_racial_equality_indicators`.

    Returns:
        True if validation passes.

    Raises:
        NISRAValidationError: If any check fails.

    Example:
        >>> try:
        ...     validate_racial_equality_data(pd.DataFrame(columns=OUTPUT_COLUMNS))
        ... except NISRAValidationError as error:
        ...     print(error)
        DataFrame is empty
    """
    missing = set(OUTPUT_COLUMNS) - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")
    if df.empty:
        raise NISRAValidationError("DataFrame is empty")

    values = df["value"].dropna()
    if (values < 0).any():
        raise NISRAValidationError("Negative values found")
    over = df[(df["unit"] == "%") & (df["value"] > 100)]
    if not over.empty:
        raise NISRAValidationError(f"Percentages above 100 found for {sorted(over['indicator'].unique())}")

    key = [*_SERIES_KEY, "period"]
    duplicated = df.duplicated(subset=key, keep=False)
    if duplicated.any():
        raise NISRAValidationError(f"Duplicate observations for {sorted(df[duplicated]['indicator'].unique())}")

    for name, frame in df.groupby("indicator"):
        periods = frame["period"].nunique()
        per_series = frame.groupby(_SERIES_KEY, dropna=False)["period"].nunique()
        short = per_series[per_series != periods]
        if not short.empty:
            raise NISRAValidationError(
                f"Indicator {name!r}: {len(short)} series lack observations for some of its {periods} periods"
            )
        years = sorted(frame["year"].dropna().unique())
        if years and years != list(range(years[0], years[-1] + 1)):
            raise NISRAValidationError(f"Indicator {name!r}: years are not consecutive: {years}")

    logger.info("Validation passed: %d rows across %d indicators", len(df), df["indicator"].nunique())
    return True


_TOTAL_LEAVERS = "Total leavers"
_APPLICATIONS_TOTAL = "Total applications"
_APPLICATIONS_KNOWN = "Total applications where ethnicity is known"
_APPLICATIONS_MINORITY = "Applications from minority ethnic people"


def _require_labels(frame: pd.DataFrame, column: str, labels: list[str], indicator: str) -> None:
    absent = [label for label in labels if label not in set(frame[column])]
    if absent:
        raise NISRAValidationError(
            f"Indicator {indicator!r} has no {column} {absent}; found {sorted(set(frame[column]))}"
        )


def validate_racial_equality_consistency(df: pd.DataFrame) -> bool:
    """Validate the arithmetic relationships within and between related cubes.

    For the indicators present in ``df``:

    - ``school_destinations``: the destination counts add up to total leavers
      for every period and group, and the destination percentages add up to
      100 (to within rounding).
    - ``racist_incidents_crimes``: recorded crimes never exceed recorded
      incidents in a period.
    - ``public_appointments``: applications from minority ethnic people never
      exceed applications where ethnicity is known, which never exceed all
      applications.

    Args:
        df: DataFrame from :func:`get_latest_racial_equality_indicators`.

    Returns:
        True if every check passes.

    Raises:
        NISRAValidationError: If a relationship does not hold, or a category the
            check needs is missing from an indicator.

    Example:
        >>> frame = pd.DataFrame(
        ...     {
        ...         "indicator": "racist_incidents_crimes",
        ...         "statistic": ["RACEINREI", "RACECRREI"],
        ...         "period": "2025/26",
        ...         "unit": "Number",
        ...         "value": [10.0, 20.0],
        ...     }
        ... )
        >>> try:
        ...     validate_racial_equality_consistency(frame)
        ... except NISRAValidationError as error:
        ...     print(error)
        Recorded crimes exceed recorded incidents in: ['2025/26']
    """
    if "indicator" not in df.columns:
        raise NISRAValidationError("Missing required column: 'indicator'")

    destinations = df[df["indicator"] == "school_destinations"]
    if not destinations.empty:
        _require_labels(destinations, "category", [_TOTAL_LEAVERS], "school_destinations")
        counts = destinations[destinations["unit"] == "Number"].pivot_table(
            index=["period", "group"], columns="category", values="value", aggfunc="sum"
        )
        parts = [c for c in counts.columns if c != _TOTAL_LEAVERS]
        gap = (counts[parts].sum(axis=1) - counts[_TOTAL_LEAVERS]).abs()
        if (gap > 0.5).any():
            raise NISRAValidationError(
                f"School destinations do not add up to total leavers for: {list(gap[gap > 0.5].index)}"
            )
        shares = destinations[destinations["unit"] == "%"].pivot_table(
            index=["period", "group"], columns="category", values="value", aggfunc="sum"
        )
        off = (shares[parts].sum(axis=1) - 100).abs()
        if (off > 0.5).any():
            raise NISRAValidationError(
                f"School destination percentages do not add up to 100 for: {list(off[off > 0.5].index)}"
            )

    police = df[df["indicator"] == "racist_incidents_crimes"]
    if not police.empty:
        _require_labels(police, "statistic", ["RACEINREI", "RACECRREI"], "racist_incidents_crimes")
        recorded = police.pivot_table(index="period", columns="statistic", values="value", aggfunc="sum")
        over = recorded[recorded["RACECRREI"] > recorded["RACEINREI"]]
        if not over.empty:
            raise NISRAValidationError(f"Recorded crimes exceed recorded incidents in: {list(over.index)}")

    appointments = df[(df["indicator"] == "public_appointments") & (df["unit"] == "Number")]
    if not appointments.empty:
        labels = [_APPLICATIONS_TOTAL, _APPLICATIONS_KNOWN, _APPLICATIONS_MINORITY]
        _require_labels(appointments, "category", labels, "public_appointments")
        applications = appointments.pivot_table(index="period", columns="category", values="value", aggfunc="sum")
        nested = (applications[_APPLICATIONS_MINORITY] <= applications[_APPLICATIONS_KNOWN]) & (
            applications[_APPLICATIONS_KNOWN] <= applications[_APPLICATIONS_TOTAL]
        )
        if not nested.all():
            raise NISRAValidationError(
                f"Public appointment applications are not nested in: {list(nested[~nested].index)}"
            )

    logger.info("Consistency validation passed")
    return True
