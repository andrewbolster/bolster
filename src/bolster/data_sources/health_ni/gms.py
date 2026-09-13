"""Northern Ireland General Medical Services (GMS) statistics.

Provides access to Business Services Organisation (BSO) / Family Practitioner
Services (FPS) statistics on GP practices, GPs, registered patients, funding
and access equity across Northern Ireland.

Three cadences/files are published:

- **Annual tables** - the richest file: registered patients, GPs and practices
  by year and geography, GP headcount back to 1985, BSO funding per patient,
  patient-to-practice distance/proximity (including by deprivation quintile),
  and a GP-density comparison against the other UK nations.
- **Quarterly tables** - the same core breakdowns (practices, GPs, registered
  patients) at each financial-quarter end, with less history and no funding
  or proximity detail.
- **Registered patients by practice** - one sheet per year, already a clean
  per-practice table of registered patients by gender and age group.

Every annual/quarterly sheet holds one or more sub-tables stacked vertically
and separated by ``Table 1.1a: ...``-style marker rows, the same layout DoH's
accessible CSVs use -- see :func:`~bolster.data_sources.health_ni._base.parse_stacked_tables`.
Sub-table numbering has been confirmed stable between the two most recent
annual editions (2024/25 and 2025/26), so sheets/topics are looked up by
number rather than by title regex (contrast
:mod:`~bolster.data_sources.health_ni.hsc_workforce`, whose DoH table numbers
have drifted release-to-release).

Data Source:
    BSO/FPS publishes through GOV.UK. Publication URLs are discovered at
    runtime through the GOV.UK Search and Content APIs (mirroring
    :mod:`~bolster.data_sources.justice.pbni_caseload`), so new releases and
    the file-hosting asset hashes -- both of which change every release --
    are picked up without a code change.

Note:
    BSO's own tables label the trust-level geography "LCG (or Health Trust)".
    This module follows the rest of :mod:`~bolster.data_sources.health_ni` and
    calls it ``trust`` for join-compatibility with
    :mod:`~bolster.data_sources.health_ni.disease_prevalence` and the
    waiting-times modules. GP Federation is a finer geography unique to GMS.

Update Frequency: Quarterly, with a richer annual edition each summer
Geographic Coverage: Northern Ireland (by Health and Social Care Trust, Local
    Government District, or GP Federation)
Reference Period: Annual 2014 - present (GP headcount back to 1985); quarterly
    financial quarters from 2017/18 - present

Example:
    >>> from bolster.data_sources.health_ni import gms
    >>> df = gms.get_list_size()  # doctest: +SKIP
    >>> df.list_size.between(1000, 2000).all()  # doctest: +SKIP
    True
"""

import logging
import re
from collections.abc import Set as AbstractSet

import pandas as pd

from bolster.utils.web import session

from ._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    parse_stacked_tables,
    parse_value,
    strip_note_refs,
    trim_row,
)

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://www.gov.uk/api/search.json"
CONTENT_API_URL = "https://www.gov.uk/api/content"

_QUARTERLY_PREFIX = "/government/statistics/general-medical-services-statistics-for-ni-quarter"
_ANNUAL_PREFIX = "/government/statistics/fps-general-medical-services-statistics-for-ni"

_CACHE_TTL_HOURS = 24 * 7

_EXCLUDED_SHEETS = {"cover sheet", "table of contents", "notes", "user guidance"}

# GEOGRAPHY_LEVELS documents the values accepted as `level=` across this
# module. Not every topic supports every level -- see list_annual_topics()
# and list_quarterly_topics() for what's actually available.
GEOGRAPHY_LEVELS = ("trust", "lgd", "federation")

_YEAR_RE = re.compile(r"(\d{4})")
_YEAR_IN_TITLE_RE = re.compile(r"(\d{4})\s*$")
_QUARTER_COLUMN_RE = re.compile(r"^Quarter\s+([1-4])\s+(\d{4})/(\d{2})$")
_QUARTER_END = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}

# Annual sub-tables are one-per-year (the year lives in table_title, e.g.
# "... by LCG 2014"), with columns as an age/gender/metric breakdown rather
# than a year axis. These are the "grand total" column per topic, used to
# build a single tidy period series for the headline accessors below.
_ANNUAL_TOTAL_COLUMN = {
    "registered_patients": "All persons total",
    "gps": "All GPs total",
    "practices": "Number of practices",
}

