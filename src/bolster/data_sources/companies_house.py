import csv
from typing import Callable, Dict, Iterator, Text

import bs4
import requests
from tqdm.auto import tqdm

from .. import always, dict_concat_safe
from ..utils.web import download_extract_zip


def get_basic_company_data_url() -> Text:
    """
    Parse the companies house website to get the current URL for the 'BasicCompanyData'

    Currently uses the 'one file' method but it could be split into the multi files for memory efficiency
    """
    base_url = "http://download.companieshouse.gov.uk/en_output.html"
    # TODO: Network integration testing - requires active Companies House website
    s = bs4.BeautifulSoup(requests.get(base_url).content)  # pragma: no cover
    for a in s.find_all("a"):  # pragma: no cover
        if a.get("href").startswith("BasicCompanyDataAsOneFile"):  # pragma: no cover
            url = f"http://download.companieshouse.gov.uk/{a.get('href')}"  # pragma: no cover
            break  # assume first time lucky  # pragma: no cover

    return url  # pragma: no cover


def query_basic_company_data(query_func: Callable[..., bool] = always) -> Iterator[Dict]:
    """
    Grab the url for the basic company data, and walk through the CSV files within, and
    for each row in each CSV file, parse the row data through the given `query_func`
    such that if `query_func(row)` is True it will be yielded
    """
    # TODO: Network integration testing - requires Companies House data download
    url = get_basic_company_data_url()  # pragma: no cover
    for filename, data in tqdm(download_extract_zip(url)):  # pragma: no cover
        for row in tqdm(csv.DictReader((d.decode("utf-8") for d in data))):  # pragma: no cover
            if query_func(row):  # pragma: no cover
                yield row  # pragma: no cover


def companies_house_record_might_be_farset(r: Dict) -> bool:
    """
    A heuristic function for working out if a record in the companies house registry *might* be based in Farset Labs
    Almost certainly incomplete and needs more testing/validation
    """
    if r["RegAddress.PostCode"].lower().replace(" ", "") != "bt125gh":
        return False
    address_line = ",".join(
        map(
            str,
            dict_concat_safe(
                r,
                [
                    "RegAddress.CareOf",
                    "RegAddress.AddressLine1",
                    "RegAddress.AddressLine2",  # This appears to be optional now
                ],
                default="",
            ),
        )
    ).lower()
    if "farset" in address_line:
        return True
    elif "unit 10" in address_line:
        return False
    elif "unit 18" in address_line:
        return False
    elif "unit 17" in address_line:
        return False
    elif "unit 1" in address_line:
        return True
    else:
        return False


def get_companies_house_records_that_might_be_in_farset() -> Iterator[Dict]:
    # TODO: Network integration testing - requires Companies House data download
    yield from query_basic_company_data(companies_house_record_might_be_farset)  # pragma: no cover
