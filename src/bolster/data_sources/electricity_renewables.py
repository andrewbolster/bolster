"""NI Electricity Consumption and Renewable Generation Statistics.

Published quarterly by the Department for the Economy (DfE) Northern Ireland
in partnership with NISRA.  Reports progress toward NI's renewable electricity
targets (80% of consumption from renewables by 2030 under the Climate Change
Act (Northern Ireland) 2022).

Data Source:
    **Interactive report** (data embedded as base64 CSV):
    https://datavis.nisra.gov.uk/Economy/electricity-consumption-and-renewable-generation-report.html

    The report embeds ten figures as base64-encoded UTF-16 LE CSV data-URIs.
    This module extracts and parses the four headline time series:

    * **renewable_pct**: Rolling 12-month renewable generation as a
      proportion of gross final electricity consumption (%) and monthly %.
    * **consumption**: Total consumption, renewable and non-renewable
      generation, and net imports (rolling 12-month GWh).
    * **generation_by_technology**: Rolling 12-month generation (GWh)
      by technology — wind, hydro, bioenergy, landfill gas, solar PV.
    * **generation_monthly**: Monthly renewable and non-renewable
      generation (GWh) going back to February 2018.

Update Frequency:
    Quarterly (March, June, September, December).

Coverage:
    Rolling 12-month figures: January 2019 – present.
    Monthly generation figures: February 2018 – present.

Example:
    >>> from bolster.data_sources import electricity_renewables
    >>> data = electricity_renewables.get_latest_data()
    >>> 'renewable_pct' in data
    True
    >>> 'renewable_pct_rolling_12m' in data['renewable_pct'].columns
    True
    >>> (data['renewable_pct']['renewable_pct_rolling_12m'] > 0).all()
    True

"""

from __future__ import annotations

import base64
import csv
import io
import logging
import re

import pandas as pd

from bolster.utils.cache import CachedDownloader, DownloadError

logger = logging.getLogger(__name__)

# ─── Data source ──────────────────────────────────────────────────────────────

_DATAVIS_URL = "https://datavis.nisra.gov.uk/Economy/electricity-consumption-and-renewable-generation-report.html"

_FIGURE_PATTERN = re.compile(r'href="data:text/csv;base64,([^"]+)"[^>]*>([^<]+)')

# ─── Column mappings ──────────────────────────────────────────────────────────

_RENEWABLE_PCT_COLS = {
    "date": "date",
    "renewable generation as a proportion of gross final electricity consumption (rolling 12 month basis)": "renewable_pct_rolling_12m",
    "renewable generation as a proportion of gross final electricity consumption (monthly basis)": "renewable_pct_monthly",
}

_CONSUMPTION_COLS = {
    "date": "date",
    "total consumption (gwh)": "total_consumption_gwh",
    "renewable generation (gwh)": "renewable_generation_gwh",
    "non renewable generation (gwh)": "non_renewable_generation_gwh",
    "net imports (gwh)": "net_imports_gwh",
}

_TECHNOLOGY_COLS = {
    "date": "date",
    "wind (gwh)": "wind_gwh",
    "hydro (gwh)": "hydro_gwh",
    "bioenergy (biomass and biogas)(gwh)": "bioenergy_gwh",
    "landfill gas (gwh)": "landfill_gas_gwh",
    "solar pv(gwh)": "solar_pv_gwh",
}

_MONTHLY_GEN_COLS = {
    "date": "date",
    "non-renewable generation (gwh)": "non_renewable_generation_gwh",
    "renewable generation (gwh)": "renewable_generation_gwh",
}

# ─── Custom exceptions ────────────────────────────────────────────────────────


class ElectricityDataNotFoundError(Exception):
    """Electricity statistics page or data could not be retrieved."""


class ElectricityValidationError(Exception):
    """Electricity DataFrame failed validation checks."""


# ─── HTML fetch + figure extraction ──────────────────────────────────────────

_downloader = CachedDownloader("electricity_renewables", timeout=60)