# Sheet number -> (topic, level). `level` is None for topics with a single
# NI-wide/UK-wide breakdown rather than a geography split. Built directly
# from each workbook's own "Table of contents" sheet.
_ANNUAL_SHEETS: dict[str, tuple[str, str | None]] = {
    "1.1": ("registered_patients", "trust"),
    "1.2": ("registered_patients", "lgd"),
    "1.3": ("registered_patients", "federation"),
    "1.4": ("patient_registrations", "trust"),
    "1.5": ("patient_registrations", "lgd"),
    "1.6": ("patient_registrations", "federation"),
    "1.7": ("non_uk_registrations", "trust"),
    "1.8": ("non_uk_registrations", "lgd"),
    "1.9": ("non_uk_registrations", "federation"),
    "2.1": ("gps", "trust"),
    "2.2": ("gps", "lgd"),
    "2.3": ("gps", "federation"),
    "2.4": ("gps_by_gender_trend", None),
    "2.5": ("gps_by_contractor_type", None),
    "3.1": ("practices", "trust"),
    "3.2": ("practices", "lgd"),
    "3.3": ("practices", "federation"),
    "4.1": ("gps_per_100k_patients", "trust"),
    "4.2": ("gps_per_100k_patients", "lgd"),
    "4.3": ("gps_per_100k_patients", "federation"),
    "4.4": ("gps_per_practice", "trust"),
    "4.5": ("gps_per_practice", "lgd"),
    "4.6": ("gps_per_practice", "federation"),
    "5.1": ("practices_per_100k_patients", "trust"),
    "5.2": ("practices_per_100k_patients", "lgd"),
    "5.3": ("practices_per_100k_patients", "federation"),
    "6.1": ("funding_per_patient", "trust"),
    "6.2": ("funding_per_patient", "lgd"),
    "6.3": ("funding_per_patient", "federation"),
    "7.1": ("patient_proximity", "trust"),
    "7.2": ("patient_proximity", "lgd"),
    "7.3": ("patient_proximity", "deprivation_quintile"),
    "8.1": ("gps_by_uk_region", None),
    "8.2": ("gps_per_100k_patients_by_uk_region", None),
    "8.3": ("practices_per_100k_patients_by_uk_region", None),
}

# Quarterly numbering doesn't run the same tidy .1/.2/.3=trust/lgd/federation
# pattern as annual (e.g. 4.1 is a flat demographic table wedged between the
# trust/lgd/federation splits), so this is hand-built from its own contents
# sheet too. Sheet "7.1" (per-practice, wide quarter columns) is handled
# separately by parse_quarterly_patients_by_practice, not through here.
_QUARTERLY_SHEETS: dict[str, tuple[str, str | None]] = {
    "1.1": ("practices", "trust"),
    "1.2": ("avg_patients_per_practice", "trust"),
    "2.1": ("practices", "lgd"),
    "2.2": ("avg_patients_per_practice", "lgd"),
    "3.1": ("practices", "federation"),
    "3.2": ("avg_patients_per_practice", "federation"),
    "4.1": ("gps_by_gender_age", None),
    "4.2": ("gps", "trust"),
    "4.3": ("avg_gps_per_practice", "trust"),
    "4.4": ("avg_gps_per_practice", "lgd"),
    "4.5": ("avg_gps_per_practice", "federation"),
    "5.1": ("registered_patients_by_gender_age", None),
    "5.2": ("registered_patients", "trust"),
    "5.3": ("registered_patients", "lgd"),
    "5.4": ("registered_patients", "federation"),
    "6.1": ("patient_registrations", None),
}

