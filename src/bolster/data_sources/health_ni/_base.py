"""Shared utilities for health-ni.gov.uk data sources.

The Department of Health (DoH) publishes data at https://www.health-ni.gov.uk.
Pages follow a consistent two-step pattern: an article page links to a
publications page, which links to the actual Excel workbook.

This module centralises the base URL constant, shared exceptions, and the
common scraping helpers so individual modules don't duplicate them.

Several DoH series also publish an accessible CSV alongside the workbook, in
which multiple sub-tables are stacked vertically and separated by single-cell
``Table 4A: ...`` marker rows. :func:`parse_csv_tables` reshapes that layout
into one long frame so heterogeneous tables can be queried uniformly.
"""

import csv
import io
import re
from pathlib import Path
from urllib.parse import urljoin

import bs4
import pandas as pd

from bolster.data_sources.nisra._base import (
    NISRADataNotFoundError,
    NISRAValidationError,
    clear_cache,
    download_file,
    make_absolute_url,
)
from bolster.utils.web import session

__all__ = [
    "HEALTH_NI_BASE_URL",
    "NISRADataNotFoundError",
    "NISRAValidationError",
    "clear_cache",
    "download_file",
    "make_absolute_url",
    "find_latest_xlsx",
    "strip_note_refs",
    "parse_value",
    "parse_period_column",
    "parse_csv_tables",
    "list_dated_publications",
    "find_publication_csv",
]

HEALTH_NI_BASE_URL = "https://www.health-ni.gov.uk"

# Footnote markers appear inline in labels, e.g. "Registered Nurses [note 3]"
_NOTE_REF_RE = re.compile(r"\s*\[note\s*\d+\]", re.IGNORECASE)

# Sub-tables are introduced by a single-cell "Table 4A: <title>" row. Some
# bulletins use a dash instead of a colon, e.g. "Table 7B - Joiners ...".
_TABLE_MARKER_RE = re.compile(r"^Table\s*(\d+)\s*([A-Za-z])?\s*[:\-–]\s*(.+)$")

# Bracketed codes used by the Government Statistical Service for absent values:
# z = not applicable, c = suppressed, x = unavailable, w = no data, u = unreliable
_SUPPRESSION_RE = re.compile(r"^\[[a-z]\]$", re.IGNORECASE)

