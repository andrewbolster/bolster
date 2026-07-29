"""PPS Statistical Bulletin: prosecution caseload, decisions and court outcomes.

Provides access to the annual statistical bulletin of the Public Prosecution
Service for Northern Ireland (PPS), covering the whole prosecution pipeline:
files arriving from police, the decisions PPS issues on them, and how the
resulting defendants fare in court.

Five datasets are available:

- **Files received** - files arriving from police by file type and PPS region
  (Table 1a).
- **Files by offence** - police files broken down by offence classification,
  with each offence's share of the total (Table 1b).
- **Files from agencies** - files submitted by bodies other than the police,
  e.g. Companies House or the Police Ombudsman (Table 1c).
- **Prosecutorial decisions** - decisions issued by type: prosecution,
  diversion (caution, informed warning, youth conference) or no prosecution
  (Table 3a), plus the reasons given for no prosecution (Table 3b).
- **Court outcomes** - defendants dealt with in the Crown Court and in the
  Magistrates' and Youth Courts, by outcome (Tables 5a and 5b).

Each bulletin edition reports two financial years side by side, so the default
fetch returns the latest year and its immediate predecessor.

Data Source:
    **Publication Page**: https://www.ppsni.gov.uk/pps-statistical-bulletin

    The module scrapes this page for per-year publication pages, then finds the
    ``.xlsx`` tables workbook attached to each.

Update Frequency: Annual (financial year, published the following summer).
    Production moved from quarterly to annual after user review.
Geographic Coverage: Northern Ireland, by PPS region
Reference Period: 2021/22 - present (earlier bulletins are PDF only)

.. warning::

    PPS moved to a three-region model in Autumn 2025. Regional figures for
    2025/26 onwards are **not** comparable with the two-region breakdown used
    up to 2024/25. The ``All PPS`` totals remain comparable throughout.

Suppressed cells are published as ``*``, ``#`` or ``-`` and are parsed as
``None`` rather than zero.

This pairs with :mod:`bolster.data_sources.justice.nicts_quarterly` for the
court-disposal stage that follows a decision to prosecute.

Example:
    >>> from bolster.data_sources.justice import pps_statistical_bulletin as pps
    >>> df = pps.get_prosecutorial_decisions()
    >>> "decision_type" in df.columns
    True
    >>> bool((df["region"] == "All PPS").any())
    True
"""

import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import bs4
import pandas as pd

from bolster.utils.cache import CachedDownloader, DownloadError
from bolster.utils.web import session

logger = logging.getLogger(__name__)

# Landing page listing every bulletin edition, newest first
PUBLICATION_URL = "https://www.ppsni.gov.uk/pps-statistical-bulletin"

# Worksheet names within the tables workbook
SHEET_FILES_RECEIVED = "Table 1A"
SHEET_FILES_BY_OFFENCE = "Table 1B"
SHEET_FILES_FROM_AGENCIES = "Table 1C"
SHEET_DECISIONS = "Table 3A"
SHEET_NO_PROSECUTION = "Table 3B"
SHEET_CROWN_COURT = "Table 5A"
SHEET_MAGISTRATES_COURT = "Table 5B"

# Column label marking the start of a region-block header row
YEAR_HEADER = "Financial Year"

# The column carrying the Northern Ireland-wide figure in every region table
ALL_PPS = "All PPS"

# Cells published in place of a suppressed or unavailable count
SUPPRESSION_MARKERS = frozenset({"*", "#", "-", "~", ".."})

# Courts addressable via get_court_outcomes()
COURTS = {"crown": SHEET_CROWN_COURT, "magistrates": SHEET_MAGISTRATES_COURT}

# Bulletin workbooks change once a year, so a long cache is safe
_downloader = CachedDownloader("justice_pps", timeout=60)


class PPSDataError(Exception):
    """Base exception for PPS statistical bulletin errors."""

    pass


class PPSDataNotFoundError(PPSDataError):
    """Raised when a bulletin edition or its workbook cannot be located."""

    pass


class PPSValidationError(PPSDataError):
    """Raised when parsed data fails validation."""

    pass