_ANNUAL_TOPICS = {topic_level: sheet for sheet, topic_level in _ANNUAL_SHEETS.items()}
_QUARTERLY_TOPICS = {topic_level: sheet for sheet, topic_level in _QUARTERLY_SHEETS.items()}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _find_latest_publication(query: str, prefix: str) -> dict:
    """Find and fetch the GOV.UK Content API record for the newest matching publication.

    Args:
        query: Free-text GOV.UK Search API query.
        prefix: Required URL prefix a search result's link must start with.

    Returns:
        The Content API JSON for the most recently published match.

    Raises:
        NISRADataNotFoundError: If no publication matches ``prefix``.
    """
    response = session.get(
        SEARCH_API_URL,
        params={"q": query, "count": 50, "fields": "title,link,public_timestamp"},
        timeout=30,
    )
    response.raise_for_status()

    matches = [r for r in response.json().get("results", []) if r.get("link", "").startswith(prefix)]
    if not matches:
        raise NISRADataNotFoundError(f"No GMS publications found matching prefix {prefix!r}")
    matches.sort(key=lambda r: r.get("public_timestamp", ""), reverse=True)

    content = session.get(f"{CONTENT_API_URL}{matches[0]['link']}", timeout=30)
    content.raise_for_status()
    return content.json()


def _find_attachment_url(content: dict, keywords: tuple[str, ...]) -> str:
    """Find an .xlsx attachment whose title contains every keyword.

    Args:
        content: A GOV.UK Content API record.
        keywords: Case-insensitive substrings the attachment title must all contain.

    Returns:
        The attachment's absolute URL.

    Raises:
        NISRADataNotFoundError: If no attachment matches.
    """
    for attachment in content.get("details", {}).get("attachments", []):
        url = attachment.get("url", "")
        title = attachment.get("title", "")
        if url.lower().endswith(".xlsx") and all(kw.lower() in title.lower() for kw in keywords):
            return url
    raise NISRADataNotFoundError(f"No .xlsx attachment matching {keywords} found")


def find_latest_quarterly_url() -> str:
    """Find the URL of the most recent quarterly GMS statistics workbook.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Example:
        >>> find_latest_quarterly_url().endswith(".xlsx")
        True
    """
    content = _find_latest_publication("general medical services statistics ni quarter", _QUARTERLY_PREFIX)
    return _find_attachment_url(content, ("Tables",))


def find_latest_annual_tables_url() -> str:
    """Find the URL of the most recent annual GMS statistics tables workbook.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Example:
        >>> find_latest_annual_tables_url().endswith(".xlsx")
        True
    """
    content = _find_latest_publication("fps general medical services statistics ni", _ANNUAL_PREFIX)
    return _find_attachment_url(content, ("Annual", "Tables"))


def find_latest_registered_patients_url() -> str:
    """Find the URL of the most recent registered-patients-by-practice workbook.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Example:
        >>> find_latest_registered_patients_url().endswith(".xlsx")
        True
    """
    content = _find_latest_publication("fps general medical services statistics ni", _ANNUAL_PREFIX)
    return _find_attachment_url(content, ("Registered", "Patients"))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _sheet_rows(workbook: pd.ExcelFile, sheet_name: str) -> list[list[str]]:
    """Convert one Excel sheet to trimmed string rows for parse_stacked_tables."""
    raw = workbook.parse(sheet_name, header=None).fillna("")
    return [trim_row([str(cell).strip() for cell in row]) for row in raw.itertuples(index=False, name=None)]


def _data_sheets(workbook: pd.ExcelFile, *, skip: AbstractSet[str] = frozenset[str]()) -> list[str]:
    return [name for name in workbook.sheet_names if name.strip().lower() not in _EXCLUDED_SHEETS and name not in skip]


def parse_annual_tables(workbook: pd.ExcelFile) -> pd.DataFrame:
    """Parse every data sheet of the annual GMS workbook into one long frame.

    Args:
        workbook: The annual GMS workbook, e.g. from :func:`find_latest_annual_tables_url`.

    Returns:
        DataFrame with ``sheet``, ``table_id``, ``table_title``, ``row_group``,
        ``row_label``, ``column`` and ``value`` columns. Most sheets carry one
        sub-table per year (the year is in ``table_title``, e.g. "... by LCG
        2014"), with ``row_label`` the geography and ``column`` an
        age/gender/metric breakdown; a few, such as ``2.4``, use ``row_label``
        for the year instead -- see :func:`list_annual_topics`.

    Raises:
        NISRADataNotFoundError: If no data tables are found.
    """
    frames = []
    for sheet_name in _data_sheets(workbook):
        try:
            df = parse_stacked_tables(_sheet_rows(workbook, sheet_name))
        except NISRADataNotFoundError:
            continue
        df["sheet"] = sheet_name
        frames.append(df)

    if not frames:
        raise NISRADataNotFoundError("No data tables found in annual GMS workbook")
    return pd.concat(frames, ignore_index=True)


