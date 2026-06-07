"""Northern Ireland Assembly (NIAssembly) AIMS data integration.

Data Source: The Northern Ireland Assembly provides data through the Assembly
Information Management System (AIMS) API at https://data.niassembly.gov.uk/.
The API is open (OGL v3.0, no authentication required) and covers Members,
Questions, Organisations, Plenary business, and Hansard contributions.

Services:
    - members.asmx  — MLAs, constituencies, parties
    - questions.asmx — oral/written Q&As since 2007
    - organisations.asmx — committees, parties, departments
    - plenary.asmx  — votes/divisions with per-member records
    - hansard.asmx  — member speech contributions

Submodules:
    members   — current MLA roster and individual member lookup
    questions — questions tabled by department or by member
    votes     — Assembly divisions (votes) with per-member records

Example:
    >>> from bolster.data_sources.niassembly import members, questions, votes
    >>> mlas = members.get_current_members()
    >>> len(mlas) > 85
    True
"""

from . import members, questions, votes

__all__ = ["members", "questions", "votes"]
