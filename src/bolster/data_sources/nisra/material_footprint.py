"""NISRA Northern Ireland Material Footprint Data Source.

Published as: Northern Ireland's Material Footprint; Material Footprint in Northern Ireland.

The material footprint is a *consumption-based* measure of the primary raw materials
(domestic and imported, wherever extracted) needed to meet the demand for goods and
services consumed by Northern Ireland residents. It is therefore not comparable with
territorial measures such as greenhouse gas emissions or waste arisings produced inside
Northern Ireland.

The estimates are produced by the University of Leeds for Defra and the Department for the
Economy, and published by NISRA as a data-visualisation report with two embedded figures:

- **Figure 1** — the total and four material groups (biomass, metal ores, fossil fuels and
  non-metallic minerals) in million tonnes (Mt), annually from 2001.
- **Figure 2** — mid-year population and material footprint per capita in tonnes per person.

Values are published to one decimal place, so the four groups can differ from the total by
up to 0.1 Mt in a given year (the validators allow 0.25 Mt, the most that rounding five
values to 0.1 can produce).

Each edition re-estimates earlier years and its tables can change name and unit between
editions (an earlier edition carried unrounded kilotonnes and called the metal ores group
``ore_materials``). The module finds the report through the GOV.UK release for the *latest*
edition only, finds both figures by title, maps ``ore_materials`` to ``metal_ores``, and raises
if the latest edition has no data page or its totals look like kilotonnes. It never returns an
older edition's data in place of the latest.

Original data source:
    https://www.gov.uk/government/statistics/northern-irelands-material-footprint-2001-to-2023

Update Frequency: Annual (the latest edition covers 2001 to 2023)
Geographic Coverage: Northern Ireland

Example:
    >>> from bolster.data_sources.nisra import material_footprint
    >>> df = material_footprint.get_latest_data()
    >>> {"year", "material", "measure", "value"}.issubset(df.columns)
    True
    >>> sorted(df["measure"].unique())
    ['material_footprint_mt', 'per_capita_tonnes']
"""

import logging
import re

import pandas as pd

from bolster.utils.embedded_downloads import EmbeddedTable, coerce_numeric, read_tables
from bolster.utils.web import session

from ._base import NISRADataNotFoundError, NISRAValidationError

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://www.gov.uk/api/search.json"
CONTENT_API_URL = "https://www.gov.uk/api/content"
DATAVIS_HOST = "datavis.nisra.gov.uk"

MATERIALS = ("biomass", "metal_ores", "fossil_fuels", "non_metallic_minerals")
"""The four material groups, in the order the source publishes them."""

MEASURE_FOOTPRINT = "material_footprint_mt"
MEASURE_PER_CAPITA = "per_capita_tonnes"

SUM_TOLERANCE_MT = 0.25
"""Largest difference between the four groups and the total: five values each rounded to 0.1 Mt."""

PER_CAPITA_TOLERANCE_TONNES = 0.08
"""Largest difference between total x 1e6 / population and published per capita: total rounded to
0.1 Mt (0.05 / 1.9 million people = 0.03 t) plus per capita rounded to 0.1 t (0.05 t)."""

_PLAUSIBLE_TOTAL_MT = (5.0, 200.0)
"""Range outside which a total cannot be million tonnes (Northern Ireland's has been 28 to 42)."""

_COLUMN_ALIASES = {"ore_materials": "metal_ores"}

_FOOTPRINT_TITLE_RE = re.compile(r"material footprint trends.*by material group", re.IGNORECASE)
_PER_CAPITA_TITLE_RE = re.compile(r"material footprint per capita", re.IGNORECASE)
_POPULATION_COLUMN = "mid_year_population_estimate"
_PER_CAPITA_COLUMN = "material_footprint_per_capita_tonnes"


def _is_northern_ireland_footprint(title: str) -> bool:
    text = title.lower()
    return "material footprint" in text and "northern ireland" in text


