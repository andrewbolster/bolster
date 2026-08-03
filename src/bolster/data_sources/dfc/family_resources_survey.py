"""Family Resources Survey (FRS) Report, Northern Ireland.

The Northern Ireland supplement to the UK-wide DWP Family Resources Survey,
published by the Department for Communities. It is the authoritative household
survey for NI incomes, state support receipt, tenure, carers, disability, and -
uniquely among routinely published NI statistics - household food security and
food bank usage.

The report is issued as a set of themed Excel chapter workbooks. This module
covers four of them:

- **Income and state support** (chapter 2) - where household income comes from,
  and which households receive benefits, with NI/UK comparisons.
- **Tenure** (chapter 3) - owned, mortgaged, social and private rented, by year,
  by district, and as a share of income spent on housing.
- **Carers, carees and disability** (chapter 5) - prevalence of informal caring
  and of disability, by age group and by district.
- **Food security and food bank usage** (chapter 6) - household food security
  status cross-tabulated by region, composition, disability, state support and
  tenure.

Data Source:
    https://www.communities-ni.gov.uk/publications/family-resources-survey-report-2024-2025

    The edition page is discovered at runtime by probing the dated publication
    URL pattern, so a new release is picked up without a code change. Chapter
    workbook links are then scraped from that page rather than being hardcoded,
    because the ``/system/files/YYYY-MM/`` directory changes each edition.

Update Frequency: Annual, published in May
Geographic Coverage: Northern Ireland, with UK and English-region comparators
Reference Period: 2021/22 - 2024/25

Note:
    Estimates are derived from a sample of roughly 1,700 NI households, so the
    published tables use suppression markers rather than printing unreliable
    figures. These are normalised on read: ``..`` (sample too small) becomes
    ``NaN``, while ``-`` (negligible, under 0.5%) becomes ``0.0``.

    A break in series falls at 2021/22, when major benefit and tax-credit
    amounts moved from survey responses to administrative data. Earlier years
    are not published in these tables and should not be compared across it.

    Only the current edition publishes machine-readable chapter workbooks;
    earlier edition pages carry no downloadable attachments. The four-year
    series inside each workbook supplies the history instead.

Example:
    >>> from bolster.data_sources.dfc import family_resources_survey as frs
    >>> df = frs.get_food_security_by_tenure()
    >>> "Social renting sector" in set(df["tenure"])
    True
"""

import datetime
import io
import logging
import re

import pandas as pd

from bolster.utils.cache import CachedDownloader
from bolster.utils.web import session

logger = logging.getLogger(__name__)

PUBLICATION_URL_TEMPLATE = "https://www.communities-ni.gov.uk/publications/family-resources-survey-report-{start}-{end}"

# First edition published as `frs-c<N>-<topic>-<YYMM>.xlsx` chapter workbooks.
EARLIEST_MACHINE_READABLE_EDITION = 2024

# Chapter workbook key -> the substring identifying it in a download URL.
CHAPTERS: dict[str, str] = {
    "confidence_intervals": "frs-c1a",
    "income": "frs-c2",
    "tenure": "frs-c3",
    "pensions": "frs-c4",
    "carers_disability": "frs-c5",
    "food_security": "frs-c6",
}

_XLSX_LINK_RE = re.compile(r'href="([^"]*/(frs-c[^"/]+\.xlsx))"')

# Suppression markers used throughout the published tables.
_SUPPRESSED = ".."
_NEGLIGIBLE = "-"

_downloader = CachedDownloader("frs", timeout=120)


class FRSDataError(Exception):
    """Base exception for Family Resources Survey data errors."""


class FRSDataNotFoundError(FRSDataError):
    """Raised when an edition, chapter workbook, or table cannot be located."""