def parse_quarterly_tables(workbook: pd.ExcelFile) -> pd.DataFrame:
    """Parse every data sheet of the quarterly GMS workbook into one long frame.

    Sheet ``7.1`` (per-practice registered patients) is excluded -- its wide,
    metadata-heavy layout needs :func:`parse_quarterly_patients_by_practice`.

    Args:
        workbook: The quarterly GMS workbook, e.g. from :func:`find_latest_quarterly_url`.

    Returns:
        DataFrame with ``sheet``, ``table_id``, ``table_title``, ``row_group``,
        ``row_label``, ``column`` and ``value`` columns. ``column`` holds a
        financial-quarter label such as ``"Quarter 1 2017/18"``.

    Raises:
        NISRADataNotFoundError: If no data tables are found.
    """
    frames = []
    for sheet_name in _data_sheets(workbook, skip={"7.1"}):
        try:
            df = parse_stacked_tables(_sheet_rows(workbook, sheet_name))
        except NISRADataNotFoundError:
            continue
        df["sheet"] = sheet_name
        frames.append(df)

    if not frames:
        raise NISRADataNotFoundError("No data tables found in quarterly GMS workbook")
    return pd.concat(frames, ignore_index=True)


def parse_registered_patients_by_practice(workbook: pd.ExcelFile) -> pd.DataFrame:
    """Parse the per-year registered-patients-by-practice workbook.

    Each sheet is already a clean header+body table (no stacked markers),
    one per year.

    Args:
        workbook: The registered-patients workbook, e.g. from
            :func:`find_latest_registered_patients_url`.

    Returns:
        DataFrame with ``year``, ``practice_code``, ``practice_name``,
        ``address_1``, ``address_2``, ``address_3``, ``postcode``,
        ``gender`` (uppercase; blank cells and the source's own ``"UNKNOWN"``
        rows both become ``"UNKNOWN"``), ``age_group`` and
        ``registered_patients`` columns.

    Raises:
        NISRADataNotFoundError: If no year sheets are found.
    """
    records: list[dict[str, object]] = []
    for sheet_name in _data_sheets(workbook):
        rows = _sheet_rows(workbook, sheet_name)
        if len(rows) < 2:
            continue
        year_match = _YEAR_RE.search(rows[0][0]) if rows[0] else None
        if not year_match:
            continue
        year = int(year_match.group(1))

        header = [strip_note_refs(cell) for cell in rows[1]]
        for row in rows[2:]:
            if not any(cell.strip() for cell in row):
                continue
            padded = row + [""] * (len(header) - len(row))
            record: dict[str, object] = dict(zip(header, padded, strict=False))
            record["year"] = year
            records.append(record)

    if not records:
        raise NISRADataNotFoundError("No registered-patients-by-practice sheets found")

    df = pd.DataFrame(records).rename(
        columns={
            "Practice": "practice_code",
            "Practice name": "practice_name",
            "Address 1": "address_1",
            "Address 2": "address_2",
            "Address 3": "address_3",
            "Postcode": "postcode",
            "Gender": "gender",
            "Age group": "age_group",
            "Registered patients": "registered_patients",
        }
    )
    df["gender"] = df["gender"].replace("", "UNKNOWN").str.upper()
    df["registered_patients"] = df["registered_patients"].apply(parse_value)
    return df


def _parse_quarter_period(label: str) -> pd.Timestamp | None:
    """Convert a "Quarter N YYYY/YY" column heading to its quarter-end date."""
    match = _QUARTER_COLUMN_RE.match(strip_note_refs(label))
    if not match:
        return None
    quarter, fy_start = int(match.group(1)), int(match.group(2))
    month, day = _QUARTER_END[quarter]
    year = fy_start if quarter != 4 else fy_start + 1
    return pd.Timestamp(year=year, month=month, day=day)


