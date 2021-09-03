import csv
from typing import Callable
from typing import Dict
from typing import Iterator
from typing import Text

import bs4
import requests
from tqdm.auto import tqdm

from .. import always
from .. import dict_concat_safe
from ..utils.web import download_extract_zip


def get_basic_company_data_url() -> Text:
    """
    Parse the companies house website to get the current URL for the 'BasicCompanyData'

    Currently uses the 'one file' method but it could be split into the multi files for memory efficiency
    """
    base_url = "http://download.companieshouse.gov.uk/en_output.html"
    s = bs4.BeautifulSoup(requests.get(base_url).content)
    for a in s.find_all("a"):
        if a.get("href").startswith("BasicCompanyDataAsOneFile"):
            url = f"http://download.companieshouse.gov.uk/{a.get('href')}"
            break  # assume first time lucky

    return url


def query_basic_company_data(
    query_func: Callable[..., bool] = always
) -> Iterator[Dict]:
    """
    Grab the url for the basic company data, and walk through the CSV files within, and
    for each row in each CSV file, parse the row data through the given `query_func`
    such that if `query_func(row)` is True it will be yielded
    """
    url = get_basic_company_data_url()
    for filename, data in tqdm(download_extract_zip(url)):
        for row in tqdm(csv.DictReader((d.decode("utf-8") for d in data))):
            if query_func(row):
                yield row


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
    yield from query_basic_company_data(companies_house_record_might_be_farset)
