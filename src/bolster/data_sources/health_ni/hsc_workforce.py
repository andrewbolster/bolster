"""NI Health and Social Care (HSC) Workforce Statistics module.

Provides access to the Department of Health's quarterly HSC workforce
statistics, covering staff numbers across Northern Ireland's health and social
care system by staff group, HSC organisation, and Agenda for Change pay band.

Each quarterly publication contains a **six-year time series at that quarter
point** (e.g. the March 2026 release covers 31 March 2021 to 31 March 2026),
so fetching all published quarters yields roughly two dozen distinct reference
dates rather than four.

The source workbook contains several differently-shaped tables. They are
flattened into a single tidy frame, with the ``table`` column identifying the
dimension combination each row came from:

===============================  ===========================================
``table``                        Contents
===============================  ===========================================
``summary``                      Headline WTE, active posts, headcount
``staff_group``                  WTE by staff group (9 groups + Total)
``sub_staff_group``              WTE by sub staff group / profession
``organisation``                 WTE by HSC organisation (16 orgs + Total)
``organisation_staff_group``     WTE by trust x staff group (current quarter)
``other_organisation_staff_group``  Same, decomposing "Other HSC Organisations"
``pay_band``                     Share of WTE by Agenda for Change pay band
``leavers``                      Annual leavers and leaving rate
``joiners``                      Annual joiners and joining rate
``stability``                    Annual workforce stability rate
===============================  ===========================================

``organisation_staff_group`` and ``other_organisation_staff_group`` overlap:
the latter decomposes the former's ``Other HSC Organisations`` row. Never sum
across both.

The ``leavers``/``joiners``/``stability`` tables are published only in the
March release and are reported by financial year, so their ``date`` is the
31 March that ends the financial year.

HSC Trusts:
    Belfast, Northern, South Eastern, Southern, Western, NI Ambulance Service

Original data source:
    https://www.health-ni.gov.uk/articles/staff-numbers

Update Frequency:
    Quarterly, published approximately 2-3 months after the reference date.

Example:
    >>> from bolster.data_sources.health_ni import hsc_workforce
    >>> df = hsc_workforce.get_latest_data()
    >>> sorted(df.columns.tolist())
    ['date', 'grade_band', 'measure', 'organisation', 'quarter', 'staff_group', 'table', 'value', 'year']

    >>> hsc_workforce.validate_data(df)
    True

Publication Details:
    - Frequency: Quarterly (March, June, September, December reference dates)
    - Published by: Department of Health NI
    - Source: https://www.health-ni.gov.uk/articles/staff-numbers
"""

import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import (
    HEALTH_NI_BASE_URL,
    NISRADataNotFoundError,
    NISRAValidationError,
    download_file,
    make_absolute_url,
)

logger = logging.getLogger(__name__)

HSC_WORKFORCE_PAGE = "https://www.health-ni.gov.uk/articles/staff-numbers"

#: Reference month for each quarterly publication slug.
PUBLICATION_MONTHS = {"march": 3, "june": 6, "september": 9, "december": 12}

#: Calendar quarter for each reference month.
MONTH_QUARTERS = {3: 1, 6: 2, 9: 3, 12: 4}

#: Workbook table number -> ``table`` dimension label.
TABLE_DIMENSIONS = {
    "1": "summary",
    "2A": "staff_group",
    "2B": "sub_staff_group",
    "3": "organisation",
    "4": "organisation_staff_group",
    "5": "other_organisation_staff_group",
    "6": "pay_band",
    "7A": "leavers",
    "7B": "joiners",
    "7C": "stability",
}

#: Row labels in Tables 1 and 7 mapped to canonical measure slugs.
MEASURE_LABELS = {
    "wte": "wte",
    "active posts": "active_posts",
    "individuals with multiple posts": "individuals_multiple_posts",
    "headcount": "headcount",
    "staff in post (headcount)": "staff_in_post",
    "leavers": "leavers",
    "leaving rate (%)": "leaving_rate",
    "joiners": "joiners",
    "joining rate (%)": "joining_rate",
    "staff in hsc employment 1 year before": "staff_year_before",
    "annual workforce stability rate (%)": "stability_rate",
}

