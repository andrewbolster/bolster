"""
Working with Election Office NI Data

The bits that we can; this module is primarily concerned with the ingestion of NI Assembly election results from 2003
onwards (where possible in a vaguely reliable automated way)

Hitlist:
[X] 2022
[X] 2017
[X] 2016
[ ] 2011
[ ] 2007
[ ] 2003

"""
import datetime
import re
from typing import AnyStr
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Union

import pandas as pd
import requests
from bs4 import BeautifulSoup

from bolster.utils.web import get_excel_dataframe
from bolster.utils.web import ua

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
    'The Electoral Office of Northern Ireland - EONI'

    """
    res = requests.get(_base_url + path, headers=_headers)
    res.raise_for_status()
    page = BeautifulSoup(res.content, features="html.parser")
    return page


def find_xls_links_in_page(page: BeautifulSoup) -> Iterable[AnyStr]:
    """
    Walk through a BeautifulSoup page and iterate through '(XLS)' suffixed links

    (Primarily Used for 'Results' pages within given elections)

    #WTF Was starting to do some consistency checks between elections to make sure all is kosher, and was wondering why I had a Strangford listing in 2017 but not 2022;
    # As a cross-check on the result page, I walk the links in the right colum of the page, looking for links that have text that ends (XLS). Pretty simple you might think. Except the Strangford link ends in (XLS  and then a random closing ) text string is added to the end.

    >>> page = get_page("/Elections/Election-results-and-statistics/Election-results-and-statistics-2003-onwards/Elections-2022/NI-Assembly-Election-2022-Result-Sheets")
    >>> len(list(find_xls_links_in_page(page)))
    18
    >>> next(find_xls_links_in_page(page))
    'https://www.eoni.org.uk/getmedia/c537e56f-c319-47d1-a2b0-44c90f9aa170/NI-Assembly-Election-2022-Result-Sheet-Belfast-East-XLS'

    """
    for _p in page.select(".right-column a"):
        if "XLS" in _p.contents[0]:
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


def get_stage_transfers_from_df(df):
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
    results_listing_dir = "/Elections/Election-results-and-statistics/Election-results-and-statistics-2003-onwards/"
    results_listing_path = {
        2022: "Elections-2022/NI-Assembly-Election-2022-Result-Sheets",
        2017: "Elections-2017/NI-Assembly-Election-2017-Result-Sheets",
        2016: "Elections-2016/NI-Assembly-Election-2016-Candidates-Elected-(1)",
    }

    results = {}
    results_listing_page = get_page(results_listing_dir + results_listing_path[year])
    for sheet_url in find_xls_links_in_page(results_listing_page):
        data = get_results_from_sheet(sheet_url)
        results[data["metadata"]["constituency"]] = data
    return results
