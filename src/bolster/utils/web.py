import io
import logging
import zipfile
from io import BytesIO
from typing import Dict, Generator, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from waybackpy import WaybackMachineCDXServerAPI, exceptions

from . import version_no

logger = logging.getLogger(__name__)
ua = f"@Bolster/{version_no} (+http://bolster.online/)"


class RateLimitAwareRetry(Retry):
    """Custom retry strategy that handles 429 (Too Many Requests) with longer backoffs."""

    def get_backoff_time(self):
        """Calculate backoff time, with special handling for 429 responses."""
        # Check if the last request resulted in a 429 by looking at history
        is_rate_limited = False
        if self.history and len(self.history) > 0:
            last_request = self.history[-1]
            if hasattr(last_request, "status") and last_request.status == 429:
                is_rate_limited = True

        # For 429 responses, use much longer backoff
        if is_rate_limited:
            # Use exponential backoff starting at 30 seconds for 429 responses
            # Calculate current retry attempt (history length - 1 since we haven't incremented yet)
            retry_count = len(self.history) - 1 if self.history else 0
            # Ensure retry_count is at least 0 for the first retry
            retry_count = max(0, retry_count)
            backoff_value = 30 * (2**retry_count)
            logger.warning(
                f"Rate limited (429) - backing off for {backoff_value:.1f} seconds. "
                f"Retry attempt {retry_count + 1}/{self.total}"
            )
            return backoff_value
        else:
            # Use normal backoff for other status codes
            return super().get_backoff_time()

    def increment(self, method=None, url=None, response=None, error=None, _pool=None, _stacktrace=None):
        """Override increment to track the last response status."""
        if response is not None:
            self._last_status = response.status
            if response.status == 429:
                logger.warning(
                    f"Received 429 Too Many Requests from {url}. "
                    f"Server may be rate limiting requests. Will retry with extended backoff."
                )

        return super().increment(method, url, response, error, _pool, _stacktrace)


# Configure retry strategy for transient failures
# Retries on: connection errors, 429, 500, 502, 503, 504 status codes
_retry_strategy = RateLimitAwareRetry(
    total=4,  # Increased for 429 handling
    backoff_factor=1,  # 1s, 2s, 4s delays for normal errors
    status_forcelist=[429, 500, 502, 503, 504],  # Added 429
    allowed_methods=["HEAD", "GET", "OPTIONS"],
    raise_on_status=True,  # Enable proper retries with exponential backoff
    # Respect server retry-after headers (important for 429)
    respect_retry_after_header=True,
)
_adapter = HTTPAdapter(max_retries=_retry_strategy)

session = requests.Session()
session.headers.update({"User-Agent": ua})
session.mount("http://", _adapter)
session.mount("https://", _adapter)


def get_last_valid(url: str) -> str:
    return WaybackMachineCDXServerAPI(url).oldest().archive_url


def resilient_get(url: str, **kwargs) -> requests.Response:
    """
    Attempt a get, but if it fails, try using the wayback machine to get the last valid version and get that.
    If all else fails, raise a HTTPError from the inner "NoCDXRecordFound" exception
    """

    try:
        res = session.get(url, **kwargs)
        res.raise_for_status()
    except Exception as outer_err:
        try:
            last_valid = get_last_valid(url)
        except exceptions.NoCDXRecordFound as inner_err:
            raise outer_err from inner_err
        res = session.get(last_valid, **kwargs)
        res.raise_for_status()
        logging.warning(f"Failed to get {url} directly, successfully used waybackmachine to get {last_valid}")
    return res


def get_excel_dataframe(
    file_url: str, requests_kwargs: Optional[Dict] = None, read_kwargs: Optional[Dict] = None
) -> pd.DataFrame:
    if requests_kwargs is None:
        requests_kwargs = {}
    if read_kwargs is None:
        read_kwargs = {}

    with session.get(file_url, **requests_kwargs) as response:
        response.raise_for_status()
        data = BytesIO(response.content)
        df = pd.read_excel(data, **read_kwargs)
        return df


def download_extract_zip(url: str) -> Generator[Tuple[str, io.BufferedReader], None, None]:
    """
    Download a ZIP file and extract its contents in memory
    yields (filename, file-like object) pairs
    """
    with session.get(url, stream=True) as response:
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as thezip:
            for zipinfo in thezip.infolist():
                with thezip.open(zipinfo) as thefile:
                    yield zipinfo.filename, thefile
