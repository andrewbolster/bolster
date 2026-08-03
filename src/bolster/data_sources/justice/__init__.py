"""Northern Ireland justice system data sources.

Modules wrapping statistical publications from the Department of Justice (DoJ),
its sponsored bodies, the Northern Ireland Courts and Tribunals Service (NICTS)
and the Public Prosecution Service (PPS):

- first_time_entrants: First time entrants to the criminal justice system,
  broken down by age band, gender, offence classification and disposal type.
- mortgages: Mortgage actions for possession (cases received, disposed, and
  final orders made in the Chancery Division of the NI High Court).
- nicts_quarterly: Quarterly provisional court business figures across all ten
  NICTS court datasets, from the Court of Appeal to the Magistrates' Courts.
- pbni_caseload: Probation Board for Northern Ireland caseload statistics
  (annual and quarterly snapshots of people under probation supervision).
- pps_statistical_bulletin: PPS casework statistics covering files received,
  prosecution and diversion decisions, timeliness, and court outcomes.
- prosecutions_convictions: Annual court prosecutions, convictions and out of
  court disposals, including conviction rates by court tier and diversionary
  disposals by gender and age.

Most have corresponding CLI commands under ``bolster justice ...``.
"""

from . import mortgages, nicts_quarterly, pbni_caseload, prosecutions_convictions

__all__ = [
    "mortgages",
    "nicts_quarterly",
    "pbni_caseload",
    "prosecutions_convictions",
]