def find_latest_edition() -> tuple[str, str]:
    """Find the most recent FRS edition that publishes chapter workbooks.

    Walks the dated publication URL pattern backwards from the current calendar
    year until a page is found that links to at least one chapter workbook.

    Returns:
        A ``(financial_year, url)`` pair, e.g. ``("2024/25", "https://...")``.

    Raises:
        FRSDataNotFoundError: If no edition page carries chapter workbooks.

    Example:
        >>> year, url = find_latest_edition()
        >>> url.startswith("https://www.communities-ni.gov.uk/publications/")
        True
    """
    for start in range(datetime.date.today().year, EARLIEST_MACHINE_READABLE_EDITION - 1, -1):
        url = PUBLICATION_URL_TEMPLATE.format(start=start, end=start + 1)
        response = session.get(url, timeout=30)
        if response.status_code != 200:
            continue
        if _XLSX_LINK_RE.search(response.text):
            financial_year = f"{start}/{str(start + 1)[2:]}"
            logger.info("Resolved latest FRS edition to %s (%s)", financial_year, url)
            return financial_year, url

    raise FRSDataNotFoundError(
        f"No FRS edition with chapter workbooks found between "
        f"{EARLIEST_MACHINE_READABLE_EDITION} and {datetime.date.today().year}"
    )


def get_chapter_urls() -> dict[str, str]:
    """Map each chapter key to the download URL of its workbook.

    Returns:
        Chapter key (see :data:`CHAPTERS`) to absolute ``.xlsx`` URL. Chapters
        absent from the current edition are omitted.

    Raises:
        FRSDataNotFoundError: If the edition page links to no chapter workbooks.

    Example:
        >>> urls = get_chapter_urls()
        >>> urls["food_security"].endswith(".xlsx")
        True
    """
    _, edition_url = find_latest_edition()
    response = session.get(edition_url, timeout=30)
    response.raise_for_status()

    found = {url for url, _ in _XLSX_LINK_RE.findall(response.text)}
    if not found:
        raise FRSDataNotFoundError(f"No chapter workbooks linked from {edition_url}")

    urls = {}
    for chapter, prefix in CHAPTERS.items():
        for url in found:
            if f"/{prefix}-" in url:
                urls[chapter] = url if url.startswith("http") else f"https://www.communities-ni.gov.uk{url}"
                break
    return urls


def list_chapters() -> list[str]:
    """List the chapter keys this module knows about.

    Returns:
        Sorted chapter keys accepted by :func:`get_chapter_urls`.

    Example:
        >>> "food_security" in list_chapters()
        True
    """
    return sorted(CHAPTERS)


def _read_table(chapter: str, sheet: str, force_refresh: bool = False) -> pd.DataFrame:
    """Read one table sheet from a chapter workbook, unparsed and unheadered."""
    urls = get_chapter_urls()
    if chapter not in urls:
        raise FRSDataNotFoundError(f"Chapter {chapter!r} is not published in the current edition")

    path = _downloader.download(urls[chapter], cache_ttl_hours=24 * 7, force_refresh=force_refresh)
    workbook = pd.ExcelFile(io.BytesIO(path.read_bytes()))
    if sheet not in workbook.sheet_names:
        raise FRSDataNotFoundError(f"Sheet {sheet!r} not found in chapter {chapter!r}: {workbook.sheet_names}")
    return workbook.parse(sheet, header=None)


def _clean_value(value: object) -> float:
    """Normalise a published cell to a float, honouring suppression markers."""
    if isinstance(value, str):
        text = value.strip()
        if text == _SUPPRESSED or not text:
            return float("nan")
        if text == _NEGLIGIBLE:
            return 0.0
        value = text.replace(",", "").replace("%", "").replace("£", "")
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def _label(value: object) -> str:
    """Normalise a published row or column label to a trimmed string."""
    return "" if pd.isna(value) else str(value).strip()


def _is_footer(text: str) -> bool:
    """Whether a leading-column label marks the end of the data block."""
    lowered = text.lower()
    return lowered.startswith(("note", "sample size", "sample_size", "source"))


def _find_header_row(frame: pd.DataFrame, *labels: str) -> int:
    """Locate the row index whose first cell matches one of ``labels``."""
    wanted = {label.lower() for label in labels}
    for index in range(len(frame)):
        if _label(frame.iat[index, 0]).lower() in wanted:
            return index
    raise FRSDataNotFoundError(f"No header row matching {labels} found")


def _data_rows(frame: pd.DataFrame, start: int) -> list[int]:
    """Row indices holding data, from ``start`` until the footer block."""
    rows = []
    for index in range(start, len(frame)):
        text = _label(frame.iat[index, 0])
        if not text:
            continue
        if _is_footer(text):
            break
        rows.append(index)
    return rows


