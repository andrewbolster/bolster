"""Health visiting reviews for pre-school children in Northern Ireland.

Published as: Healthy Child, Healthy Future: Health Review Statistics for Northern Ireland.

Every child in Northern Ireland is offered six health visitor reviews before
school age: a new baby review, then reviews at 6-8 weeks, 14-16 weeks,
6-9 months, 1 year and 2-2.5 years. The Department of Health publishes how many
of each were delivered early, on time or late, and how many never happened.

Data Coverage:
    - Annual counts of each review by outcome (contact early, on time, late, no
      contact) and children in the cohort, for Northern Ireland and each of the
      five HSC Trusts (Belfast, Northern, South Eastern, Southern, Western),
      one row per release year, 2018/19 to the latest release
    - The proportion of visits on time, quarterly, for Northern Ireland: each
      release carries its own window and the windows stitch into one series from
      2017/18 Q1

Data Source:
    Each release has its own publication page, whose address ends in the
    academic-year slug (``...-northern-ireland-202526``), with an Excel workbook
    of tables beside the PDF bulletins. The workbook's address changes from year
    to year (directory and extension case), so it is read from the publication
    page. The hub article (https://www.health-ni.gov.uk/articles/health-review-statistics-pre-school-children)
    lists only the releases it has been updated for and can trail the newest
    publication page, so the module addresses the publication pages directly.
    The series is not in PxStat.

Update Frequency: Annual, published in October for the year to 31 March.

Geographic Coverage: Northern Ireland and its five HSC Trusts.

Example:
    >>> from bolster.data_sources.health_ni import health_visiting_reviews as hvr
    >>> df = hvr.get_health_review_outcomes()
    >>> sorted(df.columns)[:3]
    ['cohort', 'contact_early', 'contact_late']

    >>> hvr.review_key("Health Review at 2-21/2 Years by HV")
    '2_2_5_years'

Notes:
    - A release's own year is the only year its workbook counts. Asking for a year
      with no published release raises :class:`NISRADataNotFoundError`; no other
      year's data is returned instead.
    - Counts of fewer than a handful of children are suppressed in some early
      releases (shown as ``-``); they are returned as missing values.
    - The cohort is the children reaching the review age in the year, not the
      births in that year, and the Trusts are the five HSC Trusts, not Local
      Government Districts.
    - Northern Ireland's rows come from each workbook's summary table. Every review
      table repeats that row, and the repeats are compared with the summary and
      logged where they differ: the 2022/23 new baby table gives Northern Ireland
      figures that disagree with both the summary and its own Trust rows.
"""

import logging
import re
from collections.abc import Callable
from datetime import date

import pandas as pd

from bolster.utils.cache import load_workbook, stitch_publications
from bolster.utils.excel import parse_sheet
from bolster.utils.web import academic_year_slug, scrape_file_links, session

from ._base import HEALTH_NI_BASE_URL, NISRADataNotFoundError, NISRAValidationError, download_file

logger = logging.getLogger(__name__)

PUBLICATION_URL_TEMPLATE = (
    HEALTH_NI_BASE_URL + "/publications/healthy-child-healthy-future-health-review-statistics-northern-ireland-{slug}"
)

#: First release year (2018 means the 2018/19 release) whose workbook has the layout this module reads.
FIRST_RELEASE_YEAR = 2018

NORTHERN_IRELAND = "Northern Ireland"
TRUSTS = ("Belfast", "Northern", "South Eastern", "Southern", "Western")

#: The six reviews, in the order a child receives them.
REVIEWS = ("new_baby", "6_8_weeks", "14_16_weeks", "6_9_months", "1_year", "2_2_5_years")

OUTCOME_COLUMNS = ("contact_early", "contact_on_time", "contact_late", "no_contact")
OUTCOMES_COLUMNS = frozenset({"year", "financial_year", "review", "trust", "cohort", "on_time_pct", *OUTCOME_COLUMNS})
QUARTERLY_COLUMNS = frozenset({"year", "financial_year", "quarter", "quarter_start", "review", "on_time_pct"})

_HEADER_TO_COLUMN = {
    "contact early": "contact_early",
    "contact on time": "contact_on_time",
    "contact late": "contact_late",
    "no contact": "no_contact",
    "children in cohort": "cohort",
}