def get_latest_publication_url(force_refresh: bool = False) -> str:
    """Find the data-visualisation page of the latest Northern Ireland material footprint edition.

    GOV.UK's search API lists the editions (their slugs change between editions); the newest is
    taken and its content record's attachments are searched for the ``datavis.nisra.gov.uk`` page.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Absolute URL of the datavis report.

    Raises:
        NISRADataNotFoundError: If no edition is found, or the latest edition has no datavis page.
            An older edition is never substituted.

    Example:
        >>> get_latest_publication_url().startswith("https://datavis.nisra.gov.uk/")
        True
    """
    response = session.get(
        SEARCH_API_URL,
        params={"q": "northern ireland material footprint", "count": 50, "fields": "title,link,public_timestamp"},
        timeout=30,
        force_refresh=force_refresh,
    )
    response.raise_for_status()

    editions = [r for r in response.json().get("results", []) if _is_northern_ireland_footprint(r.get("title", ""))]
    if not editions:
        raise NISRADataNotFoundError("No Northern Ireland material footprint release found on GOV.UK")
    latest = max(editions, key=lambda r: r.get("public_timestamp", ""))

    content = session.get(f"{CONTENT_API_URL}{latest['link']}", timeout=30, force_refresh=force_refresh)
    content.raise_for_status()
    for attachment in content.json().get("details", {}).get("attachments", []):
        url = attachment.get("url", "")
        if DATAVIS_HOST in url:
            logger.info("Resolved latest material footprint edition %r to %s", latest["title"], url)
            return url

    raise NISRADataNotFoundError(
        f"The latest GOV.UK material footprint release ({latest['title']!r}, {latest['link']}) has no "
        f"{DATAVIS_HOST} data page attachment; an earlier edition is not substituted"
    )


def _find_table(tables: dict[str, EmbeddedTable], pattern: re.Pattern[str], what: str) -> EmbeddedTable:
    """Return the one embedded table whose title matches, never choosing by position."""
    matches = [t for t in tables.values() if pattern.search(t.title)]
    if not matches:
        raise NISRADataNotFoundError(
            f"No {what} table on the material footprint page; titles found: {[t.title for t in tables.values()]}"
        )
    if len(matches) > 1:
        raise NISRAValidationError(f"{len(matches)} tables match {what!r}: {[t.title for t in matches]}")
    return matches[0]


def _numeric_frame(table: EmbeddedTable, columns: list[str], what: str) -> pd.DataFrame:
    """Select, rename and coerce a figure's columns; raise on missing columns or unreadable cells."""
    frame = table.data.rename(columns=_COLUMN_ALIASES).dropna(how="all")
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise NISRADataNotFoundError(f"{what} table is missing columns {missing}; columns found: {list(frame.columns)}")
    frame = frame[columns].apply(coerce_numeric)
    if frame.isna().any().any():
        bad = frame.columns[frame.isna().any()].tolist()
        raise NISRAValidationError(f"{what} table has blank or unreadable values in {bad}")
    frame["year"] = frame["year"].astype(int)
    return frame.reset_index(drop=True)