# Quarter-end column headings, e.g. "31 Mar 2017"
_DATE_COLUMN_RE = re.compile(r"^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}$")

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def strip_note_refs(text: str) -> str:
    """Remove footnote markers and normalise whitespace in a label.

    Args:
        text: Raw cell text, possibly containing ``[note N]`` markers,
            non-breaking spaces, or embedded newlines from a wrapped header.

    Returns:
        The cleaned label.

    Example:
        >>> strip_note_refs("Registered Nurses [note 3]")
        'Registered Nurses'
        >>> strip_note_refs("Pay bands 8   & above")
        'Pay bands 8 & above'
    """
    cleaned = _NOTE_REF_RE.sub("", str(text).replace("\xa0", " "))
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_value(text: str) -> float | None:
    """Parse a numeric cell, returning ``None`` for blanks and suppressions.

    Handles comma-grouped thousands and percentages. Percentages are returned
    as proportions so that a rate is always in ``[0, 1]``.

    Args:
        text: Raw cell text.

    Returns:
        The numeric value, or ``None`` if the cell is blank, a suppression
        marker such as ``[z]``, or otherwise non-numeric.

    Example:
        >>> parse_value("63,247.8")
        63247.8
        >>> parse_value("4.3%")
        0.043
        >>> parse_value("[z]") is None
        True
    """
    cleaned = str(text).replace("\xa0", " ").strip()
    if not cleaned or _SUPPRESSION_RE.match(cleaned) or cleaned in {"-", "..", "*"}:
        return None

    percentage = cleaned.endswith("%")
    cleaned = cleaned.removesuffix("%").replace(",", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value / 100 if percentage else value


def parse_period_column(text: str) -> pd.Timestamp | None:
    """Convert a period column heading to a timestamp.

    Headings appear in two shapes: a bare year, which always denotes the
    31 March census point, and a full quarter-end date. Financial-year
    headings such as ``2020/21`` are not points in time and return ``None``.

    Args:
        text: Column heading.

    Returns:
        The period the column refers to, or ``None`` if it is not a date.

    Example:
        >>> parse_period_column("2026").strftime("%Y-%m-%d")
        '2026-03-31'
        >>> parse_period_column("30 Jun 2017").strftime("%Y-%m-%d")
        '2017-06-30'
        >>> parse_period_column("2020/21") is None
        True
    """
    label = strip_note_refs(text)
    if re.fullmatch(r"\d{4}", label):
        return pd.Timestamp(year=int(label), month=3, day=31)
    if _DATE_COLUMN_RE.match(label):
        return pd.Timestamp(label)
    return None


def _trim(row: list[str]) -> list[str]:
    """Drop trailing empty cells left behind by spreadsheet autofill."""
    trimmed = list(row)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _label_column_count(body: list[list[str]]) -> int:
    """Count the leading columns holding labels rather than values.

    Most tables carry a single label column, but cross-tabs such as vacancies
    by profession carry two. A column is a label column when no cell in it is
    numeric or a suppression marker, and at least one cell is populated. Blanks
    are tolerated because total rows often leave the inner label empty.

    Args:
        body: Data rows of one table block.

    Returns:
        Number of leading label columns, always at least 1, and always leaving
        at least one value column.
    """
    width = max(len(row) for row in body)
    count = 0
    for column in range(width - 1):
        cells = [row[column].strip() if column < len(row) else "" for row in body]
        if any(cell for cell in cells) and not any(
            _SUPPRESSION_RE.match(cell) or parse_value(cell) is not None for cell in cells
        ):
            count += 1
        else:
            break
    return max(count, 1)


def _split_blocks(rows: list[list[str]]) -> list[tuple[str, str, list[list[str]]]]:
    """Split a CSV into ``(table_id, table_title, rows)`` blocks.

    Args:
        rows: All rows of the CSV, already trimmed of trailing empty cells.

    Returns:
        One tuple per sub-table introduced by a ``Table N:`` marker row.
        Content before the first marker is ignored.
    """
    blocks: list[tuple[str, str, list[list[str]]]] = []
    current: tuple[str, str] | None = None
    pending: list[list[str]] = []

    for row in rows:
        if len(row) == 1:
            match = _TABLE_MARKER_RE.match(row[0].strip())
            if match:
                if current:
                    blocks.append((*current, pending))
                current = (f"{match.group(1)}{(match.group(2) or '').upper()}", strip_note_refs(match.group(3)))
                pending = []
            continue
        if current:
            pending.append(row)

    if current:
        blocks.append((*current, pending))
    return blocks


def parse_csv_tables(path: Path | str) -> pd.DataFrame:
    """Parse a stacked multi-table DoH CSV into a long frame.

    Args:
        path: Path to the downloaded CSV.

    Returns:
        DataFrame with ``table_id``, ``table_title``, ``row_group``,
        ``row_label``, ``column`` and ``value`` columns. ``row_group`` holds
        the outer category when a table has two label columns and is ``None``
        otherwise; ``row_label`` is always the innermost row label.

    Raises:
        NISRADataNotFoundError: If the file cannot be read or holds no tables.
    """
    try:
        text = Path(path).read_bytes().decode("utf-8-sig", errors="replace")
    except OSError as e:
        raise NISRADataNotFoundError(f"Failed to read {path}: {e}") from e

    rows = [_trim(row) for row in csv.reader(io.StringIO(text))]

    records: list[dict[str, object]] = []
    for table_id, table_title, block in _split_blocks(rows):
        if len(block) < 2:
            continue

        header = [strip_note_refs(cell) for cell in block[0]]
        body = block[1:]
        label_count = _label_column_count(body)

        for row in body:
            padded = row + [""] * (len(header) - len(row))
            labels = [strip_note_refs(padded[i]) for i in range(label_count)]
            if not any(labels):
                continue
            for column in range(label_count, len(header)):
                name = header[column]
                if not name:
                    continue
                records.append(
                    {
                        "table_id": table_id,
                        "table_title": table_title,
                        "row_group": labels[0] if label_count > 1 else None,
                        "row_label": labels[-1] or labels[0],
                        "column": name,
                        "value": parse_value(padded[column]),
                    }
                )

    if not records:
        raise NISRADataNotFoundError(f"No data tables found in {path}")

    return pd.DataFrame(records)


def list_dated_publications(index_url: str, slug_pattern: str) -> pd.DataFrame:
    """List publications linked from an article index page.

    Args:
        index_url: Article page listing the series, e.g.
            ``https://www.health-ni.gov.uk/articles/staff-numbers``.
        slug_pattern: Regex matched against each publication href. It must
            capture the month name and the four-digit year, in that order.

    Returns:
        DataFrame with ``period`` (month-start Timestamp), ``title`` and
        ``url`` columns, most recent first.

    Raises:
        NISRADataNotFoundError: If the page cannot be fetched or no
            publication matches.
    """
    try:
        response = session.get(index_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch {index_url}: {e}") from e

    pattern = re.compile(slug_pattern, re.IGNORECASE)
    soup = bs4.BeautifulSoup(response.content, "html.parser")

    records: dict[str, dict[str, object]] = {}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        match = pattern.search(href)
        if "/publications/" not in href or not match:
            continue
        month, year = match.group(1).lower(), int(match.group(2))
        url = urljoin(HEALTH_NI_BASE_URL, href)
        records.setdefault(
            url,
            {
                "period": pd.Timestamp(year=year, month=_MONTHS.index(month) + 1, day=1),
                "title": link.get_text(strip=True),
                "url": url,
            },
        )

    if not records:
        raise NISRADataNotFoundError(f"No publications matching {slug_pattern!r} found on {index_url}")

    return pd.DataFrame(list(records.values())).sort_values("period", ascending=False).reset_index(drop=True)


def find_publication_csv(publication_url: str, keyword: str | None = None) -> str:
    """Find the CSV attachment on a publication page.

    Args:
        publication_url: Publication page URL.
        keyword: Optional case-insensitive substring the filename must
            contain, used when a page carries several CSVs.

    Returns:
        Absolute URL of the CSV.

    Raises:
        NISRADataNotFoundError: If the page cannot be fetched or has no
            matching CSV.
    """
    try:
        response = session.get(publication_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRADataNotFoundError(f"Failed to fetch {publication_url}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.lower().endswith(".csv"):
            continue
        if keyword and keyword.lower() not in href.lower():
            continue
        return make_absolute_url(href, HEALTH_NI_BASE_URL)

    detail = f" matching {keyword!r}" if keyword else ""
    raise NISRADataNotFoundError(f"No CSV{detail} found on {publication_url}")


def find_latest_xlsx(article_url: str, keyword: str | None = None) -> str:
    """Return the .xlsx URL found by following an article → publications → file path.

    Fetches *article_url*, finds the first link whose href contains
    ``"/publications/"`` (and optionally *keyword*), fetches that page, then
    returns the first ``.xlsx`` href found there.

    Args:
        article_url: The health-ni article landing page URL.
        keyword: Optional substring that must appear in the publications href
            (e.g. ``"inpatient-and-day-case"``).  If ``None``, the first
            ``/publications/`` link is used.

    Returns:
        Absolute URL of the Excel workbook.

    Raises:
        NISRADataNotFoundError: If either page fetch fails or no xlsx is found.
    """
    from bs4 import BeautifulSoup

    try:
        resp = session.get(article_url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {article_url}: {exc}") from exc

    soup = BeautifulSoup(resp.content, "html.parser")
    pub_url: str | None = None
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "/publications/" in href and (keyword is None or keyword in href):
            pub_url = make_absolute_url(href, HEALTH_NI_BASE_URL)
            break

    if pub_url is None:
        detail = f" containing '{keyword}'" if keyword else ""
        raise NISRADataNotFoundError(f"No publications link{detail} found on {article_url}")

    try:
        pub_resp = session.get(pub_url, timeout=30)
        pub_resp.raise_for_status()
    except Exception as exc:
        raise NISRADataNotFoundError(f"Failed to fetch {pub_url}: {exc}") from exc

    pub_soup = BeautifulSoup(pub_resp.content, "html.parser")
    for a in pub_soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".xlsx"):
            return make_absolute_url(href, HEALTH_NI_BASE_URL)

    raise NISRADataNotFoundError(f"No .xlsx link found on {pub_url}")