def _fetch_datavis_html(force_refresh: bool = False) -> str:
    """Download the DfE electricity datavis page with caching.

    Args:
        force_refresh: Bypass the local cache and re-download.

    Returns:
        HTML content of the datavis page.

    Raises:
        ElectricityDataNotFoundError: If the page cannot be fetched.
    """
    try:
        file_path = _downloader.download(
            _DATAVIS_URL,
            cache_ttl_hours=24 * 7,
            force_refresh=force_refresh,
        )
    except DownloadError as exc:  # pragma: no cover
        raise ElectricityDataNotFoundError(f"Failed to download electricity datavis page: {exc}") from exc

    with open(file_path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _extract_figures(html: str) -> dict[str, bytes]:
    """Extract all base64-encoded CSV figures from the datavis HTML.

    Returns:
        Mapping of figure title (e.g. ``"Figure 1.CSV (3kB)"``) to raw bytes.
    """
    return {title.strip(): base64.b64decode(b64data + "==") for b64data, title in _FIGURE_PATTERN.findall(html)}


def _decode_figure_csv(raw: bytes) -> list[list[str]]:
    """Decode a base64-figure's raw bytes into a list of CSV rows.

    The datavis page embeds each figure as a UTF-16 LE CSV without a BOM.
    The encoding produces an artifact where each cell's last value has
    non-ASCII characters appended (the next row's bytes at wrong alignment).
    Stripping all non-ASCII characters from each cell removes the artifact
    while preserving dates, numbers, and ASCII punctuation.

    Args:
        raw: Raw bytes from ``base64.b64decode``.

    Returns:
        List of rows, each a list of clean string values.
        Empty and all-whitespace rows are omitted.
    """
    text = raw.decode("utf-16-le", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = []
    for row in reader:
        # Strip non-ASCII garbage artifacts from each cell value
        clean = [re.sub(r"[^\x20-\x7E]", "", cell).strip() for cell in row]
        if any(c for c in clean):
            rows.append(clean)
    return rows


def _rows_to_dataframe(rows: list[list[str]], col_map: dict[str, str]) -> pd.DataFrame:
    """Convert decoded CSV rows to a tidy DataFrame with renamed columns.

    Args:
        rows: Output of :func:`_decode_figure_csv` (header + data rows).
        col_map: Mapping from lower-cased source column name to clean name.
            Only columns present in the map are kept.

    Returns:
        DataFrame with ``date`` column as ``pd.Timestamp`` and numeric
        columns as ``float``.

    Raises:
        ElectricityDataNotFoundError: If rows is empty.
    """
    if not rows:
        raise ElectricityDataNotFoundError("No data rows in figure")

    header = [c.lower().strip() for c in rows[0]]
    data_rows = rows[1:]

    df = pd.DataFrame(data_rows, columns=header)

    # Keep only mapped columns and rename
    keep = {src: dst for src, dst in col_map.items() if src in df.columns}
    df = df[list(keep.keys())].rename(columns=keep)

    # Parse date
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])

    # Parse numerics
    for col in df.columns:
        if col != "date":
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("date").reset_index(drop=True)

    # Add year/quarter helper columns
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    return df


# ─── Public API ───────────────────────────────────────────────────────────────


