"""Adult and youth reoffending statistics for Northern Ireland.

Provides access to the Department of Justice NI annual bulletin on one-year
proven reoffending: of everyone given a non-custodial or diversionary disposal,
or released from custody, in a financial year (the *cohort*), the share who
committed a further offence within a year that was proven by a court outcome.

Published as: Adult and Youth Reoffending in Northern Ireland.

The accessibility-format ODS workbook carries twelve numbered worksheets. This
module reads four of them, each found by its title rather than its number:

- **Annual reoffending rates** - cohort size, number who reoffended and the
  rate for all offenders, adults and youths, for every cohort from 2010/11.
- **Age and gender** - the latest cohort by age band, split by gender.
- **Disposal** - the latest cohort by disposal group and individual disposal.
- **Baseline offence category** - the latest cohort by the category of the
  offence that placed the person in the cohort.

Data Source:
    **Publication Page**:
    https://www.justice-ni.gov.uk/publications/adult-and-youth-reoffending-northern-ireland-202324-cohort

    The workbook URL changes every year (folder and filename both vary), so
    the module resolves it by scraping the publication page for the ``Tables``
    ``.ods`` attachment. Publication slugs follow
    ``adult-and-youth-reoffending-northern-ireland-YYYYYY-cohort``. The
    bulletin is published about two and a half years after its cohort begins
    (the 2023/24 cohort appeared in November 2026) because a year of follow-up
    and the court-outcome lag must both elapse.

Update Frequency: Annual
Geographic Coverage: Northern Ireland
Reference Period: Cohorts 2010/11 - 2023/24 (financial years)

.. note::
    A rate is suppressed (``NaN``) wherever the cohort is smaller than 50; the
    counts are still published. Individual disposals do not sum to their group
    or to the overall total, because a person appears once per group (first
    instance only), so subtotal rows are kept in the disposal frame and must
    not be added to the individual rows.

Example:
    >>> from bolster.data_sources.justice import reoffending
    >>> df = reoffending.get_reoffending_rates()  # doctest: +SKIP
    >>> df[(df.group == "all") & (df.cohort == "2023/24")]  # doctest: +SKIP
        cohort  cohort_start group  cohort_size  reoffenders  rate_pct
    13  2023/24          2023   all        20887         3606      17.3
"""

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
from odf.opendocument import load as load_ods
from odf.table import Table

from bolster.utils.cache import CachedDownloader, bind_download_file
from bolster.utils.web import (
    LinkNotFoundError,
    academic_year_slug,
    find_academic_year_publication_link,
    make_absolute_url,
    scrape_file_links,
)

from ._base import _parse_value, _sheet_rows

logger = logging.getLogger(__name__)

BASE_URL = "https://www.justice-ni.gov.uk"
PUBLICATION_URL_TEMPLATE = f"{BASE_URL}/publications/adult-and-youth-reoffending-northern-ireland-{{slug}}-cohort"

# The cohort year trails publication by about two and a half years, so the walk back from
# today must be long enough to reach the newest published cohort in any month.
_LOOKBACK_YEARS = 6

# Worksheets are titled "Worksheet 8: Reoffending rate by disposal [note 1] [note 5]"
_WORKSHEET_TITLE_RE = re.compile(r"^Worksheet\s+(\d+)\s*:\s*(.*)$", re.IGNORECASE)

# Footnote markers in worksheet titles and labels, e.g. "[note 2]" or "[notes 1]"
_NOTE_REF_RE = re.compile(r"\s*\[notes?\s+\d+(?:\s*(?:,|and|&)\s*\d+)*\]", re.IGNORECASE)

# Financial year labels, e.g. "2023/24"
_COHORT_RE = re.compile(r"^(\d{4})/(\d{2})$")

# Column headers: "Total number who reoffended", "Number of adults in cohort",
# "Male one-year proven reoffending rate (%)", "One-year proven reoffending rate (%)"
_REOFFENDERS_RE = re.compile(r"^(?:total number|number of (?P<group>\w+)) who reoffended\b", re.IGNORECASE)
_COHORT_SIZE_RE = re.compile(r"^(?:total number|number of (?P<group>\w+)) in cohort\b", re.IGNORECASE)
_RATE_RE = re.compile(r"^(?:(?P<group>\w+) )?one-year proven reoffending rate\b", re.IGNORECASE)

