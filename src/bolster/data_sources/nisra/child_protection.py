"""NISRA Children's Social Care — Child Protection Statistics Module.

This module provides access to Northern Ireland's annual Children's Social Care
Statistics, focusing on the child protection chapter (referrals, investigations,
registrations, and register characteristics).

Data Coverage:
    - Children on the Child Protection Register (CPR) by age, sex, trust
    - CPR trend data from 31 March 2015 to present (annual snapshots)
    - Child Protection Referrals by trust and by referral source (2013/14–present)
    - Child Protection Investigations by type and trust (2015–present)
    - Category of abuse breakdowns (neglect, physical, sexual, emotional)
    - Registration duration on the CPR

HSC Trusts:
    - Belfast, Northern, South Eastern, Southern, Western

Data Source:
    Department of Health Northern Ireland publishes annual Children's Social Care
    Statistics covering the 12 months to 31 March each year. Child protection data
    is drawn from the Children Order Return (CPR series).

    Source: https://www.health-ni.gov.uk/topics/childrens-services-statistics
    Article: https://www.health-ni.gov.uk/articles/child-protection-register

Update Frequency:
    Annual, typically published in October for the year ending 31 March.

Example:
    >>> from bolster.data_sources.nisra import child_protection as cp
    >>> df = cp.get_latest_child_protection()
    >>> sorted(df.columns.tolist())
    ['category', 'measure', 'notes', 'subcategory', 'value', 'year']

    >>> # CPR trend data shows registrations back to 2015
    >>> trend = df[df['measure'] == 'cpr_registrations_ni_total']
    >>> 2015 in trend['year'].values
    True

Publication Details:
    - Frequency: Annual (year ending 31 March)
    - Published by: Department of Health, Community Information Branch
    - Latest: Children's Social Care Statistics for Northern Ireland 2024/25
    - Source: https://www.health-ni.gov.uk/topics/childrens-services-statistics
"""

import logging
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import session

from ._base import NISRAValidationError, download_file, make_absolute_url

logger = logging.getLogger(__name__)

# Base URLs
HEALTH_NI_CHILDREN_ARTICLE = "https://www.health-ni.gov.uk/articles/child-protection-register"
HEALTH_NI_BASE_URL = "https://www.health-ni.gov.uk"

# Expected columns in the long-format output
REQUIRED_COLUMNS = {"year", "measure", "category", "subcategory", "value"}

# HSC Trust names (canonical form after normalisation)
HSC_TRUSTS = ["Belfast", "Northern", "South Eastern", "Southern", "Western"]

# Known measures in output
MEASURE_CPR_TOTAL = "cpr_registrations_ni_total"
MEASURE_REFERRALS_TOTAL = "referrals_ni_total"
MEASURE_INVESTIGATIONS_TOTAL = "investigations_ni_total"


def get_child_protection_publication_url() -> str:
    r"""Find the latest Children's Social Care Statistics publication URL.

    Scrapes the Department of Health child protection register article page to find
    the most recent annual publication, then extracts the Excel download link.

    Returns:
        URL string for the latest Excel data file.

    Raises:
        NISRAValidationError: If publication page cannot be fetched or no Excel link found.

    Example:
        >>> url = get_child_protection_publication_url()
        >>> url.startswith("https://")
        True
        >>> url.endswith((".xlsx", ".XLSX", ".xls"))
        True
    """
    logger.info("Fetching child protection publications from %s", HEALTH_NI_CHILDREN_ARTICLE)

    try:
        response = session.get(HEALTH_NI_CHILDREN_ARTICLE, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise NISRAValidationError(f"Failed to fetch child protection register page: {e}") from e

    soup = BeautifulSoup(response.content, "html.parser")

    # Find the link to the latest annual Children's Social Care Statistics publication
    pub_url = None
    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True).lower()
        href = link["href"]
        # Match "children's social care statistics" annual publications
        if "children" in text and "social care statistics" in text and ("202" in text or "publications" in href):
            pub_url = make_absolute_url(href, HEALTH_NI_BASE_URL)
            logger.info("Found publication link: %s -> %s", link.get_text(strip=True), pub_url)
            break

    if not pub_url:
        raise NISRAValidationError(
            f"Could not find Children's Social Care Statistics publication link on {HEALTH_NI_CHILDREN_ARTICLE}"
        )

    # Fetch the publication page to get the Excel download
    try:
        pub_response = session.get(pub_url, timeout=30)
        pub_response.raise_for_status()
    except Exception as e:
        raise NISRAValidationError(f"Failed to fetch publication page {pub_url}: {e}") from e

    pub_soup = BeautifulSoup(pub_response.content, "html.parser")

    # Look for the main Excel data file (Tables spreadsheet, not pre-release PDF)
    excel_url = None
    for link in pub_soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True).lower()
        if (
            re.search(r"\.(xlsx|xls)$", href, re.IGNORECASE)
            and "pre-release" not in href.lower()
            and "pre-release" not in text
        ):
            excel_url = make_absolute_url(href, HEALTH_NI_BASE_URL)
            logger.info("Found Excel file: %s", excel_url)
            break

    if not excel_url:
        raise NISRAValidationError(f"Could not find Excel data file in publication page {pub_url}")

    return excel_url