def parse_quarterly_patients_by_practice(workbook: pd.ExcelFile) -> pd.DataFrame:
    """Parse sheet 7.1: registered patients by practice, per financial quarter.

    This sheet carries several metadata label columns (practice, address,
    federation, trust, LGD) followed by one column per financial quarter, so
    it needs its own melt rather than :func:`~bolster.data_sources.health_ni._base.parse_stacked_tables`'s
    numeric-column label/value split, which misreads a numeric practice code
    as a value column.

    Args:
        workbook: The quarterly GMS workbook.

    Returns:
        DataFrame with ``practice_code``, ``practice_name``, ``address_1``,
        ``address_2``, ``address_3``, ``postcode``, ``federation``,
        ``trust``, ``lgd``, ``period`` and ``value`` (registered patients)
        columns.

    Raises:
        NISRADataNotFoundError: If sheet 7.1 or its header row can't be found.
    """
    if "7.1" not in workbook.sheet_names:
        raise NISRADataNotFoundError("Quarterly workbook has no sheet 7.1")

    rows = _sheet_rows(workbook, "7.1")
    header_idx = next((i for i, row in enumerate(rows) if row and row[0] == "Practice number"), None)
    if header_idx is None:
        raise NISRADataNotFoundError("Could not locate the header row in quarterly sheet 7.1")

    header = [strip_note_refs(cell) for cell in rows[header_idx]]
    quarter_start = next((i for i, h in enumerate(header) if _QUARTER_COLUMN_RE.match(h)), len(header))
    label_cols, quarter_cols = header[:quarter_start], header[quarter_start:]

    records: list[dict[str, object]] = []
    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * (len(header) - len(row))
        meta = dict(zip(label_cols, padded[:quarter_start], strict=False))
        for i, quarter_label in enumerate(quarter_cols, start=quarter_start):
            records.append({**meta, "quarter_label": quarter_label, "value": parse_value(padded[i])})

    if not records:
        raise NISRADataNotFoundError("No practice rows found in quarterly sheet 7.1")

    df = pd.DataFrame(records).rename(
        columns={
            "Practice number": "practice_code",
            "Partnership name": "practice_name",
            "Address 1": "address_1",
            "Address 2": "address_2",
            "Address 3": "address_3",
            "Postcode": "postcode",
            "Federation": "federation",
            "Local Commissioning Group": "trust",
            "Local Government District": "lgd",
        }
    )
    df["period"] = df["quarter_label"].map(_parse_quarter_period)
    return df.drop(columns=["quarter_label"])


# ---------------------------------------------------------------------------
# Download wrappers
# ---------------------------------------------------------------------------


def _open_workbook(url: str, force_refresh: bool) -> pd.ExcelFile:
    path = download_file(url, cache_ttl_hours=_CACHE_TTL_HOURS, force_refresh=force_refresh)
    return pd.ExcelFile(path, engine="openpyxl")


def get_latest_quarterly_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the current quarterly GMS workbook.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        See :func:`parse_quarterly_tables`.
    """
    return parse_quarterly_tables(_open_workbook(find_latest_quarterly_url(), force_refresh))


def get_latest_annual_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the current annual GMS workbook.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        See :func:`parse_annual_tables`.
    """
    return parse_annual_tables(_open_workbook(find_latest_annual_tables_url(), force_refresh))