_GROUPS = {
    "overall": "all",
    "adult": "adult",
    "adults": "adult",
    "youth": "youth",
    "youths": "youth",
    "male": "male",
    "males": "male",
    "female": "female",
    "females": "female",
}

# Worksheet titles (lower case, notes stripped) of the tables this module reads
_RATES_TITLE = "annual reoffending rates"
_AGE_GENDER_TITLE = "reoffending rate by age and gender"
_DISPOSAL_TITLE = "reoffending rate by disposal"
_OFFENCE_TITLE = "reoffending rate by baseline offence category"

# Rates are withheld where the denominator is below this size ("Percentage cannot be shown
# where denominator is less than 50")
_MIN_RATE_COHORT = 50

# Rates are published to one decimal place
_RATE_TOLERANCE_PP = 0.06

# Adult plus youth counts may exceed the overall count by this fraction (see validate_reoffending_rates)
_MAX_GROUP_OVERLAP = 0.001

# The bulletin is annual, so a long cache is safe
_CACHE_TTL_HOURS = 24 * 90

_downloader = CachedDownloader("doj_reoffending", timeout=60)


class ReoffendingDataError(Exception):
    """Base exception for reoffending data errors."""


class ReoffendingDataNotFoundError(ReoffendingDataError):
    """Raised when a publication, workbook or worksheet cannot be located."""


class ReoffendingValidationError(ReoffendingDataError):
    """Raised when parsed data fails validation."""


def cohort_label(start_year: int) -> str:
    """Format a cohort's starting year as the financial-year label DoJ uses.

    Example:
        >>> cohort_label(2023)
        '2023/24'
        >>> cohort_label(1999)
        '1999/00'
    """
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def _cohort_start(label: str) -> int:
    """Starting year of a cohort label such as ``"2023/24"``.

    Raises:
        ReoffendingDataError: If the label is not a financial year.

    Example:
        >>> _cohort_start("2010/11")
        2010
    """
    match = _COHORT_RE.match(label.strip())
    if not match:
        raise ReoffendingDataError(f"Unrecognised cohort label {label!r}")
    return int(match.group(1))


def _clean(text: str) -> str:
    r"""Strip footnote markers and surrounding whitespace (including non-breaking spaces).

    Example:
        >>> _clean("Reoffending rate by disposal [note 1] [note 5]")
        'Reoffending rate by disposal'
        >>> _clean("Reoffending rate by age and gender [notes 1] [note 2]")
        'Reoffending rate by age and gender'
        >>> _clean("Disposal group\xa0")
        'Disposal group'
    """
    return _NOTE_REF_RE.sub("", text).strip()


def _is_tables_workbook(href: str) -> bool:
    """Whether a link is the ``... - Tables.ods`` workbook (not an infographic or other file).

    Example:
        >>> _is_tables_workbook("/files/Adult%20and%20Youth%20Reoffending%20-%20Tables.ods")
        True
        >>> _is_tables_workbook("/files/infographic.pdf")
        False
    """
    return unquote(href).lower().endswith("tables.ods")


def get_data_file_url(cohort: int | None = None, force_refresh: bool = False) -> str:
    """Find the ODS workbook for a cohort.

    Args:
        cohort: Starting year of the cohort, e.g. ``2023`` for 2023/24. Defaults to the
            newest published cohort. A cohort that is not published raises rather than
            falling back to another one.
        force_refresh: Bypass the page cache.

    Returns:
        Absolute URL of the workbook.

    Raises:
        ReoffendingDataNotFoundError: If no publication or workbook can be found.
    """
    if cohort is None:
        try:
            href = find_academic_year_publication_link(
                PUBLICATION_URL_TEMPLATE,
                lambda _text, href: _is_tables_workbook(href),
                lookback_years=_LOOKBACK_YEARS,
                force_refresh=force_refresh,
            )
        except LinkNotFoundError as e:
            raise ReoffendingDataNotFoundError(f"No published reoffending workbook found: {e}") from e
        return make_absolute_url(href, BASE_URL)

    page_url = PUBLICATION_URL_TEMPLATE.format(slug=academic_year_slug(cohort))
    try:
        links = scrape_file_links(page_url, ".ods", base_url=BASE_URL, force_refresh=force_refresh)
    except Exception as e:
        raise ReoffendingDataNotFoundError(
            f"No publication page for the {cohort_label(cohort)} cohort at {page_url}: {e}"
        ) from e

    for link in links:
        if _is_tables_workbook(link["url"]):
            return link["url"]
    raise ReoffendingDataNotFoundError(
        f"No tables workbook (.ods) on the {cohort_label(cohort)} cohort page {page_url}"
    )