# Ordered: each pattern is tried in turn. Labels vary between releases
# ("6 to 8 Week Review by HV", "6 - 8 Week Review", "6 – 8 Week Review ").
_REVIEW_PATTERNS = (
    ("new_baby", re.compile(r"new baby", re.IGNORECASE)),
    ("6_8_weeks", re.compile(r"\b6\s*(?:-|–|to)\s*8\b", re.IGNORECASE)),
    ("14_16_weeks", re.compile(r"\b14\s*(?:-|–|to)\s*16\b", re.IGNORECASE)),
    ("6_9_months", re.compile(r"\b6\s*(?:-|–|to)\s*9\b", re.IGNORECASE)),
    ("1_year", re.compile(r"\b1\s*year", re.IGNORECASE)),
    ("2_2_5_years", re.compile(r"\b2\s*(?:-|–|to)\s*2", re.IGNORECASE)),
)

_TABLE_TITLE_RE = re.compile(r"Table\s*\d", re.IGNORECASE)
_QUARTER_LABEL_RE = re.compile(r"(\d{4})/(\d{2})\s+Q([1-4])")
_QUARTER_ONLY_RE = re.compile(r"Q([1-4])")
_FINANCIAL_YEAR_RE = re.compile(r"(\d{4})/(\d{2})")


def review_key(label: str) -> str | None:
    """Map a review label from any release to its canonical key.

    Args:
        label: A row or column label such as ``"6 to 8 Week Review by HV"``.

    Returns:
        One of :data:`REVIEWS`, or ``None`` if the label is not a review.

    Example:
        >>> review_key("6 - 8 Week Review")
        '6_8_weeks'
        >>> review_key("New baby review ")
        'new_baby'
        >>> review_key("Northern Ireland") is None
        True
    """
    for key, pattern in _REVIEW_PATTERNS:
        if pattern.search(label):
            return key
    return None


def financial_year_label(year: int) -> str:
    """Label the financial year starting in ``year``.

    Example:
        >>> financial_year_label(2025)
        '2025/26'
    """
    return f"{year}/{(year + 1) % 100:02d}"


# ---------------------------------------------------------------------------
# Release discovery
# ---------------------------------------------------------------------------


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _publication_page_url(year: int) -> str:
    return PUBLICATION_URL_TEMPLATE.format(slug=academic_year_slug(year))


def _find_workbook_url(page_url: str, force_refresh: bool) -> str | None:
    """Find the tables workbook linked from one publication page, or ``None``."""
    links = scrape_file_links(page_url, ".xlsx", force_refresh=force_refresh)
    for link in links:
        if "table" in link["url"].rsplit("/", 1)[-1].lower():
            return link["url"]
    return None


def _page_status(year: int, force_refresh: bool) -> int:
    response = session.get(_publication_page_url(year), force_refresh=force_refresh)
    return response.status_code


def list_publications(force_refresh: bool = False) -> pd.DataFrame:
    """List the published releases, newest first.

    Args:
        force_refresh: Bypass the page cache.

    Returns:
        DataFrame with ``year`` (the year the financial year starts), ``financial_year``,
        ``page_url`` and ``workbook_url``.

    Raises:
        NISRADataNotFoundError: If a publication page answers with anything other than
            200 or 404, or if no release is found.
    """
    records = []
    for year in range(date.today().year, FIRST_RELEASE_YEAR - 1, -1):
        status = _page_status(year, force_refresh)
        if status == 404:
            continue
        if status != 200:
            raise NISRADataNotFoundError(f"{_publication_page_url(year)} returned HTTP {status}")
        workbook_url = _find_workbook_url(_publication_page_url(year), force_refresh)
        if workbook_url is None:
            logger.warning("%s has no tables workbook", _publication_page_url(year))
            continue
        records.append(
            {
                "year": year,
                "financial_year": financial_year_label(year),
                "page_url": _publication_page_url(year),
                "workbook_url": workbook_url,
            }
        )
    if not records:
        raise NISRADataNotFoundError("No Healthy Child, Healthy Future release pages found")
    return pd.DataFrame(records)