#: Measures expressed as a proportion in the range [0, 1].
RATE_MEASURES = {"percent_wte", "leaving_rate", "joining_rate", "stability_rate"}

#: Column order of the tidy output frame.
COLUMNS = [
    "date",
    "year",
    "quarter",
    "table",
    "measure",
    "organisation",
    "staff_group",
    "grade_band",
    "value",
]

REQUIRED_COLUMNS = set(COLUMNS)

_NOTE_RE = re.compile(r"\s*\[note[^\]]*\]", re.IGNORECASE)
_TABLE_TITLE_RE = re.compile(r"^Tables?\s*(\d+[A-Za-z]?)\s*[-–:]", re.IGNORECASE)
_PUBLICATION_SLUG_RE = re.compile(r"workforce-statistics-(march|june|september|december)-(\d{4})", re.IGNORECASE)
_FINANCIAL_YEAR_RE = re.compile(r"^(\d{4})/(\d{2})$")


def _clean_label(value: object) -> str | None:
    r"""Normalise a spreadsheet label into a stable comparable string.

    Strips ``[note N]`` footnote references, collapses embedded newlines and
    repeated whitespace, and normalises curly punctuation to ASCII.

    Args:
        value: Raw cell value from the workbook.

    Returns:
        Cleaned label, or ``None`` if the cell is blank.

    Example:
        >>> _clean_label("Nursing & Midwifery Support [note 1]")
        'Nursing & Midwifery Support'
        >>> _clean_label("Pay bands 8 \n& above")
        'Pay bands 8 & above'
        >>> _clean_label(None) is None
        True
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).replace("’", "'").replace("–", "-")
    text = _NOTE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _period_end(year: int, month: int) -> pd.Timestamp:
    """Return the last calendar day of *month* in *year*.

    Args:
        year: Four-digit calendar year.
        month: Month number (1-12).

    Returns:
        Timestamp for the final day of that month.

    Example:
        >>> _period_end(2026, 3).strftime("%Y-%m-%d")
        '2026-03-31'
    """
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def _as_year(value: object) -> int | None:
    """Return *value* as a plausible calendar year, or ``None``.

    Workbook year headers arrive as floats (``2021.0``); non-year headers such
    as ``"% Change 2021 to 2026"`` are rejected.

    Args:
        value: Raw header cell value.

    Returns:
        The year as an ``int``, or ``None`` if the cell is not a year.

    Example:
        >>> _as_year(2021.0)
        2021
        >>> _as_year("% Change 2021 to 2026") is None
        True
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        year = int(float(value))
    except (TypeError, ValueError):
        return None
    return year if 1990 <= year <= 2100 else None


def _as_financial_year_end(value: object) -> int | None:
    """Return the calendar year in which a ``YYYY/YY`` financial year ends.

    Args:
        value: Raw header cell value, e.g. ``"2025/26"``.

    Returns:
        The ending calendar year, or ``None`` if *value* is not a financial year.

    Example:
        >>> _as_financial_year_end("2025/26")
        2026
        >>> _as_financial_year_end("Leavers") is None
        True
    """
    text = _clean_label(value)
    if text is None:
        return None
    match = _FINANCIAL_YEAR_RE.match(text)
    return int(match.group(1)) + 1 if match else None


