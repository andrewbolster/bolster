"""
UK Companies House Data Integration.

Data Source: UK Companies House provides comprehensive company registration data through
their bulk download service at http://download.companieshouse.gov.uk/en_output.html.
The service provides complete company information including names, addresses, status,
and registration details for all active and dissolved companies in the UK.

Update Frequency: The Companies House bulk data is updated monthly, typically available
by the first week of each month. The data reflects the state of company registrations
as of the snapshot date.

Example:
    Basic usage for querying company data:

        >>> from bolster.data_sources import companies_house
        >>> # Get all companies (warning: this is very large!)
        >>> for company in companies_house.query_basic_company_data():
        ...     print(company['CompanyName'], company['CompanyNumber'])
        ...     break  # Just show first result

        >>> # Query companies that might be associated with Farset Labs
        >>> farset_companies = list(companies_house.query_basic_company_data(
        ...     companies_house.companies_house_record_might_be_farset
        ... ))
        >>> print(f"Found {len(farset_companies)} potential Farset-related companies")

The module provides utilities for downloading and parsing the complete UK company registry,
with built-in filtering capabilities for targeted analysis.
"""

import csv
import logging
from collections.abc import Iterator
from typing import Callable

import bs4
from tqdm.auto import tqdm

from bolster import always, dict_concat_safe
from bolster.utils.web import download_extract_zip, session

logger = logging.getLogger(__name__)


def get_basic_company_data_url() -> str:
    """
    Parse the companies house website to get the current URL for the 'BasicCompanyData'.

    Currently uses the 'one file' method but it could be split into the multi files for memory efficiency
    """
    base_url = "http://download.companieshouse.gov.uk/en_output.html"
    # TODO: Network integration testing - requires active Companies House website
    s = bs4.BeautifulSoup(session.get(base_url).content)  # pragma: no cover
    for a in s.find_all("a"):  # pragma: no cover
        if a.get("href").startswith("BasicCompanyDataAsOneFile"):  # pragma: no cover
            url = f"http://download.companieshouse.gov.uk/{a.get('href')}"  # pragma: no cover
            break  # assume first time lucky  # pragma: no cover

    return url  # pragma: no cover


def query_basic_company_data(query_func: Callable[..., bool] = always) -> Iterator[dict]:
    """
    Grab the url for the basic company data, and walk through the CSV files within, and
    for each row in each CSV file, parse the row data through the given `query_func`
    such that if `query_func(row)` is True it will be yielded.
    """
    # TODO: Network integration testing - requires Companies House data download
    url = get_basic_company_data_url()  # pragma: no cover
    for _filename, data in tqdm(download_extract_zip(url)):  # pragma: no cover
        for row in tqdm(csv.DictReader(d.decode("utf-8") for d in data)):  # pragma: no cover
            if query_func(row):  # pragma: no cover
                yield row  # pragma: no cover


def companies_house_record_might_be_farset(r: dict) -> bool:
    """
    A heuristic function for working out if a record in the companies house registry *might* be based in Farset Labs
    Almost certainly incomplete and needs more testing/validation.
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
    if "unit 10" in address_line or "unit 18" in address_line or "unit 17" in address_line:
        return False
    return "unit 1" in address_line


def get_companies_house_records_that_might_be_in_farset() -> Iterator[dict]:
    # TODO: Network integration testing - requires Companies House data download
    yield from query_basic_company_data(companies_house_record_might_be_farset)  # pragma: no cover


def validate_companies_house_data(records: list[dict]) -> bool:  # pragma: no cover
    """Validate Companies House data integrity.

    Args:
        records: List of company records from Companies House

    Returns:
        True if validation passes, False otherwise
    """
    if not records:
        logger.warning("Companies House data is empty")
        return False

    # Check for required fields in first record
    required_fields = {"CompanyName", "CompanyNumber", "RegAddress.PostCode"}
    first_record = records[0]

    if not required_fields.issubset(first_record.keys()):
        missing = required_fields - set(first_record.keys())
        logger.warning(f"Missing required fields: {missing}")
        return False

    # Check for reasonable data
    valid_count = 0
    for record in records:
        if record.get("CompanyName") and record.get("CompanyNumber"):
            valid_count += 1

    if valid_count < len(records) * 0.8:  # At least 80% should have basic data
        logger.warning(f"Only {valid_count}/{len(records)} records have valid company data")
        return False

    return True
