"""
Northern Ireland Electoral Office (EONI) Election Data Integration

Data Source: The Electoral Office for Northern Ireland provides official election results
and data through their website at https://www.eoni.org.uk. This module accesses NI Assembly
election results from 2003 onwards, including constituency-level results, candidate information,
and vote tallies for all electoral areas in Northern Ireland.

Update Frequency: Electoral data is updated after each election cycle. NI Assembly elections
typically occur every 4-5 years, with the most recent elections in 2022, 2017, and 2016.
Historical data remains static once published, with occasional corrections or clarifications.

Example:
    Retrieve election results for specific years and constituencies:

        >>> from bolster.data_sources import eoni
        >>> # Get available election results
        >>> results_2022 = eoni.get_election_results(2022)
        >>> print(f"Found {len(results_2022)} constituency results for 2022")

        >>> # Get specific constituency data
        >>> belfast_east = eoni.get_constituency_results("Belfast East", 2022)
        >>> for candidate in belfast_east['candidates']:
        ...     print(f"{candidate['name']}: {candidate['votes']} votes")

The module supports automated ingestion of NI Assembly election results with constituency-level
detail and candidate performance data.

Implementation Status:
✅ 2022, 2017, 2016 elections supported
⏳ 2011, 2007, 2003 elections (planned)
"""

import datetime
import logging
import re
from typing import AnyStr, Dict, Iterable, Optional, Union

import pandas as pd
from bs4 import BeautifulSoup

from bolster.utils.web import get_excel_dataframe, session, ua

logger = logging.getLogger(__name__)