def _read_figures(force_refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    url = get_latest_publication_url(force_refresh=force_refresh)
    tables = read_tables(session.get(url, timeout=90, force_refresh=force_refresh).text)

    footprint = _numeric_frame(
        _find_table(tables, _FOOTPRINT_TITLE_RE, "material footprint trends"),
        ["year", *MATERIALS, "total"],
        "Material footprint trends",
    )
    per_capita = _numeric_frame(
        _find_table(tables, _PER_CAPITA_TITLE_RE, "material footprint per capita"),
        ["year", _POPULATION_COLUMN, _PER_CAPITA_COLUMN],
        "Material footprint per capita",
    )
    return footprint, per_capita


def _check_million_tonnes(totals: pd.Series) -> None:
    low, high = _PLAUSIBLE_TOTAL_MT
    if ((totals < low) | (totals > high)).any():
        raise NISRAValidationError(
            f"Material footprint totals span {totals.min():g} to {totals.max():g}, which cannot be million "
            "tonnes (the source can publish kilotonnes); refusing to guess the unit"
        )


def get_material_footprint(force_refresh: bool = False) -> pd.DataFrame:
    """Material footprint by material group and in total, in million tonnes.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Long-format DataFrame with columns ``year`` (int), ``material`` (``biomass``, ``metal_ores``,
        ``fossil_fuels``, ``non_metallic_minerals`` or ``total``), ``measure``
        (always ``material_footprint_mt``) and ``value`` (million tonnes).

    Raises:
        NISRADataNotFoundError: If the page, a figure or a column cannot be found.
        NISRAValidationError: If values are unreadable or not plausibly million tonnes.

    Example:
        >>> df = get_material_footprint()
        >>> sorted(df["material"].unique())
        ['biomass', 'fossil_fuels', 'metal_ores', 'non_metallic_minerals', 'total']
    """
    footprint, _ = _read_figures(force_refresh)
    _check_million_tonnes(footprint["total"])
    return _footprint_long(footprint)


def _footprint_long(footprint: pd.DataFrame) -> pd.DataFrame:
    long = footprint.melt(id_vars="year", var_name="material", value_name="value")
    long["measure"] = MEASURE_FOOTPRINT
    long["material"] = pd.Categorical(long["material"], categories=[*MATERIALS, "total"], ordered=True)
    long = long.sort_values(["year", "material"]).reset_index(drop=True)
    long["material"] = long["material"].astype(str)
    return long[["year", "material", "measure", "value"]]


def get_per_capita(force_refresh: bool = False) -> pd.DataFrame:
    """Mid-year population and material footprint per capita, by year.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with columns ``year`` (int), ``population`` (people, the NISRA mid-year estimate
        used as the denominator) and ``per_capita_tonnes`` (tonnes per person).

    Raises:
        NISRADataNotFoundError: If the page, the figure or a column cannot be found.
        NISRAValidationError: If values are blank or unreadable.

    Example:
        >>> df = get_per_capita()
        >>> list(df.columns)
        ['year', 'population', 'per_capita_tonnes']
    """
    _, per_capita = _read_figures(force_refresh)
    return _per_capita_frame(per_capita)


def _per_capita_frame(per_capita: pd.DataFrame) -> pd.DataFrame:
    frame = per_capita.rename(columns={_POPULATION_COLUMN: "population", _PER_CAPITA_COLUMN: "per_capita_tonnes"})
    frame["population"] = frame["population"].astype(int)
    return frame[["year", "population", "per_capita_tonnes"]]


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Material footprint and per-capita footprint in one tidy table.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        Long-format DataFrame with columns ``year``, ``material``, ``measure`` and ``value``.
        ``measure`` is ``material_footprint_mt`` (million tonnes) for the four material groups and
        the total, and ``per_capita_tonnes`` (tonnes per person, ``material`` = ``total``).

    Raises:
        NISRADataNotFoundError: If the latest edition, its page or a figure cannot be found.
        NISRAValidationError: If the groups do not add to the total, per-capita values do not
            follow from total and population, years are not contiguous, or units look wrong.

    Example:
        >>> df = get_latest_data()
        >>> int(df["year"].min()), bool(df["year"].max() >= 2023)
        (2001, True)
    """
    footprint, per_capita = _read_figures(force_refresh)
    _check_million_tonnes(footprint["total"])
    long = _footprint_long(footprint)
    per_capita_frame = _per_capita_frame(per_capita)
    validate_data(long)
    validate_per_capita(long, per_capita_frame)

    per_capita_long = pd.DataFrame(
        {
            "year": per_capita_frame["year"],
            "material": "total",
            "measure": MEASURE_PER_CAPITA,
            "value": per_capita_frame["per_capita_tonnes"],
        }
    )
    return pd.concat([long, per_capita_long], ignore_index=True)


def validate_data(df: pd.DataFrame) -> bool:
    """Validate a long-format material footprint table.

    Checks the required columns, that years are unique and contiguous for every material, that
    values are positive, that totals are plausibly million tonnes, and that the four groups add to
    the total within :data:`SUM_TOLERANCE_MT` in every year.

    Args:
        df: Output of :func:`get_material_footprint` (rows of other measures are ignored).

    Returns:
        True if valid.

    Raises:
        NISRAValidationError: If any check fails.

    Example:
        >>> frame = pd.DataFrame(
        ...     [(2020, m, MEASURE_FOOTPRINT, v) for m, v in
        ...      [("biomass", 9.0), ("metal_ores", 2.0), ("fossil_fuels", 8.0), ("non_metallic_minerals", 10.0), ("total", 29.0)]],
        ...     columns=["year", "material", "measure", "value"],
        ... )
        >>> validate_data(frame)
        True
    """
    missing = {"year", "material", "measure", "value"} - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing columns: {sorted(missing)}")
    data = df[df["measure"] == MEASURE_FOOTPRINT]
    if data.empty:
        raise NISRAValidationError("No material footprint rows to validate")
    if (data["value"] <= 0).any():
        raise NISRAValidationError("Material footprint values must be positive")

    for material, group in data.groupby("material"):
        years = sorted(group["year"])
        if years != list(range(years[0], years[-1] + 1)):
            raise NISRAValidationError(f"Years for {material!r} are not unique and contiguous: {years}")

    wide = data.pivot(index="year", columns="material", values="value")
    absent = [c for c in (*MATERIALS, "total") if c not in wide.columns]
    if absent:
        raise NISRAValidationError(f"Missing materials: {absent}")
    _check_million_tonnes(wide["total"])
    gap = (wide[list(MATERIALS)].sum(axis=1) - wide["total"]).abs()
    if (gap > SUM_TOLERANCE_MT).any():
        worst = gap.idxmax()
        raise NISRAValidationError(
            f"Material groups differ from the total by up to {gap.max():.2f} Mt (tolerance {SUM_TOLERANCE_MT}), "
            f"worst in {worst}"
        )
    return True


def validate_per_capita(footprint: pd.DataFrame, per_capita: pd.DataFrame) -> bool:
    """Validate that published per-capita values follow from the total and the population.

    Args:
        footprint: Long-format output of :func:`get_material_footprint`.
        per_capita: Output of :func:`get_per_capita`.

    Returns:
        True if valid.

    Raises:
        NISRAValidationError: If the years differ or any year's published per-capita value is further
            than :data:`PER_CAPITA_TOLERANCE_TONNES` from total x 1e6 / population.

    Example:
        >>> fp = pd.DataFrame({"year": [2020], "material": ["total"], "measure": [MEASURE_FOOTPRINT], "value": [30.0]})
        >>> pc = pd.DataFrame({"year": [2020], "population": [1_900_000], "per_capita_tonnes": [15.8]})
        >>> validate_per_capita(fp, pc)
        True
    """
    totals = footprint[(footprint["measure"] == MEASURE_FOOTPRINT) & (footprint["material"] == "total")]
    totals = totals.set_index("year")["value"]
    pc = per_capita.set_index("year")
    if set(totals.index) != set(pc.index):
        only = sorted(set(totals.index) ^ set(pc.index))
        raise NISRAValidationError(f"Footprint and per-capita years differ: {only}")
    implied = totals.loc[pc.index] * 1e6 / pc["population"]
    gap = (implied - pc["per_capita_tonnes"]).abs()
    if (gap > PER_CAPITA_TOLERANCE_TONNES).any():
        raise NISRAValidationError(
            f"Per-capita values differ from total / population by up to {gap.max():.3f} t "
            f"(tolerance {PER_CAPITA_TOLERANCE_TONNES}), worst in {gap.idxmax()}"
        )
    return True