def _resolve_release(year: int | None, force_refresh: bool) -> tuple[int, str]:
    """Return ``(year, workbook_url)`` for ``year``, or for the newest release when ``year`` is ``None``.

    Raises:
        NISRADataNotFoundError: If the requested year has no release, or the newest release page
            has no tables workbook. No other year is substituted.
    """
    if year is not None:
        if year < FIRST_RELEASE_YEAR:
            raise NISRADataNotFoundError(
                f"No {financial_year_label(year)} release is read: the first supported release is "
                f"{financial_year_label(FIRST_RELEASE_YEAR)}"
            )
        candidates = [year]
    else:
        candidates = list(range(date.today().year, FIRST_RELEASE_YEAR - 1, -1))

    for candidate in candidates:
        status = _page_status(candidate, force_refresh)
        if status == 404:
            continue
        if status != 200:
            raise NISRADataNotFoundError(f"{_publication_page_url(candidate)} returned HTTP {status}")
        workbook_url = _find_workbook_url(_publication_page_url(candidate), force_refresh)
        if workbook_url is None:
            raise NISRADataNotFoundError(
                f"The {financial_year_label(candidate)} publication page {_publication_page_url(candidate)} "
                "links no tables workbook"
            )
        return candidate, workbook_url

    if year is not None:
        raise NISRADataNotFoundError(f"No {financial_year_label(year)} release found at {_publication_page_url(year)}")
    raise NISRADataNotFoundError("No Healthy Child, Healthy Future release pages found")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _sheet(workbook: pd.ExcelFile, name: str) -> pd.DataFrame:
    """Read a sheet with no header and without the empty columns some releases pad it with."""
    frame = parse_sheet(workbook, name, header=None).dropna(axis=1, how="all")
    frame.columns = pd.RangeIndex(frame.shape[1])
    return frame.reset_index(drop=True)


def _parse_count_block(frame: pd.DataFrame) -> tuple[str, pd.DataFrame] | None:
    """Parse the counts block of a table sheet.

    The block is the one whose header row reads ``Contact Early``; the proportions block below
    it reads ``% Contact Early``. Returns the header's first cell and the rows under it, or
    ``None`` if the sheet has no counts block (the quarterly table).
    """
    if frame.shape[1] < 2:
        return None
    header_row = next((i for i in range(len(frame)) if _clean(frame.iat[i, 1]).lower() == "contact early"), None)
    if header_row is None:
        return None

    columns = [_HEADER_TO_COLUMN.get(_clean(frame.iat[header_row, j]).lower()) for j in range(1, frame.shape[1])]
    missing = set(_HEADER_TO_COLUMN.values()) - {c for c in columns if c}
    if missing:
        raise NISRAValidationError(f"Health review table is missing columns: {sorted(missing)}")

    records: list[dict[str, object]] = []
    for i in range(header_row + 1, len(frame)):
        label = _clean(frame.iat[i, 0])
        # The block ends at a blank row, or, where a release leaves no gap, at the next table's title
        # or the proportions header that follows the counts.
        if not label or _TABLE_TITLE_RE.match(label) or _clean(frame.iat[i, 1]).startswith("%"):
            break
        row: dict[str, object] = {"label": label}
        for j, column in enumerate(columns, start=1):
            if column:
                row[column] = pd.to_numeric(_clean(frame.iat[i, j]), errors="coerce")
        records.append(row)

    block = pd.DataFrame(records)
    for column in _HEADER_TO_COLUMN.values():
        block[column] = block[column].astype("Int64")
    return _clean(frame.iat[header_row, 0]), block


def _parse_outcomes(workbook: pd.ExcelFile, year: int) -> pd.DataFrame:
    """Parse every counts table of one release into a tidy frame."""
    by_review: list[pd.DataFrame] = []
    summary: pd.DataFrame | None = None

    for name in workbook.sheet_names:
        if not re.fullmatch(r"Table\s*\d+", str(name)):
            continue
        parsed = _parse_count_block(_sheet(workbook, str(name)))
        if parsed is None:
            continue
        corner, block = parsed
        if corner.lower() == NORTHERN_IRELAND.lower():
            keys = [review_key(label) for label in block["label"]]
            if None in keys:
                raise NISRAValidationError(f"{name}: unrecognised review label in {block['label'].tolist()}")
            summary = block.assign(review=keys, trust=NORTHERN_IRELAND).drop(columns="label")
            continue
        key = review_key(corner)
        if key is None:
            raise NISRAValidationError(f"{name}: unrecognised review heading {corner!r}")
        unknown = set(block["label"]) - {*TRUSTS, NORTHERN_IRELAND}
        if unknown:
            raise NISRAValidationError(f"{name}: unrecognised geography labels {sorted(unknown)}")
        by_review.append(block.assign(review=key).rename(columns={"label": "trust"}))

    if not by_review or summary is None:
        raise NISRAValidationError(f"{financial_year_label(year)} workbook has no health review count tables")

    outcomes = _northern_ireland_from_summary(pd.concat(by_review, ignore_index=True), summary, year)

    outcomes["year"] = year
    outcomes["financial_year"] = financial_year_label(year)
    outcomes["on_time_pct"] = outcomes["contact_on_time"].astype("Float64") / outcomes["cohort"].astype("Float64") * 100
    return _sorted(outcomes)[["year", "financial_year", "review", "trust", *OUTCOME_COLUMNS, "cohort", "on_time_pct"]]