# download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=False) -> Path,
# raising ReoffendingDataNotFoundError in place of DownloadError.
download_file = bind_download_file(_downloader, ReoffendingDataNotFoundError, _CACHE_TTL_HOURS)


def read_workbook(path: Path) -> dict[str, list[list[str]]]:
    """Read a reoffending workbook into raw rows keyed by worksheet title.

    Args:
        path: Path to the ODS workbook.

    Returns:
        Mapping of lower-case worksheet title (footnote markers removed) to its rows. The
        cover, contents and notes sheets are not numbered worksheets and are left out.

    Raises:
        ReoffendingDataError: If the workbook cannot be read or holds no numbered worksheet.
    """
    try:
        doc = load_ods(str(path))
    except Exception as e:
        raise ReoffendingDataError(f"Failed to read workbook {path}: {e}") from e

    sheets: dict[str, list[list[str]]] = {}
    for table in doc.spreadsheet.getElementsByType(Table):
        rows = _sheet_rows(table)
        match = _WORKSHEET_TITLE_RE.match(rows[0][0]) if rows and rows[0] else None
        if match:
            sheets[_clean(match.group(2)).lower()] = rows

    if not sheets:
        raise ReoffendingDataError(f"No numbered worksheets found in {path}")
    return sheets


def _sheet(sheets: dict[str, list[list[str]]], title: str) -> list[list[str]]:
    """Fetch a worksheet by title, naming what is missing when it is not there."""
    if title not in sheets:
        raise ReoffendingDataNotFoundError(f"No worksheet titled {title!r}; found: {sorted(sheets)}")
    return sheets[title]


def _group_of(token: str | None) -> str:
    """Population group named in a column header (``None`` means everyone)."""
    if token is None:
        return "all"
    try:
        return _GROUPS[token.lower()]
    except KeyError:
        raise ReoffendingDataError(f"Unrecognised population group {token!r} in a column header") from None


def _measure_of(header: str) -> tuple[str, str] | None:
    """Classify a column header as ``(measure, group)``, or ``None`` for a label column.

    Example:
        >>> _measure_of("Number of adults who reoffended")
        ('reoffenders', 'adult')
        >>> _measure_of("Total number in cohort")
        ('cohort_size', 'all')
        >>> _measure_of("Male one-year proven reoffending rate (%)")
        ('rate_pct', 'male')
        >>> _measure_of("Age") is None
        True
    """
    text = header.strip()
    for measure, pattern in (
        ("reoffenders", _REOFFENDERS_RE),
        ("cohort_size", _COHORT_SIZE_RE),
        ("rate_pct", _RATE_RE),
    ):
        match = pattern.match(text)
        if match:
            return measure, _group_of(match.group("group"))
    return None


def _parse_rate(text: str) -> float:
    """Parse a published rate such as ``"17.3%"``; suppressed ``"x"`` becomes NaN.

    Example:
        >>> _parse_rate("17.3%")
        17.3
        >>> import math
        >>> math.isnan(_parse_rate("x"))
        True
    """
    return _parse_value(text.strip().rstrip("%"))


def _header_index(rows: Sequence[Sequence[str]]) -> int:
    """Index of the column-header row: the first multi-column row that is not a ``Table`` caption."""
    for index, row in enumerate(rows[1:], start=1):
        if len(row) >= 4 and not row[0].strip().lower().startswith("table "):
            return index
    raise ReoffendingDataError("No column header row found in worksheet")


