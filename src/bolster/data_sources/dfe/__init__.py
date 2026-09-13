"""Northern Ireland Department for the Economy (DfE) data sources.

Modules wrapping annual higher-education statistical publications from the
Department for the Economy, published at https://www.economy-ni.gov.uk. Both
series in this package are ultimately sourced from HESA (the Higher
Education Statistics Agency) and share the same annual release programme.

- higher_education_enrolments: NI-domiciled student enrolments at UK HEIs,
  and enrolments at NI's own HEIs regardless of domicile.

Corresponding CLI commands live under ``bolster dfe ...``.
"""

from bolster.data_sources.dfe import higher_education_enrolments

__all__ = ["higher_education_enrolments"]