def _sample_sizes(frame: pd.DataFrame, columns: dict[int, str]) -> dict[str, float]:
    """Extract the ``Sample Size (=100%)`` row, keyed by column label."""
    for index in range(len(frame)):
        if _label(frame.iat[index, 0]).lower().startswith("sample size"):
            return {label: _clean_value(frame.iat[index, col]) for col, label in columns.items()}
    return {}


def _parse_food_security_table(sheet: str, dimension: str, force_refresh: bool) -> pd.DataFrame:
    """Parse one of the identically shaped chapter 6 cross-tabulations.

    Tables 6.2 to 6.5 all lay out a single category column against ``Food
    secure`` / ``Food insecure`` / ``All`` percentages plus a sample size.
    """
    frame = _read_table("food_security", sheet, force_refresh)
    header = _find_header_row(
        frame, "household composition", "disability in household", "state support received", "tenure"
    )

    records = []
    for index in _data_rows(frame, header + 1):
        cells = [frame.iat[index, col] for col in range(1, 5)]
        # Blank-valued rows are structural sub-headings labelling the block
        # below them; a fully suppressed row still has ".." and is kept.
        if all(_label(cell) == "" for cell in cells):
            continue
        records.append(
            {
                dimension: _label(frame.iat[index, 0]),
                "food_secure_pct": _clean_value(cells[0]),
                "food_insecure_pct": _clean_value(cells[1]),
                "total_pct": _clean_value(cells[2]),
                "sample_size": _clean_value(cells[3]),
            }
        )

    if not records:
        raise FRSDataNotFoundError(f"No data rows parsed from food security table {sheet}")
    return pd.DataFrame.from_records(records)


def _composition_sections(labels: list[str]) -> list[str]:
    """Assign each table 6.2 row to its ``with``/``without`` children block.

    The published table nests adult-count rows under two block totals without
    repeating the block name, so the same label (``Three or more adults``)
    appears in both. Carrying the block down the rows keeps rows distinguishable.
    """
    sections = []
    current = "All households"
    for label in labels:
        lowered = label.lower()
        if lowered.startswith(("all households", "households with one or more")):
            if "without children" in lowered:
                current = "Without children"
            elif "with children" in lowered:
                current = "With children"
            else:
                current = "All households"
        sections.append(current)
    return sections