def _tidy(
    header: Sequence[str], body: Sequence[Sequence[str]], label_names: Sequence[str], offset: int = 0
) -> pd.DataFrame:
    """Reshape wide ``reoffenders / cohort / rate`` column triples into one row per label and group.

    Args:
        header: Column headers of the table (or of one block of a side-by-side layout).
        body: Data rows aligned to ``header``.
        label_names: Names for the leading label columns.
        offset: Index in each ``body`` row where ``header`` starts.

    Returns:
        DataFrame with the label columns, ``group``, ``reoffenders``, ``cohort_size`` and
        ``rate_pct``. Counts are nullable integers; suppressed rates are NaN.

    Raises:
        ReoffendingDataError: If no measure columns are recognised or a group lacks a measure.
    """
    columns = {i: m for i, h in enumerate(header) if (m := _measure_of(h))}
    if not columns:
        raise ReoffendingDataError(f"No reoffending measure columns recognised in header {list(header)}")

    records: list[dict[str, object]] = []
    for row in body:
        cells = list(row[offset : offset + len(header)])
        cells += [""] * (len(header) - len(cells))
        labels = {name: _clean(cells[i]) for i, name in enumerate(label_names)}
        by_group: dict[str, dict[str, float]] = {}
        for i, (measure, group) in columns.items():
            by_group.setdefault(group, {})[measure] = (
                _parse_rate(cells[i]) if measure == "rate_pct" else _parse_value(cells[i])
            )
        for group, measures in by_group.items():
            missing = {"reoffenders", "cohort_size", "rate_pct"} - measures.keys()
            if missing:
                raise ReoffendingDataError(f"Group {group!r} lacks columns {sorted(missing)} in header {list(header)}")
            records.append({**labels, "group": group, **measures})

    df = pd.DataFrame(records)
    for column in ("reoffenders", "cohort_size"):
        df[column] = df[column].astype("Int64")
    return df


def _tidy_rates(rows: list[list[str]]) -> pd.DataFrame:
    """Parse the three side-by-side tables (overall, adult, youth) of the annual rates worksheet."""
    header_index = _header_index(rows)
    header = rows[header_index]
    starts = [i for i, cell in enumerate(header) if cell.strip().lower() == "year"]
    if not starts:
        raise ReoffendingDataError("No 'Year' column in the annual reoffending rates worksheet")

    body = [row for row in rows[header_index + 1 :] if row and _COHORT_RE.match(row[0].strip())]
    if not body:
        raise ReoffendingDataError("No cohort rows in the annual reoffending rates worksheet")

    frames = []
    for start, end in zip(starts, [*starts[1:], len(header)], strict=True):
        block = _tidy(header[start:end], body, ["cohort"], offset=start)
        frames.append(block)

    df = pd.concat(frames, ignore_index=True)
    df["cohort_start"] = df["cohort"].map(_cohort_start)
    return (
        df[["cohort", "cohort_start", "group", "cohort_size", "reoffenders", "rate_pct"]]
        .sort_values(["cohort_start", "group"])
        .reset_index(drop=True)
    )


def _check_rates(df: pd.DataFrame, what: str) -> None:
    """Check published rates against their counts and the disclosure rule.

    A rate shown must equal ``reoffenders / cohort_size`` to the published rounding, and may
    only be shown where the cohort is at least 50.

    Raises:
        ReoffendingValidationError: On any violation.
    """
    shown = df[df.rate_pct.notna()]
    too_small = shown[shown.cohort_size < _MIN_RATE_COHORT]
    if not too_small.empty:
        raise ReoffendingValidationError(
            f"{what}: rate shown for a cohort under {_MIN_RATE_COHORT}: {too_small.head(3).to_dict('records')}"
        )
    expected = shown.reoffenders.astype(float) / shown.cohort_size.astype(float) * 100
    off = shown[(shown.rate_pct - expected).abs() > _RATE_TOLERANCE_PP]
    if not off.empty:
        raise ReoffendingValidationError(f"{what}: rate disagrees with its counts: {off.head(3).to_dict('records')}")