def get_latest_data(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Download and parse the latest NI electricity and renewables statistics.

    Returns four DataFrames covering the headline series from the DfE/NISRA
    quarterly electricity report.

    Args:
        force_refresh: If ``True``, bypass the local cache and re-download.

    Returns:
        Dictionary with keys:

        * ``"renewable_pct"`` — rolling 12-month and monthly renewable
          generation as % of gross final consumption.
        * ``"consumption"`` — rolling 12-month total consumption, renewable
          generation, non-renewable generation, and net imports (GWh).
        * ``"generation_by_technology"`` — rolling 12-month renewable
          generation (GWh) by technology: wind, hydro, bioenergy,
          landfill gas, solar PV.
        * ``"generation_monthly"`` — monthly renewable and non-renewable
          generation (GWh) going back to February 2018.

    Raises:
        ElectricityDataNotFoundError: If the datavis page cannot be fetched
            or no figure data is found in the HTML.
        ElectricityValidationError: If the parsed data fails validation.

    Example:
        >>> data = get_latest_data()
        >>> sorted(data.keys())
        ['consumption', 'generation_by_technology', 'generation_monthly', 'renewable_pct']
        >>> 'total_consumption_gwh' in data['consumption'].columns
        True
    """
    html = _fetch_datavis_html(force_refresh=force_refresh)
    figures = _extract_figures(html)

    if not figures:  # pragma: no cover
        raise ElectricityDataNotFoundError(f"No figure CSV data found in {_DATAVIS_URL}")

    titles = list(figures.keys())
    logger.info("Found %d figures: %s", len(titles), titles)

    def _parse(idx: int, col_map: dict[str, str]) -> pd.DataFrame:
        if idx >= len(titles):  # pragma: no cover
            raise ElectricityDataNotFoundError(f"Expected figure index {idx} not found")
        rows = _decode_figure_csv(figures[titles[idx]])
        return _rows_to_dataframe(rows, col_map)

    data: dict[str, pd.DataFrame] = {
        "renewable_pct": _parse(0, _RENEWABLE_PCT_COLS),
        "consumption": _parse(2, _CONSUMPTION_COLS),
        "generation_by_technology": _parse(4, _TECHNOLOGY_COLS),
        "generation_monthly": _parse(6, _MONTHLY_GEN_COLS),
    }

    for key, df in data.items():
        validate_data(df, key)

    return data


# ─── Validation ───────────────────────────────────────────────────────────────

_REQUIRED_COLS: dict[str, set[str]] = {
    "renewable_pct": {"date", "renewable_pct_rolling_12m", "renewable_pct_monthly"},
    "consumption": {
        "date",
        "total_consumption_gwh",
        "renewable_generation_gwh",
        "non_renewable_generation_gwh",
    },
    "generation_by_technology": {"date", "wind_gwh", "solar_pv_gwh"},
    "generation_monthly": {"date", "renewable_generation_gwh", "non_renewable_generation_gwh"},
}

_MIN_ROWS = 10  # at least 2 years of bimonthly or monthly data


def validate_data(df: pd.DataFrame, key: str = "renewable_pct") -> bool:
    """Validate an electricity statistics DataFrame.

    Args:
        df: DataFrame from :func:`get_latest_data`.
        key: Which sub-dataset to validate (controls required-column check).
            One of ``"renewable_pct"``, ``"consumption"``,
            ``"generation_by_technology"``, ``"generation_monthly"``.

    Returns:
        ``True`` if all checks pass.

    Raises:
        ElectricityValidationError: If the DataFrame is empty, missing
            required columns, has implausible values, or is too short.

    Example:
        >>> data = get_latest_data()
        >>> validate_data(data['renewable_pct'], 'renewable_pct')
        True
    """
    if df is None or df.empty:
        raise ElectricityValidationError(f"DataFrame '{key}' is empty")

    required = _REQUIRED_COLS.get(key, set())
    missing = required - set(df.columns)
    if missing:
        raise ElectricityValidationError(f"DataFrame '{key}' missing required columns: {sorted(missing)}")

    if len(df) < _MIN_ROWS:
        raise ElectricityValidationError(f"DataFrame '{key}' has only {len(df)} rows; expected {_MIN_ROWS}+")

    # Percentage checks
    if key == "renewable_pct":
        pct = df["renewable_pct_rolling_12m"].dropna()
        if (pct < 0).any() or (pct > 100).any():
            raise ElectricityValidationError("renewable_pct_rolling_12m has values outside [0, 100]")
        if pct.max() < 20:
            raise ElectricityValidationError("renewable_pct_rolling_12m implausibly low (max < 20%)")

    # GWh sanity checks
    if key == "consumption":
        total = df["total_consumption_gwh"].dropna()
        if (total < 0).any():
            raise ElectricityValidationError("total_consumption_gwh has negative values")
        if total.median() < 1000:
            raise ElectricityValidationError("total_consumption_gwh implausibly low (median < 1000 GWh)")

    return True