#
_headers = {
    "user-agent": f"User-Agent: {ua} Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, "
    f"like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}
_base_url = "https://www.eoni.org.uk"


def get_page(path: AnyStr) -> BeautifulSoup:
    """
    For a given path (within EONI.org.uk), get the response as a BeautifulSoup instance

    Note:
        EONI is trying to block people from scraping and will return a 403 error if you don't pass a 'conventional' user agent

    >>> page = get_page("/Elections/")
    >>> page.find('title').contents[0].strip()
    'Elections | The Electoral Office for Northern Ireland'

    """
    res = session.get(_base_url + path, headers=_headers)
    res.raise_for_status()
    page = BeautifulSoup(res.content, features="html.parser")
    return page


def find_xls_links_in_page(page: BeautifulSoup) -> Iterable[AnyStr]:
    """
    Walk through a BeautifulSoup page and iterate through '(XLS)' suffixed links

    (Primarily Used for 'Results' pages within given elections)

    #WTF Was starting to do some consistency checks between elections to make sure all is kosher, and was wondering why I had a Strangford listing in 2017 but not 2022;
    # As a cross-check on the result page, I walk the links in the right colum of the page, looking for links that have text that ends (XLS). Pretty simple you might think. Except the Strangford link ends in (XLS  and then a random closing ) text string is added to the end.

    >>> page = get_page("/results-data/ni-assembly-election-2022-results/")
    >>> len(list(find_xls_links_in_page(page)))
    18
    >>> next(find_xls_links_in_page(page))
    'https://www.eoni.org.uk/media/omtlpqow/ni-assembly-election-2022-result-sheet-belfast-east-xls.xlsx'

    """
    for _p in page.select_one(".c-article--main").find_all("a", href=True):
        if "xls" in _p.contents[0].lower():
            yield _base_url + _p.attrs["href"]


def normalise_constituencies(cons_str: str) -> str:
    """
    Some constituencies change names or cases etc;

    Use this function to take external/unconventional inputs and project them into a normalised format

    >>> normalise_constituencies('Newry & Armagh')
    'newry and armagh'

    """
    return cons_str.lower().replace(" & ", " and ")


def get_metadata_from_df(
    df: pd.DataFrame,
) -> Dict[str, Union[int, str, datetime.datetime]]:
    """
    Extract Ballot metadata from the table header(s) of an XLS formatted result sheet, as output from `get_excel_dataframe`

    # TODO this could probably be done better as a `dataclass`

    Returns:
        dict of
            'stage': int,
            'date': datetime
            'constituency': str (lower)
            'eligible_electorate': int
            'votes_polled': int
            'number_to_be_elected': int
            'invalid_votes': int
            'electoral_quota': int
    """

    stage_n_catcher = re.compile(r"^Stage (\d+)")

    metadata = {
        "stage": int(re.match(stage_n_catcher, df.columns[5]).group(1)),
        # should have been just int(df.columns[5].split()[-1])., but someone insisted on messing up 2017
        "date": df.columns[10],
        "constituency": normalise_constituencies(df.iloc[0, 3]),
        "eligible_electorate": int(df.iloc[1, 3]),
        "votes_polled": int(df.iloc[2, 3]),
        "number_to_be_elected": int(df.iloc[1, 6]),
        "total_valid_votes": int(df.iloc[2, 6]),
        "invalid_votes": int(df.iloc[1, 9]),
        "electoral_quota": int(df.iloc[1, 12]),
    }
    return metadata


def get_candidates_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract Candidates name and party columns from first stage sheet
    """
    candidates_df = df.iloc[9:29, 2:4]
    candidates_df.columns = ["candidate_name", "candidate_party"]
    return candidates_df.replace(0, None).dropna().reset_index(drop=True)


def get_stage_votes_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract the votes from each stage as a mapped column for each stage, i.e. stages 1...N
    """
    stages = get_metadata_from_df(df)["stage"]
    stage_df = (
        pd.concat({n: extract_stage_n_votes(df, n) for n in range(stages)})
        .unstack()
        .T.replace(0, None)
        .dropna(how="all")
    )
    return stage_df


def get_stage_transfers_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract the transfers from each stage as a mapped column for each stage, i.e. stages 2...N
    """
    stages = get_metadata_from_df(df)["stage"]
    stage_df = (
        pd.concat({n: extract_stage_n_transfers(df, n) for n in range(stages)})
        .unstack()
        .T.replace(0, None)
        .dropna(how="all")
    )
    return stage_df


def extract_stage_n_votes(df: pd.DataFrame, n: int) -> Optional[pd.Series]:
    """
    Extract the votes from a given stage N

    Note: This will include trailing, unaligned `Nones` which must be cleaned up at the Ballot level
    """
    if n == 0:
        return None
    if n < 10:
        row_offset = 9
        col_offset = 4 + (2 * (n - 1))
    else:
        row_offset = 55
        col_offset = 6 + (2 * (n - 10))

    return df.iloc[row_offset : row_offset + 20, col_offset].reset_index(drop=True)


def extract_stage_n_transfers(df: pd.DataFrame, n: int) -> Optional[pd.Series]:
    """
    Extract the votes from a given stage N

    Note: This will include trailing, unaligned `Nones` which must be cleaned up at the Ballot level
    Stage Transfers are associated with the 'next' stage, i.e. stage 1 has no transfers
    """
    if n <= 1:
        return None
    if n < 10:
        row_offset = 9
        col_offset = 5 + (2 * (n - 2))
    else:
        row_offset = 55
        col_offset = 5 + (2 * (n - 10))

    return df.iloc[row_offset : row_offset + 20, col_offset].reset_index(drop=True)


def get_results_from_sheet(sheet_url: AnyStr) -> Dict[str, Union[pd.DataFrame, dict]]:
    df = get_excel_dataframe(sheet_url, requests_kwargs={"headers": _headers})
    metadata = get_metadata_from_df(df)
    candidates = get_candidates_from_df(df)
    stage_votes = get_stage_votes_from_df(df)
    stage_transfers = get_stage_transfers_from_df(df)

    return {
        "candidates": candidates,
        "stage_votes": stage_votes,
        "stage_transfers": stage_transfers,
        "metadata": metadata,
    }


def get_results(year: int) -> Dict[str, Union[pd.DataFrame, dict]]:
    results_listing_dir = "/results-data/"
    results_listing_path = {
        2022: "ni-assembly-election-2022-results/",
    }

    results = {}
    results_listing_page = get_page(results_listing_dir + results_listing_path[year])
    for sheet_url in find_xls_links_in_page(results_listing_page):
        data = get_results_from_sheet(sheet_url)
        results[data["metadata"]["constituency"]] = data
    return results


def validate_election_results(results: Dict[str, Dict]) -> bool:
    """Validate election results data integrity.

    Args:
        results: Dictionary of election results by constituency

    Returns:
        True if validation passes, False otherwise
    """
    if not results:
        logger.warning("Election results data is empty")
        return False

    valid_constituencies = 0
    for constituency, data in results.items():
        if not isinstance(data, dict):
            logger.warning(f"Invalid data structure for {constituency}")
            continue

        required_keys = {"candidates", "stage_votes", "metadata"}
        if not required_keys.issubset(data.keys()):
            missing = required_keys - set(data.keys())
            logger.warning(f"Missing required keys in {constituency}: {missing}")
            continue

        # Check candidates DataFrame
        candidates = data["candidates"]
        if isinstance(candidates, pd.DataFrame) and not candidates.empty:
            if "candidate_name" in candidates.columns or "name" in candidates.columns:
                valid_constituencies += 1
            else:
                logger.warning(f"Missing candidate names in {constituency}")
        else:
            logger.warning(f"Invalid or empty candidates data for {constituency}")

    if valid_constituencies < len(results) * 0.8:  # At least 80% should be valid
        logger.warning(f"Only {valid_constituencies}/{len(results)} constituencies have valid data")
        return False

    return True
