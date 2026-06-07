"""NISRA PxStat API client.

Provides access to the NISRA open data API at https://data.nisra.gov.uk/,
powered by the PxStat platform (https://github.com/CSOIreland/PxStat).

The API is publicly accessible without authentication and has no observed
rate limits, making it a more reliable alternative to scraping Excel files
from publication pages.

API endpoint pattern::

    GET https://ws-data.nisra.gov.uk/public/api.restful/
        PxStat.Data.Cube_API.ReadDataset/{MATRIX}/CSV/1.0/en

CSV responses include a UTF-8 BOM — always decode with ``utf-8-sig``.

Example::

    >>> from bolster.data_sources.nisra.pxstat import read_dataset
    >>> df = read_dataset("WDTHS")
    >>> "VALUE" in df.columns
    True
"""

import logging
from io import StringIO

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

_BASE_URL = "https://ws-data.nisra.gov.uk/public/api.restful/PxStat.Data.Cube_API.ReadDataset"
_HEADERS = {"Referer": "https://data.nisra.gov.uk/"}


class PxStatError(Exception):
    """Raised when the PxStat API returns an unexpected response."""


def read_dataset(matrix: str, timeout: int = 30) -> pd.DataFrame:
    """Fetch a dataset from the NISRA PxStat API as a DataFrame.

    Args:
        matrix: Dataset matrix code (e.g. ``"WDTHS"`` for weekly deaths).
        timeout: HTTP request timeout in seconds.

    Returns:
        DataFrame with raw API columns. The ``VALUE`` column contains the
        numeric values; all other columns are dimension labels and codes.

    Raises:
        PxStatError: If the API returns a non-200 response.

    Example:
        >>> df = read_dataset("WDTHS")
        >>> "VALUE" in df.columns
        True
    """
    url = f"{_BASE_URL}/{matrix}/CSV/1.0/en"
    response = session.get(url, headers=_HEADERS, timeout=timeout)

    if response.status_code != 200:
        raise PxStatError(f"PxStat API returned {response.status_code} for matrix {matrix!r}: {url}")

    df = pd.read_csv(StringIO(response.content.decode("utf-8-sig")))
    logger.debug("PxStat %s: %d rows, columns: %s", matrix, len(df), list(df.columns))
    return df