def _northern_ireland_from_summary(by_review: pd.DataFrame, summary: pd.DataFrame, year: int) -> pd.DataFrame:
    """Take the Northern Ireland rows from the summary table, checking them against the review tables.

    Each review table repeats the Northern Ireland row that the summary table holds. The two
    should agree; where they do not, the summary table is used, because it is the one the Trust
    rows sum to (:func:`validate_outcomes` checks that), and the disagreement is logged by cell.
    The 2022/23 release's new baby table is one such case.
    """
    label = financial_year_label(year)
    repeated = by_review[by_review["trust"] == NORTHERN_IRELAND].set_index("review")
    summary_by_review = summary.set_index("review")
    for review in summary_by_review.index:
        if review not in repeated.index:
            raise NISRAValidationError(f"{label}: no Northern Ireland row for {review}")
        for column in (*OUTCOME_COLUMNS, "cohort"):
            own, from_summary = repeated.at[review, column], summary_by_review.at[review, column]
            if pd.notna(own) and pd.notna(from_summary) and own != from_summary:
                logger.warning(
                    "%s %s %s is %s in its own table but %s in the summary table; using the summary table",
                    label,
                    review,
                    column,
                    own,
                    from_summary,
                )
    return pd.concat([by_review[by_review["trust"] != NORTHERN_IRELAND], summary], ignore_index=True)


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    """Order rows by release year, then review in the order a child receives it, then geography."""
    review_rank = {key: i for i, key in enumerate(REVIEWS)}
    trust_rank = {key: i for i, key in enumerate((NORTHERN_IRELAND, *TRUSTS))}
    return (
        frame.assign(_r=frame["review"].map(review_rank), _t=frame["trust"].map(trust_rank))
        .sort_values(["year", "_r", "_t"])
        .drop(columns=["_r", "_t"])
        .reset_index(drop=True)
    )


def _find_quarter_header(frame: pd.DataFrame) -> tuple[int, list[tuple[int, int, int]]] | None:
    """Locate the quarter header of the quarterly table.

    Returns the header row and ``(column, financial_year_start, quarter)`` for each quarter
    column. Releases label quarters in three ways: ``2020/21 Q1`` in one row, a ``Q1`` row under
    a row repeating the year in every column, or a ``Q1`` row under a year that heads its four columns.
    """
    for i in range(len(frame)):
        cells = [_clean(frame.iat[i, j]) for j in range(frame.shape[1])]
        combined = [(j, _QUARTER_LABEL_RE.fullmatch(c)) for j, c in enumerate(cells)]
        found = [(j, int(m.group(1)), int(m.group(3))) for j, m in combined if m]
        if len(found) >= 4:
            return i, found
        quarters = [(j, int(m.group(1))) for j, c in enumerate(cells) if (m := _QUARTER_ONLY_RE.fullmatch(c))]
        if len(quarters) >= 4 and i > 0:
            carried: dict[int, int] = {}
            current: int | None = None
            for j in range(frame.shape[1]):
                match = _FINANCIAL_YEAR_RE.fullmatch(_clean(frame.iat[i - 1, j]))
                if match:
                    current = int(match.group(1))
                if current is not None:
                    carried[j] = current
            if any(j not in carried for j, _ in quarters):
                raise NISRAValidationError(f"Quarterly table row {i}: a quarter column has no financial year above it")
            return i, [(j, carried[j], q) for j, q in quarters]
    return None


