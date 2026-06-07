"""NI Assembly Members (MLAs) data module.

Fetches current Member of the Legislative Assembly (MLA) data from the
NI Assembly AIMS API.  The API returns XML; this module parses it into
tidy DataFrames.

Update frequency: Real-time (reflects current membership).

Example:
    >>> from bolster.data_sources.niassembly import members
    >>> df = members.get_current_members()
    >>> "PersonId" in df.columns
    True
    >>> len(df) >= 85
    True
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.niassembly.gov.uk/members.asmx"


def _xml_to_records(xml_text: str, list_tag: str, item_tag: str) -> list[dict]:
    """Parse an XML response from the NI Assembly API into a list of dicts.

    Args:
        xml_text: Raw XML response text.
        list_tag: Root element name that contains the items (may be absent for
            flat structures).
        item_tag: Element name for each individual record.

    Returns:
        List of dicts with text content keyed by child tag name.
    """
    if not xml_text or not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    # The root itself may be the list container, or it may be nested
    container = root if root.tag == list_tag else root.find(list_tag)
    if container is None:
        # Flat structure — root contains items directly
        container = root
    records = []
    for item in container.findall(item_tag):
        records.append({child.tag: child.text for child in item})
    return records


def get_current_members() -> pd.DataFrame:
    """Return all current MLAs as a DataFrame.

    Fetches live data from the NI Assembly AIMS API.

    Returns:
        DataFrame with columns: PersonId, MemberName, MemberFirstName,
        MemberLastName, MemberFullDisplayName, PartyName,
        PartyOrganisationId, ConstituencyName, ConstituencyId,
        MemberTitle, MemberImgUrl, MemberPrefix, AffiliationId,
        MemberSortName.

    Raises:
        requests.HTTPError: If the API request fails.

    Example:
        >>> df = get_current_members()
        >>> "PartyName" in df.columns
        True
        >>> df["PersonId"].dtype == object or df["PersonId"].dtype.kind in "iu"
        True
    """
    url = f"{_BASE_URL}/GetAllCurrentMembers"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    records = _xml_to_records(response.text, "AllMembersList", "Member")
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    # Coerce numeric IDs
    for col in ("PersonId", "PartyOrganisationId", "ConstituencyId", "AffiliationId"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_member_by_id(person_id: int) -> pd.DataFrame:
    """Return a single MLA record by PersonId.

    Filters the full current members list to the requested person.  The AIMS
    API does not expose a single-member endpoint, so the full list is fetched
    and filtered locally.

    Args:
        person_id: NI Assembly AIMS PersonId for the MLA.

    Returns:
        Single-row DataFrame for the matching member, or an empty DataFrame
        if not found.

    Example:
        >>> df = get_member_by_id(5797)
        >>> len(df) <= 1
        True
    """
    all_members = get_current_members()
    if all_members.empty:
        return all_members
    return all_members[all_members["PersonId"] == person_id].reset_index(drop=True)
