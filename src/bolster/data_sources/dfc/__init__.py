"""Northern Ireland Department for Communities (DfC) data sources.

Modules wrapping statistical publications from the Department for Communities,
published at https://www.communities-ni.gov.uk.

- family_resources_survey: Annual Family Resources Survey report covering
  household income and state support, tenure, carers and disability, and
  household food security and food bank usage.

Corresponding CLI commands live under ``bolster dfc ...``.
"""

from bolster.data_sources.dfc import family_resources_survey

__all__ = ["family_resources_survey"]