def get_latest_registered_patients_by_practice(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the current registered-patients-by-practice workbook.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        See :func:`parse_registered_patients_by_practice`.
    """
    return parse_registered_patients_by_practice(_open_workbook(find_latest_registered_patients_url(), force_refresh))


def get_latest_quarterly_patients_by_practice(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the current quarter's per-practice patient counts.

    Args:
        force_refresh: Bypass the download cache.

    Returns:
        See :func:`parse_quarterly_patients_by_practice`.
    """
    return parse_quarterly_patients_by_practice(_open_workbook(find_latest_quarterly_url(), force_refresh))


# ---------------------------------------------------------------------------
# Topic accessors
# ---------------------------------------------------------------------------


def list_annual_topics() -> list[tuple[str, str | None]]:
    """List the ``(topic, level)`` pairs accepted by :func:`get_annual_data`.

    Example:
        >>> ("registered_patients", "trust") in list_annual_topics()
        True
    """
    return sorted(_ANNUAL_TOPICS, key=lambda t: (t[0], t[1] or ""))


def list_quarterly_topics() -> list[tuple[str, str | None]]:
    """List the ``(topic, level)`` pairs accepted by :func:`get_quarterly_data`.

    Example:
        >>> ("practices", "trust") in list_quarterly_topics()
        True
    """
    return sorted(_QUARTERLY_TOPICS, key=lambda t: (t[0], t[1] or ""))


def get_annual_data(topic: str, level: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get one annual GMS topic as a raw long frame.

    Args:
        topic: A topic from :func:`list_annual_topics`.
        level: Geography level for that topic (``None`` for topics with a
            single NI-wide/UK-wide breakdown). See :func:`list_annual_topics`
            for valid ``(topic, level)`` pairs.
        force_refresh: Bypass the download cache.

    Returns:
        Long frame with ``table_id``, ``table_title``, ``row_group``,
        ``row_label``, ``column`` and ``value``. Most topics carry one
        sub-table per year (the year is in ``table_title``), with
        ``row_label`` the geography and ``column`` an age/gender/metric
        breakdown; a few, such as ``gps_by_gender_trend``, use ``row_label``
        for the year instead -- check ``table_title`` when using a topic for
        the first time.

    Raises:
        ValueError: If ``(topic, level)`` isn't a valid pair.
        NISRADataNotFoundError: If the workbook or sheet can't be found.

    Example:
        >>> df = get_annual_data("registered_patients", "trust")  # doctest: +SKIP
        >>> "Belfast" in set(df.row_label)  # doctest: +SKIP
        True
    """
    key = (topic, level)
    if key not in _ANNUAL_TOPICS:
        raise ValueError(f"Unknown annual GMS topic {key}; see list_annual_topics()")
    sheet = _ANNUAL_TOPICS[key]
    df = get_latest_annual_data(force_refresh=force_refresh)
    return df[df.sheet == sheet].reset_index(drop=True)


def get_quarterly_data(topic: str, level: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get one quarterly GMS topic as a raw long frame.

    Args:
        topic: A topic from :func:`list_quarterly_topics`.
        level: Geography level for that topic (``None`` for topics with a
            single NI-wide breakdown). See :func:`list_quarterly_topics` for
            valid ``(topic, level)`` pairs.
        force_refresh: Bypass the download cache.

    Returns:
        Long frame with ``table_id``, ``table_title``, ``row_group``,
        ``row_label``, ``column`` (a ``"Quarter N YYYY/YY"`` label) and
        ``value``.

    Raises:
        ValueError: If ``(topic, level)`` isn't a valid pair.
        NISRADataNotFoundError: If the workbook or sheet can't be found.
    """
    key = (topic, level)
    if key not in _QUARTERLY_TOPICS:
        raise ValueError(f"Unknown quarterly GMS topic {key}; see list_quarterly_topics()")
    sheet = _QUARTERLY_TOPICS[key]
    df = get_latest_quarterly_data(force_refresh=force_refresh)
    return df[df.sheet == sheet].reset_index(drop=True)


def _annual_geography_series(topic: str, level: str, force_refresh: bool) -> pd.DataFrame:
    """Reshape an annual topic's one-sub-table-per-year sheet into a tidy period series.

    Picks the topic's "grand total" column (see ``_ANNUAL_TOTAL_COLUMN``) out
    of each year's sub-table and takes the year from ``table_title``, since
    these sheets carry the year per sub-table rather than as a column.
    """
    total_column = _ANNUAL_TOTAL_COLUMN[topic]
    df = get_annual_data(topic, level, force_refresh)
    df = df[df.column == total_column]
    years = df.table_title.str.extract(_YEAR_IN_TITLE_RE)[0]
    out = df.assign(period=pd.to_datetime(years + "-03-31", errors="coerce"))
    out = out[out.period.notna()]
    return out.rename(columns={"row_label": level})[[level, "period", "value"]].reset_index(drop=True)


def get_registered_patients(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get annual registered-patient headcounts by geography.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"federation"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``<level>``, ``period`` (31 March census point) and
        ``value`` columns.

    Example:
        >>> df = get_registered_patients("trust")  # doctest: +SKIP
        >>> df.value.gt(0).all()  # doctest: +SKIP
        True
    """
    return _annual_geography_series("registered_patients", level, force_refresh)


def get_gp_count(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get annual GP headcounts by geography.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"federation"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``<level>``, ``period`` (31 March census point) and
        ``value`` columns.
    """
    return _annual_geography_series("gps", level, force_refresh)


def get_practice_count(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get annual GP practice counts by geography.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"federation"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``<level>``, ``period`` (31 March census point) and
        ``value`` columns.
    """
    return _annual_geography_series("practices", level, force_refresh)


def get_funding_per_patient(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get average BSO funding per registered patient by geography.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"federation"``.
        force_refresh: Bypass the download cache.

    Returns:
        Raw sub-table rows (``table_id``, ``table_title``, ``row_label``,
        ``column``, ``value``) -- each financial-year sub-table already
        carries payment, patient count and average-payment columns together,
        so it isn't reshaped into a single ``value`` series.
    """
    return get_annual_data("funding_per_patient", level, force_refresh)


def get_patient_proximity(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Get registered-patient distance/proximity to the nearest GP practice.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"deprivation_quintile"``.
        force_refresh: Bypass the download cache.

    Returns:
        Raw sub-table rows (``table_id``, ``table_title``, ``row_label``,
        ``column``, ``value``); ``row_label`` holds the geography/quintile
        and ``column`` the distance/proximity metric.
    """
    return get_annual_data("patient_proximity", level, force_refresh)


def get_list_size(level: str = "trust", force_refresh: bool = False) -> pd.DataFrame:
    """Compute the average GP list size (registered patients per GP) by geography.

    GMS's own GP counts (table 2.x) are headcount, not whole-time-equivalent,
    so this runs lower than press figures that adjust for part-time GPs --
    roughly 1,300-1,600 rather than the ~1,900-2,100 a WTE-adjusted figure
    would give. There's no WTE column in the published tables to correct for
    this.

    Args:
        level: ``"trust"``, ``"lgd"`` or ``"federation"``.
        force_refresh: Bypass the download cache.

    Returns:
        DataFrame with ``<level>``, ``period`` and ``list_size`` columns.

    Example:
        >>> df = get_list_size()  # doctest: +SKIP
        >>> df.list_size.between(1000, 3000).all()  # doctest: +SKIP
        True
    """
    patients = get_registered_patients(level, force_refresh).rename(columns={"value": "registered_patients"})
    gps = get_gp_count(level, force_refresh).rename(columns={"value": "gp_count"})
    merged = patients.merge(gps, on=[level, "period"], how="inner")
    merged["list_size"] = merged["registered_patients"] / merged["gp_count"]
    return merged[[level, "period", "list_size"]]


def validate_data(df: pd.DataFrame) -> bool:
    """Check that a GMS frame is structurally sound.

    Works on any frame this module returns: the raw long frames from
    :func:`get_annual_data`/:func:`get_quarterly_data`, the geography-series
    frames from :func:`get_registered_patients`/:func:`get_gp_count`/
    :func:`get_practice_count`/:func:`get_list_size`, or the practice-level
    frames from :func:`parse_registered_patients_by_practice`/
    :func:`parse_quarterly_patients_by_practice`.

    Args:
        df: A GMS DataFrame.

    Returns:
        True if the frame passes every check.

    Raises:
        NISRAValidationError: If the frame is empty or values look implausible.

    Example:
        >>> validate_data(get_list_size())  # doctest: +SKIP
        True
    """
    if df.empty:
        raise NISRAValidationError("GMS data is empty")

    if "value" in df.columns:
        # Counts/amounts can't be negative, but derived "% Change" columns can.
        counted = df if "column" not in df.columns else df[~df.column.str.contains("% Change", case=False, na=False)]
        numeric = pd.to_numeric(counted["value"], errors="coerce").dropna()
        if not numeric.empty and (numeric < 0).any():
            raise NISRAValidationError("GMS data contains negative values")

    if "list_size" in df.columns:
        sizes = df["list_size"].dropna()
        if not sizes.empty and not sizes.between(500, 5000).all():
            raise NISRAValidationError("GMS list-size values are outside a plausible range")

    if "registered_patients" in df.columns:
        counts = pd.to_numeric(df["registered_patients"], errors="coerce").dropna()
        if not counts.empty and (counts < 0).any():
            raise NISRAValidationError("GMS registered-patient counts contain negative values")

    return True
