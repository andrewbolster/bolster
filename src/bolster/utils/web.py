import io
import logging
import zipfile
from io import BytesIO
from typing import Dict, Generator, Optional, Tuple

import pandas as pd
import requests
from waybackpy import WaybackMachineCDXServerAPI, exceptions

from . import version_no

ua = f"@Bolster/{version_no} (+http://bolster.online/)"

session = requests.Session()
session.headers.update({"User-Agent": ua})


def get_last_valid(url: str) -> str:
    return WaybackMachineCDXServerAPI(url).oldest().archive_url


def resilient_get(url: str, **kwargs) -> requests.Response:
    """
    Attempt a get, but if it fails, try using the wayback machine to get the last valid version and get that.
    If all else fails, raise a HTTPError from the inner "NoCDXRecordFound" exception
    """

    try:
        res = requests.get(url, **kwargs)
        res.raise_for_status()
    except requests.HTTPError as outer_err:
        try:
            last_valid = get_last_valid(url)
        except exceptions.NoCDXRecordFound as inner_err:
            raise outer_err from inner_err
        res = requests.get(last_valid, **kwargs)
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

    with requests.get(file_url, **requests_kwargs) as response:
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
