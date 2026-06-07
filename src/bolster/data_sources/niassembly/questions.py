"""NI Assembly Questions data module.

Fetches oral and written question data from the NI Assembly AIMS API.
Questions are indexed by department (using the AIMS OrganisationId) or by
the tabling MLA (PersonId).

The ``GetQuestionsByDepartment`` endpoint accepts a numeric ``departmentId``
which corresponds to the ``OrganisationId`` returned by
``organisations.asmx/GetDepartmentListCurrent_JSON``.

Known department IDs (as of 2026):
    76  DAERA, 78  Education, 79  Economy, 81  Finance,
    82  Health, 84  Infrastructure, 85  Communities,
    86  The Executive Office, 134 Justice

Update frequency: Real-time.

Example:
    >>> from bolster.data_sources.niassembly import questions
    >>> df = questions.get_questions_by_department(82)
    >>> len(df) > 100
    True
    >>> "QuestionText" in df.columns
    True
"""

from __future__ import annotations

import logging

import pandas as pd

from bolster.utils.web import session

logger = logging.getLogger(__name__)

_BASE_URL = "https://data.niassembly.gov.uk/questions.asmx"

# Mapping of common department name fragments to AIMS OrganisationId
DEPARTMENT_NAME_TO_ID: dict[str, int] = {
    "Department of Agriculture, Environment and Rural Affairs": 76,
    "DAERA": 76,
    "Department of Education": 78,
    "DE": 78,
    "Department for the Economy": 79,
    "DfE": 79,
    "Department of Finance": 81,
    "DoF": 81,
    "Department of Health": 82,
    "DoH": 82,
    "Department for Infrastructure": 84,
    "DfI": 84,
    "Department for Communities": 85,
    "DfC": 85,
    "The Executive Office": 86,
    "TEO": 86,
    "Department of Justice": 134,
    "DoJ": 134,
}


def _resolve_department_id(department: str | int) -> int:
    """Resolve a department name or ID to an integer AIMS OrganisationId.

    Args:
        department: Either an integer ID or a string name (full or abbreviation).

    Returns:
        Integer department (organisation) ID.

    Raises:
        ValueError: If the name cannot be resolved.

    Example:
        >>> _resolve_department_id(82)
        82
        >>> _resolve_department_id("Department of Health")
        82
        >>> _resolve_department_id("DoH")
        82
    """
    if isinstance(department, int):
        return department
    # Exact match first
    if department in DEPARTMENT_NAME_TO_ID:
        return DEPARTMENT_NAME_TO_ID[department]
    # Case-insensitive partial match
    lower = department.lower()
    for name, dept_id in DEPARTMENT_NAME_TO_ID.items():
        if lower in name.lower() or name.lower() in lower:
            return dept_id
    raise ValueError(
        f"Cannot resolve department '{department}'. Use an integer ID or one of: {list(DEPARTMENT_NAME_TO_ID.keys())}"
    )


def get_questions_by_department(department: str | int) -> pd.DataFrame:
    """Return all questions directed to a department as a DataFrame.

    Args:
        department: Department name (full or abbreviation) or integer
            AIMS OrganisationId.  E.g. ``"Department of Health"``, ``"DoH"``,
            or ``82``.

    Returns:
        DataFrame with columns including DocumentId, Reference, TabledDate,
        QuestionText, TablerPersonId, TablerName, QOralAnswerRequested.
        Returns an empty DataFrame if no questions are found.

    Raises:
        requests.HTTPError: If the API request fails.
        ValueError: If the department name cannot be resolved.

    Example:
        >>> df = get_questions_by_department("Department of Health")
        >>> len(df) > 100
        True
        >>> "QuestionText" in df.columns
        True
    """
    dept_id = _resolve_department_id(department)
    url = f"{_BASE_URL}/GetQuestionsByDepartment_JSON"
    response = session.get(url, params={"departmentId": dept_id}, timeout=60)
    response.raise_for_status()
    data = response.json()
    questions_list = data.get("QuestionsList") or {}
    records = questions_list.get("Question") if questions_list else None
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "TabledDate" in df.columns:
        df["TabledDate"] = pd.to_datetime(df["TabledDate"], errors="coerce", utc=True)
    for col in ("DocumentId", "TablerPersonId", "MinisterPersonId"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_questions_by_member(person_id: int) -> pd.DataFrame:
    """Return all questions tabled by an MLA as a DataFrame.

    Args:
        person_id: NI Assembly AIMS PersonId for the MLA.

    Returns:
        DataFrame with columns including DocumentId, Reference, TabledDate,
        QuestionText, DepartmentId, DepartmentName, QOralAnswerRequested.
        Returns an empty DataFrame if no questions are found.

    Raises:
        requests.HTTPError: If the API request fails.

    Example:
        >>> df = get_questions_by_member(5797)
        >>> len(df) >= 0
        True
    """
    url = f"{_BASE_URL}/GetQuestionsByMember_JSON"
    response = session.get(url, params={"personId": person_id}, timeout=60)
    response.raise_for_status()
    data = response.json()
    questions_list = data.get("QuestionsList") or {}
    records = questions_list.get("Question") if questions_list else None
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "TabledDate" in df.columns:
        df["TabledDate"] = pd.to_datetime(df["TabledDate"], errors="coerce", utc=True)
    for col in ("DocumentId", "TablerPersonId", "DepartmentId"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