def _check_totals(df: pd.DataFrame, total_mask: pd.Series, what: str) -> pd.DataFrame:
    """Check the non-total rows sum to the total row for each group, then drop the total row.

    Raises:
        ReoffendingValidationError: If a group's rows do not sum to its total, or there is no total row.
    """
    totals = df[total_mask].set_index("group")
    parts = df[~total_mask].groupby("group")[["reoffenders", "cohort_size"]].sum()
    if totals.empty:
        raise ReoffendingValidationError(f"{what}: no total row found")
    for group, total in totals.iterrows():
        for column in ("reoffenders", "cohort_size"):
            if int(parts.loc[group, column]) != int(total[column]):
                raise ReoffendingValidationError(
                    f"{what}: {group} {column} sums to {int(parts.loc[group, column])}, total row says {int(total[column])}"
                )
    return df[~total_mask].reset_index(drop=True)


def validate_reoffending_rates(df: pd.DataFrame) -> bool:
    """Validate the annual rates frame.

    Checks the columns, that every group has a contiguous run of cohorts, that rates agree
    with their counts, and that adult and youth counts sum to the overall counts. The sum may
    exceed the overall count by up to 0.1% but never fall short of it: the 2010/11 cohort is
    published with adult and youth cohorts totalling 33,824 against an overall 33,815, and
    every later cohort sums exactly.

    Args:
        df: Frame from :func:`get_reoffending_rates`.

    Returns:
        True if validation passes.

    Raises:
        ReoffendingValidationError: If the frame is empty, malformed or inconsistent.
    """
    required = {"cohort", "cohort_start", "group", "cohort_size", "reoffenders", "rate_pct"}
    missing = required - set(df.columns)
    if missing:
        raise ReoffendingValidationError(f"Missing columns: {sorted(missing)}")
    if df.empty:
        raise ReoffendingValidationError("Empty frame")
    if set(df.group) != {"all", "adult", "youth"}:
        raise ReoffendingValidationError(f"Unexpected groups: {sorted(set(df.group))}")

    for group, rows in df.groupby("group"):
        starts = sorted(rows.cohort_start)
        if starts != list(range(starts[0], starts[0] + len(starts))):
            raise ReoffendingValidationError(f"Cohorts for {group!r} are not contiguous: {starts}")

    _check_rates(df, "annual rates")

    wide = df.pivot(index="cohort_start", columns="group", values=["cohort_size", "reoffenders"])
    for measure in ("cohort_size", "reoffenders"):
        overall = wide[measure]["all"]
        gap = wide[measure]["adult"] + wide[measure]["youth"] - overall
        outside = gap[(gap < 0) | (gap > overall * _MAX_GROUP_OVERLAP)]
        if not outside.empty:
            raise ReoffendingValidationError(
                f"Adult + youth {measure} is not within [0, {_MAX_GROUP_OVERLAP:.1%}] above overall "
                f"in cohorts {list(outside.index)}: gap {outside.tolist()}"
            )
    return True


def _load(cohort: int | None, force_refresh: bool) -> dict[str, list[list[str]]]:
    """Download (or reuse the cached) workbook for a cohort and read it."""
    url = get_data_file_url(cohort, force_refresh=force_refresh)
    logger.info("Using reoffending workbook %s", url)
    return read_workbook(download_file(url, force_refresh=force_refresh))