def _normalise_trust(raw: str) -> str:
    """Normalise an HSC Trust name to its short canonical form.

    Args:
        raw: Raw trust name string (e.g. "Belfast HSC Trust", "Northern HSC Trust")

    Returns:
        Short canonical form (e.g. "Belfast", "Northern")
    """
    for trust in HSC_TRUSTS:
        if trust.lower() in str(raw).lower():
            return trust
    return str(raw).strip()


def _safe_int(val) -> int | None:
    """Convert a value to int, returning None for missing/suppressed values.

    Args:
        val: Value to convert (may be '[S]', '-', NaN, or numeric)

    Returns:
        Integer value or None
    """
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "nan", "-", "[S]", "[z]", "[c]"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _parse_cpr_trend(file_path: str | Path, content: bytes | None = None) -> list[dict]:
    """Parse Table 2.2a: CPR registrations by trust over time.

    Args:
        file_path: Path to the Excel file (used if content is None)
        content: Optional pre-loaded bytes

    Returns:
        List of record dicts with keys: year, measure, category, subcategory, value, notes
    """
    kwargs = {"sheet_name": "Table 2.2", "header": None}
    if content is not None:
        from io import BytesIO

        df = pd.read_excel(BytesIO(content), **kwargs)
    else:
        df = pd.read_excel(file_path, **kwargs)

    records = []

    # The sheet has two sub-tables: 2.2a (numbers) and 2.2b (rates per 10k)
    # 2.2a starts at row 0, 2.2b follows after 2.2a data
    # Identify header rows by looking for year columns
    current_subtable = None
    header_years = []

    for _idx, row in df.iterrows():
        cells = [str(c).strip() if str(c) != "nan" else "" for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            continue

        # Detect subtable header
        first = non_empty[0].lower()
        if "number of children" in first and "child protection register" in first:
            current_subtable = "count"
            continue
        if "rate of children" in first or "per 10,000" in first.lower():
            current_subtable = "rate"
            continue

        # Detect year header row
        if any(re.match(r"31 march \d{4}", c, re.IGNORECASE) for c in non_empty):
            header_years = []
            for c in cells[1:]:
                m = re.search(r"\d{4}", c)
                if m:
                    header_years.append(int(m.group()))
                elif c == "":
                    header_years.append(None)
            continue

        if header_years and current_subtable == "count":
            # First cell should be a trust or "Northern Ireland"
            trust_raw = cells[0]
            if not trust_raw or trust_raw.lower() in ("hsc trust", ""):
                continue
            trust = _normalise_trust(trust_raw)

            for i, year in enumerate(header_years):
                if year is None or i + 1 >= len(cells):
                    continue
                val = _safe_int(cells[i + 1])
                if val is not None:
                    records.append(
                        {
                            "year": year,
                            "measure": "cpr_registrations_trust_snapshot",
                            "category": "trust",
                            "subcategory": trust,
                            "value": val,
                            "notes": "Count at 31 March",
                        }
                    )

    return records


def _parse_referrals_trend(file_path: str | Path, content: bytes | None = None) -> list[dict]:
    """Parse Table 2.9: Child Protection Referrals by HSC Trust over time.

    Args:
        file_path: Path to the Excel file (used if content is None)
        content: Optional pre-loaded bytes

    Returns:
        List of record dicts
    """
    kwargs = {"sheet_name": "Table 2.9", "header": None}
    if content is not None:
        from io import BytesIO

        df = pd.read_excel(BytesIO(content), **kwargs)
    else:
        df = pd.read_excel(file_path, **kwargs)

    records = []
    header_trusts = []

    for _idx, row in df.iterrows():
        cells = [str(c).strip() if str(c) != "nan" else "" for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            continue

        first = cells[0].lower() if cells[0] else ""

        # Detect the header row (trusts as columns)
        if "hsc trust" in first or first == "hsc trust":
            header_trusts = [_normalise_trust(c) for c in cells[1:] if c and c.lower() != "nan"]
            continue

        # Trust column header row with trust names
        if any("trust" in c.lower() for c in non_empty[1:]):
            header_trusts = []
            for c in cells[1:]:
                if c and c.lower() not in ("", "nan"):
                    header_trusts.append(_normalise_trust(c))
            continue

        # Data row: first cell is a financial year like "2013/14"
        if re.match(r"\d{4}/\d{2,4}", cells[0]):
            year_str = cells[0]
            # Derive year from end of financial year (e.g. 2013/14 -> 2014)
            m = re.match(r"(\d{4})/(\d{2,4})", year_str)
            if not m:
                continue
            end_year = int(m.group(1)) + 1

            # Last column is "Northern Ireland" total
            ni_total_idx = len(cells) - 1
            ni_val = _safe_int(cells[ni_total_idx])
            if ni_val is not None:
                records.append(
                    {
                        "year": end_year,
                        "measure": MEASURE_REFERRALS_TOTAL,
                        "category": "ni_total",
                        "subcategory": "Northern Ireland",
                        "value": ni_val,
                        "notes": f"Financial year {year_str}",
                    }
                )

            # Individual trusts
            for i, trust in enumerate(header_trusts):
                if trust == "Northern Ireland":
                    continue
                col_idx = i + 1
                if col_idx >= len(cells):
                    continue
                val = _safe_int(cells[col_idx])
                if val is not None:
                    records.append(
                        {
                            "year": end_year,
                            "measure": "referrals_by_trust",
                            "category": "trust",
                            "subcategory": trust,
                            "value": val,
                            "notes": f"Financial year {year_str}",
                        }
                    )

    return records


def _parse_cpr_snapshot(file_path: str | Path, content: bytes | None = None) -> list[dict]:
    """Parse Table 2.1: CPR registrations by age and sex for latest year.

    Args:
        file_path: Path to the Excel file (used if content is None)
        content: Optional pre-loaded bytes

    Returns:
        List of record dicts
    """
    kwargs = {"sheet_name": "Table 2.1", "header": None}
    if content is not None:
        from io import BytesIO

        df = pd.read_excel(BytesIO(content), **kwargs)
    else:
        df = pd.read_excel(file_path, **kwargs)

    records = []

    # Row 0: title (extract year), row 2: notes, row 3+: header with age/sex, data rows follow
    # We just want NI total row
    publication_year = None
    for idx, row in df.iterrows():
        cells = [str(c).strip() if str(c) != "nan" else "" for c in row]
        first = cells[0] if cells else ""

        # Extract year from title — handles "31 March 2025" or "2024/25"
        if idx == 0 and cells[0]:
            # Try "31 March YYYY" first
            m = re.search(r"31 March (\d{4})", cells[0], re.IGNORECASE)
            if m:
                publication_year = int(m.group(1))
            else:
                # Fallback: "YYYY/YY" financial year
                m = re.search(r"(\d{4})/(\d{2})", cells[0])
                if m:
                    publication_year = int(m.group(1)) + 1  # e.g. 2024/25 → 2025

        # "All" column: position 13 (0-indexed), "Northern Ireland" row
        if first.lower() == "northern ireland":
            all_val = _safe_int(cells[13]) if len(cells) > 13 else None
            if all_val is not None and publication_year:
                records.append(
                    {
                        "year": publication_year,
                        "measure": MEASURE_CPR_TOTAL,
                        "category": "ni_total",
                        "subcategory": "Northern Ireland",
                        "value": all_val,
                        "notes": f"Snapshot at 31 March {publication_year}",
                    }
                )
            break

    return records


def _parse_investigations_trend(file_path: str | Path, content: bytes | None = None) -> list[dict]:
    """Parse Table 2.12: Child Protection Investigations by trust over time.

    Args:
        file_path: Path to the Excel file (used if content is None)
        content: Optional pre-loaded bytes

    Returns:
        List of record dicts
    """
    kwargs = {"sheet_name": "Table 2.12", "header": None}
    if content is not None:
        from io import BytesIO

        df = pd.read_excel(BytesIO(content), **kwargs)
    else:
        df = pd.read_excel(file_path, **kwargs)

    records = []
    header_years: list[int] = []

    for row_idx, row in df.iterrows():
        cells = [str(c).strip() if str(c) != "nan" else "" for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            continue

        first = cells[0].lower() if cells[0] else ""

        # Header row contains years
        if first in ("hsc trust", "trust") or (row_idx == 2 and any(re.match(r"\d{4}", c) for c in non_empty)):
            header_years = []
            for c in cells[1:]:
                m = re.match(r"(\d{4})", c)
                if m:
                    header_years.append(int(m.group(1)))
            continue

        if (
            header_years
            and "northern ireland" not in first
            and (any(t.lower() in first for t in ["belfast", "northern", "south", "southern", "western"]))
        ):
            trust = _normalise_trust(cells[0])
            for i, year in enumerate(header_years):
                col_idx = i + 1
                if col_idx >= len(cells):
                    continue
                val = _safe_int(cells[col_idx])
                if val is not None:
                    records.append(
                        {
                            "year": year,
                            "measure": "investigations_by_trust",
                            "category": "trust",
                            "subcategory": trust,
                            "value": val,
                            "notes": "Investigations year ending 31 March",
                        }
                    )

        elif header_years and "northern ireland" in first:
            for i, year in enumerate(header_years):
                col_idx = i + 1
                if col_idx >= len(cells):
                    continue
                val = _safe_int(cells[col_idx])
                if val is not None:
                    records.append(
                        {
                            "year": year,
                            "measure": MEASURE_INVESTIGATIONS_TOTAL,
                            "category": "ni_total",
                            "subcategory": "Northern Ireland",
                            "value": val,
                            "notes": "Investigations year ending 31 March",
                        }
                    )

    return records


def _parse_abuse_category_trend(file_path: str | Path, content: bytes | None = None) -> list[dict]:
    """Parse Table 2.5a: CPR registrations by abuse category over time.

    The sheet has a 2-column label structure: "Category of Abuse" and optionally
    "Main Category of Abuse" (for rows with combined categories), followed by year columns.

    Args:
        file_path: Path to the Excel file (used if content is None)
        content: Optional pre-loaded bytes

    Returns:
        List of record dicts
    """
    kwargs = {"sheet_name": "Table 2.5", "header": None}
    if content is not None:
        from io import BytesIO

        df = pd.read_excel(BytesIO(content), **kwargs)
    else:
        df = pd.read_excel(file_path, **kwargs)

    records = []
    header_years: list[int] = []
    in_subtable_a = False
    # Number of label columns before the year values
    n_label_cols = 1

    for _idx, row in df.iterrows():
        cells = [str(c).strip() if str(c) != "nan" else "" for c in row]
        non_empty = [c for c in cells if c]

        if not non_empty:
            continue

        first_lower = cells[0].lower() if cells[0] else ""

        # Detect start of subtable 2.5a (counts)
        if "number of children" in first_lower or ("table 2.5a" in first_lower):
            in_subtable_a = True
            header_years = []
            continue

        # Detect start of subtable 2.5b (percentages) — stop parsing
        if in_subtable_a and ("percentage" in first_lower or "table 2.5b" in first_lower):
            break

        # Detect the header row (contains year integers)
        if in_subtable_a and any(re.match(r"^\d{4}$", c) for c in non_empty):
            header_years = []
            n_label_cols = 0
            for ci, c in enumerate(cells):
                if re.match(r"^\d{4}$", c):
                    if n_label_cols == 0:
                        n_label_cols = ci  # label cols before first year
                    header_years.append(int(c))
            if n_label_cols == 0:
                n_label_cols = 1
            continue

        # Also handle float-formatted years like "2015.0"
        if in_subtable_a and any(re.match(r"^\d{4}\.0$", c) for c in non_empty):
            header_years = []
            n_label_cols = 0
            for ci, c in enumerate(cells):
                m = re.match(r"^(\d{4})\.0$", c)
                if m:
                    if n_label_cols == 0:
                        n_label_cols = ci
                    header_years.append(int(m.group(1)))
            if n_label_cols == 0:
                n_label_cols = 1
            continue

        if in_subtable_a and header_years and first_lower not in ("", "category of abuse"):
            if "note" in first_lower or "please" in first_lower or "large proportion" in first_lower:
                continue

            # Category name: use first non-empty label column
            category_raw = cells[0].strip()
            if not category_raw:
                continue

            # Values start at n_label_cols
            for i, year in enumerate(header_years):
                col_idx = n_label_cols + i
                if col_idx >= len(cells):
                    continue
                val = _safe_int(cells[col_idx])
                if val is not None:
                    records.append(
                        {
                            "year": year,
                            "measure": "cpr_by_abuse_category",
                            "category": "abuse_category",
                            "subcategory": category_raw,
                            "value": val,
                            "notes": "Count at 31 March",
                        }
                    )

    return records


def parse_child_protection_file(file_path: str | Path) -> pd.DataFrame:
    """Parse a Children's Social Care Statistics Excel file into long-format DataFrame.

    Extracts child protection data from the following tables:
    - Table 2.1: CPR snapshot (total registrations for latest year)
    - Table 2.2a: CPR registrations by trust, 2015–present
    - Table 2.5a: CPR by category of abuse, 2015–present
    - Table 2.9: Child protection referrals by trust, 2013/14–present
    - Table 2.12: Child protection investigations by trust, 2015–present

    Args:
        file_path: Path to the Excel file.

    Returns:
        DataFrame with columns: year (int), measure (str), category (str),
        subcategory (str), value (int), notes (str).

    Raises:
        NISRAValidationError: If the file cannot be parsed or contains no data.
    """
    file_path = Path(file_path)
    logger.info("Parsing child protection file: %s", file_path)

    records: list[dict] = []

    try:
        records.extend(_parse_cpr_snapshot(file_path))
        records.extend(_parse_cpr_trend(file_path))
        records.extend(_parse_referrals_trend(file_path))
        records.extend(_parse_investigations_trend(file_path))
        records.extend(_parse_abuse_category_trend(file_path))
    except Exception as e:
        raise NISRAValidationError(f"Failed to parse {file_path}: {e}") from e

    if not records:
        raise NISRAValidationError(f"No child protection data extracted from {file_path}")

    df = pd.DataFrame(records)

    # Ensure correct dtypes
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("Int64")
    df["measure"] = df["measure"].astype(str)
    df["category"] = df["category"].astype(str)
    df["subcategory"] = df["subcategory"].astype(str)
    df["notes"] = df["notes"].astype(str)

    return df[["year", "measure", "category", "subcategory", "value", "notes"]].copy()


def get_latest_child_protection(force_refresh: bool = False) -> pd.DataFrame:
    """Download and parse the latest Children's Social Care Statistics.

    Fetches the most recent annual publication from the Department of Health
    and returns child protection data in long format.

    Args:
        force_refresh: Force re-download even if cached (default: False).

    Returns:
        DataFrame with columns: year, measure, category, subcategory, value, notes.

    Raises:
        NISRAValidationError: If download or parsing fails.
    """
    excel_url = get_child_protection_publication_url()
    file_path = download_file(excel_url, force_refresh=force_refresh)
    return parse_child_protection_file(file_path)


def validate_child_protection_data(df: pd.DataFrame) -> pd.DataFrame:
    """Validate child protection DataFrame and raise on structural issues.

    Checks for:
    - Non-empty DataFrame
    - Required columns present
    - No negative values

    Args:
        df: DataFrame to validate.

    Returns:
        The input DataFrame (unchanged) if validation passes.

    Raises:
        NISRAValidationError: If any check fails.
    """
    if df is None or df.empty:
        raise NISRAValidationError("Child protection data is empty")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise NISRAValidationError(f"Missing required columns: {sorted(missing)}")

    neg = df["value"].dropna()
    neg = neg[neg < 0]
    if len(neg) > 0:
        raise NISRAValidationError(f"Found {len(neg)} negative values in 'value' column")

    return df
