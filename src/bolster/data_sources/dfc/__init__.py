"""Northern Ireland Department for Communities (DfC) data sources.

Modules wrapping statistical publications from the Department for Communities,
published at https://www.communities-ni.gov.uk.

- child_maintenance: Quarterly Child Maintenance Service statistics covering
  applications, arrangements, children covered, paying parent compliance and
  characteristics, maintenance due and paid, and enforcement collections.

Corresponding CLI commands live under ``bolster dfc ...``.
"""

from bolster.data_sources.dfc import child_maintenance

__all__ = ["child_maintenance"]