def get_food_security_by_region(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve household food security and food bank usage by region and country.

    Table 6.1. Covers the UK, its four countries, Great Britain, and the nine
    English regions, so NI can be read against a directly comparable baseline.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        One row per area with columns ``area``, the four food security levels
        (``high_pct``, ``marginal_pct``, ``low_pct``, ``very_low_pct``),
        ``food_secure_pct``, ``food_insecure_pct``, the food bank usage rates
        ``food_bank_30_day_pct`` and ``food_bank_12_month_pct``, and
        ``sample_size``.

    Example:
        >>> df = get_food_security_by_region()
        >>> "Northern Ireland" in set(df["area"])
        True
    """
    frame = _read_table("food_security", "T6.1", force_refresh)
    header = _find_header_row(frame, "region/country")

    # Sub-headings ("Country", "Region") label the blocks below them but carry
    # no figures, so they are dropped rather than emitted as areas.
    records = []
    for index in _data_rows(frame, header + 1):
        area = _label(frame.iat[index, 0])
        sample = _clean_value(frame.iat[index, 11])
        if pd.isna(sample):
            continue
        records.append(
            {
                "area": area,
                "high_pct": _clean_value(frame.iat[index, 1]),
                "marginal_pct": _clean_value(frame.iat[index, 2]),
                "low_pct": _clean_value(frame.iat[index, 3]),
                "very_low_pct": _clean_value(frame.iat[index, 4]),
                "food_secure_pct": _clean_value(frame.iat[index, 6]),
                "food_insecure_pct": _clean_value(frame.iat[index, 7]),
                "food_bank_30_day_pct": _clean_value(frame.iat[index, 9]),
                "food_bank_12_month_pct": _clean_value(frame.iat[index, 10]),
                "sample_size": sample,
            }
        )

    if not records:
        raise FRSDataNotFoundError("No data rows parsed from table 6.1")
    return pd.DataFrame.from_records(records)


def get_food_security_by_composition(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve NI household food security status by household composition.

    Table 6.2, breaking households down by adult count, pension age and the
    presence of children.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Columns ``household_composition``, ``section`` (which of the ``with``
        or ``without`` children blocks the row sits in), ``food_secure_pct``,
        ``food_insecure_pct``, ``total_pct`` and ``sample_size``.

    Example:
        >>> df = get_food_security_by_composition()
        >>> "All households" in set(df["household_composition"])
        True
    """
    frame = _parse_food_security_table("T6.2", "household_composition", force_refresh)
    frame.insert(1, "section", _composition_sections(list(frame["household_composition"])))
    return frame


def get_food_security_by_disability(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve NI household food security status by disability in the household.

    Table 6.3, contrasting households with and without disabled adults, and
    separately with and without disabled adults under pension age.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Columns ``disability_in_household``, ``food_secure_pct``,
        ``food_insecure_pct``, ``total_pct`` and ``sample_size``.

    Example:
        >>> df = get_food_security_by_disability()
        >>> len(df) > 1
        True
    """
    return _parse_food_security_table("T6.3", "disability_in_household", force_refresh)


def get_food_security_by_state_support(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve NI household food security status by state support receipt.

    Table 6.4, splitting households by whether they receive any state support
    and, within that, income-related versus non-income-related benefits.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Columns ``state_support_received``, ``food_secure_pct``,
        ``food_insecure_pct``, ``total_pct`` and ``sample_size``.

    Example:
        >>> df = get_food_security_by_state_support()
        >>> "All households" in set(df["state_support_received"])
        True
    """
    return _parse_food_security_table("T6.4", "state_support_received", force_refresh)


def get_food_security_by_tenure(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve NI household food security status by housing tenure.

    Table 6.5, the sharpest of the chapter 6 cross-tabulations: social renters
    report several times the food insecurity rate of outright owners.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Columns ``tenure``, ``food_secure_pct``, ``food_insecure_pct``,
        ``total_pct`` and ``sample_size``.

    Example:
        >>> df = get_food_security_by_tenure()
        >>> "Social renting sector" in set(df["tenure"])
        True
    """
    return _parse_food_security_table("T6.5", "tenure", force_refresh)


def get_income_sources(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the composition of gross weekly household income, NI against UK.

    Table 2.1, giving the share of households whose main income source is each
    of wages, state support, pensions or other, for every published year.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Long-form data with columns ``financial_year``, ``area`` (``NI`` or
        ``UK``), ``income_source``, ``percentage`` and ``sample_size``.

    Example:
        >>> df = get_income_sources()
        >>> set(df["area"]) == {"NI", "UK"}
        True
    """
    frame = _read_table("income", "T2.1", force_refresh)
    header = _find_header_row(frame, "year")
    labels = {col: _label(frame.iat[header, col]) for col in range(2, frame.shape[1])}
    sources = {col: name for col, name in labels.items() if name and not name.lower().startswith("sample")}
    sample_col = next((col for col, name in labels.items() if name.lower().startswith("sample")), None)

    # Each year spans an NI row and a UK row, but only the NI row carries the
    # year label, so it is carried forward rather than read from every row.
    records = []
    financial_year = ""
    for index in range(header + 1, len(frame)):
        first = _label(frame.iat[index, 0])
        if _is_footer(first):
            break
        area = _label(frame.iat[index, 1])
        if not area:
            continue
        financial_year = first or financial_year
        sample = _clean_value(frame.iat[index, sample_col]) if sample_col is not None else float("nan")
        for col, source in sources.items():
            records.append(
                {
                    "financial_year": _normalise_year(financial_year),
                    "area": area,
                    "income_source": source,
                    "percentage": _clean_value(frame.iat[index, col]),
                    "sample_size": sample,
                }
            )

    if not records:
        raise FRSDataNotFoundError("No data rows parsed from table 2.1")
    return pd.DataFrame.from_records(records)


def get_state_support_by_country(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the share of households receiving state support, NI against UK.

    Table 2.2, the headline NI/UK comparison of benefit receipt.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Columns ``state_support_received``, ``northern_ireland_pct`` and
        ``united_kingdom_pct``. The trailing sample-size row is excluded.

    Example:
        >>> df = get_state_support_by_country()
        >>> "All in receipt of state support" in set(df["state_support_received"])
        True
    """
    frame = _read_table("income", "T2.2", force_refresh)
    header = _find_header_row(frame, "state support received")

    records = []
    for index in _data_rows(frame, header + 1):
        label = _label(frame.iat[index, 0])
        if label.lower() in {"northern ireland", "united kingdom"}:
            continue
        records.append(
            {
                "state_support_received": label,
                "northern_ireland_pct": _clean_value(frame.iat[index, 1]),
                "united_kingdom_pct": _clean_value(frame.iat[index, 2]),
            }
        )

    records = [r for r in records if not pd.isna(r["northern_ireland_pct"])]
    if not records:
        raise FRSDataNotFoundError("No data rows parsed from table 2.2")
    return pd.DataFrame.from_records(records)


def get_state_support_trend(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the NI state support receipt time series.

    Table 2.3, tracking the share of households on income-related and
    non-income-related benefits across the published years.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Long-form data with columns ``financial_year``, ``state_support_type``
        and ``percentage``, plus a ``sample_size`` column repeated per year.

    Example:
        >>> df = get_state_support_trend()
        >>> df["financial_year"].nunique() >= 4
        True
    """
    return _parse_year_rows("income", "T2.3", "state_support_type", force_refresh)


def _parse_year_rows(chapter: str, sheet: str, dimension: str, force_refresh: bool) -> pd.DataFrame:
    """Parse a table laid out as year rows against category columns."""
    frame = _read_table(chapter, sheet, force_refresh)
    header = _find_header_row(frame, "year")

    categories = {}
    sample_col = None
    for col in range(1, frame.shape[1]):
        name = _label(frame.iat[header, col])
        if not name:
            continue
        if name.lower().startswith("sample"):
            sample_col = col
        else:
            categories[col] = name

    records = []
    for index in _data_rows(frame, header + 1):
        financial_year = _normalise_year(_label(frame.iat[index, 0]))
        sample = _clean_value(frame.iat[index, sample_col]) if sample_col else float("nan")
        for col, category in categories.items():
            records.append(
                {
                    "financial_year": financial_year,
                    dimension: category,
                    "percentage": _clean_value(frame.iat[index, col]),
                    "sample_size": sample,
                }
            )

    if not records:
        raise FRSDataNotFoundError(f"No data rows parsed from {sheet}")
    return pd.DataFrame.from_records(records)


def _parse_year_matrix(
    chapter: str, sheet: str, dimension: str, header_label: str, force_refresh: bool
) -> pd.DataFrame:
    """Parse a table laid out as category rows against year columns."""
    frame = _read_table(chapter, sheet, force_refresh)
    label_row = _find_header_row(frame, header_label)

    # The financial-year headings sit on the row below the dimension caption.
    years = {}
    for offset in (0, 1):
        candidate = {
            col: _label(frame.iat[label_row + offset, col])
            for col in range(1, frame.shape[1])
            if re.fullmatch(r"\d{4}[/-]\d{2}", _label(frame.iat[label_row + offset, col]))
        }
        if candidate:
            years = candidate
            break
    if not years:
        raise FRSDataNotFoundError(f"No financial-year columns found in {sheet}")

    samples = _sample_sizes(frame, {col: _normalise_year(year) for col, year in years.items()})

    records = []
    for index in _data_rows(frame, label_row + 1):
        category = _label(frame.iat[index, 0])
        if not category or category in years.values():
            continue
        for col, year in years.items():
            normalised = _normalise_year(year)
            records.append(
                {
                    "financial_year": normalised,
                    dimension: category,
                    "percentage": _clean_value(frame.iat[index, col]),
                    "sample_size": samples.get(normalised, float("nan")),
                }
            )

    if not records:
        raise FRSDataNotFoundError(f"No data rows parsed from {sheet}")
    return pd.DataFrame.from_records(records)


def _normalise_year(value: str) -> str:
    """Render a published year label consistently as ``YYYY/YY``."""
    return value.replace("-", "/").strip()


def get_tenure_trend(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the NI housing tenure time series.

    Table 3.5, giving the share of households in each tenure for every published
    year.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Long-form data with columns ``financial_year``, ``tenure``,
        ``percentage`` and ``sample_size``.

    Example:
        >>> df = get_tenure_trend()
        >>> "Owned outright" in set(df["tenure"])
        True
    """
    return _parse_year_matrix("tenure", "T3.5", "tenure", "tenure", force_refresh)


def get_tenure_by_district(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve NI housing tenure by Local Government District.

    Table 3.3. District estimates pool three survey years to reach a usable
    sample, so they are not directly comparable with the single-year series in
    :func:`get_tenure_trend`.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Long-form data with columns ``district``, ``tenure``, ``percentage``
        and ``sample_size``.

    Example:
        >>> df = get_tenure_by_district()
        >>> "Belfast City" in set(df["district"])
        True
    """
    frame = _read_table("tenure", "T3.3", force_refresh)
    label_row = _find_header_row(frame, "tenure")

    districts = {
        col: _label(frame.iat[label_row + 1, col])
        for col in range(1, frame.shape[1])
        if _label(frame.iat[label_row + 1, col])
    }
    samples = _sample_sizes(frame, districts)

    records = []
    for index in _data_rows(frame, label_row + 2):
        tenure = _label(frame.iat[index, 0])
        for col, district in districts.items():
            records.append(
                {
                    "district": district,
                    "tenure": tenure,
                    "percentage": _clean_value(frame.iat[index, col]),
                    "sample_size": samples.get(district, float("nan")),
                }
            )

    if not records:
        raise FRSDataNotFoundError("No data rows parsed from table 3.3")
    return pd.DataFrame.from_records(records)


def get_housing_cost_burden(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the share of NI households spending 30% or more of income on housing.

    Table 3.8, published on two bases - all households, and renters and
    mortgage holders only - across the available years.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Long-form data with columns ``financial_year``, ``measure`` and
        ``percentage``.

    Example:
        >>> df = get_housing_cost_burden()
        >>> df["measure"].nunique() >= 1
        True
    """
    frame = _read_table("tenure", "T3.8", force_refresh)

    years = {}
    year_row = None
    for index in range(len(frame)):
        candidate = {
            col: _label(frame.iat[index, col])
            for col in range(1, frame.shape[1])
            if re.fullmatch(r"\d{4}[/-]\d{2}", _label(frame.iat[index, col]))
        }
        if candidate:
            years, year_row = candidate, index
            break
    if year_row is None:
        raise FRSDataNotFoundError("No financial-year columns found in table 3.8")

    records = []
    for index in _data_rows(frame, year_row + 1):
        measure = _label(frame.iat[index, 0])
        for col, year in years.items():
            records.append(
                {
                    "financial_year": _normalise_year(year),
                    "measure": measure,
                    "percentage": _clean_value(frame.iat[index, col]),
                }
            )

    if not records:
        raise FRSDataNotFoundError("No data rows parsed from table 3.8")
    return pd.DataFrame.from_records(records)


def get_carer_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve the prevalence of informal carers by age group over time.

    Table 5.1, giving the share of each age group providing informal care in
    each published year.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Long-form data with columns ``financial_year``, ``age_group``,
        ``percentage`` and ``sample_size``.

    Example:
        >>> df = get_carer_prevalence()
        >>> "All adults" in set(df["age_group"])
        True
    """
    return _parse_year_rows("carers_disability", "T5.1", "age_group", force_refresh)


def get_disability_prevalence(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve NI disability prevalence by age group over time.

    Table 5.9, giving the share of each age group reporting a disability in each
    published year.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Long-form data with columns ``financial_year``, ``age_group``,
        ``percentage`` and ``sample_size``.

    Example:
        >>> df = get_disability_prevalence()
        >>> "All individuals" in set(df["age_group"])
        True
    """
    return _parse_year_matrix("carers_disability", "T5.9", "age_group", "age group", force_refresh)


def get_disability_by_district(force_refresh: bool = False) -> pd.DataFrame:
    """Retrieve NI disability prevalence by Local Government District.

    Table 5.10. District estimates pool three survey years to reach a usable
    sample, and the Northern Ireland total is included as a comparison row.

    Args:
        force_refresh: Bypass the local cache and re-download the workbook.

    Returns:
        Columns ``district`` and ``percentage``.

    Example:
        >>> df = get_disability_by_district()
        >>> "Northern Ireland" in set(df["district"])
        True
    """
    frame = _read_table("carers_disability", "T5.10", force_refresh)
    header = _find_header_row(frame, "local government district")

    records = []
    for index in _data_rows(frame, header + 1):
        percentage = _clean_value(frame.iat[index, 1])
        if pd.isna(percentage):
            continue
        records.append({"district": _label(frame.iat[index, 0]), "percentage": percentage})

    if not records:
        raise FRSDataNotFoundError("No data rows parsed from table 5.10")
    return pd.DataFrame.from_records(records)
