import io
import zipfile
from io import BytesIO

import pandas as pd
import requests

from . import version_no

ua = f"@Bolster/{version_no} (+http://bolster.online/)"


def get_excel_dataframe(file_url, requests_kwargs=None, read_kwargs=None):
    if requests_kwargs is None:
        requests_kwargs = {}
    if read_kwargs is None:
        read_kwargs = {}

    with requests.get(file_url, **requests_kwargs) as response:
        response.raise_for_status()
        data = BytesIO(response.content)
        df = pd.read_excel(data, **read_kwargs)
        return df


def download_extract_zip(url):
    """
    Download a ZIP file and extract its contents in memory
    yields (filename, file-like object) pairs
    """
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as thezip:
            for zipinfo in thezip.infolist():
                with thezip.open(zipinfo) as thefile:
                    yield zipinfo.filename, thefile