def get_reoffending_rates(cohort: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the one-year proven reoffending rate for every cohort, for all offenders, adults and youths.

    Args:
        cohort: Starting year of the cohort whose workbook to read, e.g. ``2023`` for 2023/24
            (the series then ends at that cohort). Defaults to the newest published.
        force_refresh: Bypass the cache.

    Returns:
        DataFrame with ``cohort`` (``"2023/24"``), ``cohort_start`` (``2023``), ``group``
        (``all``, ``adult`` or ``youth``), ``cohort_size``, ``reoffenders`` and ``rate_pct``.

    Raises:
        ReoffendingDataNotFoundError: If the cohort is not published or the worksheet is missing.
        ReoffendingValidationError: If the parsed series is inconsistent.

    Example:
        >>> df = get_reoffending_rates()  # doctest: +SKIP
        >>> df[df.group == "all"].tail(2)[["cohort", "cohort_size", "rate_pct"]]  # doctest: +SKIP
             cohort  cohort_size  rate_pct
        39  2022/23        20373      17.6
        42  2023/24        20887      17.3
    """
    df = _tidy_rates(_sheet(_load(cohort, force_refresh), _RATES_TITLE))
    validate_reoffending_rates(df)
    return df


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Get the annual reoffending rates for the newest published cohort (see :func:`get_reoffending_rates`)."""
    return get_reoffending_rates(force_refresh=force_refresh)


def get_reoffending_by_age_gender(cohort: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the reoffending rate by age band and gender for one cohort.

    Args:
        cohort: Starting year of the cohort. Defaults to the newest published.
        force_refresh: Bypass the cache.

    Returns:
        DataFrame with ``age_band``, ``group`` (``all``, ``male`` or ``female``),
        ``reoffenders``, ``cohort_size`` and ``rate_pct``. The age bands sum to the published
        total, which is checked and then left out.

    Raises:
        ReoffendingDataNotFoundError: If the cohort is not published or the worksheet is missing.
        ReoffendingValidationError: If the bands do not sum to the total or a rate disagrees with its counts.
    """
    rows = _sheet(_load(cohort, force_refresh), _AGE_GENDER_TITLE)
    index = _header_index(rows)
    df = _tidy(rows[index], [r for r in rows[index + 1 :] if r and r[0].strip()], ["age_band"])
    _check_rates(df, "age and gender")
    df = _check_totals(df, df.age_band.str.lower() == "total", "age and gender")
    return df[["age_band", "group", "reoffenders", "cohort_size", "rate_pct"]]


def get_reoffending_by_disposal(cohort: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the reoffending rate by disposal for one cohort.

    Args:
        cohort: Starting year of the cohort. Defaults to the newest published.
        force_refresh: Bypass the cache.

    Returns:
        DataFrame with ``disposal_group``, ``disposal``, ``group`` (``all``, ``adult`` or
        ``youth``), ``reoffenders``, ``cohort_size`` and ``rate_pct``. Each group has a
        ``Total`` row and the frame ends with an ``Overall total`` row. Disposals do not sum to
        their group's total (a person is counted once per group), so filter ``disposal != "Total"``
        before adding anything up.

    Raises:
        ReoffendingDataNotFoundError: If the cohort is not published or the worksheet is missing.
        ReoffendingValidationError: If a rate disagrees with its counts.
    """
    rows = _sheet(_load(cohort, force_refresh), _DISPOSAL_TITLE)
    index = _header_index(rows)
    df = _tidy(rows[index], [r for r in rows[index + 1 :] if r and r[0].strip()], ["disposal_group", "disposal"])
    df["disposal"] = df.disposal.where(df.disposal != "", "Total")
    _check_rates(df, "disposal")
    return df[["disposal_group", "disposal", "group", "reoffenders", "cohort_size", "rate_pct"]]


def get_reoffending_by_offence_category(cohort: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the reoffending rate by baseline offence category for one cohort.

    The baseline offence is the offence that placed the person in the cohort (the one for which
    they received the disposal or were released).

    Args:
        cohort: Starting year of the cohort. Defaults to the newest published.
        force_refresh: Bypass the cache.

    Returns:
        DataFrame with ``offence_category``, ``group`` (``all``, ``adult`` or ``youth``),
        ``reoffenders``, ``cohort_size`` and ``rate_pct``. The categories sum to the published
        total, which is checked and then left out.

    Raises:
        ReoffendingDataNotFoundError: If the cohort is not published or the worksheet is missing.
        ReoffendingValidationError: If the categories do not sum to the total or a rate disagrees with its counts.
    """
    rows = _sheet(_load(cohort, force_refresh), _OFFENCE_TITLE)
    index = _header_index(rows)
    df = _tidy(rows[index], [r for r in rows[index + 1 :] if r and r[0].strip()], ["offence_category"])
    _check_rates(df, "offence category")
    df = _check_totals(df, df.offence_category.str.lower() == "total", "offence category")
    return df[["offence_category", "group", "reoffenders", "cohort_size", "rate_pct"]]
