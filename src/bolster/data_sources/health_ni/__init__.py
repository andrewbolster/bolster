"""Health and Social Care (DoH) data sources for Northern Ireland.

Data published by the Department of Health at https://www.health-ni.gov.uk.

Modules:
    - cancer_waiting_times: Cancer treatment waiting times (14-day, 31-day, 62-day targets)
    - child_protection: Children's Social Care child protection statistics
    - diagnostic_waiting_times: Quarterly diagnostic waiting times by HSC Trust
    - disease_prevalence: Annual GP disease register sizes and prevalence per 1,000 patients
    - elective_waiting_times: Elective and outpatient waiting times
    - emergency_care_waiting_times: Emergency care (A&E) waiting times against the 4-hour target
"""

from bolster.data_sources.health_ni import (
    cancer_waiting_times,
    child_protection,
    diagnostic_waiting_times,
    disease_prevalence,
    elective_waiting_times,
    emergency_care_waiting_times,
)

__all__ = [
    "cancer_waiting_times",
    "child_protection",
    "diagnostic_waiting_times",
    "disease_prevalence",
    "elective_waiting_times",
    "emergency_care_waiting_times",
]
