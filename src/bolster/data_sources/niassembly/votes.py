"""NI Assembly Votes / Divisions data module.

Fetches plenary division (vote) records from the NI Assembly AIMS API.
Divisions are fetched by date range via ``GetVotesOnDivision_JSON`` and
per-member vote records are fetched via ``GetDivisionMemberVoting``
(which returns XML).

Update frequency: Real-time.

Example:
    >>> from bolster.data_sources.niassembly import votes
    >>> df = votes.get_all_divisions()
    >>> len(df) > 100
    True
    >>> "DivisionDate" in df.columns
    True
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.niassembly.gov.uk/plenary.asmx"

# Earliest mandate date to search from
_EARLIEST_DATE = "2007-01-01"


def get_all_divisions(
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return all Assembly divisions (votes) in a date range as a DataFrame.

    Defaults to fetching from the start of the current Assembly mandate
    (2022-05-01) to today.  Pass explicit dates for a narrower or wider window.

    Args:
        start_date: ISO-8601 date string (YYYY-MM-DD).  Defaults to
            ``"2022-05-01"`` (current mandate start).
        end_date: ISO-8601 date string (YYYY-MM-DD).  Defaults to today.

    Returns:
        DataFrame with columns: EventID, SessionID, DocumentID, DivisionDate,
        DivisionSubject, DivisonType, DivisionResult, MemberVoting.
        Returns an empty DataFrame if no divisions are found.

    Raises:
        requests.HTTPError: If the API request fails.

    Example:
        >>> df = get_all_divisions()
        >>> len(df) >= 0
        True
        >>> "DivisionSubject" in df.columns
        True
    """
    if start_date is None:
        start_date = "2022-05-01"
    if end_date is None:
        end_date = date.today().isoformat()

    url = f"{_BASE_URL}/GetVotesOnDivision_JSON"
    response = session.get(url, params={"startDate": start_date, "endDate": end_date}, timeout=60)
    response.raise_for_status()
    data = response.json()
    division_list = data.get("DivisionList") or {}
    records = division_list.get("Division") if division_list else None
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "DivisionDate" in df.columns:
        df["DivisionDate"] = pd.to_datetime(df["DivisionDate"], errors="coerce", utc=True)
    for col in ("EventID", "SessionID", "DocumentID"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_division_votes(division_id: int) -> pd.DataFrame:
    """Return per-member voting records for a single division.

    Fetches ``GetDivisionMemberVoting`` (XML) and parses member vote records.

    Args:
        division_id: NI Assembly AIMS DocumentID for the division.

    Returns:
        DataFrame with columns: DocumentID, EventID, PersonID, MemberName,
        Vote, Designation, VoteInVacancy, MemberSortName.
        Returns an empty DataFrame if no records are found.

    Raises:
        requests.HTTPError: If the API request fails.

    Example:
        >>> df = get_division_votes(406283)
        >>> "Vote" in df.columns
        True
        >>> len(df) > 0
        True
    """
    url = f"{_BASE_URL}/GetDivisionMemberVoting"
    response = session.get(url, params={"documentId": division_id}, timeout=30)
    response.raise_for_status()
    xml_text = response.text
    if not xml_text or not xml_text.strip():
        return pd.DataFrame()
    root = ET.fromstring(xml_text)
    records = []
    for member in root.findall("Member"):
        records.append({child.tag: child.text for child in member})
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    for col in ("DocumentID", "EventID", "PersonID"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "VoteInVacancy" in df.columns:
        df["VoteInVacancy"] = df["VoteInVacancy"].map({"true": True, "false": False}, na_action="ignore")
    return df