def _parse_quarterly(workbook: pd.ExcelFile, year: int) -> pd.DataFrame:
    """Parse the quarterly on-time table of one release."""
    for name in workbook.sheet_names:
        if not re.fullmatch(r"Table\s*\d+", str(name)):
            continue
        frame = _sheet(workbook, str(name))
        header = _find_quarter_header(frame)
        if header is None:
            continue
        header_row, quarter_columns = header
        records = []
        for i in range(header_row + 1, len(frame)):
            key = review_key(_clean(frame.iat[i, 0]))
            if key is None:
                break
            for j, start, quarter in quarter_columns:
                value = pd.to_numeric(_clean(frame.iat[i, j]), errors="coerce")
                records.append(
                    {
                        "year": start,
                        "financial_year": financial_year_label(start),
                        "quarter": quarter,
                        "quarter_start": pd.Timestamp(year=start, month=4, day=1)
                        + pd.DateOffset(months=3 * (quarter - 1)),
                        "review": key,
                        "on_time_pct": value * 100,
                    }
                )
        if not records:
            raise NISRAValidationError(f"{financial_year_label(year)}: quarterly table has no review rows")
        out = pd.DataFrame(records)
        out["on_time_pct"] = out["on_time_pct"].astype("Float64")
        return _order_quarterly(out)
    raise NISRAValidationError(f"{financial_year_label(year)} workbook has no quarterly table")


