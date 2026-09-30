"""Northern Ireland Department for Communities (DfC) data sources.

Modules wrapping statistical publications from the Department for Communities,
published at https://www.communities-ni.gov.uk.

- child_maintenance: Quarterly Child Maintenance Service statistics covering
  applications, arrangements, children covered, paying parent compliance and
  characteristics, maintenance due and paid, and enforcement collections.
- neighbourhood_renewal_profiles: Annual statistical profiles of the 36 Neighbourhood Renewal Areas
  (population, employment, health, education, crime and census charts) read from the Plotly data in
  each area's NISRA datavis page.
- family_resources_survey: Annual Family Resources Survey report covering
  household income and state support, tenure, carers and disability, and
  household food security and food bank usage.

Corresponding CLI commands live under ``bolster dfc ...``.
"""

from bolster.data_sources.dfc import child_maintenance, family_resources_survey, neighbourhood_renewal_profiles

__all__ = ["child_maintenance", "family_resources_survey", "neighbourhood_renewal_profiles"]