def get_available_editions(base_url: str = PUBLICATION_URL) -> dict[str, str]:
    """Map each published financial year to its PPS publication page.

    Only annual editions are returned; the quarterly bulletins published up to
    2019/20 are skipped, since PPS discontinued that cadence.

    Args:
        base_url: URL of the bulletin listing page.

    Returns:
        Mapping of financial year (e.g. ``"2025/26"``) to absolute page URL,
        newest first.

    Raises:
        PPSDataNotFoundError: If the listing page cannot be fetched or no
            editions are found.

    Example:
        >>> editions = get_available_editions()  # doctest: +SKIP
        >>> "2024/25" in editions  # doctest: +SKIP
        True
    """
    try:
        response = session.get(base_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise PPSDataNotFoundError(f"Failed to fetch PPS publication page {base_url}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, features="html.parser")

    editions: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text().split())
        match = re.fullmatch(r"PPS Statistical Bulletin (\d{4})-(\d{2})", label)
        if match is None:
            # Quarterly editions carry a "Quarter"/"Quarters" qualifier
            continue
        year = f"{match.group(1)}/{match.group(2)}"
        editions.setdefault(year, urljoin(base_url, anchor["href"]))

    if not editions:
        raise PPSDataNotFoundError(f"Could not find any bulletin editions on {base_url}")

    logger.info(f"Found {len(editions)} PPS bulletin editions")
    return editions


def get_workbook_url(edition: str | None = None) -> str:
    """Find the tables workbook for a given bulletin edition.

    Args:
        edition: Financial year such as ``"2024/25"``. Defaults to the most
            recent edition that publishes a workbook.

    Returns:
        Absolute URL of the ``.xlsx`` tables workbook.

    Raises:
        PPSDataNotFoundError: If the edition is unknown, or no edition has an
            attached workbook.
    """
    editions = get_available_editions()

    if edition is not None:
        if edition not in editions:
            raise PPSDataNotFoundError(f"Unknown edition {edition!r}; available: {', '.join(sorted(editions))}")
        candidates = [edition]
    else:
        candidates = sorted(editions, reverse=True)

    for year in candidates:
        url = _find_workbook_on_page(editions[year])
        if url is not None:
            return url
        logger.info(f"Edition {year} has no tables workbook, trying the previous year")

    raise PPSDataNotFoundError(f"No tables workbook found for edition(s): {', '.join(candidates)}")


def _find_workbook_on_page(page_url: str) -> str | None:
    """Return the first ``.xlsx`` link on a publication page, if any."""
    try:
        response = session.get(page_url, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise PPSDataNotFoundError(f"Failed to fetch publication page {page_url}: {e}") from e

    soup = bs4.BeautifulSoup(response.content, features="html.parser")
    for anchor in soup.find_all("a", href=True):
        if anchor["href"].lower().endswith(".xlsx"):
            return urljoin(page_url, anchor["href"])
    return None


def download_workbook(edition: str | None = None, force_refresh: bool = False) -> Path:
    """Download a bulletin tables workbook, using the local cache when fresh.

    Args:
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the cache and re-download.

    Returns:
        Path to the downloaded (or cached) ``.xlsx`` file.

    Raises:
        PPSDataNotFoundError: If the download fails.
    """
    url = get_workbook_url(edition)
    try:
        return _downloader.download(url, cache_ttl_hours=24 * 7, force_refresh=force_refresh)
    except DownloadError as e:
        raise PPSDataNotFoundError(str(e)) from e


def _safe_count(value) -> int | None:
    """Convert a cell to an int, mapping blanks and suppression markers to None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "" or text in SUPPRESSION_MARKERS:
            return None
        value = text.replace(",", "")
    try:
        return int(round(float(value)))
    except (ValueError, TypeError):
        return None


def _safe_rate(value) -> float | None:
    """Convert a cell to a float, mapping blanks and suppression markers to None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "" or text in SUPPRESSION_MARKERS:
            return None
        value = text.replace(",", "").rstrip("%")
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _clean_label(value) -> str:
    """Strip footnote digits and whitespace from a header or row label."""
    if pd.isna(value):
        return ""
    text = " ".join(str(value).split())
    # Footnote markers are appended as space-separated digits, e.g. "Outcome 3".
    # The leading \s+ is load-bearing: without it "2025/26" is truncated to "2025/".
    return re.sub(r"\s+\d+(?:\s*,\s*\d+)*$", "", text).strip()


def _read_sheet(file_path: Path, sheet_name: str) -> pd.DataFrame:
    """Read a worksheet with no header, raising a clear error if it is absent."""
    try:
        return pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    except ValueError as e:
        raise PPSValidationError(f"Worksheet {sheet_name!r} not found in {file_path.name}") from e


def _parse_region_table(file_path: Path, sheet_name: str, category_label: str, value_label: str) -> pd.DataFrame:
    """Parse a stacked per-year region table into tidy long format.

    These worksheets hold one block per financial year. Each block starts with
    a ``Financial Year`` header row naming the PPS regions, followed by rows
    whose first cell carries the year (once) and whose second cell names the
    category. Because the region model changed in 2025, the two blocks in a
    single workbook can name different regions, so each block is parsed
    against its own header.

    Args:
        file_path: Path to the tables workbook.
        sheet_name: Worksheet to read.
        category_label: Name for the category column, e.g. ``"decision_type"``.
        value_label: Name for the value column, e.g. ``"decisions"``.

    Returns:
        DataFrame with columns: financial_year, ``category_label``, region,
        ``value_label``.
    """
    raw = _read_sheet(file_path, sheet_name)

    records: list[dict] = []
    regions: list[str] = []
    year: str | None = None

    for _, row in raw.iterrows():
        first = _clean_label(row.iloc[0])

        if first == YEAR_HEADER:
            regions = [_clean_label(cell) for cell in row.iloc[2:] if not pd.isna(cell)]
            year = None
            continue

        if not regions:
            # Still in the title rows above the first block
            continue

        if re.fullmatch(r"\d{4}/\d{2}", first):
            year = first
        elif first != "":
            # A non-year, non-blank first cell means the block has ended and we
            # have reached the footnotes.
            regions = []
            continue

        if year is None:
            continue

        category = _clean_label(row.iloc[1])
        if category == "" or category.lower() == "nan":
            continue

        is_rate = "rate" in category.lower()
        for offset, region in enumerate(regions):
            cell = row.iloc[2 + offset]
            value = _safe_rate(cell) if is_rate else _safe_count(cell)
            records.append(
                {
                    "financial_year": year,
                    category_label: category,
                    "region": region,
                    value_label: value,
                }
            )

    if not records:
        raise PPSValidationError(f"No data rows parsed from worksheet {sheet_name!r}")

    return pd.DataFrame.from_records(records)


def _parse_comparison_table(file_path: Path, sheet_name: str, category_label: str) -> pd.DataFrame:
    """Parse a two-year side-by-side table (Tables 1b and 1c) into long format.

    These worksheets place both financial years on one row, as a count column
    and a percentage-share column each, followed by change columns that this
    parser drops in favour of deriving them.

    Args:
        file_path: Path to the tables workbook.
        sheet_name: Worksheet to read.
        category_label: Name for the category column.

    Returns:
        DataFrame with columns: financial_year, ``category_label``, files,
        share_pct.
    """
    raw = _read_sheet(file_path, sheet_name)

    header_idx = None
    year_columns: dict[int, tuple[str, str]] = {}
    for idx in range(min(10, len(raw))):
        columns = {}
        for col, cell in enumerate(raw.iloc[idx]):
            match = re.match(r"\s*(\d{4}/\d{2})\s*\((Number|% Share)\)", str(cell))
            if match:
                columns[col] = (match.group(1), match.group(2))
        if columns:
            header_idx, year_columns = idx, columns
            break

    if header_idx is None:
        raise PPSValidationError(f"Could not find a year header row in worksheet {sheet_name!r}")

    counts = {col: year for col, (year, kind) in year_columns.items() if kind == "Number"}
    shares = {year: col for col, (year, kind) in year_columns.items() if kind == "% Share"}

    records = []
    for _, row in raw.iloc[header_idx + 1 :].iterrows():
        category = _clean_label(row.iloc[0])
        if category == "" or category.lower() == "nan":
            continue
        files = {col: _safe_count(row.iloc[col]) for col in counts}
        if all(value is None for value in files.values()):
            # Footnote row below the data block
            break
        for col, year in counts.items():
            share = _safe_rate(row.iloc[shares[year]]) if year in shares else None
            records.append(
                {
                    "financial_year": year,
                    category_label: category,
                    "files": files[col],
                    "share_pct": None if share is None else round(share * 100, 4),
                }
            )

    if not records:
        raise PPSValidationError(f"No data rows parsed from worksheet {sheet_name!r}")

    return pd.DataFrame.from_records(records)


def get_files_received(edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get files received from police by file type and PPS region (Table 1a).

    Args:
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with columns: financial_year, file_type, region, files.

    Example:
        >>> df = get_files_received()  # doctest: +SKIP
        >>> sorted(df["file_type"].unique())  # doctest: +SKIP
        ['All Files', 'Hybrid', 'Indictable', 'Summary']
    """
    path = download_workbook(edition, force_refresh=force_refresh)
    return _parse_region_table(path, SHEET_FILES_RECEIVED, "file_type", "files").astype({"files": "Int64"})


def get_files_by_offence(edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get police files broken down by offence classification (Table 1b).

    Args:
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with columns: financial_year, offence_classification, files,
        share_pct.
    """
    path = download_workbook(edition, force_refresh=force_refresh)
    return _parse_comparison_table(path, SHEET_FILES_BY_OFFENCE, "offence_classification")


def get_files_from_agencies(edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get files submitted to PPS by bodies other than the police (Table 1c).

    Args:
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with columns: financial_year, agency, files, share_pct.
    """
    path = download_workbook(edition, force_refresh=force_refresh)
    return _parse_comparison_table(path, SHEET_FILES_FROM_AGENCIES, "agency")


def get_prosecutorial_decisions(edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get prosecutorial decisions by decision type and PPS region (Table 3a).

    Decision types cover prosecution (indictable or summary), diversion
    (caution, informed warning, youth conference, other) and no prosecution,
    together with the subtotals PPS publishes for each group.

    Args:
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with columns: financial_year, decision_type, region,
        decisions.
    """
    path = download_workbook(edition, force_refresh=force_refresh)
    return _parse_region_table(path, SHEET_DECISIONS, "decision_type", "decisions").astype({"decisions": "Int64"})


def get_no_prosecution_reasons(edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get reasons given for no-prosecution decisions (Table 3b).

    PPS applies a two-stage test: a case must pass an evidential test before
    the public interest test is considered, so failures of the evidential test
    dominate.

    Args:
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with columns: financial_year, reason, region, decisions.
    """
    path = download_workbook(edition, force_refresh=force_refresh)
    return _parse_region_table(path, SHEET_NO_PROSECUTION, "reason", "decisions").astype({"decisions": "Int64"})


def _is_rate_row(outcomes: pd.Series) -> pd.Series:
    """Identify the published-rate rows embedded in a court outcome table."""
    return outcomes.str.contains("rate", case=False, na=False)


def _parse_court_table(court: str, edition: str | None, force_refresh: bool) -> pd.DataFrame:
    """Resolve a court name to its worksheet and parse it."""
    key = court.lower()
    if key not in COURTS:
        raise ValueError(f"Unknown court {court!r}; choose from: {', '.join(sorted(COURTS))}")

    path = download_workbook(edition, force_refresh=force_refresh)
    return _parse_region_table(path, COURTS[key], "outcome", "defendants")


def get_court_outcomes(court: str = "crown", edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get defendants dealt with by court outcome (Tables 5a and 5b).

    Args:
        court: Either ``"crown"`` for the Crown Court or ``"magistrates"`` for
            the Magistrates' and Youth Courts.
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with columns: financial_year, outcome, region, defendants.
        The published conviction rate is excluded — see
        :func:`get_conviction_rates`.

    Raises:
        ValueError: If ``court`` is not a recognised court.
    """
    df = _parse_court_table(court, edition, force_refresh)
    counts = df[~_is_rate_row(df["outcome"])].reset_index(drop=True)
    counts["defendants"] = counts["defendants"].astype("Int64")
    return counts


def get_conviction_rates(court: str = "crown", edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Get the published conviction rate by PPS region (Tables 5a and 5b).

    PPS publishes the rate as a proportion; it is rescaled to a percentage here
    for consistency with the share columns on other tables.

    Args:
        court: Either ``"crown"`` for the Crown Court or ``"magistrates"`` for
            the Magistrates' and Youth Courts.
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with columns: financial_year, region, conviction_rate_pct.

    Raises:
        ValueError: If ``court`` is not a recognised court.
    """
    df = _parse_court_table(court, edition, force_refresh)
    rates = df[_is_rate_row(df["outcome"])].copy()
    rates["conviction_rate_pct"] = (rates["defendants"] * 100).round(4)
    return rates[["financial_year", "region", "conviction_rate_pct"]].reset_index(drop=True)


def validate_pps_data(df: pd.DataFrame) -> bool:
    """Validate a parsed PPS table for structural integrity.

    Args:
        df: DataFrame returned by any of the ``get_*`` functions.

    Returns:
        True if the data passes all checks.

    Raises:
        PPSValidationError: If the frame is empty, is missing a financial year
            column, carries a malformed year, or contains negative counts.

    Example:
        >>> import pandas as pd
        >>> frame = pd.DataFrame({"financial_year": ["2025/26"], "files": [10]})
        >>> validate_pps_data(frame)
        True
    """
    if df.empty:
        raise PPSValidationError("PPS data is empty")

    if "financial_year" not in df.columns:
        raise PPSValidationError("PPS data is missing the financial_year column")

    bad_years = [year for year in df["financial_year"].unique() if not re.fullmatch(r"\d{4}/\d{2}", str(year))]
    if bad_years:
        raise PPSValidationError(f"Malformed financial year values: {bad_years}")

    for column in ("files", "decisions", "defendants"):
        if column in df.columns:
            values = df[column].dropna()
            if (values < 0).any():
                raise PPSValidationError(f"Negative values found in {column}")

    return True


def get_prosecution_rate_summary(edition: str | None = None, force_refresh: bool = False) -> pd.DataFrame:
    """Summarise how PPS disposed of its caseload, Northern Ireland-wide.

    Rates are expressed as a share of all decisions issued, so prosecution,
    diversion and no-prosecution shares sum to 100%.

    Args:
        edition: Financial year such as ``"2024/25"``; defaults to the latest.
        force_refresh: If True, bypass the download cache.

    Returns:
        DataFrame with one row per financial year and columns: financial_year,
        total_decisions, prosecutions, diversions, no_prosecutions,
        prosecution_rate_pct, diversion_rate_pct, no_prosecution_rate_pct.
    """
    decisions = get_prosecutorial_decisions(edition, force_refresh=force_refresh)
    ni_wide = decisions[decisions["region"] == ALL_PPS]

    wanted = {
        "Total Prosecution": "prosecutions",
        "Total Diversion": "diversions",
        "No Prosecution": "no_prosecutions",
        "All Decisions Issued": "total_decisions",
    }

    pivot = (
        ni_wide[ni_wide["decision_type"].isin(wanted)]
        .pivot(index="financial_year", columns="decision_type", values="decisions")
        .rename(columns=wanted)
        .reset_index()
    )

    missing = [name for name in wanted.values() if name not in pivot.columns]
    if missing:
        raise PPSValidationError(f"Decision summary is missing expected rows: {missing}")

    for name in ("prosecutions", "diversions", "no_prosecutions"):
        pivot[f"{name.rstrip('s')}_rate_pct"] = (pivot[name] / pivot["total_decisions"] * 100).round(1)

    pivot.columns.name = None
    return pivot[
        [
            "financial_year",
            "total_decisions",
            "prosecutions",
            "diversions",
            "no_prosecutions",
            "prosecution_rate_pct",
            "diversion_rate_pct",
            "no_prosecution_rate_pct",
        ]
    ].sort_values("financial_year", ignore_index=True)
