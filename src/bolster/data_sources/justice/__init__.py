"""Northern Ireland Department of Justice data sources.

Modules wrapping statistical publications from the Department of Justice (DoJ),
its sponsored bodies, and the Northern Ireland Courts and Tribunals Service
(NICTS):

- mortgages: Mortgage actions for possession (cases received, disposed, and
  final orders made in the Chancery Division of the NI High Court).
- nicts_quarterly: Quarterly provisional court business figures across all ten
  NICTS court datasets, from the Court of Appeal to the Magistrates' Courts.
- pbni_caseload: Probation Board for Northern Ireland caseload statistics
  (annual and quarterly snapshots of people under probation supervision).

Most have corresponding CLI commands under ``bolster justice ...``.
"""

from . import mortgages, nicts_quarterly, pbni_caseload

__all__ = ["mortgages", "nicts_quarterly", "pbni_caseload"]