def _order_quarterly(frame: pd.DataFrame) -> pd.DataFrame:
    review_rank = {key: i for i, key in enumerate(REVIEWS)}
    return (
        frame.assign(_r=frame["review"].map(review_rank))
        .sort_values(["quarter_start", "_r"])
        .drop(columns="_r")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def get_health_review_outcomes(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Health visiting reviews by outcome, for Northern Ireland and each Trust, in one release year.

    Args:
        year: The year the financial year starts (``2025`` for 2025/26). ``None`` reads the
            newest release.
        force_refresh: Bypass the page and file caches.

    Returns:
        DataFrame with ``year``, ``financial_year``, ``review`` (one of :data:`REVIEWS`), ``trust``
        (``"Northern Ireland"`` or a Trust), the counts ``contact_early``, ``contact_on_time``,
        ``contact_late`` and ``no_contact``, ``cohort`` and ``on_time_pct`` (on time as a
        percentage of the cohort).

    Raises:
        NISRADataNotFoundError: If ``year`` has no release, or the newest release has no workbook.
        NISRAValidationError: If the workbook's layout is not recognised or its tables disagree.
    """
    release_year, url = _resolve_release(year, force_refresh)
    outcomes = _parse_outcomes(load_workbook(url, download_file, force_refresh=force_refresh), release_year)
    validate_outcomes(outcomes)
    return outcomes


def get_quarterly_on_time(year: int | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """The proportion of reviews on time, by quarter, for Northern Ireland, as one release reports it.

    Args:
        year: The year the financial year starts. ``None`` reads the newest release.
        force_refresh: Bypass the page and file caches.

    Returns:
        DataFrame with ``year``, ``financial_year``, ``quarter`` (1-4), ``quarter_start``,
        ``review`` and ``on_time_pct`` (0-100). A release covers the quarters from its own window,
        not every quarter ever published; see :func:`get_quarterly_on_time_series`.

    Raises:
        NISRADataNotFoundError: If ``year`` has no release, or the newest release has no workbook.
        NISRAValidationError: If the workbook's layout is not recognised.
    """
    release_year, url = _resolve_release(year, force_refresh)
    quarterly = _parse_quarterly(load_workbook(url, download_file, force_refresh=force_refresh), release_year)
    validate_quarterly(quarterly)
    return quarterly


def _stitched(fetch: Callable[[int], pd.DataFrame], dedup_keys: list[str], force_refresh: bool) -> pd.DataFrame:
    publications = list_publications(force_refresh=force_refresh).to_dict("records")
    return stitch_publications(
        publications,
        lambda publication: fetch(int(publication["year"])),
        dedup_keys=dedup_keys,
        errors=(NISRADataNotFoundError, NISRAValidationError),
    )


def get_health_review_outcomes_series(force_refresh: bool = False) -> pd.DataFrame:
    """Health visiting review outcomes for every published release year, 2018/19 onwards.

    A release that cannot be read is logged and skipped, so check ``financial_year`` for gaps.

    Args:
        force_refresh: Bypass the page and file caches.

    Returns:
        The frame :func:`get_health_review_outcomes` returns, for every year.
    """
    series = _stitched(
        lambda y: get_health_review_outcomes(year=y, force_refresh=force_refresh),
        ["year", "review", "trust"],
        force_refresh,
    )
    return _sorted(series)


def get_quarterly_on_time_series(force_refresh: bool = False) -> pd.DataFrame:
    """The proportion of reviews on time by quarter, stitched across every release.

    Each release repeats the quarters of its own window; where releases overlap the newest
    release's figure is kept. A release that cannot be read is logged and skipped.

    Args:
        force_refresh: Bypass the page and file caches.

    Returns:
        The frame :func:`get_quarterly_on_time` returns, from 2017/18 Q1.
    """
    series = _stitched(
        lambda y: get_quarterly_on_time(year=y, force_refresh=force_refresh),
        ["quarter_start", "review"],
        force_refresh,
    )
    return _order_quarterly(series)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_outcomes(df: pd.DataFrame) -> bool:
    """Check a frame from :func:`get_health_review_outcomes`.

    Args:
        df: The frame to check.

    Returns:
        ``True`` if valid.

    Raises:
        NISRAValidationError: If a column is missing, a count is negative, a release year is
            incomplete, a Trust's cohort does not sum to Northern Ireland's, or a row's outcomes
            do not sum to its cohort.
    """
    missing = OUTCOMES_COLUMNS - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Health review outcomes missing columns: {sorted(missing)}")
    if df.empty:
        raise NISRAValidationError("Health review outcomes are empty")

    counts = df[[*OUTCOME_COLUMNS, "cohort"]]
    if (counts.dropna(how="all").stack().astype(float) < 0).any():
        raise NISRAValidationError("Health review outcomes contain negative counts")
    if (df["cohort"] <= 0).any():
        raise NISRAValidationError("Health review outcomes contain a non-positive cohort")

    for financial_year, group in df.groupby("financial_year"):
        expected = {(review, trust) for review in REVIEWS for trust in (NORTHERN_IRELAND, *TRUSTS)}
        found = set(zip(group["review"], group["trust"], strict=True))
        if found != expected:
            raise NISRAValidationError(
                f"{financial_year}: expected every review for Northern Ireland and each Trust; "
                f"missing {sorted(expected - found)}, unexpected {sorted(found - expected)}"
            )
        for review, rows in group.groupby("review"):
            trust_rows = rows[rows["trust"].isin(TRUSTS)]
            ni_row = rows[rows["trust"] == NORTHERN_IRELAND].iloc[0]
            for column in (*OUTCOME_COLUMNS, "cohort"):
                if trust_rows[column].isna().any():
                    continue  # a suppressed Trust count cannot be summed
                total = trust_rows[column].sum()
                if total != ni_row[column]:
                    raise NISRAValidationError(
                        f"{financial_year} {review} {column}: Trust counts sum to {total}, not {ni_row[column]}"
                    )

    complete = df.dropna(subset=list(OUTCOME_COLUMNS))
    wrong = complete[complete[list(OUTCOME_COLUMNS)].sum(axis=1) != complete["cohort"]]
    if not wrong.empty:
        first = wrong.iloc[0]
        raise NISRAValidationError(
            f"{first['financial_year']} {first['review']} {first['trust']}: outcomes do not sum to the cohort"
        )
    return True


def validate_quarterly(df: pd.DataFrame) -> bool:
    """Check a frame from :func:`get_quarterly_on_time`.

    Args:
        df: The frame to check.

    Returns:
        ``True`` if valid.

    Raises:
        NISRAValidationError: If a column is missing, a value is outside 0-100, a review is
            missing, or a review's quarters are not contiguous.
    """
    missing = QUARTERLY_COLUMNS - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Quarterly on-time frame missing columns: {sorted(missing)}")
    if df.empty:
        raise NISRAValidationError("Quarterly on-time frame is empty")
    values = df["on_time_pct"].dropna().astype(float)
    if ((values < 0) | (values > 100)).any():
        raise NISRAValidationError("Quarterly on-time percentages fall outside 0-100")
    if set(df["review"]) != set(REVIEWS):
        raise NISRAValidationError(f"Quarterly reviews are {sorted(set(df['review']))}, expected {sorted(REVIEWS)}")
    for review, rows in df.groupby("review"):
        starts = pd.DatetimeIndex(sorted(rows["quarter_start"]))
        expected = pd.date_range(starts.min(), starts.max(), freq="3MS")
        if len(starts) != len(expected) or not (starts == expected).all():
            raise NISRAValidationError(f"{review}: quarters are not contiguous")
    return True