def _as_measure(label: str | None) -> str | None:
    """Map a Table 1 or Table 7 row label to a canonical measure slug.

    Args:
        label: Cleaned row label.

    Returns:
        Canonical measure slug, or ``None`` if the label is blank.

    Example:
        >>> _as_measure("Individuals with multiple posts")
        'individuals_multiple_posts'
        >>> _as_measure("Some New Measure")
        'some_new_measure'
    """
    if label is None:
        return None
    known = MEASURE_LABELS.get(label.lower())
    if known is not None:
        return known
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def list_publications() -> list[dict]:
    """List the quarterly HSC workforce publications linked from the article page.

    Returns:
        List of dictionaries sorted oldest-first, each with keys ``url``
        (publication page URL), ``period`` (e.g. ``"march-2026"``), ``date``
        (reference date as a Timestamp), ``year`` and ``quarter``.

    Raises:
        NISRADataNotFoundError: If the article page cannot be fetched or lists
            no quarterly publications.

    Example:
        >>> pubs = list_publications()
        >>> all(p["quarter"] in (1, 2, 3, 4) for p in pubs)
        True
    """
    try:
        resp = session.get(HSC_WORKFORCE_PAGE, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {HSC_WORKFORCE_PAGE}: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")
    publications: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        match = _PUBLICATION_SLUG_RE.search(anchor["href"])
        if match is None:
            continue
        url = make_absolute_url(anchor["href"], HEALTH_NI_BASE_URL)
        if url in publications:
            continue
        month = PUBLICATION_MONTHS[match.group(1).lower()]
        year = int(match.group(2))
        publications[url] = {
            "url": url,
            "period": f"{match.group(1).lower()}-{year}",
            "date": _period_end(year, month),
            "year": year,
            "quarter": MONTH_QUARTERS[month],
        }

    if not publications:
        raise NISRADataNotFoundError(f"No quarterly workforce publications found on {HSC_WORKFORCE_PAGE}")

    return sorted(publications.values(), key=lambda pub: pub["date"])


def find_publication_xlsx(publication_url: str) -> str:
    """Return the workbook URL linked from a quarterly publication page.

    Args:
        publication_url: A publication page URL from :func:`list_publications`.

    Returns:
        Absolute URL of the ``.xlsx`` workbook.

    Raises:
        NISRADataNotFoundError: If the page cannot be fetched or has no
            ``.xlsx`` link.
    """
    try:
        resp = session.get(publication_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {publication_url}: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")
    for anchor in soup.find_all("a", href=True):
        if anchor["href"].lower().endswith(".xlsx"):
            return make_absolute_url(anchor["href"], HEALTH_NI_BASE_URL)

    raise NISRADataNotFoundError(f"No .xlsx link found on {publication_url}")


def _iter_table_blocks(raw: pd.DataFrame):
    """Split a raw sheet into ``(table_id, header, body)`` blocks.

    Sheets may stack several tables (e.g. ``Tables 2A to 2B``). Each block
    starts at a ``Table N:`` title in the first column; the row beneath it is
    the header and the rows after that are the body.

    Args:
        raw: Sheet read with ``header=None``.

    Yields:
        Tuples of table identifier (e.g. ``"2A"``), header Series, and body
        DataFrame with all-blank rows removed.
    """
    titles: list[tuple[int, str]] = []
    for position, value in enumerate(raw.iloc[:, 0]):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        match = _TABLE_TITLE_RE.match(str(value).strip())
        if match is not None:
            titles.append((position, match.group(1).upper()))

    for index, (start, table_id) in enumerate(titles):
        end = titles[index + 1][0] if index + 1 < len(titles) else len(raw)
        if start + 2 >= end:
            continue
        header = raw.iloc[start + 1]
        body = raw.iloc[start + 2 : end].dropna(how="all")
        yield table_id, header, body


def _parse_year_series(header: pd.Series, body: pd.DataFrame, table: str, month: int) -> list[dict]:
    """Parse a table whose rows are labels and columns are calendar years.

    Covers Tables 1, 2A, 2B and 3. ``% Change`` columns are ignored.

    Args:
        header: Header row of the block.
        body: Body rows of the block.
        table: ``table`` dimension label for the output rows.
        month: Reference month of the publication (used to date each year column).

    Returns:
        List of tidy record dictionaries.
    """
    year_columns = {col: year for col, value in header.items() if col != 0 and (year := _as_year(value)) is not None}
    dimension = {"summary": "measure", "organisation": "organisation"}.get(table, "staff_group")

    records: list[dict] = []
    for _, row in body.iterrows():
        label = _clean_label(row[0])
        if label is None:
            continue
        for column, year in year_columns.items():
            value = pd.to_numeric(row[column], errors="coerce")
            if pd.isna(value):
                continue
            date = _period_end(year, month)
            records.append(
                {
                    "date": date,
                    "year": year,
                    "quarter": MONTH_QUARTERS[month],
                    "table": table,
                    "measure": _as_measure(label) if dimension == "measure" else "wte",
                    "organisation": label if dimension == "organisation" else None,
                    "staff_group": label if dimension == "staff_group" else None,
                    "grade_band": None,
                    "value": float(value),
                }
            )
    return records


def _parse_cross_tab(header: pd.Series, body: pd.DataFrame, table: str, date: pd.Timestamp) -> list[dict]:
    """Parse a table whose rows and columns are both dimensions.

    Covers Tables 4 and 5 (organisation x staff group) and Table 6
    (staff group x pay band). Table 6 values are proportions of WTE, except
    its trailing ``Total WTE`` column which is an absolute WTE count.

    Args:
        header: Header row of the block.
        body: Body rows of the block.
        table: ``table`` dimension label for the output rows.
        date: Reference date of the publication.

    Returns:
        List of tidy record dictionaries.
    """
    by_pay_band = table == "pay_band"
    column_labels = {col: label for col, value in header.items() if col != 0 and (label := _clean_label(value))}

    records: list[dict] = []
    for _, row in body.iterrows():
        row_label = _clean_label(row[0])
        if row_label is None:
            continue
        for column, column_label in column_labels.items():
            value = pd.to_numeric(row[column], errors="coerce")
            if pd.isna(value):
                continue
            is_total_wte = by_pay_band and column_label == "Total WTE"
            records.append(
                {
                    "date": date,
                    "year": int(date.year),
                    "quarter": MONTH_QUARTERS[date.month],
                    "table": table,
                    "measure": "wte" if (is_total_wte or not by_pay_band) else "percent_wte",
                    "organisation": None if by_pay_band else row_label,
                    "staff_group": row_label if by_pay_band else column_label,
                    "grade_band": None if (is_total_wte or not by_pay_band) else column_label,
                    "value": float(value),
                }
            )
    return records


def _parse_financial_year(header: pd.Series, body: pd.DataFrame, table: str) -> list[dict]:
    """Parse a Table 7 block reported by financial year.

    Rows are measures; columns are ``YYYY/YY`` financial years. Each column is
    dated to the 31 March that ends the financial year.

    Args:
        header: Header row of the block.
        body: Body rows of the block.
        table: ``table`` dimension label (``leavers``, ``joiners`` or ``stability``).

    Returns:
        List of tidy record dictionaries.
    """
    year_columns = {
        col: year for col, value in header.items() if col != 0 and (year := _as_financial_year_end(value)) is not None
    }

    records: list[dict] = []
    for _, row in body.iterrows():
        measure = _as_measure(_clean_label(row[0]))
        if measure is None:
            continue
        for column, year in year_columns.items():
            value = pd.to_numeric(row[column], errors="coerce")
            if pd.isna(value):
                continue
            records.append(
                {
                    "date": _period_end(year, 3),
                    "year": year,
                    "quarter": 1,
                    "table": table,
                    "measure": measure,
                    "organisation": None,
                    "staff_group": None,
                    "grade_band": None,
                    "value": float(value),
                }
            )
    return records


def parse_workbook(file_path: str | Path, period_date: pd.Timestamp) -> pd.DataFrame:
    """Parse one quarterly HSC workforce workbook into tidy long format.

    Args:
        file_path: Path to a downloaded ``.xlsx`` workbook.
        period_date: Reference date of the publication (e.g. 2026-03-31).
            Used to date the year columns of the time-series tables and to
            date the current-quarter cross-tab tables.

    Returns:
        Long-format DataFrame with the columns listed in :data:`COLUMNS`.

    Raises:
        NISRAValidationError: If no recognised tables are found in the workbook.
    """
    with pd.ExcelFile(file_path) as workbook:
        sheet_names = workbook.sheet_names

    records: list[dict] = []
    for sheet in sheet_names:
        if sheet.lower().startswith(("cover", "notes", "source")):
            continue
        raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
        for table_id, header, body in _iter_table_blocks(raw):
            table = TABLE_DIMENSIONS.get(table_id)
            if table is None:
                logger.warning(f"Unrecognised table '{table_id}' on sheet '{sheet}' — skipping")
                continue
            if table in {"leavers", "joiners", "stability"}:
                records.extend(_parse_financial_year(header, body, table))
            elif table in {"organisation_staff_group", "other_organisation_staff_group", "pay_band"}:
                records.extend(_parse_cross_tab(header, body, table, period_date))
            else:
                records.extend(_parse_year_series(header, body, table, period_date.month))

    if not records:
        raise NISRAValidationError(f"No recognised workforce tables found in {file_path}")

    return pd.DataFrame.from_records(records, columns=COLUMNS)


def get_latest_data(force_refresh: bool = False) -> pd.DataFrame:
    """Download and combine every published quarterly HSC workforce release.

    Each release carries a six-year series at its own quarter point, so the
    combined frame spans considerably more history than the handful of
    publications currently listed.

    Args:
        force_refresh: If ``True``, bypass the on-disk cache and re-download.

    Returns:
        Tidy long-format DataFrame with columns:

        - ``date`` (datetime): Reference date (quarter end)
        - ``year`` (int): Calendar year of the reference date
        - ``quarter`` (int): Calendar quarter, 1-4
        - ``table`` (str): Source table dimension (see module docstring)
        - ``measure`` (str): ``wte``, ``headcount``, ``percent_wte``, etc.
        - ``organisation`` (str or None): HSC organisation, where applicable
        - ``staff_group`` (str or None): Staff group or profession
        - ``grade_band`` (str or None): Agenda for Change pay band
        - ``value`` (float): The observed value

    Raises:
        NISRADataNotFoundError: If no publications or workbooks can be located.
        NISRAValidationError: If the combined data fails validation.
    """
    frames = []
    for publication in list_publications():
        url = find_publication_xlsx(publication["url"])
        logger.info(f"Downloading HSC workforce workbook for {publication['period']} from {url}")
        file_path = download_file(url, force_refresh=force_refresh)
        frames.append(parse_workbook(file_path, publication["date"]))

    df = pd.concat(frames, ignore_index=True)
    dimensions = ["date", "table", "measure", "organisation", "staff_group", "grade_band"]
    df = (
        df.drop_duplicates(subset=dimensions, keep="last")
        .sort_values(["date", "table", "measure", "organisation", "staff_group", "grade_band"], na_position="first")
        .reset_index(drop=True)
    )
    validate_data(df)
    return df


def get_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Return the headline workforce totals (Table 1).

    Args:
        df: DataFrame from :func:`get_latest_data`.

    Returns:
        Rows where ``table == "summary"``, covering WTE, active posts,
        individuals with multiple posts, and headcount.
    """
    return df[df["table"] == "summary"].reset_index(drop=True)


def get_staff_groups(df: pd.DataFrame, include_total: bool = False) -> pd.DataFrame:
    """Return WTE by staff group (Table 2A).

    Args:
        df: DataFrame from :func:`get_latest_data`.
        include_total: If ``True``, retain the ``Total`` row.

    Returns:
        Rows where ``table == "staff_group"``.
    """
    subset = df[df["table"] == "staff_group"]
    if not include_total:
        subset = subset[subset["staff_group"] != "Total"]
    return subset.reset_index(drop=True)


def get_organisations(df: pd.DataFrame, include_total: bool = False) -> pd.DataFrame:
    """Return WTE by HSC organisation (Table 3).

    Args:
        df: DataFrame from :func:`get_latest_data`.
        include_total: If ``True``, retain the ``Total`` row.

    Returns:
        Rows where ``table == "organisation"``.
    """
    subset = df[df["table"] == "organisation"]
    if not include_total:
        subset = subset[subset["organisation"] != "Total"]
    return subset.reset_index(drop=True)


def get_pay_bands(df: pd.DataFrame) -> pd.DataFrame:
    """Return the share of WTE by Agenda for Change pay band (Table 6).

    Args:
        df: DataFrame from :func:`get_latest_data`.

    Returns:
        Rows where ``table == "pay_band"`` and ``measure == "percent_wte"``.
        Each staff group's proportions sum to 1.
    """
    subset = df[(df["table"] == "pay_band") & (df["measure"] == "percent_wte")]
    return subset.reset_index(drop=True)


def get_turnover(df: pd.DataFrame) -> pd.DataFrame:
    """Return annual joiner, leaver and stability figures (Tables 7A-7C).

    Only published in the March release, and reported by financial year.

    Args:
        df: DataFrame from :func:`get_latest_data`.

    Returns:
        Rows where ``table`` is one of ``leavers``, ``joiners`` or ``stability``.
    """
    return df[df["table"].isin({"leavers", "joiners", "stability"})].reset_index(drop=True)


def list_staff_groups(df: pd.DataFrame) -> list[str]:
    """Return the sorted staff group names present in *df*.

    Args:
        df: DataFrame from :func:`get_latest_data`.

    Returns:
        Sorted list of staff group labels, excluding ``Total``.
    """
    values = df.loc[df["table"] == "staff_group", "staff_group"].dropna().unique()
    return sorted(value for value in values if value != "Total")


def list_organisations(df: pd.DataFrame) -> list[str]:
    """Return the sorted HSC organisation names present in *df*.

    Args:
        df: DataFrame from :func:`get_latest_data`.

    Returns:
        Sorted list of organisation labels, excluding ``Total``.
    """
    values = df.loc[df["table"] == "organisation", "organisation"].dropna().unique()
    return sorted(value for value in values if value != "Total")


def validate_data(df: pd.DataFrame, min_records: int = 1000) -> bool:
    """Validate an HSC workforce DataFrame against quality expectations.

    Args:
        df: DataFrame from :func:`get_latest_data` or :func:`parse_workbook`.
        min_records: Minimum acceptable row count.

    Returns:
        ``True`` if all checks pass.

    Raises:
        NISRAValidationError: If the frame is empty, missing required columns,
            too small, contains unknown ``table`` labels, has negative values,
            or has rate measures outside the range [0, 1].
    """
    if df is None or len(df) == 0:
        raise NISRAValidationError("HSC workforce DataFrame is empty")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    if len(df) < min_records:
        raise NISRAValidationError(f"Expected at least {min_records} records, got {len(df)}")

    unknown = set(df["table"].dropna().unique()) - set(TABLE_DIMENSIONS.values())
    if unknown:
        raise NISRAValidationError(f"Unknown table labels: {sorted(unknown)}")

    values = df["value"].dropna()
    if (values < 0).any():
        raise NISRAValidationError(f"value contains negative entries; min = {values.min()}")

    rates = df.loc[df["measure"].isin(RATE_MEASURES), "value"].dropna()
    if len(rates) > 0 and rates.max() > 1:
        raise NISRAValidationError(f"Rate measures must be proportions in [0, 1]; max = {rates.max()}")

    return True
