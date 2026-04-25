"""Generic utility for extracting DataTables data from HTML pages.

Many Northern Ireland government statistics pages use R's flexdashboard/DT package
to embed DataTables widgets. The data is stored as column-transposed JSON inside
``<script type="application/json">`` blocks with a ``{"x": {"data": [...], ...}}``
structure, where ``x["data"]`` is a list of column arrays (not row arrays) and
``x["container"]`` holds the HTML table header with column names.

Example:
    >>> from bolster.utils.datatables import fetch_datatables_json, datatables_to_dataframe
    >>> payload = fetch_datatables_json("https://datavis.nisra.gov.uk/health/my-data.html")
    >>> df = datatables_to_dataframe(payload)
    >>> print(df.head())
"""

import json
import logging

import pandas as pd
from bs4 import BeautifulSoup

from .web import session

logger = logging.getLogger(__name__)


class DataTablesError(Exception):
    """Raised when DataTables extraction fails."""


def fetch_datatables_json(url: str, timeout: int = 30) -> dict:
    """Fetch an HTML page and extract the embedded DT widget JSON payload.

    The payload is the parsed content of the largest
    ``<script type="application/json">`` block whose ``x.data`` key is a
    column-transposed list (i.e. a list of lists).

    Args:
        url: URL of the HTML page containing a DataTables widget.
        timeout: HTTP request timeout in seconds.

    Returns:
        The ``x`` sub-dict from the DT widget payload, containing at minimum
        ``"data"`` (list of column arrays) and ``"container"`` (HTML header).

    Raises:
        DataTablesError: If the page cannot be fetched or no DT payload is found.

    Example:
        >>> payload = fetch_datatables_json("https://example.com/data.html")
        >>> len(payload["data"])   # number of columns
        11
    """
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
    except Exception as e:
        raise DataTablesError(f"Failed to fetch page {url}: {e}") from e

    return _extract_datatables_payload(response.text, url)


def _extract_datatables_payload(html: str, source_url: str = "") -> dict:
    """Extract the DT widget payload from an HTML string.

    Args:
        html: Full HTML page content.
        source_url: Source URL used only in error messages.

    Returns:
        The ``x`` sub-dict from the largest matching DT widget payload.

    Raises:
        DataTablesError: If no valid DT widget payload is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    json_scripts = soup.find_all("script", type="application/json")

    if not json_scripts:
        raise DataTablesError(f"No application/json script blocks found in {source_url}")

    candidates = []
    for script in json_scripts:
        text = script.string
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue

        if not isinstance(parsed, dict):
            continue
        x = parsed.get("x")
        if not isinstance(x, dict):
            continue
        data = x.get("data")
        if isinstance(data, list) and data and isinstance(data[0], list):
            candidates.append((len(text), x))

    if not candidates:
        raise DataTablesError(
            f"No DataTables column-transposed payload found in {source_url}. "
            "Expected a script block with x.data as a list of column arrays."
        )

    # Return the payload from the largest matching script block
    _, best = max(candidates, key=lambda t: t[0])
    return best


def _parse_column_headers(container_html: str) -> list[str]:
    """Extract column header names from the DT container HTML.

    Args:
        container_html: HTML string containing a ``<thead>`` with ``<th>`` cells.

    Returns:
        List of column header strings in order.
    """
    soup = BeautifulSoup(container_html, "html.parser")
    return [th.get_text(strip=True) for th in soup.find_all("th")]


def datatables_to_dataframe(payload: dict) -> pd.DataFrame:
    """Convert a DT widget payload into a row-oriented DataFrame.

    The ``payload["data"]`` field is a list of column arrays (column-transposed).
    This function transposes it into a normal row-oriented DataFrame and uses
    column names from ``payload["container"]`` if available.

    Args:
        payload: The ``x`` sub-dict from a DT widget JSON block, as returned by
            :func:`fetch_datatables_json`.

    Returns:
        DataFrame with one row per record and columns named from the HTML header.

    Raises:
        DataTablesError: If ``payload["data"]`` is missing or malformed.

    Example:
        >>> payload = {
        ...     "data": [["a", "b"], [1, 2]],
        ...     "container": "<table><thead><tr><th>Name</th><th>Value</th></tr></thead></table>",
        ... }
        >>> df = datatables_to_dataframe(payload)
        >>> list(df.columns)
        ['Name', 'Value']
        >>> len(df)
        2
    """
    col_arrays = payload.get("data")
    if not isinstance(col_arrays, list) or not col_arrays:
        raise DataTablesError("payload['data'] is missing or empty")
    if not isinstance(col_arrays[0], list):
        raise DataTablesError("payload['data'] must be a list of column arrays")

    n_cols = len(col_arrays)
    n_rows = len(col_arrays[0])

    # Validate all columns have the same length
    for i, col in enumerate(col_arrays):
        if len(col) != n_rows:
            raise DataTablesError(f"Column {i} has {len(col)} rows but column 0 has {n_rows} rows")

    # Build column names from container HTML if available
    container = payload.get("container", "")
    col_names: list[str] = []
    if container:
        col_names = _parse_column_headers(container)

    if len(col_names) != n_cols:
        if col_names:
            logger.warning(
                "Column header count (%d) does not match data column count (%d); falling back to positional names",
                len(col_names),
                n_cols,
            )
        col_names = [f"col_{i}" for i in range(n_cols)]

    return pd.DataFrame(dict(zip(col_names, col_arrays, strict=False)))


def get_column_headers_from_url(url: str, timeout: int = 30) -> list[str]:
    """Fetch a DataTables page and return its column header names.

    Convenience helper for discovery.

    Args:
        url: URL of the HTML page.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of column header strings.
    """
    payload = fetch_datatables_json(url, timeout=timeout)
    container = payload.get("container", "")
    return _parse_column_headers(container) if container else []
